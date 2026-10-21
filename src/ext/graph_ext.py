"""개선판 그래프. 원본 agent/graph.py 의 노드 함수를 그대로 가져다 쓰고, config 플래그에
따라 일부 노드만 교체한다. 그래프 연결 구조(엣지·조건 분기)는 원본과 같다.

v1 (1차 실측)
  runbook_selection=rag      replan_check  키워드 규칙 → RAG 순위 (ext/rag.py)
  validator=judge            validate      규칙 → LLM-as-a-Judge 4지표 (ext/judge.py)
  cost.model_tiering=true    write         1차는 저가 모델, Judge 반려 시 원래 고품질 모델로 재작성

v2 (1차 실측에서 찾은 약점 보완, 모두 플래그)
  rag.min_score              replan_check  최소 유사도 미만이면 런북을 넣지 않고 '일치 런북 없음' 안내
  rag.notices                replan_check  질의에 등록 시스템이 없어 폴백 조회했음을 근거에 명시
  judge.version=2            validate      근거 밖 요구 금지 + fixable 판정, 고칠 수 없으면 재작성 생략
  judge.factcheck            validate      답변 수치를 코드로 먼저 대조, 근거 없는 수치는 Judge 없이 반려
  runtime.tolerant_research  research      도구 일부 실패 시 성공한 결과는 살리고 실패를 근거에 명시
  runtime.async_io           route·plan·write·validate  동기 LLM 호출을 스레드로 빼 이벤트 루프를 막지 않음

base 구성은 이 파일을 쓰지 않고 원본 build_graph 를 그대로 호출한다 (src/adapter.py).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph
from langsmith import traceable

from agent.deps import SupervisorDeps
from agent.graph import (KNOWN_SYSTEMS, AgentState, _after_replan_check, _after_route,
                         _after_validate, _cost, _extract_system_name, analysis_node,
                         chat_answer_node, finalize_node, gate_node, plan_node,
                         replan_check_node, research_node, route_node, validate_node,
                         write_node)
from agent.retry import with_retry

from .factcheck import check as factcheck
from .judge import METRICS, facts_from_collected, facts_from_prompt
from .rag import select_feed


class ExtState(AgentState, total=False):
    started_at: float
    rag_ranking: list
    rag_fed: list
    judge_history: list
    notices: list
    tool_failures: int


@dataclass
class ExtDeps(SupervisorDeps):
    cfg: dict = field(default_factory=dict)
    retriever: Any = None      # runbook_selection=rag
    judge: Any = None          # validator=judge
    cheap_writer: Any = None   # cost.model_tiering=true


def _async_io(deps: ExtDeps) -> bool:
    return bool(deps.cfg.get("runtime", {}).get("async_io"))


async def _call(deps: ExtDeps, fn, *args):
    """async_io 면 동기 함수를 스레드에서 돌려 이벤트 루프를 막지 않는다."""
    return await asyncio.to_thread(fn, *args) if _async_io(deps) else fn(*args)


class ThreadedWriter:
    """write/chat 은 async 메서드지만 안에서 동기 httpx 를 부른다. 통째로 스레드에서 실행한다."""

    def __init__(self, inner):
        self._inner = inner
        self.name = inner.name

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def write(self, *args, **kwargs):
        return await asyncio.to_thread(asyncio.run, self._inner.write(*args, **kwargs))

    async def chat(self, *args, **kwargs):
        return await asyncio.to_thread(asyncio.run, self._inner.chat(*args, **kwargs))


# --- route · plan (async_io 판) — 원본과 같은 로직, LLM 호출만 스레드로 ------------------

@traceable(name="route_node_async")
async def route_node_async(state: ExtState, deps: ExtDeps) -> dict:
    result, usage = await _call(deps, deps.fast_llm.route, state["query"])
    event = {"type": "RouteDecided", "route": result["route"]}
    return {"route": result["route"], "needs_analysis": result["needs_analysis"],
            "cost_usd": _cost(state, usage), "events": state.get("events", []) + [event]}


@traceable(name="plan_node_async")
async def plan_node_async(state: ExtState, deps: ExtDeps) -> dict:
    prompt_server = await deps.mcp.find_prompt("incident_analysis_prompt")
    procedure = await deps.mcp.get_prompt(
        "incident_analysis_prompt",
        {"system_name": _extract_system_name(state["query"]), "symptom": state["query"]},
        server=prompt_server)
    result, usage = await _call(deps, deps.fast_llm.plan, state["query"], procedure)
    targets = [t["target"] for t in result["tasks"] if t["agent"] == "research" and t.get("target")]
    event = {"type": "PlanCreated", "task_count": len(result["tasks"]), "targets": targets}
    return {"tasks": result["tasks"], "needs_analysis": result["needs_analysis"],
            "cost_usd": _cost(state, usage), "events": state["events"] + [event]}


# --- research (부분 실패 허용판) — 원본 research_node 와 같은 흐름, 태스크별 예외만 흡수 -------

@traceable(name="research_tolerant_node")
async def research_tolerant_node(state: ExtState, deps: ExtDeps) -> dict:
    tasks = state["tasks"]
    idxs = [i for i, t in enumerate(tasks) if t["agent"] == "research" and t["status"] == "pending"]
    if not idxs:
        return {"events": state["events"] + [{"type": "ResearchSkipped", "reason": "pending research task 0개"}]}
    retry_total = state.get("retry_count", 0)
    runbook_server = tmpl = None
    if any(tasks[i]["kind"] != "monitoring" for i in idxs):
        runbook_server, tmpl = await deps.mcp.find_resource_template("get_incident_runbook")

    async def run_one(idx: int) -> dict:
        task = tasks[idx]
        await asyncio.sleep(0.35)   # 원본과 같은 고정 지연
        try:
            if task["kind"] == "monitoring":
                data, retries = await with_retry(deps.mcp.call_tool, "get_monitoring_status",
                                                 {"system_name": task["target"]})
                return {"idx": idx, "source": "monitoring", "data": data, "retries": retries}
            data = await deps.mcp.read_resource(tmpl.format(incident_type=task["target"]),
                                                server=runbook_server)
            return {"idx": idx, "source": "runbook", "data": data, "retries": 0}
        except Exception as e:   # 이 태스크만 실패로 남기고 나머지는 살린다
            return {"idx": idx, "error": f"{type(e).__name__}: {e}", "retries": 0}

    started = time.perf_counter()
    results = await asyncio.gather(*(run_one(i) for i in idxs))
    elapsed = round(time.perf_counter() - started, 2)

    new_tasks = [dict(t) for t in tasks]
    collected = list(state.get("collected", []))
    events = list(state["events"])
    failures = state.get("tool_failures", 0)
    for r in results:
        t = new_tasks[r["idx"]]
        if "error" in r:
            t["status"] = "failed"
            failures += 1
            collected.append({"source": "analysis",
                              "data": f"{t['target']} {t['kind']} 조회 실패 — 이 대상의 값은 없음. 추측하지 말 것."})
            events.append({"type": "TaskFailed", "id": t["id"], "target": t["target"], "error": r["error"]})
            continue
        t["status"] = "done"
        collected.append({"source": r["source"], "data": r["data"]})
        retry_total += r["retries"]
        events.append({"type": "TaskCompleted", "id": t["id"], "source": r["source"],
                       "target": t["target"], "retries": r["retries"]})
    return {"tasks": new_tasks, "collected": collected, "retry_count": retry_total,
            "parallel_elapsed": elapsed, "tool_failures": failures, "events": events}


# --- replan_check (RAG) ---------------------------------------------------------------

@traceable(name="replan_check_rag_node")
async def replan_check_rag_node(state: ExtState, deps: ExtDeps) -> dict:
    """원본 replan_check 와 같은 판정(런북 없으면 1회 보충 조사). 보충할 런북만 RAG로 고른다."""
    has_runbook = any(c["source"] == "runbook" for c in state.get("collected", []))
    rounds = state.get("replan_rounds", 0)
    if has_runbook or rounds >= 1:
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True}
        return {"events": state["events"] + [verdict]}
    rag = deps.cfg.get("rag", {})
    ranking = await _call(deps, deps.retriever.rank, state["query"], rag.get("top_k", 3))
    fed = select_feed(ranking, margin=rag.get("margin", 0.05))

    # v2 — 최소 유사도, 안내 문구
    notices = []
    min_score = rag.get("min_score")
    if min_score is not None:
        fed = [rid for rid, s in ranking if rid in fed and s >= min_score]
        if not fed:
            notices.append(f"등록된 런북 중 질문과 일치하는 절차가 없음 (최고 유사도 {ranking[0][1]:.3f} < "
                           f"기준 {min_score:.3f}). 추측한 절차를 쓰지 말고, 확인한 모니터링 범위만 전한 뒤 "
                           f"대상 시스템과 증상을 되물을 것.")
    if rag.get("notices") and not any(s in state["query"] for s in KNOWN_SYSTEMS):
        notices.append("질문에 등록된 모니터링 대상 시스템 이름이 없어 auth-service 를 기본으로 조회함 — "
                       "질문 대상과 다를 수 있음을 밝힐 것.")
    collected = state.get("collected", []) + [{"source": "analysis", "data": n} for n in notices]

    gap_tasks = [{"id": f"task-gap-runbook-{i}", "agent": "research", "kind": "runbook",
                  "target": rid, "status": "pending"} for i, rid in enumerate(fed)]
    verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": not gap_tasks,
               "selector": "rag", "gap_task": [t["id"] for t in gap_tasks], "target": fed,
               "ranking": [[rid, round(s, 4)] for rid, s in ranking], "notices": len(notices)}
    return {"tasks": state["tasks"] + gap_tasks, "replan_rounds": rounds + 1,
            "rag_ranking": ranking, "rag_fed": fed, "collected": collected,
            "notices": state.get("notices", []) + notices,
            "events": state["events"] + [verdict]}


# --- write (캐스케이드) -----------------------------------------------------------------

@traceable(name="write_cascade_node")
async def write_cascade_node(state: ExtState, deps: ExtDeps) -> dict:
    """1차 초안만 저가 모델로 쓴다. 반려되면 원래 고품질 모델로 재작성."""
    attempt = state.get("validation_attempts", 0) + 1
    use = deps if (attempt > 1 or deps.cheap_writer is None) else replace(
        deps, quality_llm=deps.cheap_writer)
    out = await write_node(state, deps=use)
    out["events"][-1] = {**out["events"][-1], "writer": use.quality_llm.name}
    return out


# --- validate (Judge) -----------------------------------------------------------------

@traceable(name="validate_judge_node")
async def validate_judge_node(state: ExtState, deps: ExtDeps) -> dict:
    jcfg = deps.cfg.get("judge", {})
    threshold = jcfg.get("threshold", 0.75)
    max_retries = jcfg.get("max_retries", 2)
    max_seconds = jcfg.get("max_seconds", 120)

    draft = state["draft"]
    attempts = state.get("validation_attempts", 0) + 1
    context = (facts_from_prompt(state.get("last_prompt"))
               or facts_from_collected(state.get("collected", [])))

    fc = factcheck(draft, context) if jcfg.get("factcheck") else None
    if fc is not None and not fc["ok"]:
        # 근거 없는 수치 — LLM Judge 를 부르지 않고 코드에서 바로 반려
        res = {"verdicts": {m: ("Fail" if m == "completeness" else "Pass") for m in METRICS},
               "reasons": {m: (f"근거에 없는 수치 {fc['unsupported']}" if m == "completeness" else "")
                           for m in METRICS},
               "fixable": True}
        score, ok, by = 0.0, False, "factcheck"
    else:
        res = await _call(deps, deps.judge.evaluate, state["query"], context, draft)
        n_pass = sum(1 for m in METRICS if res["verdicts"][m] == "Pass")
        score, ok, by = n_pass / len(METRICS), n_pass / len(METRICS) >= threshold, "judge"
    verdict = "합격" if ok else "불합격"

    guard = None
    if not ok:
        elapsed = time.monotonic() - state.get("started_at", time.monotonic())
        if not res.get("fixable", True):
            guard = "근거 밖 요구 — 재작성 생략"
        elif attempts - 1 >= max_retries:
            guard = f"재시도 상한 {max_retries}회"
        elif elapsed >= max_seconds:
            guard = f"시간 상한 {max_seconds}초"
        if guard:
            ok, verdict = True, f"통과 처리({guard})"

    failed = [m for m in METRICS if res["verdicts"][m] != "Pass"]
    feedback = None if ok else (
        "평가자 반려 사유를 반영해 다시 작성하라. "
        + " / ".join(f"{m}: {res['reasons'][m]}" for m in failed))
    record = {"attempt": attempts, "score": score, "by": by, "verdicts": res["verdicts"],
              "reasons": res["reasons"], "fixable": res.get("fixable", True), "guard": guard,
              "factcheck_unsupported": fc["unsupported"] if fc else None}
    event = {"type": "Validation", "validator": by, "attempt": attempts,
             "score": score, "failed": failed, "verdict": verdict}
    return {"validation_attempts": attempts, "validation_feedback": feedback,
            "judge_history": state.get("judge_history", []) + [record],
            "events": state["events"] + [event]}


def build_graph_ext(deps: ExtDeps):
    cfg = deps.cfg
    rt = cfg.get("runtime", {})
    if rt.get("async_io"):   # write/chat 의 동기 HTTP 호출을 스레드로
        deps = replace(deps, fast_llm=ThreadedWriter(deps.fast_llm),
                       quality_llm=ThreadedWriter(deps.quality_llm),
                       cheap_writer=ThreadedWriter(deps.cheap_writer) if deps.cheap_writer else None)
        # ThreadedWriter 는 route/plan 을 그대로 위임한다 (async 판 노드가 스레드로 부름)
    use_rag = cfg.get("runbook_selection") == "rag"
    use_judge = cfg.get("validator") == "judge"
    use_cascade = cfg.get("cost", {}).get("model_tiering", False)

    g = StateGraph(ExtState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("route", node(route_node_async if rt.get("async_io") else route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("plan", node(plan_node_async if rt.get("async_io") else plan_node))
    g.add_node("gate", node(gate_node))
    g.add_node("research", node(research_tolerant_node if rt.get("tolerant_research") else research_node))
    g.add_node("replan_check", node(replan_check_rag_node if use_rag else replan_check_node))
    g.add_node("analysis", node(analysis_node))
    g.add_node("write", node(write_cascade_node if use_cascade else write_node))
    g.add_node("validate", node(validate_judge_node if use_judge else validate_node))
    g.add_node("finalize", node(finalize_node))

    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route, {"chat_answer": "chat_answer", "plan": "plan"})
    g.add_edge("chat_answer", END)
    g.add_edge("plan", "gate")
    g.add_edge("gate", "research")
    g.add_edge("research", "replan_check")
    g.add_conditional_edges("replan_check", _after_replan_check,
                            {"analysis": "analysis", "research": "research"})
    g.add_edge("analysis", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate, {"finalize": "finalize", "write": "write"})
    g.add_edge("finalize", END)
    return g.compile()
