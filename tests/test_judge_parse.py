"""Judge 응답 파싱 — 파이프라인 Judge(src/ext/judge.py)와 평가 Judge(eval/judge.py). LLM 호출 없음."""
import json
import math
from types import SimpleNamespace

import pytest

from ext import judge as J
from eval import judge as EJ

M = J.METRICS


def _all(v, fixable=None):
    d = {m: {"verdict": v, "reason": f"{m} 사유"} for m in M}
    if fixable is not None:
        d["fixable"] = fixable
    return d


def pipeline_judge(content: str, version: int = 1) -> J.OpenAIJudge:
    j = J.OpenAIJudge("gpt-4o-mini", 0.00015, version=version)
    j._chat = lambda system, user, json_mode=False: (content, {})
    return j


# --- 파이프라인 Judge (ext.judge.OpenAIJudge) -------------------------------

def test_valid_json_all_pass():
    r = pipeline_judge(json.dumps(_all("Pass"))).evaluate("q", "c", "a")
    assert r["verdicts"] == {m: "Pass" for m in M}
    assert r["reasons"]["clarity"] == "clarity 사유" and r["fixable"] is True


def test_malformed_json_becomes_all_fail_and_fixable():
    r = pipeline_judge("이건 JSON 이 아니다 {", version=2).evaluate("q", "c", "a")
    assert r["verdicts"] == {m: "Fail" for m in M}
    assert r["fixable"] is True   # 파싱 실패는 '고칠 수 없음'으로 보지 않는다 → 재작성 기회 유지


def test_missing_metric_defaults_to_fail():
    d = _all("Pass")
    del d["clarity"]
    d["relevance"] = {"reason": "verdict 키 없음"}
    r = pipeline_judge(json.dumps(d)).evaluate("q", "c", "a")
    assert r["verdicts"]["clarity"] == "Fail" and r["verdicts"]["relevance"] == "Fail"
    assert r["verdicts"]["completeness"] == "Pass"


@pytest.mark.parametrize("version,fixable,expected", [
    (2, False, False),
    (2, True, True),
    (2, None, True),    # v2 인데 fixable 키가 없으면 고칠 수 있다고 본다
    (1, False, True),   # v1 은 fixable 을 보지 않는다
])
def test_fixable_flag_by_version(version, fixable, expected):
    r = pipeline_judge(json.dumps(_all("Fail", fixable)), version=version).evaluate("q", "c", "a")
    assert r["fixable"] is expected


def test_version_selects_system_prompt():
    seen = []
    for v in (1, 2):
        j = J.OpenAIJudge("gpt-4o-mini", 0.00015, version=v)
        j._chat = lambda system, user, json_mode=False: (seen.append((system, user, json_mode)) or "{}", {})
        j.evaluate("질문", "근거", "답변")
    assert seen[0][0] == J.SYSTEM and seen[1][0] == J.SYSTEM_V2
    assert all(js for _, _, js in seen)                        # JSON 모드 요청
    assert "[Query]\n질문" in seen[0][1] and "[Answer]\n답변" in seen[0][1]


@pytest.mark.xfail(strict=True, raises=AttributeError, reason="버그: 지표 값이 dict 가 아닌 문자열('Pass')이면 "
                   "AttributeError 로 파이프라인 질의가 죽는다 (eval/judge.py 는 isinstance 로 방어함)")
def test_metric_value_as_plain_string_does_not_crash():
    r = pipeline_judge(json.dumps({m: "Pass" for m in M})).evaluate("q", "c", "a")
    assert set(r["verdicts"]) == set(M)


@pytest.mark.xfail(strict=True, raises=AttributeError, reason="버그: 유효한 JSON 이지만 객체가 아닌 배열이면 data.get 에서 AttributeError")
def test_json_array_does_not_crash():
    r = pipeline_judge("[]").evaluate("q", "c", "a")
    assert r["verdicts"] == {m: "Fail" for m in M}


@pytest.mark.xfail(strict=True, reason="버그: v2 fixable 이 문자열 \"false\" 로 오면 `is not False` 비교라 "
                   "고칠 수 있음(True)으로 처리된다")
def test_fixable_string_false_is_not_fixable():
    r = pipeline_judge(json.dumps(_all("Fail", "false")), version=2).evaluate("q", "c", "a")
    assert r["fixable"] is False


# --- FakeJudge (오프라인 백엔드) -------------------------------------------

def test_fake_judge_mirrors_original_rule():
    fj = J.FakeJudge()
    ok = fj.evaluate("q", "c", "1) 디스크 사용량을 확인하고 오래된 로그를 정리한다.")
    bad = fj.evaluate("q", "c", "짧음")
    assert set(ok["verdicts"].values()) == {"Pass"}
    assert set(bad["verdicts"].values()) == {"Fail"} and bad["fixable"] is True


# --- 근거 추출 ---------------------------------------------------------------

def test_facts_from_prompt_cuts_feedback_section():
    p = "## 지시\nx\n## 수집된 사실\n- 모니터링 A\n\n## 이전 초안에 대한 검증 반려 사유\n짧음"
    assert J.facts_from_prompt(p) == "- 모니터링 A"
    assert J.facts_from_prompt("사실 구간 없음") is None and J.facts_from_prompt(None) is None


def test_facts_from_collected_format():
    out = J.facts_from_collected([
        {"source": "monitoring", "data": {"system_name": "web-01", "status": "warning",
                                          "cpu_percent": 91, "memory_percent": 40, "alerts": ["cpu high"]}},
        {"source": "runbook", "data": "  1) 프로세스 확인  "},
        {"source": "analysis", "data": "패턴 A"},
        {"source": "unknown", "data": "무시"}])
    assert out.splitlines()[0] == "- 모니터링 web-01: 상태=warning, CPU 91%, 메모리 40%, 알림 1건 ['cpu high']"
    assert "- runbook 발췌:\n1) 프로세스 확인" in out and "- 패턴 분석: 패턴 A" in out
    assert "무시" not in out


# --- 평가 Judge (eval.judge.Judge) — 3/4 규칙, 파싱 오류 분리 -----------------

def eval_judge(content: str, threshold: float = 0.75) -> EJ.Judge:
    j = EJ.Judge.__new__(EJ.Judge)
    j.threshold = threshold
    j.chain = SimpleNamespace(invoke=lambda _: SimpleNamespace(content=content))
    return j


@pytest.mark.parametrize("n_pass,passed", [(4, True), (3, True), (2, False), (0, False)])
def test_eval_judge_threshold_three_of_four(n_pass, passed):
    d = {m: {"verdict": "Pass" if i < n_pass else "Fail", "reason": ""} for i, m in enumerate(M)}
    r = eval_judge(json.dumps(d)).evaluate("q", "c", "a")
    assert r.score == n_pass / 4 and r.passed is passed


def test_eval_judge_parse_error_is_not_counted_as_fail():
    r = eval_judge("not json").evaluate("q", "c", "a")
    assert r.passed is None and math.isnan(r.score)           # 통과율 분모에서 빠진다
    assert set(r.verdicts.values()) == {"ParseError"} and r.raw == "not json"


def test_eval_judge_strips_code_fence_and_tolerates_bad_shapes():
    body = {"relevance": "Pass", "completeness": {"verdict": "Pass"},
            "domain_appropriateness": {"verdict": "Pass"}, "clarity": {"verdict": "Pass"}}
    r = eval_judge("```json\n" + json.dumps(body) + "\n```").evaluate("q", "c", "a")
    assert r.verdicts["relevance"] == "Fail"    # 문자열 값은 형식 오류 → Fail
    assert r.score == 0.75 and r.passed is True


def test_strip_fence_variants():
    assert EJ._strip_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert EJ._strip_fence('  {"a":1}  ') == '{"a":1}'


# --- 평가 쪽 RetryGuard — 재시도 2회 / 120초 중 먼저 닿는 쪽 ------------------

def test_retry_guard_stops_on_retries(monkeypatch):
    g = EJ.RetryGuard(max_retries=2, max_seconds=120)
    assert g.should_continue() == (True, "")
    g.record()
    g.record()
    ok, why = g.should_continue()
    assert not ok and "재시도 상한 2회" in why


def test_retry_guard_stops_on_time(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(EJ.time, "monotonic", lambda: t[0])
    g = EJ.RetryGuard(max_retries=2, max_seconds=120)
    t[0] += 120.0
    ok, why = g.should_continue()
    assert not ok and "시간 상한 120초" in why and g.attempts == 0
