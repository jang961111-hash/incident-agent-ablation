"""로컬 Ollama 실행 가능성 데모 (API 비용 0, 데이터 외부 전송 없음). 정량 비교 대상 아님.

개선 파이프라인(src/ext)은 OpenAI 호환 /v1/chat/completions 형식으로 호출한다. Ollama 도 같은 형식을
제공하므로, 원본·ext 코드는 고치지 않고 이 프로세스 안에서만 API 주소를 Ollama 로 바꿔 끼운다
(eval/mock_llm_bench.py 와 같은 방식).
  - 모델: qwen3:8b (로컬). qwen3 의 생각 과정 출력은 끄고(reasoning_effort none), 남은 <think> 블록은 지운다.
  - 임베딩: embedding: local (LocalNgram). OpenAI 임베딩으로 보정한 min_score 는 로컬에선 의미가 다르다.
  - 요청 타임아웃 300초 (로컬 8B 모델은 느리다).
결과 수치(통과율·지연)는 OpenAI Ablation 과 모델·임베더·채점관이 모두 달라 비교하지 않는다.

    python -m eval.ollama_demo                       # base·final 을 같은 질문 1개로 1회씩
    python -m eval.ollama_demo --model qwen3:8b --query "..."
결과: results/ollama_demo_<YYYYMMDD_HHMM>.json, results/ollama_demo_latest.json
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
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)
_real_post = httpx.post


def _ollama_post(url, *a, json=None, timeout=None, **kw):
    """Ollama 로 가는 요청만: 생각 과정 끄기, 타임아웃 300초, 응답의 <think> 블록 제거."""
    if not str(url).startswith(OLLAMA):
        return _real_post(url, *a, json=json, timeout=timeout, **kw)
    payload = dict(json or {})
    payload["reasoning_effort"] = "none"
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:8b")
    ap.add_argument("--query", default="DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요.")
    ap.add_argument("--configs", default="base,final")
    a = ap.parse_args()

    import agent.openai_llm as ol
    import ext.meter as em
    import src.adapter as adapter
    ol.OPENAI_URL = em.OPENAI_URL = f"{OLLAMA}/chat/completions"
    em.PRICE[a.model] = (0.0, 0.0)          # 로컬 모델은 과금 0 (없으면 비용이 NaN)
    httpx.post = _ollama_post

    out = {"environment": f"로컬 Ollama ({a.model}), API 비용 0, 정량 비교 대상 아님",
           "query": a.query, "model": a.model, "embedding": "local (LocalNgram)", "runs": {}}
    for name in a.configs.split(","):
        cfg = copy.deepcopy(yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text()))
        cfg["name"] = f"{name}_local"
        cfg["models"] = {k: a.model for k in ("fast", "quality", "cascade_writer", "judge")}
        cfg.setdefault("rag", {})["embedding"] = "local"
        cfg.setdefault("cost", {})["cache"] = False
        t0 = time.perf_counter()
        try:
            o = adapter.run_once(a.query, cfg)
            res = {"ok": bool(o.get("answer")), "latency_s": round(time.perf_counter() - t0, 1),
                   "route": o.get("route"), "runbooks": o.get("fed_runbooks"),
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
    for p in (R / f"ollama_demo_{ts}.json", R / "ollama_demo_latest.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", f"results/ollama_demo_{ts}.json")


if __name__ == "__main__":
    main()
