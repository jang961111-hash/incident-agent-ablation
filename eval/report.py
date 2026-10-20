"""results/*_latest.json 을 읽어 Ablation 비교표를 만든다.

    python -m eval.report
    python -m eval.report --md > docs/02_실험로그_표.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "rag_judge", "rag_judge_cost"]

ROWS = [
    ("relevance",              "관련성",         "pct"),
    ("completeness",           "완전성",         "pct"),
    ("domain_appropriateness", "도메인 적합성",  "pct"),
    ("clarity",                "명확성",         "pct"),
    ("judge_mean",             "4지표 평균",     "pct"),
    ("pass_rate",              "임계치 통과율",  "pct"),
    ("recall@1",               "Recall@1",       "pct"),
    ("recall@3",               "Recall@3",       "pct"),
    ("mrr",                    "MRR",            "f3"),
    ("latency_p50_ms",         "지연 p50(ms)",   "f0"),
    ("latency_p95_ms",         "지연 p95(ms)",   "f0"),
    ("rewrites_total",         "재작성 합계",    "f0"),
    ("cost_usd_total",         "추정 비용(USD)", "f4"),
    ("judge_agreement",        "Judge 일치율",   "pct"),
]

FMT = {
    "pct": lambda v: f"{v:.0%}",
    "f3":  lambda v: f"{v:.3f}",
    "f0":  lambda v: f"{v:.0f}",
    "f4":  lambda v: f"{v:.4f}",
}
DELTA = {
    "pct": lambda v: f"{v:+.0%}",
    "f3":  lambda v: f"{v:+.3f}",
    "f0":  lambda v: f"{v:+.0f}",
    "f4":  lambda v: f"{v:+.4f}",
}


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    args = ap.parse_args()

    found = {}
    for nm in ORDER:
        p = RESULTS / f"{nm}_latest.json"
        if p.exists():
            found[nm] = json.loads(p.read_text(encoding="utf-8"))["summary"]
    if not found:
        print("results/ 에 결과가 없습니다. 먼저 run_ablation 을 실행하세요.")
        return

    cols = list(found)
    table = []
    for key, label, kind in ROWS:
        if not any(key in found[c] for c in cols):
            continue
        line = [label]
        for c in cols:
            v = found[c].get(key)
            line.append(FMT[kind](v) if is_num(v) else "-")
        a, b = found[cols[0]].get(key), found[cols[-1]].get(key)
        line.append(DELTA[kind](b - a) if is_num(a) and is_num(b) else "-")
        table.append(line)

    print(tabulate(table, headers=["지표"] + cols + ["변화"],
                   tablefmt="github" if args.md else "simple"))
    n = next(iter(found.values())).get("n")
    agree = found[cols[-1]].get("judge_agreement")
    print(f"\n평가셋 {n}건.", end=" ")
    if is_num(agree):
        print(f"Judge 일치율 {agree:.0%} — 위 수치는 그만큼의 오차를 안고 읽어야 함.")
    else:
        print("사람 라벨 미입력 — Judge 일치율 미산출.")


if __name__ == "__main__":
    main()
