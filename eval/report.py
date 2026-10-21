"""results/*_latest.json 을 읽어 Ablation 비교표를 만든다.

    python -m eval.report
    python -m eval.report --md > docs/04_결과표.md

Judge 일치율은 실행 시점이 아니라 지금 queries.yaml 에 적힌 human_label 과
base_latest.json 의 평가용 Judge 판정을 대조해 계산한다. 라벨은 base 답변을 보고 매긴
것이므로 base 행에서만 의미가 있다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml
from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "rag_judge", "rag_judge_cost"]

ROWS = [
    ("__q", "답변 품질 (평가 Judge gpt-4o)", None),
    ("relevance",              "관련성",            "pct"),
    ("completeness",           "완전성",            "pct"),
    ("domain_appropriateness", "도메인 적합성",     "pct"),
    ("clarity",                "명확성",            "pct"),
    ("pass_rate",              "통과율 (3/4 이상)", "pct"),
    ("__d", "답변 품질 (결정적, Judge 무관 — must_include 13건)", None),
    ("must_phrase_rate",       "런북 핵심 어구 포함률", "pct"),
    ("must_all_rate",          "어구 전부 포함 비율", "pct"),
    ("__r", "검색 품질 (gold 있는 18건)", None),
    ("recall@1",               "Recall@1",          "pct"),
    ("recall@3",               "Recall@3 *",        "pct"),
    ("mrr",                    "MRR",               "f3"),
    ("fed_recall",             "투입 런북 재현율",  "pct"),
    ("fed_precision",          "투입 런북 정밀도",  "pct"),
    ("fed_count_mean",         "투입 런북 수(평균)", "f2"),
    ("recall@1|incident",      "Recall@1 (장애 경로만)", "pct"),
    ("n_retrieval_incident",   "  └ 장애 경로 건수", "f0"),
    ("__o", "운영", None),
    ("latency_p50_ms",         "지연 p50 (ms)",     "f0"),
    ("latency_p95_ms",         "지연 p95 (ms)",     "f0"),
    ("rewrites_total",         "재작성 합계",       "f0"),
    ("tokens_prompt",          "입력 토큰",         "f0"),
    ("tokens_completion",      "출력 토큰",         "f0"),
    ("cost_usd_total",         "추정 비용 (USD)",   "f4"),
    ("errors",                 "실행 오류",         "f0"),
    ("n_judged",               "평가 Judge 판정 건수", "f0"),
]

FMT = {"pct": lambda v: f"{v:.0%}", "f3": lambda v: f"{v:.3f}", "f2": lambda v: f"{v:.2f}",
       "f0": lambda v: f"{v:,.0f}", "f4": lambda v: f"{v:.4f}"}
DELTA = {"pct": lambda v: f"{v * 100:+.0f}%p", "f3": lambda v: f"{v:+.3f}", "f2": lambda v: f"{v:+.2f}",
         "f0": lambda v: f"{v:+,.0f}", "f4": lambda v: f"{v:+.4f}"}


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def stale_labels() -> list[str]:
    """라벨을 매긴 뒤 base 를 다시 돌려 답변이 바뀐 건. 이 건의 라벨은 새 답변에 맞지 않는다."""
    import hashlib
    meta_p, base_p = ROOT / "eval" / "labels_meta.json", RESULTS / "base_latest.json"
    if not (meta_p.exists() and base_p.exists()):
        return []
    meta = json.loads(meta_p.read_text())
    rows = {r["id"]: r for r in json.loads(base_p.read_text())["rows"] if "answer" in r}
    return [qid for qid, h in meta.items()
            if qid in rows and hashlib.sha1(rows[qid]["answer"].encode()).hexdigest()[:12] != h]


def judge_agreement() -> tuple[float | None, int, list[str]]:
    p = RESULTS / "base_latest.json"
    if not p.exists():
        return None, 0, []
    labels = {q["id"]: q.get("human_label") for q in
              yaml.safe_load((ROOT / "eval" / "queries.yaml").read_text())["queries"]}
    rows = [r for r in json.loads(p.read_text())["rows"]
            if labels.get(r["id"]) in ("Pass", "Fail") and r.get("judge_passed") is not None]
    if not rows:
        return None, 0, []
    agree = [r for r in rows if (labels[r["id"]] == "Pass") == bool(r["judge_passed"])]
    miss = [f"{r['id']}(사람 {labels[r['id']]} / Judge {'Pass' if r['judge_passed'] else 'Fail'})"
            for r in rows if r not in agree]
    return len(agree) / len(rows), len(rows), miss


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
    from eval.answer_metrics import load_all
    for nm, m in load_all().items():   # 저장된 답변에서 계산하는 결정적 지표를 합친다
        if nm in found:
            found[nm].update({k: v for k, v in m.items() if k != "per_query"})

    cols = list(found)
    table = []
    for key, label, kind in ROWS:
        if kind is None:
            table.append([f"**{label}**" if args.md else f"[{label}]"] + [""] * (len(cols) + 1))
            continue
        line = [label]
        for c in cols:
            v = found[c].get(key)
            line.append(FMT[kind](v) if is_num(v) else "-")
        a, b = found[cols[0]].get(key), found[cols[-1]].get(key)
        line.append(DELTA[kind](b - a) if is_num(a) and is_num(b) and len(cols) > 1 else "-")
        table.append(line)

    cats = sorted({k[10:-1] for s in found.values() for k in s if k.startswith("pass_rate[")})
    if cats:
        table.append(["**카테고리별 통과율**" if args.md else "[카테고리별 통과율]"]
                     + [""] * (len(cols) + 1))
        for cat in cats:
            vals = [found[c].get(f"pass_rate[{cat}]") for c in cols]
            a, b = vals[0], vals[-1]
            table.append([f"  {cat}"] + [FMT["pct"](v) if is_num(v) else "-" for v in vals]
                         + [DELTA["pct"](b - a) if is_num(a) and is_num(b) and len(cols) > 1 else "-"])

    print(tabulate(table, headers=["지표"] + cols + [f"{cols[0]}→{cols[-1]}"],
                   tablefmt="github" if args.md else "simple"))
    n = next(iter(found.values())).get("n")
    agree, n_lab, miss = judge_agreement()
    print(f"\n평가셋 {n}건. 비용은 OpenAI 공개 단가 × 실측 토큰으로 낸 추정치.")
    print("* base 는 런북을 1개만 고르므로 base 의 Recall@3 = Recall@1. 공정 비교는 '투입 런북' 행으로 본다.")
    stale = stale_labels()
    if stale:
        print(f"경고: 라벨 이후 base 답변이 바뀐 건 {stale} — 이 건의 일치율은 신뢰할 수 없음.")
    if agree is None:
        print("사람 라벨 미입력 — Judge 일치율 미산출. 품질 수치는 Judge 오차를 모른 채 읽어야 함.")
    else:
        print(f"Judge 일치율 {agree:.0%} ({n_lab}건, base 답변 기준) — 품질 수치는 이 오차를 안고 읽는다.")
        if miss:
            print("불일치: " + ", ".join(miss))


if __name__ == "__main__":
    main()
