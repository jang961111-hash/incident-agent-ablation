"""평가 하네스(eval/run_ablation.py)가 질의 1건마다 부르는 단일 진입점.

    from src.adapter import run_once
    out = run_once("log-service 디스크가 95%입니다", cfg)

질의마다 MCP 서버 2개(원본 server.py 와 같은 구성)를 띄우고 그래프를 1회 실행한 뒤 닫는다.
latency_ms 는 그래프 실행 시간만 잰다 (MCP 기동 시간 제외).

구성별 그래프:
  base       원본 agent.graph.build_graph 를 그대로 사용 (키워드 규칙 + 규칙 Validator)
  그 외      ext.graph_ext.build_graph_ext — 플래그에 따라 노드만 교체

반환값 중 평가의 핵심 두 가지:
  retrieved  base 에서도 채운다. base 는 replan_check 가 키워드 규칙으로 고른 런북 1개,
             rag 는 임베딩 순위 상위 top_k. 같은 Recall@k·MRR 로 비교하기 위함.
  context    write 노드가 실제로 받은 '수집된 사실' 원문. 최종 답변이 아니다.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from langsmith import traceable  # noqa: E402
from langsmith.run_helpers import get_current_run_tree  # noqa: E402

from agent.fake_llm import FastLLM, QualityLLM  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.mcp_client import MCPClient  # noqa: E402
from ext.graph_ext import ExtDeps, build_graph_ext  # noqa: E402
from ext.judge import FakeJudge, OpenAIJudge, facts_from_collected, facts_from_prompt  # noqa: E402
from ext.meter import MeteredFastLLM, MeteredQualityLLM, QueryCache, start_meter  # noqa: E402
from ext.rag import LocalNgramEmbedder, OpenAIEmbedder, RunbookRetriever  # noqa: E402

RUNBOOK_DIR = SRC / "data" / "runbooks"
CACHE_DIR = ROOT / ".cache"
NO_CONTEXT = "(수집된 근거 없음 — chat 경로로 답변)"

# 구성 이름별로 프로세스 수명 동안 유지 (cost.cache 가 켜진 구성만 사용)
_CACHES: dict[str, QueryCache] = {}


def _cache_for(cfg: dict) -> QueryCache | None:
    if not cfg.get("cost", {}).get("cache"):
        return None
    return _CACHES.setdefault(cfg["name"], QueryCache(cfg["cost"].get("cache_ttl", 600)))


def _build_deps(cfg: dict, mcp: MCPClient) -> ExtDeps:
    backend = cfg.get("backend", "openai")
    models = cfg.get("models", {})
    cache = _cache_for(cfg)

    if backend == "fake":
        fast = FastLLM("fast-model-stub", usd_per_1k_tokens=0.00015)
        quality = QualityLLM("quality-model-stub", usd_per_1k_tokens=0.005)
        cheap = QualityLLM("quality-model-stub(cheap)", usd_per_1k_tokens=0.00015)
        judge = FakeJudge()
        embedder = LocalNgramEmbedder()
    else:
        # 원본 server.py 의 기본값과 같은 단가 인자 (cost_usd 상태값 호환용, 보고서 비용은 Meter 사용)
        fast = MeteredFastLLM(models.get("fast", "gpt-4o-mini"), 0.00015, cache=cache)
        quality = MeteredQualityLLM(models.get("quality", "gpt-4o"), 0.005)
        cheap = MeteredQualityLLM(models.get("cascade_writer", "gpt-4o-mini"), 0.00015)
        judge = OpenAIJudge(models.get("judge", "gpt-4o-mini"), 0.00015)
        emb_model = cfg.get("rag", {}).get("embedding", "text-embedding-3-small")
        embedder = (LocalNgramEmbedder() if emb_model == "local" else
                    OpenAIEmbedder(emb_model, os.environ.get("OPENAI_API_KEY", ""), CACHE_DIR))

    use_rag = cfg.get("runbook_selection") == "rag"
    use_judge = cfg.get("validator") == "judge"
    use_cascade = cfg.get("cost", {}).get("model_tiering", False)
    return ExtDeps(
        fast_llm=fast, quality_llm=quality, mcp=mcp, session_store=None, version="v2",
        cfg=cfg,
        retriever=RunbookRetriever(RUNBOOK_DIR, embedder, cache) if use_rag else None,
        judge=judge if use_judge else None,
        cheap_writer=cheap if use_cascade else None,
    )


def _is_base(cfg: dict) -> bool:
    return (cfg.get("runbook_selection", "keyword") == "keyword"
            and cfg.get("validator", "rule") == "rule"
            and not cfg.get("cost", {}).get("model_tiering")
            and not cfg.get("cost", {}).get("cache"))


def _retrieved(result: dict) -> list[str]:
    """선택된 런북 id, 순위 순서. RAG면 임베딩 순위, 아니면 실제로 조회한 런북 태스크 순서."""
    if result.get("rag_ranking"):
        return [rid for rid, _ in result["rag_ranking"]]
    return [t["target"] for t in result.get("tasks", []) if t.get("kind") == "runbook"]


async def _run(query: str, cfg: dict) -> dict:
    meter = start_meter()
    mcp = MCPClient()
    await mcp.start()
    try:
        deps = _build_deps(cfg, mcp)
        graph = build_graph(deps) if _is_base(cfg) else build_graph_ext(deps)
        state = {"query": query, "thread_id": f"eval-{uuid.uuid4().hex[:8]}", "history": [],
                 "events": [], "cost_usd": 0.0, "started_at": time.monotonic()}
        if _is_base(cfg):
            state.pop("started_at")   # 원본 AgentState 에 없는 키는 넣지 않는다

        @traceable(name=f"ablation:{cfg['name']}")
        async def invoke(q: str):
            res = await graph.ainvoke(state)
            rt = get_current_run_tree()
            return res, (str(rt.id) if rt else None)

        t0 = time.perf_counter()
        result, run_id = await invoke(query)
        latency_ms = (time.perf_counter() - t0) * 1000
    finally:
        await mcp.stop()

    context = (facts_from_prompt(result.get("last_prompt"))
               or (facts_from_collected(result.get("collected", [])) if result.get("collected")
                   else NO_CONTEXT))
    return {
        "answer": result.get("final", ""),
        "context": context,
        "retrieved": _retrieved(result),
        "fed_runbooks": [t["target"] for t in result.get("tasks", []) if t.get("kind") == "runbook"],
        "rewrites": max(result.get("validation_attempts", 0) - 1, 0),
        "tokens": meter.tokens(),
        "tokens_by_model": meter.by_model,
        "llm_calls": meter.calls,
        "cost_usd": meter.cost_usd(),
        "cache": {"lookups": meter.cache_lookups, "hits": meter.cache_hits},
        "latency_ms": latency_ms,
        "route": result.get("route"),
        "judge_history": result.get("judge_history", []),
        "events": result.get("events", []),
        "trace_url": f"langsmith-run:{run_id}" if run_id and os.environ.get(
            "LANGCHAIN_TRACING_V2") == "true" else None,
    }


def run_once(query: str, config: dict) -> dict:
    """질의 1건을 실행한다. 하네스가 동기 함수로 부르므로 이벤트 루프를 여기서 연다."""
    return asyncio.run(_run(query, config))
