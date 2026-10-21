"""README 의 결과 표를 results/ 에서 자동 생성한다 — 손으로 옮겨 적는 숫자를 없앤다.

README 안의 <!-- AUTO:이름 --> ... <!-- /AUTO:이름 --> 구간만 바꾼다.
    .venv/bin/python scripts/gen_readme_tables.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.extra_metrics import load_all  # noqa: E402

ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]
LABEL = {"base": "base", "rag": "+RAG", "judge": "+Judge만", "rag_judge": "RAG+Judge",
         "rag_judge_cost": "+비용", "rag_judge_v2": "+v2 보완", "final": "**final**"}
R = ROOT / "results"


def pct(v):
    return f"{round(v * 100)}%"


def holdout_table() -> str:
    H = {n: json.loads((R / f"{n}_latest.json").read_text())["summary"]["by_split"]["holdout"]["mean"] for n in ORDER}
    X = load_all("holdout")
    rows = [("정답 런북 누락률 ↓", lambda n: pct(X[n]["miss_runbook_rate"])),
            ("무관 런북 혼입률 ↓", lambda n: pct(X[n]["wrong_runbook_rate"])),
            ("런북 핵심 어구 포함 (Judge 무관)", lambda n: pct(H[n]["must_phrase_rate"])),
            ("평가 Judge 통과 (gpt-4o)", lambda n: pct(H[n]["pass_rate"])),
            ("Recall@1", lambda n: pct(H[n]["recall@1"])),
            ("장애 1건당 비용 (USD)", lambda n: f"{X[n]['cost_per_incident']:.5f}"),
            ("p95 지연", lambda n: f"{H[n]['latency_p95_ms'] / 1000:.1f}초")]
    out = ["| | " + " | ".join(LABEL[n] for n in ORDER) + " |", "|---|" + "---|" * len(ORDER)]
    out += [f"| {lab} | " + " | ".join(f(n) for n in ORDER) + " |" for lab, f in rows]
    return "\n".join(out)


def contrib_table() -> str:
    st = json.loads((R / "stats_holdout.json").read_text())["pairs"]

    def c(r, k):
        if not r:
            return "-"
        if k == "cost":
            s = f"{r['diff']:+.4f}".replace("+", "+$").replace("-", "-$")
        elif k == "latency":
            s = f"{r['diff']:+.1f}초"
        else:
            lo, hi = round(r["lo"] * 100), round(r["hi"] * 100)
            s = f"{round(r['diff'] * 100):+d}%p [{lo:+d}, {hi:+d}]"
        return f"**{s}** ★" if r["significant"] else s
    head = "| 켠 것 | 정답 누락 | 무관 혼입 | 어구 포함 | 질의당 비용 | 질의당 지연 |\n|---|---|---|---|---|---|"
    lines = [f"| {'**' + p['label'] + '**' if p['a'] == 'base' and p['b'] == 'final' else p['label']} | "
             + " | ".join(c(p[k], k) for k in ("miss", "wrong", "must", "cost", "latency")) + " |" for p in st]
    return head + "\n" + "\n".join(lines)


def main():
    p = ROOT / "README.md"
    s = p.read_text()
    for name, fn in (("holdout", holdout_table), ("contrib", contrib_table)):
        s, n = re.subn(rf"(<!-- AUTO:{name} -->).*?(<!-- /AUTO:{name} -->)",
                       lambda m: m.group(1) + "\n" + fn() + "\n" + m.group(2), s, flags=re.S)
        assert n == 1, f"README 에 AUTO:{name} 구간이 없음"
    p.write_text(s)
    print("README 표 갱신")


if __name__ == "__main__":
    main()
