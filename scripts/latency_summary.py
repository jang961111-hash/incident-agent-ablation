"""지연 통제 재측정(_latctl) 집계: 건수·오류·재시도·타임아웃, 구성별 p50·p95·평균±표준편차·95% CI.

    .venv/bin/python scripts/latency_summary.py            # results/latctl_summary_<YYYYMMDD_HHMM>.md 저장
    .venv/bin/python scripts/latency_summary.py --tag _latctl

p50·p95 는 README·덱과 같은 정의다: 반복(rep)마다 백분위를 구해 3회 평균(run_ablation 요약과 같음).
95% CI 는 반복 3회의 평균을 표본으로 한 t 구간(t_{0.975,2}=4.303)이다.
타임아웃은 adapter 의 HARD_TIMEOUT_S(300초) 도달 또는 error 문자열에 timeout 이 있는 행이다.
"""
import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776}


def pct(vals, q):
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="_latctl")
    a = ap.parse_args()
    lines = [f"# 지연 통제 재측정 집계 ({a.tag})", "",
             "조건: 7구성 동시 실행(7프로세스 x workers 2), holdout 36문제 x 3회, 평가 Judge 생략. "
             "출처 `results/{구성}" + a.tag + "_latest.json`.", "",
             "| 구성 | 행 | 오류 | API 재시도 | 타임아웃 | p50 (초, 반복 평균) | p95 (초, 반복 평균) | 평균 ± 표준편차 (초, 108회) | 평균의 95% CI (반복 3회) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for n in ORDER:
        rows = json.loads((R / f"{n}{a.tag}_latest.json").read_text())["rows"]
        ok = [r for r in rows if "error" not in r]
        lat = [r["latency_ms"] / 1000 for r in ok]
        retries = sum(r.get("api_retries", 0) or 0 for r in rows)
        tout = sum(1 for r in rows if "timeout" in str(r.get("error", "")).lower()
                   or (r.get("latency_ms") or 0) >= 300_000)
        reps = sorted({r.get("rep") for r in ok})
        rep_means = [statistics.fmean([r["latency_ms"] / 1000 for r in ok if r.get("rep") == k]) for k in reps]
        m = statistics.fmean(rep_means)
        half = T975.get(len(rep_means) - 1, 2.0) * statistics.stdev(rep_means) / len(rep_means) ** 0.5 if len(rep_means) > 1 else float("nan")
        rp = lambda q: statistics.fmean(pct([r["latency_ms"] / 1000 for r in ok if r.get("rep") == k], q) for k in reps)
        lines.append(f"| {n} | {len(rows)} | {len(rows) - len(ok)} | {retries} | {tout} | {rp(.5):.1f} | {rp(.95):.1f} | "
                     f"{statistics.fmean(lat):.1f} ± {statistics.stdev(lat):.1f} | {m:.1f} [{m - half:.1f}, {m + half:.1f}] |")
    st = R / f"stats_holdout{a.tag}.json"
    if st.exists():
        lines += ["", "구성 간 차이 (질의 단위 paired bootstrap 95% CI, `python -m eval.stats --tag " + a.tag + "`):", "",
                  "| 비교 | 질의당 지연 차이 (초) |", "|---|---|"]
        for p in json.loads(st.read_text())["pairs"]:
            q = p["latency"]
            lines.append(f"| {p['label']} | {q['diff']:+.1f} [{q['lo']:+.1f}, {q['hi']:+.1f}]{' ★' if q['significant'] else ''} |")
    out = R / f"latctl_summary_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
