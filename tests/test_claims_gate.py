"""수치 일관성 게이트 — 문서 수치 ↔ CLAIMS ↔ results/ 가 서로 맞는지 오프라인으로 확인한다.

CLAUDE.md 1번: 모든 Before/After 숫자는 results/ 실행 결과에서 나온다.
  1) scripts/claims.py 를 다시 돌리면 커밋된 CLAIMS.md · results/claims.json 과 글자 하나까지 같아야 한다
     (파일은 쓰지 않는다 — write_text 를 가로채 비교만 한다).
  2) claims 가 쓰는 paired bootstrap 결과(stats_holdout*.json)도 seed 고정으로 그대로 재현돼야 한다.
  3) scripts/check_claims.py --strict 는 확인 필요 0건, 못 읽은 문서 0개로 exit 0 이어야 한다.
"""
import importlib.util
import json
import pathlib
import runpy

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
R = ROOT / "results"


def load_check_claims():
    spec = importlib.util.spec_from_file_location("check_claims", ROOT / "scripts" / "check_claims.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CC = load_check_claims()


@pytest.fixture(scope="module")
def regenerated():
    written = {}
    mp = pytest.MonkeyPatch()

    def capture(self, data, *a, **k):
        written[pathlib.Path(self).resolve()] = data
        return len(data)
    mp.setattr(pathlib.Path, "write_text", capture)
    try:
        runpy.run_path(str(ROOT / "scripts" / "claims.py"), run_name="claims_regen")
    finally:
        mp.undo()
    return written


def test_claims_script_writes_only_claims_files(regenerated):
    assert set(regenerated) == {(R / "claims.json").resolve(), (ROOT / "CLAIMS.md").resolve()}


def test_claims_json_reproduces_from_results(regenerated):
    assert regenerated[(R / "claims.json").resolve()] == (R / "claims.json").read_text(encoding="utf-8"), \
        "results/claims.json 이 결과 파일과 어긋남 — python scripts/claims.py 재실행 필요"


def test_claims_md_reproduces_from_results(regenerated):
    assert regenerated[(ROOT / "CLAIMS.md").resolve()] == (ROOT / "CLAIMS.md").read_text(encoding="utf-8")


def test_claims_have_provenance(regenerated):
    claims = json.loads(regenerated[(R / "claims.json").resolve()])
    ids = [c["id"] for c in claims]
    assert len(ids) == len(set(ids)) and len(ids) > 50
    for c in claims:
        assert c["값"] and c["결과 파일"] and c["재현 명령"], c["id"]


@pytest.mark.parametrize("split,tag", [("holdout", ""), ("holdout", "_latctl"), ("dev", ""), (None, "")])
def test_paired_bootstrap_reproduces_committed_stats(split, tag):
    from eval import stats as S
    res = json.loads(json.dumps(S.run(split, tag)))
    cur = json.loads((R / f"stats_{res['split']}{tag}.json").read_text())
    assert res["pairs"] == cur["pairs"]


# --- check_claims 단위 ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("누락 33% → 8%", ["33%", "8%"]),
    ("−25%p 감소", ["-25%p"]),
    ("$0.01234 / 질의", ["$0.01234"]),
    ("지연 1,234.5 초", ["1234.5초"]),
    ("3.2배 빠름", ["3.2배"]),
    ("Q01 3건 2026년", []),
])
def test_check_claims_tokens(text, expected):
    assert CC.tokens(text) == expected


def test_history_lines_are_exempt():
    assert CC.HISTORY.search("처음 측정 때는 45%였다")
    assert not CC.HISTORY.search("최종 누락률 8%")


def test_check_claims_strict_passes_on_repo(capsys):
    with pytest.raises(SystemExit) as e:
        CC.main(["--strict"])
    out = capsys.readouterr().out
    assert e.value.code == 0, out
    assert "확인 필요 0건" in out and "읽기 실패" not in out


def _run_main(argv, capsys):
    with pytest.raises(SystemExit) as e:
        CC.main(argv)
    out = capsys.readouterr().out
    n_bad = int(out.rsplit("확인 필요 ", 1)[1].split("건", 1)[0])
    return e.value.code, n_bad, out


def test_check_claims_flags_unknown_number(monkeypatch, capsys):
    """문서 상태와 무관하게: 결과에 없는 수치 한 줄을 넣으면 확인 필요가 정확히 1건 늘고 exit 1."""
    monkeypatch.setattr(CC, "deck_text", lambda: "덱")
    _, base_bad, _ = _run_main([], capsys)
    real_read = pathlib.Path.read_text

    def read(self, *a, **k):
        text = real_read(self, *a, **k)
        return text + "\n최종 정확도 77.7% 달성\n" if self.name == "submission_sheet_draft.md" else text
    monkeypatch.setattr(pathlib.Path, "read_text", read)
    code, n_bad, out = _run_main([], capsys)
    assert code == 1 and n_bad == base_bad + 1 and "77.7%" in out


def test_strict_only_adds_unreadable_check(monkeypatch, capsys):
    monkeypatch.setattr(CC, "deck_text", lambda: "덱")
    code_default, n_default, out_default = _run_main([], capsys)
    code_strict, n_strict, out_strict = _run_main(["--strict"], capsys)
    assert (code_default, n_default) == (code_strict, n_strict)          # 다 읽히면 결과가 같다
    assert out_strict == out_default                                    # 기본 출력 형식도 그대로
    monkeypatch.setattr(CC, "deck_text", lambda: "")          # markitdown 없음 → 덱 텍스트 비어 있음
    code, _, out = _run_main([], capsys)
    assert code == code_default and "읽기 실패" not in out              # 기본 동작은 못 읽어도 통과 판정 그대로
    code, _, out = _run_main(["--strict"], capsys)
    assert code == 1 and "읽기 실패  deck (pptx 2종)" in out
