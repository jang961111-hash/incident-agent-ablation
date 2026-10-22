"""평가 지표 — 누락/혼입, 검색 지표, 어구 포함률, 반복 집계, paired bootstrap. 합성 데이터만 쓴다."""
import math

import pytest

from eval import extra_metrics as X
from eval import retrieval_metrics as RM
from eval import stats as S
from eval.answer_metrics import must_include_scores
from eval.run_ablation import _agg, _pct, aggregate

QS = {"A": {"design_note": "aligned"}, "B": {"design_note": "paraphrased"}, "C": {}, "D": {}}


def row(id, fed, gold, route="incident", rep=1, retrieved=None, cost=0.01, split="holdout", **kw):
    return {"id": id, "fed_runbooks": fed, "gold": gold, "route": route, "rep": rep, "split": split,
            "retrieved": retrieved if retrieved is not None else fed, "cost_usd": cost, **kw}


# --- 누락 / 혼입 (extra_metrics) ----------------------------------------------------

def test_miss_and_wrong_definitions():
    assert X._miss(row("A", ["cpu-spike"], ["db-down"])) is True
    assert X._miss(row("A", ["db-down", "cpu-spike"], ["db-down"])) is False
    assert X._wrong(row("A", ["db-down", "cpu-spike"], ["db-down"])) is True    # 정답 + 무관 혼입
    assert X._wrong(row("A", ["db-down"], ["db-down"])) is False
    assert X._wrong(row("C", ["db-down"], [])) is True        # 정답 없는 질의에 런북을 넣음
    assert X._wrong(row("C", [], [])) is False


def test_compute_rates_counts_only_incident_routes():
    rows = [row("A", ["db-down"], ["db-down"]),                       # 정상
            row("B", ["cpu-spike"], ["memory-leak"]),                 # 누락 + 혼입
            row("C", ["disk-full"], []),                              # 정답 없음 → 혼입
            row("D", [], ["db-down"], route="chat"),                  # chat 경로 — 분모 제외
            {"id": "A", "rep": 1, "split": "holdout", "error": "boom"}]  # 오류 행 제외
    m = X.compute(rows, QS)
    assert m["incident_n"] == 3
    assert m["miss_runbook_rate"] == pytest.approx(1 / 2)    # 정답 있는 장애 질의 A,B 중 B
    assert m["wrong_runbook_rate"] == pytest.approx(2 / 3)
    assert m["wrong_runbook_n"] == 2
    assert m["cost_per_incident"] == pytest.approx(0.04 / 3)  # 비용은 chat 포함 합 / 장애 건수
    assert m["recall@1[aligned]"] == 1.0 and m["recall@1[paraphrased]"] == 0.0


def test_compute_averages_over_reps_and_filters_split():
    rows = [row("A", ["db-down"], ["db-down"], rep=1), row("A", ["x"], ["db-down"], rep=2),
            row("A", ["x"], ["db-down"], rep=1, split="dev")]
    assert X.compute(rows, QS, split="holdout")["miss_runbook_rate"] == pytest.approx(0.5)
    assert X.compute(rows, QS, split="dev")["miss_runbook_rate"] == 1.0


def test_compute_ignores_nan_cost():
    rows = [row("A", ["db-down"], ["db-down"], cost=float("nan")), row("B", [], ["x"], cost=0.02)]
    assert X.compute(rows, QS)["cost_per_incident"] == pytest.approx(0.01)


# --- 검색 지표 ---------------------------------------------------------------

def test_recall_hit_mrr():
    assert RM.recall_at_k(["a", "b", "c"], ["b", "z"], 1) == 0.0
    assert RM.recall_at_k(["a", "b", "c"], ["b", "z"], 3) == 0.5
    assert math.isnan(RM.recall_at_k(["a"], [], 1))
    assert RM.hit_at_k(["a", "b"], ["b"], 2) == 1 and RM.hit_at_k(["a", "b"], ["b"], 1) == 0
    assert RM.hit_at_k(["a"], [], 1) == 0
    assert RM.mrr(["a", "b", "c"], ["c"]) == pytest.approx(1 / 3) and RM.mrr(["a"], ["z"]) == 0.0


def test_retrieval_summarize():
    s = RM.summarize([{"retrieved": ["a", "b"], "gold": ["a"]},
                      {"retrieved": ["x", "b"], "gold": ["b"]}])
    assert s["recall@1"] == 0.5 and s["hit@3"] == 1.0 and s["mrr"] == pytest.approx(0.75)


# --- must_include 어구 포함률 ----------------------------------------------------

def test_must_include_scores_case_insensitive():
    qs = {"Q1": {"must_include": ["Failover", "커넥션 풀"]}, "Q2": {"must_include": []}}
    rows = [{"id": "Q1", "answer": "failover 를 수행하고 커넥션 풀을 늘린다"},
            {"id": "Q1", "answer": "재시작한다"}, {"id": "Q2", "answer": "x"}, {"id": "Q1"}]
    s = must_include_scores(rows, qs)
    assert s["must_phrase_rate"] == pytest.approx(2 / 4) and s["must_all_rate"] == pytest.approx(1 / 1)
    assert s["per_query"]["Q1"] == "0/2" and s["n_must"] == 1   # per_query 는 id 기준 마지막 값


# --- 반복 집계 (run_ablation) --------------------------------------------------

def test_percentile_linear_interpolation():
    assert _pct([100.0, 300.0], 0.5) == 200.0
    assert _pct([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)
    assert math.isnan(_pct([], 0.5))


def test_agg_t_distribution_ci():
    a = _agg([{"x": 1.0, "flag": True}, {"x": 2.0}, {"x": 3.0}])
    assert a["x"]["mean"] == 2.0 and a["x"]["sd"] == 1.0 and a["x"]["n_reps"] == 3
    assert a["x"]["ci95"] == pytest.approx(4.303 / math.sqrt(3))
    assert "flag" not in a                                   # bool 은 집계 대상 아님
    single = _agg([{"x": 5.0}])["x"]
    assert single["sd"] == 0.0 and math.isnan(single["ci95"])


def _full_row(id, rep, passed, split="holdout", gold=("db-down",), fed=("db-down",)):
    return {"id": id, "rep": rep, "split": split, "category": "normal", "route": "incident",
            "judge_passed": passed, "judge_score": 1.0 if passed else 0.5,
            **{f"judge_{m}": "Pass" for m in ("relevance", "completeness", "domain_appropriateness", "clarity")},
            "latency_ms": 100.0, "rewrites": 0, "cost_usd": 0.01, "tokens": {}, "cache": {},
            "retrieved": list(fed), "gold": list(gold), "fed_runbooks": list(fed), "must_total": 2,
            "must_hit": 1, "unsupported_numbers": [], "llm_calls": [{"stage": "judge"}], "pipeline_judge": []}


def test_aggregate_by_rep_and_split():
    rows = [_full_row("Q1", 1, True), _full_row("Q2", 1, False, split="dev"),
            _full_row("Q1", 2, False), _full_row("Q2", 2, False, split="dev")]
    s = aggregate("t", rows, reps=2)
    assert len(s["per_rep"]) == 2 and s["pass_rate"] == pytest.approx(0.25)
    assert s["by_split"]["holdout"]["mean"]["pass_rate"] == pytest.approx(0.5)
    assert s["by_split"]["dev"]["mean"]["pass_rate"] == 0.0
    assert s["must_phrase_rate"] == 0.5 and s["judge_calls"] == 2


# --- paired bootstrap (eval/stats) -------------------------------------------

def _pq(vals):
    return {f"q{i}": {"m": v} for i, v in enumerate(vals)}


def test_bootstrap_is_deterministic_with_seed():
    a, b = _pq([0, 1, 0, 1, 0, 0, 1, 0]), _pq([1, 1, 0, 1, 1, 0, 1, 1])
    r1, r2 = S.bootstrap(a, b, "m", seed=0), S.bootstrap(a, b, "m", seed=0)
    assert r1 == r2 and r1["n"] == 8 and r1["diff"] == pytest.approx(3 / 8)
    assert r1["lo"] <= r1["diff"] <= r1["hi"]
    r3 = S.bootstrap(a, b, "m", seed=1)
    assert r3["diff"] == r1["diff"] and r3["n"] == r1["n"]    # 점추정은 seed 와 무관, 구간만 재표집


def test_bootstrap_identical_configs_not_significant():
    a = _pq([0.2, 0.5, 0.9, 0.1])
    r = S.bootstrap(a, a, "m")
    assert r["diff"] == 0 and r["lo"] == 0 and r["hi"] == 0 and r["significant"] is False


def test_bootstrap_all_positive_diffs_significant():
    r = S.bootstrap(_pq([0] * 10), _pq([1] * 10), "m")
    assert r["significant"] is True and r["lo"] == 1.0


def test_bootstrap_skips_none_and_unpaired():
    a = {"q1": {"m": 0.0}, "q2": {"m": None}, "q3": {"m": 1.0}}
    b = {"q1": {"m": 1.0}, "q2": {"m": 1.0}}
    r = S.bootstrap(a, b, "m")
    assert r["n"] == 1 and r["diff"] == 1.0
    assert S.bootstrap({"q": {"m": None}}, {"q": {"m": 1}}, "m") is None


def test_per_query_averages_reps_and_routes():
    rows = [{"id": "Q1", "gold": ["a"], "judge_passed": True, "must_hit": 1, "must_total": 2,
             "retrieved": ["a"], "fed_runbooks": ["a"], "route": "incident", "cost_usd": 0.1, "latency_ms": 1000},
            {"id": "Q1", "gold": ["a"], "judge_passed": False, "must_hit": 2, "must_total": 2,
             "retrieved": ["b"], "fed_runbooks": ["b"], "route": "incident", "cost_usd": 0.3, "latency_ms": 3000},
            {"id": "Q2", "gold": [], "judge_passed": None, "must_hit": 0, "must_total": 0,
             "retrieved": [], "fed_runbooks": [], "route": "chat", "cost_usd": 0.0, "latency_ms": 500},
            {"id": "Q3", "error": "x"}]
    pq = S._per_query(rows)
    assert set(pq) == {"Q1", "Q2"}
    q1 = pq["Q1"]
    assert q1["pass"] == 0.5 and q1["must"] == 0.75 and q1["hit1"] == 0.5
    assert q1["miss"] == 0.5 and q1["wrong"] == 0.5 and q1["cost"] == pytest.approx(0.2) and q1["latency"] == 2.0
    q2 = pq["Q2"]
    assert q2["pass"] is None and q2["must"] is None and q2["miss"] is None and q2["wrong"] is None


def test_stats_fmt():
    r = {"diff": 0.123, "lo": 0.05, "hi": 0.2, "significant": True}
    assert S.fmt(r, "pass") == "+12 [+5, +20] *"
    assert S.fmt(None, "pass") == "-"
    assert S.fmt({"diff": -0.0012, "lo": -0.002, "hi": 0.0001, "significant": False}, "cost") == \
        "-0.0012 [-0.0020, +0.0001]"
