"""로컬 Ollama 실행 가능성 데모 (API 비용 0, 데이터 외부 전송 없음). 정량 비교 대상 아님.

개선 파이프라인(src/ext)은 OpenAI 호환 /v1/chat/completions 형식으로 호출한다. Ollama 도 같은 형식을
제공하므로, 원본·ext 코드는 고치지 않고 이 프로세스 안에서만 API 주소를 Ollama 로 바꿔 끼운다
(eval/mock_llm_bench.py 와 같은 방식).
  - 모델: qwen3:8b (로컬). qwen3 의 생각 과정 출력은 끄고(reasoning_effort none), 남은 <think> 블록은 지운다.
  - 임베딩: OpenAI 임베딩 구성(final 등)은 embedding: local (LocalNgram)로 바꾼다. 다만 OpenAI 로 보정한 min_score 는
    로컬에선 의미가 달라 런북이 하나도 안 걸린다. 로컬용 기준값은 eval/configs/final_local.yaml
    (embedding: local-tfidf, dev 보정 results/calibrate_rag_local_latest.json)을 쓴다.
  - 요청 타임아웃 300초 (로컬 8B 모델은 느리다).
결과 수치(통과율·지연)는 OpenAI Ablation 과 모델·임베더·채점관이 모두 달라 비교하지 않는다.

    python -m eval.ollama_demo                       # base·final 을 같은 질문 1개로 1회씩
    python -m eval.ollama_demo --model qwen3:8b --query "..."
    python -m eval.ollama_demo --configs final_local,base --qid Q31 --tag q31   # 평가셋 질문 id 로 지정
결과: results/ollama_demo_[<tag>_]<YYYYMMDD_HHMM>.json, results/ollama_demo_latest.json

주소 바꿔 끼우기: agent.openai_llm.OPENAI_URL·ext.meter.OPENAI_URL 을 Ollama 의 /v1/chat/completions 로,
httpx.post 를 _ollama_post 로 바꾼다. 이 프로세스 안에서만 바뀌고 파일은 고치지 않는다.
eval/ollama_holdout.py 도 이 모듈의 OLLAMA·_ollama_post 를 그대로 가져다 쓴다.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENAI_API_KEY", "ollama-local")   # 실제 키 불필요 (load_dotenv 는 덮지 않음)
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

import httpx  # noqa: E402
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
R = ROOT / "results"
OLLAMA = "http://127.0.0.1:11434/v1"
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)   # qwen3 의 생각 블록 — JSON 파싱을 깨뜨리므로 지운다
_real_post = httpx.post   # 바꿔 끼우기 전 원래 함수 (Ollama 가 아닌 요청과 실제 전송에 쓴다)


def _ollama_post(url, *a, json=None, timeout=None, **kw):
    """Ollama 로 가는 요청만: 생각 과정 끄기, 타임아웃 300초, 응답의 <think> 블록 제거."""
    if not str(url).startswith(OLLAMA):
        return _real_post(url, *a, json=json, timeout=timeout, **kw)
    payload = dict(json or {})
    payload["reasoning_effort"] = "none"
    # 호출하는 쪽(post_with_retry)의 60초 대신 300초 — 로컬 8B 모델은 한 번의 작성도 오래 걸린다
    resp = _real_post(url, *a, json=payload, timeout=300.0, **kw)
    if resp.status_code != 200:
        return resp
    data = resp.json()
    for ch in data.get("choices", []):
        msg = ch.get("message", {})
        if isinstance(msg.get("content"), str):
            msg["content"] = _THINK.sub("", msg["content"]).strip()
    return httpx.Response(200, json=data, request=resp.request)


def main():
    """구성마다 같은 질문 1개를 로컬 모델로 1회 실행하고 고른 런북·답·지연을 저장한다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--query", default="DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요.")
    ap.add_argument("--configs", default="base,final")
    ap.add_argument("--qid", default=None, help="eval/queries.yaml 의 질문 id (주면 --query 대신 사용)")
    ap.add_argument("--tag", default="", help="결과 파일 이름에 붙일 꼬리표")
    a = ap.parse_args()
    gold = None
    if a.qid:
        q = next(q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"] if q["id"] == a.qid)
        a.query, gold = q["query"], q["gold_runbooks"]

    import src.adapter as adapter          # src/ 를 import 경로에 올린다 (agent·ext 보다 먼저)
    import agent.openai_llm as ol
    import ext.meter as em
    ol.OPENAI_URL = em.OPENAI_URL = f"{OLLAMA}/chat/completions"
    em.PRICE[a.model] = (0.0, 0.0)          # 로컬 모델은 과금 0 (없으면 비용이 NaN)
    httpx.post = _ollama_post

    out = {"environment": f"로컬 Ollama ({a.model}), API 비용 0, 정량 비교 대상 아님",
           "query": a.query, "qid": a.qid, "gold_runbooks": gold, "model": a.model, "runs": {}}
    for name in a.configs.split(","):
        cfg = copy.deepcopy(yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text()))
        cfg["name"] = f"{name}_local"
        cfg["models"] = {k: a.model for k in ("fast", "quality", "cascade_writer", "judge")}   # 모든 역할을 로컬 모델 하나로
        if not str(cfg.setdefault("rag", {}).get("embedding", "")).startswith(("local", "ollama:")):
            cfg["rag"]["embedding"] = "local"      # OpenAI 임베딩 구성은 LocalNgram 으로 (API 호출 없음)
        cfg.setdefault("cost", {})["cache"] = False
        t0 = time.perf_counter()
        try:
            o = adapter.run_once(a.query, cfg)
            res = {"ok": bool(o.get("answer")), "latency_s": round(time.perf_counter() - t0, 1),
                   "selection": cfg.get("runbook_selection", "keyword"),
                   "embedding": cfg["rag"]["embedding"] if cfg.get("runbook_selection") == "rag" else None,
                   "min_score": cfg["rag"].get("min_score") if cfg.get("runbook_selection") == "rag" else None,
                   "route": o.get("route"), "runbooks": o.get("fed_runbooks"),
                   "ranking": next(([r for r in e.get("ranking", [])] for e in o.get("events", [])
                                    if e.get("type") == "ReplanCheck" and e.get("ranking")), None),
                   "notices": o.get("notices"),
                   "rewrites": o.get("rewrites"), "llm_calls": o.get("llm_calls"),
                   "judge_history": o.get("judge_history"),
                   "answer": o.get("answer", "")}
        except Exception as e:
            res = {"ok": False, "latency_s": round(time.perf_counter() - t0, 1),
                   "error": f"{type(e).__name__}: {str(e)[:300]}"}
        out["runs"][name] = res
        print(f"== {name}_local  ok={res['ok']}  {res['latency_s']}초  runbooks={res.get('runbooks')}  "
              f"{res.get('error', '')}", flush=True)
        print((res.get("answer") or "")[:600], flush=True)
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    stem = f"ollama_demo_{a.tag}_{ts}" if a.tag else f"ollama_demo_{ts}"
    for p in (R / f"{stem}.json", R / "ollama_demo_latest.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", f"results/{stem}.json")


if __name__ == "__main__":
    main()
