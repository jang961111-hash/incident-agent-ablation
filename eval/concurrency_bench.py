"""동시성 실측 — 같은 이벤트 루프에서 질의 N건을 동시에 처리하는 시간.

원본 노드는 async 지만 그 안의 LLM 호출(httpx.post)은 동기라서 이벤트 루프를 막는다.
FastAPI 서버(원본 server.py)도 같은 루프에서 그래프를 돌리므로, 동시 요청이 사실상 줄을 선다.
runtime.async_io=true 는 그 호출을 스레드로 빼서 루프를 막지 않는다. 그 효과만 보려고
final 구성에서 async_io 만 끄고 켠 두 변형을 비교한다 (캐시는 꺼서 반복 질의 효과를 뺀다).

    python -m eval.concurrency_bench            # N = 1, 3, 5, 10
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


async def run_batch(cfg: dict, queries: list[str]) -> dict:
    from src.adapter import _build_deps
    from agent.mcp_client import MCPClient
    from ext.graph_ext import build_graph_ext
    from ext.meter import start_meter

    mcp = MCPClient(flaky_first_tool_call=False)   # 벤치에서는 원본의 데모용 1회 타임아웃을 끈다
    await mcp.start()
    try:
        deps = _build_deps(cfg, mcp)
        if deps.retriever is not None:
            deps.retriever._index()
        graph = build_graph_ext(deps)

        async def one(q: str):
            meter = start_meter()
            t0 = time.perf_counter()
            await graph.ainvoke({"query": q, "thread_id": uuid.uuid4().hex, "history": [],
                                 "events": [], "cost_usd": 0.0, "started_at": time.monotonic()})
            return (time.perf_counter() - t0) * 1000, meter.cost_usd()

        t0 = time.perf_counter()
        res = await asyncio.gather(*(one(q) for q in queries))
        wall = (time.perf_counter() - t0) * 1000
    finally:
        await mcp.stop()
    lat = [r[0] for r in res]
    return {"n": len(queries), "wall_ms": wall, "throughput_qps": len(queries) / (wall / 1000),
            "latency_mean_ms": statistics.fmean(lat), "latency_max_ms": max(lat),
            "cost_usd": sum(r[1] for r in res)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", default="1,3,5,10")
    ap.add_argument("--backend", choices=["openai", "fake", "fake_slow"])
    ap.add_argument("--latency", type=float, default=0.5, help="fake_slow 호출당 지연(초)")
    ap.add_argument("--tag", default="", help="결과 파일 접미사 (반복 측정 시 기존 결과 보존, 예: _rep2)")
    args = ap.parse_args()
    ns = [int(x) for x in args.ns.split(",")]

    qs = yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
    pool = [q["query"] for q in qs if q["category"] == "normal" and q.get("split") == "dev"]
    base_cfg = yaml.safe_load((ROOT / "eval/configs/final.yaml").read_text())
    base_cfg["cost"]["cache"] = False
    if args.backend:
        base_cfg["backend"] = args.backend
        base_cfg["fake_latency_s"] = args.latency

    out = {"config": "final (cache off)", "queries": pool[:max(ns)], "runs": []}
    warm = copy.deepcopy(base_cfg)   # 예열 1회 (임베딩 색인·모듈 로딩) — 측정에서 뺀다
    warm["name"] = "bench_warmup"
    asyncio.run(run_batch(warm, pool[:1]))
    for n in ns:
        for async_io in (False, True):
            cfg = copy.deepcopy(base_cfg)
            cfg["runtime"]["async_io"] = async_io
            cfg["name"] = f"bench_async{int(async_io)}"
            r = asyncio.run(run_batch(cfg, pool[:n]))
            r["async_io"] = async_io
            out["runs"].append(r)
            print(f"N={n:2d} async_io={async_io!s:5}  wall {r['wall_ms']/1000:6.1f}s  "
                  f"throughput {r['throughput_qps']:.2f} q/s  mean {r['latency_mean_ms']/1000:.1f}s", flush=True)
    out["backend"] = args.backend or "openai"
    if args.backend == "fake_slow":
        out["note"] = f"모의 LLM(호출당 동기 지연 {args.latency}초, 작성 {args.latency * 2}초) — 이벤트 루프 블로킹 메커니즘 검증, 실제 API 지연 아님"
    if args.backend != "fake":
        tag = ("_simulated" if args.backend == "fake_slow" else "") + args.tag
        p = ROOT / "results" / f"concurrency_bench{tag}_{datetime.now():%Y%m%d_%H%M}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        (ROOT / f"results/concurrency_bench{tag}_latest.json").write_text(p.read_text())
        print("saved", p.name)


if __name__ == "__main__":
    main()
