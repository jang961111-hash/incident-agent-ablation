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
             rag 는 임베딩 순위 상위 top_k. 같은 Recall@k, MRR 로 비교하기 위함.
  context    write 노드가 실제로 받은 '수집된 사실' 원문. 최종 답변이 아니다.

위치: eval/*(run_ablation, cache_bench, fault_bench, mock_llm_bench, ollama_*)와
scripts/demo_side_by_side.py 가 부르는 유일한 실행 경로. 원본 src/agent 는 import 만 하고 고치지 않는다.

구성 파일(eval/configs/*.yaml)에서 읽는 스위치:
  backend                openai(실제 API), fake(키 없이 배관 점검), fake_slow(동기 지연 모의)
  runbook_selection      keyword | rag            → RunbookRetriever 주입 여부
  validator              rule | judge             → OpenAIJudge 주입 여부
  cost.model_tiering     캐스케이드용 저가 writer 주입 여부
  cost.cache             QueryCache 사용 여부 (route, plan, 질의 임베딩만 캐시)
  rag.embedding          text-embedding-3-small | local | local-tfidf | ollama:<모델>
  fault_injection        있으면 MCP 를 FaultyMCP 로 감싼다 (eval/fault_bench.py 전용)
네 스위치(runbook_selection, validator, model_tiering, cache)와 runtime.* 가 모두 꺼져 있으면
원본 build_graph 를 그대로 쓴다 (_is_base). 그래야 base 가 '원본 동작 그대로'인 기준선이 된다.

관련 파일: src/ext/graph_ext.py(개선 그래프), src/ext/meter.py(토큰, 비용, 캐시),
src/ext/rag.py, src/ext/judge.py, src/ext/faults.py, src/ext/slow_fake.py.
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
from ext.rag import (LocalNgramEmbedder, LocalTfidfEmbedder, OllamaEmbedder, OpenAIEmbedder,  # noqa: E402
                     RunbookRetriever)
from ext.faults import FaultyMCP  # noqa: E402

RUNBOOK_DIR = SRC / "data" / "runbooks"
CACHE_DIR = ROOT / ".cache"
NO_CONTEXT = "(수집된 근거 없음 — chat 경로로 답변)"
# 질의 1건의 절대 상한. Judge 가드(2회, 120초)는 Judge 호출 사이에서만 검사되므로,
# API 지연이 길어지는 경우까지 막는 바깥 울타리다. 넘으면 오류로 기록한다.
HARD_TIMEOUT_S = 300

# 구성 이름별로 프로세스 수명 동안 유지 (cost.cache 가 켜진 구성만 사용)
_CACHES: dict[str, QueryCache] = {}


def _cache_for(cfg: dict) -> QueryCache | None:
    """cost.cache=true 인 구성에만 캐시를 돌려준다. 구성 이름당 1개를 프로세스 동안 공유한다.

    질의마다 새 캐시를 만들면 '같은 질문을 다시 물었을 때'의 적중을 잴 수 없어서 모듈 전역에 둔다.
    반복 사이의 오염은 eval/run_ablation.py 가 반복 시작마다 _CACHES 를 비워서 막는다.
    TTL 은 cost.cache_ttl (없으면 600초).
    """
    if not cfg.get("cost", {}).get("cache"):
        return None
    return _CACHES.setdefault(cfg["name"], QueryCache(cfg["cost"].get("cache_ttl", 600)))


def _build_deps(cfg: dict, mcp: MCPClient) -> ExtDeps:
    """구성(cfg)에 맞는 LLM, Judge, 임베더, 검색기를 만들어 ExtDeps 하나로 묶는다.

    Args:
        cfg: eval/configs/*.yaml 을 읽은 dict.
        mcp: 시작된 MCP 클라이언트 (장애 주입 중이면 FaultyMCP 로 감싼 것).
    Returns:
        ExtDeps. 꺼진 기능의 자리(retriever, judge, cheap_writer)는 None 이라,
        graph_ext 는 None 여부만 보고 원본 노드를 그대로 쓴다.
    """
    backend = cfg.get("backend", "openai")
    models = cfg.get("models", {})
    cache = _cache_for(cfg)

    if backend == "fake_slow":   # 동시성 메커니즘 검증용 모의 지연 (src/ext/slow_fake.py)
        from ext.slow_fake import SlowFastLLM, SlowJudge, SlowQualityLLM
        d = cfg.get("fake_latency_s", 0.5)
        fast = SlowFastLLM("fast-stub-slow", 0.00015, d)
        quality = SlowQualityLLM("quality-stub-slow", 0.005, d)
        cheap = SlowQualityLLM("quality-stub-slow(cheap)", 0.00015, d)
        judge = SlowJudge(d)
        embedder = LocalNgramEmbedder()
    elif backend == "fake":
        fast = FastLLM("fast-model-stub", usd_per_1k_tokens=0.00015)
        quality = QualityLLM("quality-model-stub", usd_per_1k_tokens=0.005)
        cheap = QualityLLM("quality-model-stub(cheap)", usd_per_1k_tokens=0.00015)
        judge = FakeJudge()
        embedder = LocalNgramEmbedder()
        if cfg.get("fake_force_incident"):   # 장애 주입 실험용 — 라우팅과 무관하게 모든 질의를 장애 경로로
            fast.route = lambda q: ({"route": "incident", "needs_analysis": False}, fast._usage(q, "incident"))
    else:
        # 원본 server.py 의 기본값과 같은 단가 인자 (cost_usd 상태값 호환용, 보고서 비용은 Meter 사용)
        fast = MeteredFastLLM(models.get("fast", "gpt-4o-mini"), 0.00015, cache=cache)
        quality = MeteredQualityLLM(models.get("quality", "gpt-4o"), 0.005)
        cheap = MeteredQualityLLM(models.get("cascade_writer", "gpt-4o-mini"), 0.00015)
        judge = OpenAIJudge(models.get("judge", "gpt-4o-mini"), 0.00015,
                            version=cfg.get("judge", {}).get("version", 1))
        emb_model = cfg.get("rag", {}).get("embedding", "text-embedding-3-small")
        # rag.embedding 값으로 임베더를 고른다. local, local-tfidf, ollama:* 는 API 없이 도는 로컬 데모용
        embedder = (LocalNgramEmbedder() if emb_model == "local" else
                    LocalTfidfEmbedder(RUNBOOK_DIR) if emb_model == "local-tfidf" else
                    OllamaEmbedder(emb_model.split(":", 1)[1], CACHE_DIR) if emb_model.startswith("ollama:") else
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
    """개선 스위치가 하나도 켜지지 않았는지. 참이면 원본 build_graph, 원본 상태 키를 그대로 쓴다.

    fault_injection 은 여기서 보지 않는다. 장애 주입 실험에서도 base 는 원본 그래프로 돌아야
    '원본은 도구 하나가 실패하면 어떻게 되나'를 잴 수 있기 때문이다.
    """
    return (cfg.get("runbook_selection", "keyword") == "keyword"
            and cfg.get("validator", "rule") == "rule"
            and not cfg.get("cost", {}).get("model_tiering")
            and not cfg.get("cost", {}).get("cache")
            and not any(cfg.get("runtime", {}).values()))


def _retrieved(result: dict) -> list[str]:
    """선택된 런북 id, 순위 순서. RAG면 임베딩 순위, 아니면 실제로 조회한 런북 태스크 순서."""
    if result.get("rag_ranking"):
        return [rid for rid, _ in result["rag_ranking"]]
    return [t["target"] for t in result.get("tasks", []) if t.get("kind") == "runbook"]


async def _run(query: str, cfg: dict) -> dict:
    """MCP 기동 → 그래프 1회 실행 → MCP 종료 후, 평가 하네스가 쓰는 행 재료를 dict 로 돌려준다.

    질의마다 MCP 서버를 새로 띄우므로 질의 간 상태가 섞이지 않는다. 원본 MCPClient 의 기본값
    (flaky_first_tool_call=True, 첫 get_monitoring_status 1회 타임아웃 시뮬레이션)도 모든 구성이
    질의마다 똑같이 한 번씩 겪는다. 지연(latency_ms)은 그래프 실행 구간만 잰다.
    """
    mcp = MCPClient()
    await mcp.start()
    try:
        fi = cfg.get("fault_injection")
        # 장애 주입: 에이전트에게는 FaultyMCP 를 주고, 종료(stop)는 원래 클라이언트로 한다
        agent_mcp = (FaultyMCP(mcp, fi.get("tool", "get_monitoring_status"), fi["rate"],
                               fi.get("seed", 7), query) if fi else mcp)
        deps = _build_deps(cfg, agent_mcp)
        if deps.retriever is not None:
            deps.retriever._index()   # 런북 색인은 1회성 비용 — 질의 계측 전에 만든다
        meter = start_meter()
        graph = build_graph(deps) if _is_base(cfg) else build_graph_ext(deps)
        state = {"query": query, "thread_id": f"eval-{uuid.uuid4().hex[:8]}", "history": [],
                 "events": [], "cost_usd": 0.0, "started_at": time.monotonic()}
        if _is_base(cfg):
            state.pop("started_at")   # 원본 AgentState 에 없는 키는 넣지 않는다

        @traceable(name=f"ablation:{cfg['name']}")
        async def invoke(q: str):
            """그래프를 1회 실행하고 (최종 상태, LangSmith run id) 를 돌려준다.

            traceable 로 감싸 실행 1건이 트레이스 하나로 묶이게 한다. 인자 q 는 본문에서 쓰지 않고
            (실행은 바깥의 state 를 쓴다) 트레이스 입력으로만 남는다. 현재 run tree 가 없으면 run id 는 None 이다.
            """
            res = await graph.ainvoke(state)
            rt = get_current_run_tree()
            return res, (str(rt.id) if rt else None)

        t0 = time.perf_counter()
        # 바깥 울타리: 300초를 넘기면 TimeoutError 가 올라가 하네스가 오류 행으로 기록한다
        result, run_id = await asyncio.wait_for(invoke(query), timeout=HARD_TIMEOUT_S)
        latency_ms = (time.perf_counter() - t0) * 1000
    finally:
        await mcp.stop()

    # 평가 Judge 에 넘길 근거: 실제 write 프롬프트의 '수집된 사실' → (fake 백엔드처럼 프롬프트가 없으면)
    # collected 를 같은 형식으로 정리 → 둘 다 없으면 chat 경로였다는 표시
    context = (facts_from_prompt(result.get("last_prompt"))
               or (facts_from_collected(result.get("collected", [])) if result.get("collected")
                   else NO_CONTEXT))
    return {
        "answer": result.get("final", ""),
        "context": context,
        "retrieved": _retrieved(result),
        "fed_runbooks": [t["target"] for t in result.get("tasks", []) if t.get("kind") == "runbook"],
        "rewrites": max(result.get("validation_attempts", 0) - 1, 0),   # 첫 검증은 재작성이 아님
        "tokens": meter.tokens(),
        "tokens_by_model": meter.by_model,
        "llm_calls": meter.calls,
        "cost_usd": meter.cost_usd(),
        "cache": {"lookups": meter.cache_lookups, "hits": meter.cache_hits},
        "api_retries": meter.retries,
        "latency_ms": latency_ms,
        "route": result.get("route"),
        "judge_history": result.get("judge_history", []),
        "events": result.get("events", []),
        "notices": result.get("notices", []),
        "tool_failures": result.get("tool_failures", 0),
        "faults_injected": getattr(agent_mcp, "injected", 0),
        "trace_url": f"langsmith-run:{run_id}" if run_id and os.environ.get(
            "LANGCHAIN_TRACING_V2") == "true" else None,
    }


def run_once(query: str, config: dict) -> dict:
    """질의 1건을 실행한다. 하네스가 동기 함수로 부르므로 이벤트 루프를 여기서 연다."""
    return asyncio.run(_run(query, config))
