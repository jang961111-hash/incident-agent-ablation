"""모의 LLM 서버 장애 주입 벤치 (모의 환경, API 비용 0).

로컬 모의 OpenAI 서버(chat completions·embeddings)를 띄우고 응답을 일부러 망가뜨려,
지금 구조의 파이프라인이 죽는지·부분 결과로 답하는지·재시도와 타임아웃 상한이 지연을 어떻게 바꾸는지 잰다.
원본 코드는 고치지 않는다. 이 프로세스 안에서만 API 주소를 모의 서버로 바꾸고, 임베딩 캐시는 임시 폴더를 쓴다.
실제 키는 쓰지 않는다(가짜 키로 덮어씀). 답 내용은 고정 문장이라 품질은 재지 않는다.

시나리오: normal(지연 0.3초) · slow(지연 2초) · e503(30% 503) · badjson(JSON 요청의 30%에 깨진 JSON) ·
         hang(15% 요청이 65초 멈춤 → 클라이언트 60초 타임아웃 후 재시도)
    python -m eval.mock_llm_bench            # 결과: results/mock_llm_bench_<YYYYMMDD_HHMM>.json·.md, _latest.json
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

os.environ["OPENAI_API_KEY"] = "mock-key-not-real"      # load_dotenv(override=False)가 실제 키로 덮지 않는다
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
R = ROOT / "results"

SCEN = {"delay": 0.3, "p503": 0.0, "pbad": 0.0, "phang": 0.0, "hang_s": 65.0}
_rng = random.Random(7)
_lock = threading.Lock()
STATS = {"requests": 0, "e503": 0, "bad": 0, "hang": 0}

TEXT = "1) 모니터링 상태를 확인한다.\n2) 런북 절차에 따라 조치한다.\n3) 정상화 후 원인을 기록한다."


def _roll(p):
    with _lock:
        return _rng.random() < p


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with _lock:
            STATS["requests"] += 1
        if self.path.endswith("/embeddings"):
            inp = req.get("input")
            inp = inp if isinstance(inp, list) else [inp]
            data = [{"index": i, "embedding": [((int(hashlib.md5(f"{t}:{k}".encode()).hexdigest()[:6], 16) % 2000) - 1000) / 1000
                                               for k in range(64)]} for i, t in enumerate(inp)]
            return self._send(200, {"data": data, "usage": {"prompt_tokens": 10, "total_tokens": 10}})
        time.sleep(SCEN["delay"])
        if _roll(SCEN["phang"]):
            with _lock:
                STATS["hang"] += 1
            time.sleep(SCEN["hang_s"])
        if _roll(SCEN["p503"]):
            with _lock:
                STATS["e503"] += 1
            return self._send(503, {"error": {"message": "mock 503"}})
        system = (req.get("messages") or [{}])[0].get("content", "")
        if req.get("response_format", {}).get("type") == "json_object":
            if _roll(SCEN["pbad"]):
                with _lock:
                    STATS["bad"] += 1
                content = "이건 JSON 이 아니다 {"
            elif "라우터" in system:
                content = json.dumps({"route": "incident", "needs_analysis": False})
            elif "planning" in system:
                content = json.dumps({"needs_analysis": False, "tasks": [{"agent": "research", "target": "auth-service"}]})
            else:   # Judge 등
                content = json.dumps({m: {"verdict": "Pass", "reason": "mock"} for m in
                                      ("relevance", "completeness", "domain_appropriateness", "clarity")} | {"fixable": True})
        else:
            content = TEXT
        self._send(200, {"choices": [{"message": {"content": content}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}/v1"

    import src.adapter as adapter
    import agent.openai_llm as ol
    import ext.meter as em
    import ext.rag as rg
    ol.OPENAI_URL = em.OPENAI_URL = f"{base_url}/chat/completions"
    rg.EMBED_URL = f"{base_url}/embeddings"
    adapter.CACHE_DIR = Path(tempfile.mkdtemp(prefix="mock_emb_"))   # 실제 임베딩 캐시 보호
    rg._INDEX.clear() if hasattr(rg, "_INDEX") else None

    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
          if q.get("split") == "holdout" and q["category"] == "normal"][:8]
    load = lambda n: yaml.safe_load((ROOT / f"eval/configs/{n}.yaml").read_text())
    scenarios = [("normal", {"delay": 0.3}, 8), ("slow", {"delay": 2.0}, 8), ("e503", {"delay": 0.3, "p503": 0.3}, 8),
                 ("badjson", {"delay": 0.3, "pbad": 0.3}, 8), ("hang", {"delay": 0.3, "phang": 0.15}, 4)]
    out = {"environment": "모의 환경 (로컬 모의 OpenAI 서버, API 비용 0, 답 품질 미측정)", "queries": [q["id"] for q in qs],
           "client_policy": "post_with_retry: 429·5xx·타임아웃 재시도 최대 7회, 요청당 60초 타임아웃 / adapter HARD_TIMEOUT 300초",
           "results": {}}
    for sname, conf, nq in scenarios:
        for cname in ("base", "final"):
            SCEN.update({"delay": 0.3, "p503": 0.0, "pbad": 0.0, "phang": 0.0, **conf})
            _rng.seed(7)
            cfg = copy.deepcopy(load(cname))
            cfg.setdefault("cost", {})["cache"] = False
            adapter._CACHES.clear() if hasattr(adapter, "_CACHES") else None
            before = dict(STATS)

            def job(q):
                t0 = time.perf_counter()
                try:
                    o = adapter.run_once(q["query"], cfg)
                    return {"id": q["id"], "ok": bool(o.get("answer")), "latency_s": time.perf_counter() - t0,
                            "retries": o.get("api_retries", 0), "rewrites": o.get("rewrites", 0)}
                except Exception as e:
                    return {"id": q["id"], "ok": False, "latency_s": time.perf_counter() - t0,
                            "error": f"{type(e).__name__}: {str(e)[:100]}"}

            with ThreadPoolExecutor(4) as ex:
                rows = list(ex.map(job, qs[:nq]))
            lat = [r["latency_s"] for r in rows]
            res = {"n": len(rows), "completed": sum(r["ok"] for r in rows),
                   "latency_median_s": statistics.median(lat), "latency_max_s": max(lat),
                   "retries": sum(r.get("retries", 0) or 0 for r in rows),
                   "rewrites": sum(r.get("rewrites", 0) or 0 for r in rows),
                   "injected": {k: STATS[k] - before[k] for k in STATS},
                   "errors": sorted({r["error"].split(":")[0] for r in rows if "error" in r}), "rows": rows}
            out["results"][f"{sname}/{cname}"] = res
            print(f"{sname:8} {cname:6} 완주 {res['completed']}/{res['n']}  중앙 {res['latency_median_s']:.1f}s  "
                  f"최대 {res['latency_max_s']:.1f}s  재시도 {res['retries']}  주입 {res['injected']}  {res['errors']}", flush=True)
    srv.shutdown()
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    (R / f"mock_llm_bench_{ts}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (R / "mock_llm_bench_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 모의 LLM 서버 장애 주입 벤치 (모의 환경)", "", out["environment"], "", out["client_policy"], "",
             "| 시나리오 | 구성 | 완주 | 지연 중앙값 | 지연 최대 | API 재시도 | 재작성 | 오류 종류 |", "|---|---|---|---|---|---|---|---|"]
    for k, r in out["results"].items():
        s, c = k.split("/")
        lines.append(f"| {s} | {c} | {r['completed']}/{r['n']} | {r['latency_median_s']:.1f}초 | {r['latency_max_s']:.1f}초 | "
                     f"{r['retries']} | {r['rewrites']} | {', '.join(r['errors']) or '-'} |")
    (R / f"mock_llm_bench_{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
