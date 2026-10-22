"""validate_judge_node (src/ext/graph_ext.py) — 3/4 합격 규칙, 수치 검증 선반려, 무한 루프 가드.

CLAUDE.md: 재시도 2회 또는 총 2분 중 먼저 닿는 조건에서 종료. 둘 다 반드시 둔다.
노드를 직접 호출한다 (그래프, MCP, LLM 없음).
"""
import asyncio
import time
from types import SimpleNamespace

import pytest

from ext.graph_ext import validate_judge_node
from ext.judge import METRICS

CTX_PROMPT = "## 수집된 사실\n- 모니터링 log-service: CPU 42%, 알림 1건 ['disk usage 95%']"
DRAFT = "1) 디스크 사용률 95%를 확인한다.\n2) 오래된 로그를 정리한다."


class StubJudge:
    def __init__(self, n_pass=4, fixable=True):
        self.n_pass, self.fixable, self.calls = n_pass, fixable, 0

    def evaluate(self, query, context, answer):
        self.calls += 1
        self.context = context
        v = {m: ("Pass" if i < self.n_pass else "Fail") for i, m in enumerate(METRICS)}
        return {"verdicts": v, "reasons": {m: f"{m} 사유" for m in METRICS}, "fixable": self.fixable}


class ExplodingJudge:
    def evaluate(self, *a):
        raise AssertionError("factcheck 반려 시 Judge 를 부르면 안 된다")


def run(judge, attempts_before=0, elapsed=0.0, draft=DRAFT, **jcfg):
    jcfg = {"threshold": 0.75, "max_retries": 2, "max_seconds": 120, **jcfg}
    deps = SimpleNamespace(cfg={"judge": jcfg}, judge=judge)
    state = {"query": "log-service 디스크", "draft": draft, "events": [], "last_prompt": CTX_PROMPT,
             "validation_attempts": attempts_before, "started_at": time.monotonic() - elapsed}
    return asyncio.run(validate_judge_node(state, deps=deps))


@pytest.mark.parametrize("n_pass,ok", [(4, True), (3, True), (2, False), (1, False), (0, False)])
def test_threshold_three_of_four(n_pass, ok):
    out = run(StubJudge(n_pass))
    rec = out["judge_history"][-1]
    assert rec["score"] == n_pass / 4 and rec["by"] == "judge" and rec["guard"] is None
    assert (out["validation_feedback"] is None) is ok


def test_feedback_lists_only_failed_metrics():
    out = run(StubJudge(2))
    fb = out["validation_feedback"]
    assert "domain_appropriateness: domain_appropriateness 사유" in fb and "clarity: clarity 사유" in fb
    assert "relevance:" not in fb
    assert out["events"][-1]["failed"] == ["domain_appropriateness", "clarity"]


def test_custom_threshold_one_rejects_three_of_four():
    assert run(StubJudge(3), threshold=1.0)["validation_feedback"] is not None


def test_context_comes_from_write_prompt():
    j = StubJudge()
    run(j)
    assert j.context.startswith("- 모니터링 log-service")


# --- 가드: 재시도 2회 / 120초 ------------------------------------------------

def test_retry_cap_stops_after_two_rewrites():
    out = run(StubJudge(0), attempts_before=2)          # 이번이 3번째 검증 = 재작성 2회 뒤
    rec = out["judge_history"][-1]
    assert rec["guard"] == "재시도 상한 2회" and out["validation_feedback"] is None
    assert out["events"][-1]["verdict"].startswith("통과 처리")


def test_below_retry_cap_and_time_keeps_rewriting():
    out = run(StubJudge(0), attempts_before=1, elapsed=10)
    assert out["judge_history"][-1]["guard"] is None and out["validation_feedback"]


def test_time_cap_stops_even_on_first_attempt():
    out = run(StubJudge(0), attempts_before=0, elapsed=121)
    assert out["judge_history"][-1]["guard"] == "시간 상한 120초"
    assert out["validation_feedback"] is None


def test_whichever_first_retry_cap_wins_when_both_hit():
    out = run(StubJudge(0), attempts_before=2, elapsed=500)
    assert out["judge_history"][-1]["guard"] == "재시도 상한 2회"


def test_guard_values_come_from_config():
    assert run(StubJudge(0), attempts_before=1, max_retries=1)["judge_history"][-1]["guard"] == "재시도 상한 1회"
    assert run(StubJudge(0), elapsed=31, max_seconds=30)["judge_history"][-1]["guard"] == "시간 상한 30초"


def test_missing_started_at_means_no_time_guard():
    deps = SimpleNamespace(cfg={"judge": {}}, judge=StubJudge(0))
    state = {"query": "q", "draft": DRAFT, "events": [], "last_prompt": CTX_PROMPT}
    out = asyncio.run(validate_judge_node(state, deps=deps))
    assert out["judge_history"][-1]["guard"] is None and out["validation_attempts"] == 1


def test_unfixable_skips_rewrite():
    out = run(StubJudge(0, fixable=False))
    assert out["judge_history"][-1]["guard"] == "근거 밖 요구 — 재작성 생략"
    assert out["validation_feedback"] is None


def test_pass_ignores_fixable_false():
    out = run(StubJudge(4, fixable=False))
    assert out["judge_history"][-1]["guard"] is None


# --- factcheck (judge.factcheck=true) ----------------------------------------

def test_factcheck_rejects_unsupported_number_without_calling_judge():
    out = run(ExplodingJudge(), draft="1) CPU 88%로 높다. 2) 재시작한다.", factcheck=True)
    rec = out["judge_history"][-1]
    assert rec["by"] == "factcheck" and rec["score"] == 0.0
    assert rec["factcheck_unsupported"] == [88.0]
    assert rec["verdicts"]["completeness"] == "Fail" and rec["verdicts"]["relevance"] == "Pass"
    assert "근거에 없는 수치 [88.0]" in out["validation_feedback"]


def test_factcheck_passes_supported_numbers_to_judge():
    j = StubJudge(4)
    out = run(j, factcheck=True)
    assert j.calls == 1 and out["judge_history"][-1]["factcheck_unsupported"] == []


def test_factcheck_off_does_not_block():
    j = StubJudge(4)
    out = run(j, draft="1) CPU 88%로 높다. 2) 재시작한다.")
    assert j.calls == 1 and out["judge_history"][-1]["factcheck_unsupported"] is None


def test_factcheck_reject_is_still_bounded_by_retry_cap():
    out = run(ExplodingJudge(), attempts_before=2, draft="1) CPU 88%. 2) 재시작.", factcheck=True)
    assert out["judge_history"][-1]["guard"] == "재시도 상한 2회" and out["validation_feedback"] is None


def test_history_accumulates():
    deps = SimpleNamespace(cfg={"judge": {}}, judge=StubJudge(0))
    state = {"query": "q", "draft": DRAFT, "events": [], "last_prompt": CTX_PROMPT,
             "started_at": time.monotonic(), "judge_history": [{"attempt": 1}], "validation_attempts": 1}
    out = asyncio.run(validate_judge_node(state, deps=deps))
    assert [h["attempt"] for h in out["judge_history"]] == [1, 2]
