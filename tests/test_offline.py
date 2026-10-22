"""API 키 없이 도는 배관 테스트 (fake 백엔드 + 로컬 임베더 + FakeJudge).

    .venv/bin/python -m pytest -q tests/

품질 수치를 보는 테스트가 아니다. 네 구성이 끝까지 돌고, adapter 계약
(retrieved, context, rewrites)이 지켜지는지만 본다.
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


def test_cache_does_not_leak_across_reps(tmp_path, monkeypatch):
    """반복마다 캐시를 비워야 한다 — 앞 반복의 캐시가 다음 반복 비용, 지연을 낮추면 안 된다."""
    import eval.run_ablation as ra
    monkeypatch.setattr(ra, "RESULTS", tmp_path)
    qs = [{"id": "T1", "query": QUERY, "gold_runbooks": ["disk-full"], "split": "dev",
           "category": "normal"}]
    p = tmp_path / "c.yaml"
    c = cfg("rag_judge_cost")
    c["runbook_selection"] = "rag"
    p.write_text(yaml.safe_dump(c, allow_unicode=True))
    s = ra.run_config(p, qs, 0.75, use_judge=False, save=False, backend="fake", reps=2, workers=1)
    hits = [r["cache_hits"] for r in s["per_rep"]]
    assert hits == [0, 0], f"반복 간 캐시 적중 {hits}"


def test_local_tfidf_embedder_ranks_db_down():
    """로컬 Ollama 데모용 TF-IDF 임베더: LocalNgram 이 놓치던 DB 장애 질문에서 db-down 이 1위여야 한다."""
    from ext.rag import LocalTfidfEmbedder, RunbookRetriever
    rb = ROOT / "src/data/runbooks"
    ret = RunbookRetriever(rb, LocalTfidfEmbedder(rb))
    assert ret.rank("DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요.", top_k=3)[0][0] == "db-down"
    assert ret.rank("전혀 관계없는 문장 xyz", top_k=1)[0][1] < 0.0782   # final_local.yaml min_score 미만


def test_ollama_embedder_offline(tmp_path, monkeypatch):
    """rag.embedding: ollama:<모델> — /api/embed 형식으로 부르고, 런북 색인만 별도 캐시 파일에 남긴다 (네트워크 없이 확인)."""
    import httpx
    from ext.rag import OllamaEmbedder
    calls = []

    def fake_post(url, json=None, timeout=None, **kw):
        calls.append((url, json))
        return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in json["input"]]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    emb = OllamaEmbedder("bge-m3", tmp_path)
    assert emb.name == "ollama:bge-m3"
    v = emb.embed(["abc", "de"], persist=True)
    assert calls[0][0].endswith("/api/embed") and calls[0][1] == {"model": "bge-m3", "input": ["abc", "de"]}
    assert abs(sum(x * x for x in v[0]) - 1) < 1e-9                     # 단위 벡터
    assert (tmp_path / "emb_ollama_bge-m3.json").exists()                # OpenAI 캐시와 다른 파일
    emb.embed(["abc"], persist=True)
    assert len(calls) == 1                                               # 색인은 캐시 재사용
