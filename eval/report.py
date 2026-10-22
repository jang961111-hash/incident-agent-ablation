"""results/*_latest.json 을 읽어 Ablation 비교표를 만든다.

    python -m eval.report                       # 전체 (dev+holdout)
    python -m eval.report --split holdout --md  # 최종 보고용 (holdout 만)

반복 실행 결과면 '평균 ±95% CI 반폭'으로 표시한다 (t 분포, 반복 수 기준).
Judge 일치율은 eval/agreement.py 가 eval/human_labels.yaml(사람 지표별 라벨)과
base_latest.json 의 평가 Judge 판정을 대조해 낸다. 라벨은 base 답변 기준이다.

입력: results/<구성>_latest.json 의 summary (eval/run_ablation.py 가 만든 것). 재실행, 재계산 없음.
--split 을 주면 summary.by_split[split] 의 평균, CI 를 쓴다. 구성 간 유의성은 이 표가 아니라
eval/stats.py(질의 단위 paired bootstrap)를 본다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]

# 표의 행: (summary 키, 표시 이름, 서식). 서식 None 은 구획 제목 행
ROWS = [
    ("__q", "답변 품질 — 평가 Judge (gpt-4o)", None),
    ("relevance",              "관련성",            "pct"),
    ("completeness",           "완전성",            "pct"),
    ("domain_appropriateness", "도메인 적합성",     "pct"),
    ("clarity",                "명확성",            "pct"),
    ("pass_rate",              "통과율 (3/4 이상)", "pct"),
    ("__d", "답변 품질 — 결정적 (Judge 무관)", None),
    ("must_phrase_rate",       "런북 핵심 어구 포함률", "pct"),
    ("must_all_rate",          "어구 전부 포함 비율", "pct"),
    ("unsupported_answer_rate", "근거 없는 수치가 있는 답 비율", "pct"),
    ("__r", "검색 품질", None),
    ("recall@1",               "Recall@1",          "pct"),
    ("recall@3",               "Recall@3 *",        "pct"),
    ("mrr",                    "MRR",               "f3"),
    ("fed_recall",             "투입 런북 재현율",  "pct"),
    ("fed_precision",          "투입 런북 정밀도",  "pct"),
    ("fed_count_mean",         "투입 런북 수 (평균)", "f2"),
    ("__o", "운영", None),
    ("latency_p50_ms",         "지연 p50 (ms)",     "f0"),
    ("latency_p95_ms",         "지연 p95 (ms)",     "f0"),
    ("rewrites_total",         "재작성 합계",       "f1"),
    ("judge_calls",            "파이프라인 Judge 호출", "f1"),
    ("factcheck_rejects",      "수치 검증 반려",    "f1"),
    ("tokens_prompt",          "입력 토큰",         "f0"),
    ("tokens_completion",      "출력 토큰",         "f0"),
    ("cost_usd_total",         "추정 비용 (USD)",   "f4"),
    ("errors",                 "실행 오류",         "f0"),
]

FMT = {"pct": lambda v: f"{v:.0%}", "f3": lambda v: f"{v:.3f}", "f2": lambda v: f"{v:.2f}",
       "f1": lambda v: f"{v:.1f}", "f0": lambda v: f"{v:,.0f}", "f4": lambda v: f"{v:.4f}"}
CIF = {"pct": lambda v: f"{v * 100:.0f}", "f3": lambda v: f"{v:.3f}", "f2": lambda v: f"{v:.2f}",
       "f1": lambda v: f"{v:.1f}", "f0": lambda v: f"{v:,.0f}", "f4": lambda v: f"{v:.4f}"}


def is_num(v) -> bool:
    """표에 쓸 수 있는 수인지 (bool, NaN 제외)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def load(split: str | None) -> dict:
    """구성 이름 → 요약 dict. 결과 파일이 없거나 해당 split 이 없는 구성은 건너뛴다."""
    found = {}
    for nm in ORDER:
        p = RESULTS / f"{nm}_latest.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text(encoding="utf-8"))["summary"]
        if split:
            sp = s.get("by_split", {}).get(split)
            if not sp:
                continue
            found[nm] = {**sp["mean"], "agg": sp["agg"], "reps": s.get("reps", 1)}
        else:
            found[nm] = s
    return found


def cell(s: dict, key: str, kind: str) -> str:
    """값 1칸. 반복이 2회 이상이면 '평균 ±95% CI 반폭' (퍼센트 지표의 반폭은 %p 숫자만)."""
    v = s.get(key)
    if not is_num(v):
        return "-"
    a = (s.get("agg") or {}).get(key)
    if a and a.get("n_reps", 1) > 1 and is_num(a.get("ci95")):
        return f"{FMT[kind](v)} ±{CIF[kind](a['ci95'])}"
    return FMT[kind](v)


def main():
    """CLI 진입점. results/ 의 최신 결과로 구성별 지표 표를 출력한다 (--split 으로 dev, holdout 선택).

    표 아래에 반복 횟수와 해석 주의, 사람 라벨이 있으면 base 기준 Judge 와 사람의 일치율을 덧붙인다.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    ap.add_argument("--split", choices=["dev", "holdout"])
    args = ap.parse_args()

    found = load(args.split)
    if not found:
        print("results/ 에 결과가 없습니다. 먼저 run_ablation 을 실행하세요.")
        return
    cols = list(found)
    table = []
    for key, label, kind in ROWS:
        if kind is None:
            table.append([f"**{label}**" if args.md else f"[{label}]"] + [""] * len(cols))
            continue
        if not any(is_num(found[c].get(key)) for c in cols):
            continue
        table.append([label] + [cell(found[c], key, kind) for c in cols])
    # 'pass_rate[normal]' → 'normal' (앞 10글자 'pass_rate[' 와 끝 ']' 를 뗀다)
    cats = sorted({k[10:-1] for s in found.values() for k in s if k.startswith("pass_rate[")})
    if cats:
        table.append(["**카테고리별 평가 Judge 통과율**" if args.md else "[카테고리별 통과율]"] + [""] * len(cols))
        for cat in cats:
            table.append([f"  {cat}"] + [cell(found[c], f"pass_rate[{cat}]", "pct") for c in cols])

    title = {"holdout": "holdout 36건 (조정에 쓰지 않은 질의)", "dev": "dev 24건", None: "전체 60건"}[args.split]
    print(f"{'### ' if args.md else ''}{title}\n")
    print(tabulate(table, headers=["지표"] + cols, tablefmt="github" if args.md else "simple"))
    reps = max(int(found[c].get("reps", 1)) for c in cols)
    print(f"\n반복 {reps}회. 값 옆 ±는 반복 간 95% 신뢰구간 반폭 (퍼센트는 %p). "
          "비용은 OpenAI 공개 단가 x 실측 토큰 추정치 (평가 Judge 비용 제외).")
    print("* base 는 런북을 1개만 고르므로 base 의 Recall@3 = Recall@1. 공정 비교는 '투입 런북' 행.")

    try:
        from eval.agreement import summary_dict
        a = summary_dict("base")
        ov = (a.get("metrics") or {}).get("overall") or {}
        if ov.get("n"):
            k = ov.get("kappa")
            print(f"Judge-사람 일치 (base 답변 {ov['n']}건): 일치율 {ov['agreement']:.0%}, "
                  + (f"kappa {k:.2f}" if is_num(k) else f"kappa 산출 불가 ({ov.get('kappa_note')})"))
        else:
            print("사람 라벨 미입력 — Judge 일치율 미산출 (python scripts/label.py).")
    except Exception as e:   # 리포트 표는 라벨 유무와 무관하게 나와야 한다
        print(f"Judge 일치율 계산 생략: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
