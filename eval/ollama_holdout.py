"""로컬 Ollama 로 holdout 36건 전체를 구성별 1회 실행한다 (API 비용 0, 데이터 외부 전송 없음). 정량 비교 대상 아님.

eval/ollama_demo.py 와 같은 방식으로 프로세스 안에서만 OpenAI 호환 주소를 Ollama 로 바꿔 끼운다
(원본·ext 코드 수정 없음, 모델 전부 qwen3:8b, 생각 출력 끔, 요청 타임아웃 300초, 단가 0).
행 형식은 eval/run_ablation.py 의 _evaluate_one 과 같다. 다만 평가용 Judge(gpt-4o)는 부르지 않는다
(judge_passed = None). 파이프라인 안의 Judge 기록은 pipeline_judge 에 남는다.

- 순차 실행 (Ollama 는 요청을 한 줄로 처리한다). 질의 1건은 자식 프로세스에서 돌리고
  QUERY_TIMEOUT_S(360초)를 넘으면 끊고 오류 행으로 남긴 뒤 다음으로 넘어간다.
- 이어 하기: results/ollama_holdout_<구성>_partial.json 에 1건마다 저장하고, 다시 실행하면 이미 끝난 id 는 건너뛴다.
  끝나면 results/ollama_holdout_<구성>_<YYYYMMDD_HHMM>.json 으로 저장하고 partial 을 지운다.
- 연속 3건 오류면 Ollama 상태를 확인하고, 응답이 없으면 멈춘다 (partial 은 남는다).

    python -m eval.ollama_holdout --configs base,final_local_bge
    python -m eval.ollama_holdout --configs base --ids Q25,Q26     # 일부만 (저장 안 함: --no-save)
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "ollama-local")
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
R = ROOT / "results"
QUERY_TIMEOUT_S = 360


def local_cfg(name: str, model: str) -> dict:
    cfg = copy.deepcopy(yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text()))
    cfg["name"] = name if "local" in name else f"{name}_local"
    cfg["models"] = {k: model for k in ("fast", "quality", "cascade_writer", "judge")}
    if not str(cfg.setdefault("rag", {}).get("embedding", "")).startswith(("local", "ollama:")):
        cfg["rag"]["embedding"] = "local"
    cfg.setdefault("cost", {})["cache"] = False
    return cfg


def _child(q: dict, cfg: dict, model: str, conn):
    """자식 프로세스: 주소 바꿔 끼우기 → 질의 1건 실행 → 행을 부모에게 보낸다."""
    import httpx

    from eval import ollama_demo as od   # _real_post 를 원래 httpx.post 로 먼저 잡는다
    import src.adapter as adapter
    import agent.openai_llm as ol
    import ext.meter as em
    from eval.run_ablation import _evaluate_one
    ol.OPENAI_URL = em.OPENAI_URL = f"{od.OLLAMA}/chat/completions"
    em.PRICE[model] = (0.0, 0.0)
    httpx.post = od._ollama_post
    t0 = time.perf_counter()
    row = _evaluate_one(q, 1, cfg, adapter.run_once, None)
    row["wall_s"] = round(time.perf_counter() - t0, 1)
    conn.send(row)
    conn.close()


def run_query(q: dict, cfg: dict, model: str) -> dict:
    ctx = mp.get_context("spawn")
    rx, tx = ctx.Pipe(duplex=False)
    p = ctx.Process(target=_child, args=(q, cfg, model, tx), daemon=False)
    t0 = time.perf_counter()
    p.start()
    tx.close()
    row = None
    if rx.poll(QUERY_TIMEOUT_S):
        try:
            row = rx.recv()
        except EOFError:
            row = None
    p.join(10)
    if p.is_alive():
        p.terminate()
        p.join(10)
    if row is None:
        wall = round(time.perf_counter() - t0, 1)
        why = (f"TimeoutError: 질의 상한 {QUERY_TIMEOUT_S}초 초과" if wall >= QUERY_TIMEOUT_S
               else f"ChildExit: exitcode={p.exitcode}")
        row = {"id": q["id"], "rep": 1, "split": q.get("split"), "category": q.get("category"),
               "error": why, "wall_s": wall}
    return row


def ollama_alive() -> bool:
    import httpx
    try:
        return httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).status_code == 200
    except Exception:
        return False


def run_config(name: str, qs: list[dict], model: str, save: bool) -> list[dict]:
    cfg = local_cfg(name, model)
    partial = R / f"ollama_holdout_{cfg['name']}_partial.json"
    rows = json.loads(partial.read_text())["rows"] if (save and partial.exists()) else []
    done = {r["id"] for r in rows}
    todo = [q for q in qs if q["id"] not in done]
    print(f"\n=== {cfg['name']} === model={model} embedding={cfg['rag'].get('embedding')} "
          f"min_score={cfg['rag'].get('min_score')} 남은 {len(todo)}/{len(qs)} (이어 하기 {len(done)}건)", flush=True)
    consecutive_err = 0
    for q in todo:
        row = run_query(q, cfg, model)
        rows.append(row)
        if "error" in row:
            consecutive_err += 1
            print(f"  {row['id']}  ERROR {row['error'][:160]}  ({row.get('wall_s')}초)  [{len(rows)}/{len(qs)}]", flush=True)
        else:
            consecutive_err = 0
            jh = row.get("pipeline_judge") or []
            print(f"  {row['id']}  {row['route']:8}  fed={row['fed_runbooks']}  gold={row['gold']}  "
                  f"rw={row['rewrites']}  judge={len(jh)}  must={row['must_hit']}/{row['must_total']}  "
                  f"{row['latency_ms'] / 1000:.1f}s  [{len(rows)}/{len(qs)}]", flush=True)
        if save:
            partial.write_text(json.dumps({"config": cfg, "model": model, "rows": rows}, ensure_ascii=False))
        if consecutive_err >= 3 and not ollama_alive():
            print("!! 연속 3건 오류 + Ollama 응답 없음 — 멈춘다 (partial 보존, 다시 실행하면 이어 한다)", flush=True)
            raise SystemExit(2)
    rows.sort(key=lambda r: r["id"])
    if save:
        ts = f"{datetime.now():%Y%m%d_%H%M}"
        out = {"environment": f"로컬 Ollama ({model}), API 비용 0, 1회 실행, OpenAI 수치와 비교 대상 아님",
               "config": cfg, "model": model, "split": "holdout", "n": len(rows),
               "eval_judge_model": None, "query_timeout_s": QUERY_TIMEOUT_S, "rows": rows}
        p = R / f"ollama_holdout_{cfg['name']}_{ts}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        partial.unlink(missing_ok=True)
        print("saved", p.relative_to(ROOT), flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="base,final_local_bge")
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--ids", default=None)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"] if q.get("split") == "holdout"]
    assert len(qs) == 36
    if a.ids:
        want = set(a.ids.split(","))
        qs = [q for q in qs if q["id"] in want]
    if not ollama_alive():
        raise SystemExit("Ollama(127.0.0.1:11434)가 응답하지 않는다")
    for name in a.configs.split(","):
        run_config(name, qs, a.model, save=not a.no_save)


if __name__ == "__main__":
    main()
