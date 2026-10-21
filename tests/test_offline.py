"""API 키 없이 도는 배관 테스트 (fake 백엔드 + 로컬 임베더 + FakeJudge).

    .venv/bin/python -m pytest -q tests/

품질 수치를 보는 테스트가 아니다. 네 구성이 끝까지 돌고, adapter 계약
(retrieved·context·rewrites)이 지켜지는지만 본다.
"""
import re
from pathlib import Path

import pytest
import yaml

from src.adapter import run_once

ROOT = Path(__file__).resolve().parent.parent
QUERY = "log-service 디스크 공간 부족 장애 진단해줘"   # fake 라우터가 incident 로 보내는 문장


def cfg(name: str) -> dict:
    c = yaml.safe_load((ROOT / "eval" / "configs" / f"{name}.yaml").read_text())
    c["backend"] = "fake"
    return c


@pytest.mark.parametrize("name", ["base", "rag", "rag_judge", "rag_judge_cost"])
def test_contract(name):
    out = run_once(QUERY, cfg(name))
    assert out["route"] == "incident"
    assert out["answer"]
    # base 에서도 retrieved 가 채워져야 Recall@k 비교가 성립한다
    assert out["retrieved"], "retrieved 비어 있음"
    assert set(out["fed_runbooks"]) <= set(p.stem for p in (ROOT / "src/data/runbooks").glob("*.md"))
    # context 는 근거 원문이어야 하고 최종 답변이면 안 된다
    assert "모니터링 log-service" in out["context"]
    assert out["context"] != out["answer"]
    assert out["rewrites"] >= 0 and out["latency_ms"] > 0


def test_base_uses_keyword_rule():
    out = run_once(QUERY, cfg("base"))
    assert out["retrieved"] == ["disk-full"]       # 알림 'disk usage 95%' → disk-full


def test_rag_ranks_top_k():
    out = run_once(QUERY, cfg("rag"))
    assert len(out["retrieved"]) == 3


def test_judge_rejects_then_accepts():
    out = run_once(QUERY, cfg("rag_judge"))
    scores = [h["score"] for h in out["judge_history"]]
    assert scores[0] < 0.75 and scores[-1] >= 0.75   # fake 1차 초안은 짧아서 반려된다


def test_cascade_writer_switches():
    out = run_once(QUERY, cfg("rag_judge_cost"))
    writers = [e.get("writer") for e in out["events"] if e["type"] == "DraftWritten"]
    assert writers[0].endswith("(cheap)") and not writers[1].endswith("(cheap)")


def test_retry_guard_stops(monkeypatch):
    """Judge 가 계속 반려해도 재시도 상한에서 멈춘다."""
    from ext import judge as J
    monkeypatch.setattr(J.FakeJudge, "evaluate", lambda self, q, c, a: {
        "verdicts": {m: "Fail" for m in J.METRICS}, "reasons": {m: "x" for m in J.METRICS}})
    out = run_once(QUERY, cfg("rag_judge"))
    assert out["rewrites"] == 2
    assert "재시도 상한" in (out["judge_history"][-1]["guard"] or "")


def test_summary_metrics_shape():
    from eval.run_ablation import build_summary
    rows = [{"id": "Q1", "category": "normal", "route": "incident", "judge_passed": True,
             "judge_score": 1.0, **{f"judge_{m}": "Pass" for m in
             ("relevance", "completeness", "domain_appropriateness", "clarity")},
             "latency_ms": 100.0, "rewrites": 0, "cost_usd": 0.01,
             "tokens": {"prompt": 10, "completion": 5}, "cache": {}},
            {"id": "Q2", "category": "normal", "route": "chat", "judge_passed": None,
             "judge_score": float("nan"), "latency_ms": 300.0, "rewrites": 0,
             "cost_usd": 0.0, "tokens": {}, "cache": {}}]
    rec = [{"retrieved": ["a"], "gold": ["a"], "fed": ["a"], "route": "incident"},
           {"retrieved": [], "gold": ["b"], "fed": [], "route": "chat"}]
    s = build_summary("t", rows, rec)
    assert s["n_judged"] == 1 and s["pass_rate"] == 1.0        # 판정 불가 건은 분모에서 제외
    assert s["latency_p50_ms"] == 200.0
    assert s["recall@1"] == 0.5 and s["recall@1|incident"] == 1.0
    assert s["fed_recall"] == 0.5 and s["fed_precision"] == 1.0
