"""개선판 그래프. 원본 agent/graph.py 의 노드 함수를 그대로 가져다 쓰고, config 플래그에
따라 일부 노드만 교체한다. 그래프 연결 구조(엣지, 조건 분기)는 원본과 같다.

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
  runtime.async_io           route, plan, write, validate  동기 LLM 호출을 스레드로 빼 이벤트 루프를 막지 않음

base 구성은 이 파일을 쓰지 않고 원본 build_graph 를 그대로 호출한다 (src/adapter.py).

입력: src/adapter.py 의 ExtDeps (cfg + 구성별로 만든 LLM, 검색기, Judge).
출력: 원본 AgentState 키 + ExtState 의 추가 키(rag_ranking, judge_history, notices, tool_failures 등).
      adapter 가 이 추가 키를 결과 행(retrieved, judge_history, notices…)으로 옮긴다.
교체 노드가 원본 노드와 같은 상태 키를 읽고 쓰기 때문에, 원본 라우팅 함수(_after_route,
_after_replan_check, _after_validate)를 그대로 재사용한다. 즉 스위치를 모두 끈 build_graph_ext 는
노드 구성이 원본 build_graph 와 같다.
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
    """원본 상태에 개선판만 쓰는 키를 더한 것 (total=False: 없어도 된다)."""
    started_at: float        # adapter 가 그래프 시작 시각(monotonic)을 넣는다 — Judge 시간 상한 기준
    rag_ranking: list
    rag_fed: list            # ranking 중 margin, min_score 를 통과해 write 에 실제로 넣은 런북
    judge_history: list
    notices: list
    tool_failures: int       # tolerant_research 가 흡수한 도구 실패 수


@dataclass
class ExtDeps(SupervisorDeps):
    """원본 의존성 묶음 + 개선판 부품. 꺼진 기능의 부품은 None 으로 둔다."""
    cfg: dict = field(default_factory=dict)
    retriever: Any = None      # runbook_selection=rag
    judge: Any = None          # validator=judge
    cheap_writer: Any = None   # cost.model_tiering=true


def _async_io(deps: ExtDeps) -> bool:
    """runtime.async_io 스위치."""
    return bool(deps.cfg.get("runtime", {}).get("async_io"))


async def _call(deps: ExtDeps, fn, *args):
    """async_io 면 동기 함수를 스레드에서 돌려 이벤트 루프를 막지 않는다."""
    return await asyncio.to_thread(fn, *args) if _async_io(deps) else fn(*args)


class ThreadedWriter:
    """write/chat 은 async 메서드지만 안에서 동기 httpx 를 부른다. 통째로 스레드에서 실행한다.

    asyncio.to_thread(asyncio.run, 코루틴): 작업 스레드에서 새 이벤트 루프로 코루틴을 끝까지 돌린다.
    그 사이 메인 루프는 다른 질의의 노드를 처리할 수 있다. route, plan, analyze 같은 동기 메서드는
    __getattr__ 로 그대로 넘기고, 스레드로 빼는 일은 *_async 노드의 _call 이 맡는다.
    """

    def __init__(self, inner):
        self._inner = inner
        self.name = inner.name

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def write(self, *args, **kwargs):
        return await asyncio.to_thread(asyncio.run, self._inner.write(*args, **kwargs))

    async def chat(self, *args, **kwargs):
        return await asyncio.to_thread(asyncio.run, self._inner.chat(*args, **kwargs))


# --- route, plan (async_io 판) — 원본과 같은 로직, LLM 호출만 스레드로 ------------------

@traceable(name="route_node_async")
async def route_node_async(state: ExtState, deps: ExtDeps) -> dict:
    """원본 route_node 와 같은 출력. fast_llm.route 만 _call 로 스레드에서 부른다."""
    result, usage = await _call(deps, deps.fast_llm.route, state["query"])
    event = {"type": "RouteDecided", "route": result["route"]}
    return {"route": result["route"], "needs_analysis": result["needs_analysis"],
            "cost_usd": _cost(state, usage), "events": state.get("events", []) + [event]}


@traceable(name="plan_node_async")
async def plan_node_async(state: ExtState, deps: ExtDeps) -> dict:
    """원본 plan_node 와 같은 출력. MCP 프롬프트 조회는 원래 async, fast_llm.plan 만 스레드로."""
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
    """runtime.tolerant_research=true 일 때 원본 research_node 를 대신한다.

    원본은 태스크들을 asyncio.gather 로 묶어, 한 태스크라도 영구 실패하면 질의 전체가 예외로 끝난다.
    여기서는 태스크마다 예외를 잡아 실패한 태스크만 status=failed 로 두고, '조회 실패 — 추측하지 말 것'
    문장을 근거(collected)에 넣는다. 그래야 write 가 빈 값을 지어내지 않고 실패 사실을 답에 밝힌다.
    재시도는 원본과 같은 with_retry (TimeoutError 만, 최대 3번 시도)를 그대로 쓴다.
    """
    tasks = state["tasks"]
    idxs = [i for i, t in enumerate(tasks) if t["agent"] == "research" and t["status"] == "pending"]
    if not idxs:
        return {"events": state["events"] + [{"type": "ResearchSkipped", "reason": "pending research task 0개"}]}
    retry_total = state.get("retry_count", 0)
    runbook_server = tmpl = None
    if any(tasks[i]["kind"] != "monitoring" for i in idxs):   # 런북 태스크가 있을 때만 리소스 템플릿 조회
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
    # 1) 질의 임베딩으로 런북 순위 top_k (Recall@k, MRR 은 이 순위로 잰다)
    ranking = await _call(deps, deps.retriever.rank, state["query"], rag.get("top_k", 3))
    # 2) 1위 점수 - margin 이내만 투입 후보 (복합 장애면 2개, 단일이면 대개 1개)
    fed = select_feed(ranking, margin=rag.get("margin", 0.05))

    # v2 — 최소 유사도, 안내 문구
    notices = []
    min_score = rag.get("min_score")
    if min_score is not None:
        # 3) 절대 기준: 유사도가 rag.min_score 미만이면 '맞는 런북 없음'으로 본다. margin 은 1위와의
        #    상대 거리라서, 1위 자체가 엉뚱한 경우(미등록, 모호 질의)를 거르지 못한다.
        #    값은 dev 질의만으로 eval/calibrate_rag.py 가 정했고, 임베더마다 척도가 달라 구성마다 다르다.
        fed = [rid for rid, s in ranking if rid in fed and s >= min_score]
        if not fed:
            notices.append(f"등록된 런북 중 질문과 일치하는 절차가 없음 (최고 유사도 {ranking[0][1]:.3f} < "
                           f"기준 {min_score:.3f}). 추측한 절차를 쓰지 말고, 확인한 모니터링 범위만 전한 뒤 "
                           f"대상 시스템과 증상을 되물을 것.")
    # 원본 _extract_system_name 은 질의에 등록 시스템이 없으면 auth-service 로 폴백한다 — 그 사실을 근거에 밝힌다
    if rag.get("notices") and not any(s in state["query"] for s in KNOWN_SYSTEMS):
        notices.append("질문에 등록된 모니터링 대상 시스템 이름이 없어 auth-service 를 기본으로 조회함 — "
                       "질문 대상과 다를 수 있음을 밝힐 것.")
    # 안내 문구는 source=analysis 로 넣는다 — 원본 write 프롬프트가 이 항목을 '패턴 분석'으로 그대로 싣는다
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
    """1차 초안만 저가 모델로 쓴다. 반려되면 원래 고품질 모델로 재작성.

    cost.model_tiering=true 일 때 원본 write_node 를 감싼다. 1차(attempt=1)는 models.cascade_writer
    (구성 기본 gpt-4o-mini), 검증 반려 후 재작성(attempt>=2)은 models.quality(gpt-4o)로 올린다.
    1차에서 통과하면 비싼 모델을 아예 부르지 않는다. 품질 대가는 Ablation(rag_judge →
    rag_judge_cost)에서 따로 잰다. 어떤 모델이 썼는지는 DraftWritten 이벤트의 writer 로 남긴다.
    """
    attempt = state.get("validation_attempts", 0) + 1
    # 캐스케이드 승급: 재작성이거나 저가 writer 가 없으면 원래 deps(고품질), 1차면 quality_llm 만 바꿔 끼운다
    use = deps if (attempt > 1 or deps.cheap_writer is None) else replace(
        deps, quality_llm=deps.cheap_writer)
    out = await write_node(state, deps=use)
    out["events"][-1] = {**out["events"][-1], "writer": use.quality_llm.name}
    return out


# --- validate (Judge) -----------------------------------------------------------------

@traceable(name="validate_judge_node")
async def validate_judge_node(state: ExtState, deps: ExtDeps) -> dict:
    """validator=judge 일 때 원본 규칙 Validator(30자 + "1)")를 대신한다.

    순서: (judge.factcheck 면) 코드 수치 검증 → LLM Judge 4지표 → 합격 판정 → 루프 가드.
    합격: 4지표 중 Pass 비율 >= judge.threshold (구성값 0.75 → 4개 중 3개 이상).
    불합격이면 실패 지표의 사유를 validation_feedback 으로 넘기고, 원본 _after_validate 가
    feedback 유무만 보고 write 로 되돌린다. 가드에 걸리면 feedback=None 으로 '통과 처리'해 루프를 끝낸다.
    가드 (먼저 닿는 쪽):
      - fixable=false (Judge v2): 근거 밖 정보가 있어야 고칠 수 있음 → 재작성해도 나아지지 않으므로 생략
      - 재시도 상한 judge.max_retries (구성값 2): 재작성 2회 = 초안 최대 3개
      - 시간 상한 judge.max_seconds (구성값 120초): 질의 시작(started_at)부터 잰 누적 시간
    시간 상한은 검증 시점에만 검사하므로, 긴 API 호출 한 번은 막지 못한다 — 그건 adapter 의 HARD_TIMEOUT_S 몫.
    """
    jcfg = deps.cfg.get("judge", {})
    threshold = jcfg.get("threshold", 0.75)
    max_retries = jcfg.get("max_retries", 2)
    max_seconds = jcfg.get("max_seconds", 120)

    draft = state["draft"]
    attempts = state.get("validation_attempts", 0) + 1
    context = (facts_from_prompt(state.get("last_prompt"))
               or facts_from_collected(state.get("collected", [])))

    # 평가 Judge 와 같은 근거 원문(write 가 받은 '수집된 사실')으로 검증한다
    fc = factcheck(draft, context) if jcfg.get("factcheck") else None
    if fc is not None and not fc["ok"]:
        # 근거 없는 수치 — LLM Judge 를 부르지 않고 코드에서 바로 반려
        res = {"verdicts": {m: ("Fail" if m == "completeness" else "Pass") for m in METRICS},
               "reasons": {m: (f"근거에 없는 수치 {fc['unsupported']}" if m == "completeness" else "")
                           for m in METRICS},
               "fixable": True}   # 수치는 근거 안에서 고칠 수 있으므로 재작성 대상
        score, ok, by = 0.0, False, "factcheck"   # score 0 = Judge 를 거치지 않은 코드 반려 표시
    else:
        res = await _call(deps, deps.judge.evaluate, state["query"], context, draft)
        n_pass = sum(1 for m in METRICS if res["verdicts"][m] == "Pass")
        # 3/4 규칙: threshold 0.75 면 Pass 3개(0.75) 이상 합격. 지표 하나의 흔들림으로 재작성하지 않게 한다
        score, ok, by = n_pass / len(METRICS), n_pass / len(METRICS) >= threshold, "judge"
    verdict = "합격" if ok else "불합격"

    guard = None
    if not ok:
        elapsed = time.monotonic() - state.get("started_at", time.monotonic())
        if not res.get("fixable", True):
            guard = "근거 밖 요구 — 재작성 생략"
        elif attempts - 1 >= max_retries:   # attempts-1 = 지금까지 재작성 횟수
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
    """스위치에 따라 노드 함수만 고르고, 엣지, 조건 분기는 원본 build_graph 와 같게 연결한다.

    스위치 → 교체 노드
      runtime.async_io          route, plan → *_async, LLM 객체 → ThreadedWriter
      runtime.tolerant_research research → research_tolerant_node
      runbook_selection=rag     replan_check → replan_check_rag_node
      cost.model_tiering        write → write_cascade_node
      validator=judge           validate → validate_judge_node
    chat_answer, gate, analysis, finalize 는 항상 원본 노드다.
    """
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
