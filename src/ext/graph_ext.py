"""개선판 그래프. 원본 agent/graph.py 의 노드 함수를 그대로 가져다 쓰고, config 플래그에
따라 세 노드만 교체한다. 그래프 연결 구조(엣지·조건 분기)는 원본과 같다.

  runbook_selection=rag      replan_check  키워드 규칙 → RAG 순위 (ext/rag.py)
  validator=judge            validate      규칙 → LLM-as-a-Judge 4지표 (ext/judge.py)
  cost.model_tiering=true    write         1차는 저가 모델, Judge 반려 시 원래 고품질 모델로 재작성

base 구성은 이 파일을 쓰지 않고 원본 build_graph 를 그대로 호출한다 (src/adapter.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph
from langsmith import traceable

from agent.deps import SupervisorDeps
from agent.graph import (AgentState, _after_replan_check, _after_route, _after_validate,
                         analysis_node, chat_answer_node, finalize_node, gate_node,
                         plan_node, replan_check_node, research_node, route_node,
                         validate_node, write_node)

from .judge import METRICS, facts_from_collected, facts_from_prompt
from .rag import select_feed


class ExtState(AgentState, total=False):
    started_at: float
    rag_ranking: list
    rag_fed: list
    judge_history: list


@dataclass
class ExtDeps(SupervisorDeps):
    cfg: dict = field(default_factory=dict)
    retriever: Any = None      # runbook_selection=rag
    judge: Any = None          # validator=judge
    cheap_writer: Any = None   # cost.model_tiering=true


@traceable(name="replan_check_rag_node")
async def replan_check_rag_node(state: ExtState, deps: ExtDeps) -> dict:
    """원본 replan_check 와 같은 판정(런북 없으면 1회 보충 조사). 보충할 런북만 RAG로 고른다."""
    has_runbook = any(c["source"] == "runbook" for c in state.get("collected", []))
    rounds = state.get("replan_rounds", 0)
    if has_runbook or rounds >= 1:
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True}
        return {"events": state["events"] + [verdict]}
    rag = deps.cfg.get("rag", {})
    ranking = deps.retriever.rank(state["query"], top_k=rag.get("top_k", 3))
    fed = select_feed(ranking, margin=rag.get("margin", 0.05))
    gap_tasks = [{"id": f"task-gap-runbook-{i}", "agent": "research", "kind": "runbook",
                  "target": rid, "status": "pending"} for i, rid in enumerate(fed)]
    verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": False,
               "selector": "rag", "gap_task": [t["id"] for t in gap_tasks], "target": fed,
               "ranking": [[rid, round(s, 4)] for rid, s in ranking]}
    return {"tasks": state["tasks"] + gap_tasks, "replan_rounds": rounds + 1,
            "rag_ranking": ranking, "rag_fed": fed,
            "events": state["events"] + [verdict]}


@traceable(name="write_cascade_node")
async def write_cascade_node(state: ExtState, deps: ExtDeps) -> dict:
    """1차 초안만 저가 모델로 쓴다. Judge가 반려하면 원래 고품질 모델로 재작성."""
    attempt = state.get("validation_attempts", 0) + 1
    use = deps if (attempt > 1 or deps.cheap_writer is None) else replace(
        deps, quality_llm=deps.cheap_writer)
    out = await write_node(state, deps=use)
    out["events"][-1] = {**out["events"][-1], "writer": use.quality_llm.name}
    return out


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
    res = deps.judge.evaluate(state["query"], context, draft)
    n_pass = sum(1 for m in METRICS if res["verdicts"][m] == "Pass")
    score = n_pass / len(METRICS)
    ok = score >= threshold
    verdict = "합격" if ok else "불합격"

    # 무한 루프 가드 — 재시도 횟수와 경과 시간 중 먼저 닿는 쪽에서 종료
    guard = None
    if not ok:
        elapsed = time.monotonic() - state.get("started_at", time.monotonic())
        if attempts - 1 >= max_retries:
            guard = f"재시도 상한 {max_retries}회"
        elif elapsed >= max_seconds:
            guard = f"시간 상한 {max_seconds}초"
        if guard:
            ok, verdict = True, f"통과 처리({guard})"

    failed = [m for m in METRICS if res["verdicts"][m] != "Pass"]
    feedback = None if ok else (
        "평가자 반려 사유를 반영해 다시 작성하라. "
        + " / ".join(f"{m}: {res['reasons'][m]}" for m in failed))
    record = {"attempt": attempts, "score": score, "verdicts": res["verdicts"],
              "reasons": res["reasons"], "guard": guard}
    event = {"type": "Validation", "validator": "judge", "attempt": attempts,
             "score": score, "failed": failed, "verdict": verdict}
    return {"validation_attempts": attempts, "validation_feedback": feedback,
            "judge_history": state.get("judge_history", []) + [record],
            "events": state["events"] + [event]}


def build_graph_ext(deps: ExtDeps):
    cfg = deps.cfg
    use_rag = cfg.get("runbook_selection") == "rag"
    use_judge = cfg.get("validator") == "judge"
    use_cascade = cfg.get("cost", {}).get("model_tiering", False)

    g = StateGraph(ExtState)
    node = lambda fn: partial(fn, deps=deps)
    g.add_node("route", node(route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("plan", node(plan_node))
    g.add_node("gate", node(gate_node))
    g.add_node("research", node(research_node))
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
