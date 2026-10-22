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
# 지연 통제 재측정(scripts/run_latency_ctrl.sh)이 7구성 모두 있으면 지연은 그 값을 쓴다
LATCTL = all((R / f"{n}_latctl_latest.json").exists() for n in ORDER) and (R / "stats_holdout_latctl.json").exists()


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
    if LATCTL:
        Lc = {n: json.loads((R / f"{n}_latctl_latest.json").read_text())["summary"]["by_split"]["holdout"]["mean"] for n in ORDER}
        rows[-1] = ("p95 지연 (같은 부하 재측정)", lambda n: f"{Lc[n]['latency_p95_ms'] / 1000:.1f}초")
    out = ["| | " + " | ".join(LABEL[n] for n in ORDER) + " |", "|---|" + "---|" * len(ORDER)]
    out += [f"| {lab} | " + " | ".join(f(n) for n in ORDER) + " |" for lab, f in rows]
    if LATCTL:
        out += ["", "p95 지연 행: 동일 부하·동시 실행 조건(7구성 동시, workers 2, holdout 36문제 x 3회) 재측정 값. 나머지 행은 원 측정."]
    return "\n".join(out)


def contrib_table() -> str:
    st = json.loads((R / "stats_holdout.json").read_text())["pairs"]
    if LATCTL:   # 지연만 같은 부하 재측정 값으로 바꾼다 (품질·비용은 원 측정)
        lat = {(q["a"], q["b"]): q["latency"] for q in json.loads((R / "stats_holdout_latctl.json").read_text())["pairs"]}
        st = [{**q, "latency": lat[(q["a"], q["b"])]} for q in st]

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
    lat_head = "질의당 지연 (같은 부하 재측정)" if LATCTL else "질의당 지연"
    head = f"| 켠 것 | 정답 누락 | 무관 혼입 | 어구 포함 | 질의당 비용 | {lat_head} |\n|---|---|---|---|---|---|"
    lines = [f"| {'**' + p['label'] + '**' if p['a'] == 'base' and p['b'] == 'final' else p['label']} | "
             + " | ".join(c(p[k], k) for k in ("miss", "wrong", "must", "cost", "latency")) + " |" for p in st]
    tail = ("\n\n지연 열: 동일 부하·동시 실행 조건(7구성 동시, workers 2, holdout 36문제 x 3회) 재측정 값. 나머지 열은 원 측정."
            if LATCTL else "")
    return head + "\n" + "\n".join(lines) + tail


def old_latency_table() -> str:
    """처음 측정한 지연 (부하 조건이 달라 직접 비교 불가). 지우지 않고 부록에 남긴다."""
    H = {n: json.loads((R / f"{n}_latest.json").read_text())["summary"]["by_split"]["holdout"]["mean"] for n in ORDER}
    st = json.loads((R / "stats_holdout.json").read_text())["pairs"]
    out = ["| | " + " | ".join(LABEL[n] for n in ORDER) + " |", "|---|" + "---|" * len(ORDER),
           "| p95 지연 (처음 측정) | " + " | ".join(f"{H[n]['latency_p95_ms'] / 1000:.1f}초" for n in ORDER) + " |",
           "", "| 켠 것 | 질의당 지연 차이 (처음 측정) |", "|---|---|"]
    for q in st:
        r = q["latency"]
        out.append(f"| {q['label']} | {r['diff']:+.1f}초 [{r['lo']:+.1f}, {r['hi']:+.1f}]{' ★' if r['significant'] else ''} |")
    out += ["", "부하 조건이 달라 직접 비교 불가: base·rag·judge·rag_judge·rag_judge_v2 는 7프로세스 동시, "
            "rag_judge_cost·final 은 캐시 버그 수정 뒤 2프로세스로 쟀다. 본문 표는 동일 부하 재측정 값을 쓴다."]
    return "\n".join(out)


def main():
    p = ROOT / "README.md"
    s = p.read_text()
    for name, fn in (("holdout", holdout_table), ("contrib", contrib_table), ("latency_old", old_latency_table)):
        s, n = re.subn(rf"(<!-- AUTO:{name} -->).*?(<!-- /AUTO:{name} -->)",
                       lambda m: m.group(1) + "\n" + fn() + "\n" + m.group(2), s, flags=re.S)
        assert n == 1, f"README 에 AUTO:{name} 구간이 없음"
    p.write_text(s)
    print("README 표 갱신")


if __name__ == "__main__":
    main()
