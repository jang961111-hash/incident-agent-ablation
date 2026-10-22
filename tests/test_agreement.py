"""사람 라벨 저장 + Judge 일치도 계산 테스트 (API, 네트워크 없음)."""
import importlib.util
import json
import math
from pathlib import Path

import pytest
import yaml

from eval import agreement as ag

ROOT = Path(__file__).resolve().parent.parent
M = ag.METRICS


def load_label_script():
    spec = importlib.util.spec_from_file_location("label", ROOT / "scripts" / "label.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


label = load_label_script()


def verdicts(*pf):
    return dict(zip(M, pf))


# --- kappa ------------------------------------------------------------------

def test_kappa_hand_computed():
    # P/P=20 P/F=5 F/P=10 F/F=15, n=50: po=0.7, pe=(25*30+25*20)/2500=0.5 → kappa=0.4
    k, note = ag.cohen_kappa(20, 5, 10, 15)
    assert k == pytest.approx(0.4) and note == ""


def test_kappa_perfect_and_chance():
    assert ag.cohen_kappa(10, 0, 0, 10)[0] == pytest.approx(1.0)
    assert ag.cohen_kappa(5, 5, 5, 5)[0] == pytest.approx(0.0)


def test_kappa_degenerate_is_nan_with_note():
    k, note = ag.cohen_kappa(10, 0, 0, 0)   # 둘 다 전부 Pass → pe == 1
    assert math.isnan(k) and "정의 불가" in note
    k, note = ag.cohen_kappa(0, 0, 0, 0)
    assert math.isnan(k) and note


# --- overall ----------------------------------------------------------------

@pytest.mark.parametrize("pf,expected", [
    (("Pass",) * 4, "Pass"),
    (("Pass", "Pass", "Pass", "Fail"), "Pass"),
    (("Pass", "Pass", "Fail", "Fail"), "Fail"),
    (("Fail",) * 4, "Fail"),
])
def test_overall_threshold(pf, expected):
    assert ag.overall_label(verdicts(*pf)) == expected


# --- 라벨 파일 왕복 ---------------------------------------------------------

def test_label_file_round_trip(tmp_path):
    p = tmp_path / "human_labels.yaml"
    labels = {
        "Q02": label.make_entry(verdicts("Pass", "Fail", "Fail", "Pass"), "답변 B"),
        "Q01": label.make_entry(verdicts("Pass", "Pass", "Pass", "Pass"), "답변 A"),
    }
    label.save_labels(p, labels)
    text = p.read_text()
    assert text.startswith("# 사람 라벨") and text.index("Q01:") < text.index("Q02:")
    back = ag.load_human(p)
    assert back["source_config"] == "base"
    assert back["labels"]["Q01"]["overall"] == "Pass" and back["labels"]["Q02"]["overall"] == "Fail"
    assert back["labels"]["Q02"]["answer_sha"] == ag.answer_sha("답변 B")
    assert {k: v for k, v in back["labels"].items()} == labels
    assert not list(tmp_path.glob("*.tmp"))   # 임시 파일이 남지 않는다


def test_sha_that_looks_numeric_stays_string(tmp_path):
    e = label.make_entry(verdicts(*("Pass",) * 4), "x")
    e["answer_sha"] = "012345678901"   # 따옴표 없이 쓰면 YAML 이 정수로 읽는다
    p = tmp_path / "l.yaml"
    label.save_labels(p, {"Q01": e})
    assert ag.load_human(p)["labels"]["Q01"]["answer_sha"] == "012345678901"


def test_missing_label_file_is_empty(tmp_path):
    assert ag.load_human(tmp_path / "none.yaml")["labels"] == {}


# --- 일치도 계산 + stale ----------------------------------------------------

def make_results(tmp_path, rows):
    d = tmp_path / "results"
    d.mkdir()
    (d / "base_latest.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return d


def row(qid, answer, judge, category="normal", **extra):
    r = {"id": qid, "category": category, "answer": answer,
         "judge_reasons": {m: f"{qid}-{m}-사유" for m in M}}
    r.update({f"judge_{m}": v for m, v in zip(M, judge)})
    r.update(extra)
    return r


def test_summary_counts_and_stale_exclusion(tmp_path):
    P, F = "Pass", "Fail"
    rows = [
        row("Q01", "a1", (P, P, P, P)),
        row("Q02", "a2", (P, P, P, F), category="constrained"),   # 사람 F → relevance 관대
        row("Q03", "a3-new", (P, P, P, P)),                        # 라벨 뒤 답변이 바뀜 → stale
        row("Q04", "a4", (P, P, P, P), rep=2),                     # rep 2 는 무시 → missing
        row("Q05", "a5", (P, P, P, P), error="boom"),              # 오류 행 → missing
        row("Q06", "a6", (P, P, P, P)),                            # 사람이 안 매김 → 비교 대상 아님
        row("Q07", "a7", ("ParseError",) * 4),                     # Judge 판정 불가 → 제외
    ]
    results = make_results(tmp_path, rows)
    lp = tmp_path / "human_labels.yaml"
    label.save_labels(lp, {
        "Q01": label.make_entry(verdicts(P, P, P, P), "a1"),
        "Q02": label.make_entry(verdicts(F, P, P, P), "a2"),
        "Q03": label.make_entry(verdicts(P, P, P, P), "a3-old"),
        "Q04": label.make_entry(verdicts(P, P, P, P), "a4"),
        "Q05": label.make_entry(verdicts(P, P, P, P), "a5"),
        "Q07": label.make_entry(verdicts(P, P, P, P), "a7"),
    })
    s = ag.summary_dict("base", lp, results)
    assert s["stale"] == ["Q03"] and s["missing"] == ["Q04", "Q05"]
    assert s["n_labeled"] == 6 and s["n_compared"] == 2

    rel = s["metrics"]["relevance"]
    assert rel["n"] == 2 and rel["agreement"] == 0.5
    assert rel["confusion"]["사람Fail_JudgePass"] == 1 and rel["confusion"]["사람Pass_JudgePass"] == 1
    assert rel["leniency"] == 1.0 and rel["strictness"] == 0.0
    assert rel["disagree_ids"] == ["Q02"]
    comp = s["metrics"]["completeness"]
    assert comp["agreement"] == 1.0 and comp["kappa"] is None   # 사람, Judge 모두 전부 Pass → kappa 정의 불가

    # overall: 사람 Q02 = P,P,P (3개) → Pass, Judge Q02 = P,P,P,F → Pass → 일치
    assert s["metrics"]["overall"]["agreement"] == 1.0

    assert len(s["disagreements"]) == 2   # Q02 relevance(관대), Q02 clarity(사람 P, Judge F → 엄격)
    by = {(d["metric"], d["direction"]): d for d in s["disagreements"]}
    d = by[("relevance", ag.LENIENT)]
    assert (d["id"], d["category"], d["reason"]) == ("Q02", "constrained", "Q02-relevance-사유")
    assert ("clarity", ag.STRICT) in by
    assert s["by_category"]["constrained"] == {"n": 4, "disagree": 2, "lenient": 1, "strict": 1}
    assert s["by_metric_direction"]["relevance"][ag.LENIENT] == ["Q02"]

    json.dumps(s, allow_nan=False)   # 덱, 리포트 생성기에 넘길 수 있게 JSON 직렬화 가능


def test_render_plain_and_md(tmp_path):
    P, F = "Pass", "Fail"
    results = make_results(tmp_path, [row("Q01", "a1", (P, P, F, P))])
    lp = tmp_path / "l.yaml"
    label.save_labels(lp, {"Q01": label.make_entry(verdicts(P, P, P, P), "a1")})
    s = ag.summary_dict("base", lp, results)
    assert "domain_appropriateness" in ag.render(s)
    assert "| 지표" in ag.render(s, md=True)
    assert "라벨 없음" in ag.render(ag.summary_dict("base", tmp_path / "none.yaml", results))


# --- label.py 흐름 ----------------------------------------------------------

def test_select_rows_filters():
    rows = [{"id": "Q01", "answer": "x", "query": "q"},
            {"id": "Q02", "answer": "x", "query": "q", "error": "e"},
            {"id": "Q03", "answer": "x", "query": "q", "rep": 2},
            {"id": "Q04", "answer": "x", "query": "q"},
            {"id": "Q05", "answer": "x", "query": "q", "rep": 1}]
    queries = {"Q01": {"split": "dev"}, "Q04": {"split": "holdout"}, "Q05": {"split": "holdout"}}
    ids = lambda **kw: [r["id"] for r in label.select_rows(rows, queries, {"Q04": {}}, **kw)]
    assert ids() == ["Q01", "Q05"]
    assert ids(split="holdout") == ["Q05"]
    assert ids(only={"Q01"}) == ["Q01"]


def test_label_cli_saves_each_item_and_never_overwrites(tmp_path, capsys):
    base = make_results(tmp_path, [
        {"id": "Q01", "category": "normal", "route": "incident", "query": "q1", "answer": "a1",
         "context": "c1", "judge_relevance": "Fail"},
        {"id": "Q02", "category": "normal", "route": "incident", "query": "q2", "answer": "a2",
         "context": "c2"}]) / "base_latest.json"
    qy = tmp_path / "queries.yaml"
    qy.write_text(yaml.safe_dump({"queries": [
        {"id": "Q01", "human_label": "Pass"}, {"id": "Q02", "split": "dev"}]}))
    lp = tmp_path / "human_labels.yaml"

    # Q01: p,f(오타 x 무시),u → 처음부터 → p,p,f,p 저장. Q02: s 로 건너뜀
    keys = iter(["p", "x", "u", "p", "p", "f", "p", "s"])
    label.main([], lambda prompt: next(keys), base_path=base, labels_path=lp, queries_path=qy)
    out = capsys.readouterr().out
    assert "경고" in out and "Q01" in out        # queries.yaml 의 옛 human_label 경고
    assert "Fail" not in out.split("답변")[1]      # Judge 판정은 화면에 나오지 않는다 (블라인드)
    got = ag.load_human(lp)["labels"]
    assert list(got) == ["Q01"]
    assert [got["Q01"][m] for m in M] == ["Pass", "Pass", "Fail", "Pass"]
    assert got["Q01"]["overall"] == "Pass"
    assert yaml.safe_load(qy.read_text())["queries"][0]["human_label"] == "Pass"   # queries.yaml 불변

    # 다시 실행하면 Q01 은 대상이 아니다 — Q02 만 묻고 q 로 종료(저장 안 함)
    label.main([], lambda prompt: "q", base_path=base, labels_path=lp, queries_path=qy)
    assert list(ag.load_human(lp)["labels"]) == ["Q01"]
