"""eval/configs/*.yaml — 전 구성 로드, base = 원본 그대로(개선 플래그 전부 off), 플래그 → 의존성 매핑."""
from pathlib import Path

import pytest
import yaml

import src.adapter as A
from ext import rag as rg
from ext.judge import FakeJudge, OpenAIJudge

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = sorted((ROOT / "eval/configs").glob("*.yaml"))
NAMES = [p.stem for p in CONFIGS]
ABLATION = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]


def load(name):
    return yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text(encoding="utf-8"))


def test_ablation_order_matches_config_files():
    from eval.run_ablation import ORDER
    assert ORDER == ABLATION and set(ORDER) <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_every_config_loads_with_matching_name(name):
    c = load(name)
    assert c["name"] == name and c.get("description")
    assert c["runbook_selection"] in ("keyword", "rag")
    assert c["validator"] in ("rule", "judge")
    assert c["backend"] == "openai"


@pytest.mark.parametrize("name", [n for n in NAMES if load(n)["validator"] == "judge"])
def test_judge_configs_keep_both_loop_guards(name):
    j = load(name)["judge"]
    assert j["max_retries"] == 2 and j["max_seconds"] == 120     # CLAUDE.md: 둘 다 반드시
    assert j["threshold"] == 0.75


@pytest.mark.parametrize("name", [n for n in NAMES if load(n)["runbook_selection"] == "rag"])
def test_rag_configs_have_ranking_params(name):
    r = load(name)["rag"]
    assert r["top_k"] == 3 and 0 < r["margin"] <= 0.05 and r.get("embedding")
    if "min_score" in r:
        assert 0 < r["min_score"] < 1 and r.get("notices") is True


def test_base_is_original_with_all_improvements_off():
    c = load("base")
    assert c["runbook_selection"] == "keyword" and c["validator"] == "rule"
    assert c["cost"] == {"model_tiering": False, "cache": False}
    for key in ("rag", "judge", "runtime", "fault_injection"):
        assert key not in c
    assert c["models"] == {"fast": "gpt-4o-mini", "quality": "gpt-4o"}
    assert A._is_base(c)


def test_only_base_uses_original_graph():
    assert [n for n in NAMES if A._is_base(load(n))] == ["base"]


def test_any_single_improvement_flag_leaves_base():
    for flag in ({"runtime": {"async_io": True}}, {"runtime": {"tolerant_research": True}},
                 {"cost": {"cache": True}}, {"cost": {"model_tiering": True}},
                 {"validator": "judge"}, {"runbook_selection": "rag"}):
        assert not A._is_base({**load("base"), **flag}), flag


def test_final_turns_on_every_improvement():
    c = load("final")
    assert c["cost"]["model_tiering"] and c["cost"]["cache"]
    assert c["runtime"] == {"async_io": True, "tolerant_research": True}
    assert c["judge"]["version"] == 2 and c["judge"]["factcheck"]


def test_base_run_never_builds_ext_graph(monkeypatch):
    """base 는 원본 agent.graph.build_graph 로만 돈다 — Ablation 기준선이 원본 동작이어야 한다."""
    def boom(deps):
        raise AssertionError("base 에서 build_graph_ext 호출됨")
    monkeypatch.setattr(A, "build_graph_ext", boom)
    out = A.run_once("log-service 디스크 공간 부족 장애 진단해줘", {**load("base"), "backend": "fake"})
    assert out["answer"] and out["judge_history"] == [] and out["retrieved"] == ["disk-full"]


# --- 플래그 → 의존성 (_build_deps) -------------------------------------------------

@pytest.mark.parametrize("name", ABLATION)
def test_fake_deps_follow_flags(name):
    c = {**load(name), "backend": "fake"}
    d = A._build_deps(c, mcp=None)
    assert (d.retriever is not None) == (c["runbook_selection"] == "rag")
    assert (d.judge is not None) == (c["validator"] == "judge")
    assert (d.cheap_writer is not None) == bool(c["cost"].get("model_tiering"))
    if d.judge is not None:
        assert isinstance(d.judge, FakeJudge)


@pytest.mark.parametrize("name,emb_type", [("rag", rg.OpenAIEmbedder), ("final", rg.OpenAIEmbedder),
                                           ("final_local", rg.LocalTfidfEmbedder),
                                           ("final_local_bge", rg.OllamaEmbedder)])
def test_openai_backend_deps_models_and_embedder(name, emb_type, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "CACHE_DIR", tmp_path)           # 실제 임베딩 캐시를 건드리지 않는다
    A._CACHES.clear()
    c = load(name)
    d = A._build_deps(c, mcp=None)                          # 생성만 한다 — 네트워크 호출 없음
    assert isinstance(d.retriever.embedder, emb_type)
    assert d.fast_llm.model == c["models"]["fast"] and d.quality_llm.model == c["models"]["quality"]
    if c["validator"] == "judge":
        assert isinstance(d.judge, OpenAIJudge) and d.judge.version == c["judge"].get("version", 1)
    if c["cost"].get("model_tiering"):
        assert d.cheap_writer.model == c["models"]["cascade_writer"]
    assert (d.fast_llm.cache is not None) == bool(c["cost"].get("cache"))
    A._CACHES.clear()


def test_ollama_embedder_model_parsed_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "CACHE_DIR", tmp_path)
    d = A._build_deps(load("final_local_bge"), mcp=None)
    assert d.retriever.embedder.model == "bge-m3"
