"""구성 간 차이의 유의성 — 질의 단위 paired bootstrap.

같은 질의끼리 짝지어 (구성 B - 구성 A) 차이를 구하고, 질의를 복원 추출로 2,000번 다시 뽑아
차이 평균의 95% 신뢰구간을 낸다. 질의별 값은 3회 반복의 평균이다.
구간이 0을 포함하지 않으면 '유의' 로 표시한다. 반복 간 CI(report.py)는 실행 변동만 보고,
이 구간은 '다른 질의였다면' 의 변동까지 본다.

    python -m eval.stats                 # holdout (기본)
    python -m eval.stats --split all
    python -m eval.stats --tag _latctl   # 지연 통제 재측정 (results/*_latctl_latest.json)

입력: results/<구성><tag>_latest.json 의 rows. 출력: results/stats_<split><tag>.json (+ 표 출력).
이 파일의 pairs 가 README 기여도 표, fig6, CLAIMS 의 '짝지은 차이'의 출처다.
질의마다 두 구성 모두 값이 있어야 짝이 되므로, 지표마다 n(공통 질의 수)이 다를 수 있다.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

PAIRS = [   # (A, B, 이 비교가 보여주는 것)
    ("base", "rag", "RAG 단독"),
    ("base", "judge", "Judge 단독"),
    ("rag", "rag_judge", "RAG 위에 Judge"),
    ("rag_judge", "rag_judge_cost", "캐스케이드+캐시"),
    ("rag_judge", "rag_judge_v2", "v2 보완"),
    ("rag_judge_v2", "final", "v2 위에 비용·런타임"),
    ("base", "final", "전체 (Before→After)"),
]


def _per_query(rows: list[dict]) -> dict:
    """질의별 지표 (반복 평균).

    지표 정의 (None = 이 질의는 그 지표의 대상이 아님 → 짝에서 빠짐)
      pass     평가 Judge 합격 (판정 불가 행 제외)
      must     must_include 어구 포함 비율
      hit1     1순위 런북이 정답 (정답 있는 질의만)
      miss     장애 경로 + 정답 있는 질의에서, 넣은 런북에 정답이 하나도 없음
      wrong    장애 경로 질의에서, 정답 아닌 런북이 섞임 (정답 없는 질의에 런북을 넣은 것 포함)
      cost     질의 비용(USD), latency 지연(초)
    miss, wrong 의 정의는 eval/extra_metrics.py 의 _miss, _wrong 과 같다.
    """
    by = {}
    for r in rows:
        if "error" in r:
            continue
        by.setdefault(r["id"], []).append(r)
    out = {}
    for qid, rs in by.items():
        def avg(f):
            """이 질의의 반복 행들에 f 를 적용해 None 을 뺀 평균. 대상 값이 하나도 없으면 None."""
            vals = [v for v in (f(r) for r in rs) if v is not None]
            return statistics.fmean(vals) if vals else None
        gold = rs[0]["gold"]
        out[qid] = {
            "pass": avg(lambda r: None if r.get("judge_passed") is None else float(r["judge_passed"])),
            "must": avg(lambda r: r["must_hit"] / r["must_total"] if r["must_total"] else None),
            "hit1": avg(lambda r: float(bool(r["retrieved"]) and r["retrieved"][0] in gold) if gold else None),
            "miss": avg(lambda r: float(not set(r["fed_runbooks"]) & set(gold))
                        if gold and r["route"] == "incident" else None),
            "wrong": avg(lambda r: float(bool(set(r["fed_runbooks"]) - set(gold)) if gold
                                         else bool(r["fed_runbooks"])) if r["route"] == "incident" else None),
            "cost": avg(lambda r: r["cost_usd"]),
            "latency": avg(lambda r: r["latency_ms"] / 1000),
        }
    return out


def bootstrap(a: dict, b: dict, metric: str, n: int = 2000, seed: int = 0) -> dict | None:
    """질의 단위 paired bootstrap: 짝 차이(b - a)를 복원 추출 n번 → 평균 차이의 백분위 95% 구간.

    seed 고정이라 다시 돌려도 같은 구간이 나온다. 구간이 0을 포함하지 않으면 significant=True.
    Returns: {n(짝 수), diff(평균 차이), lo, hi, significant} 또는 짝이 없으면 None.
    """
    ids = [q for q in a if q in b and a[q][metric] is not None and b[q][metric] is not None]
    if not ids:
        return None
    diffs = [b[q][metric] - a[q][metric] for q in ids]
    rnd = random.Random(seed)
    boots = sorted(statistics.fmean(rnd.choices(diffs, k=len(diffs))) for _ in range(n))
    lo, hi = boots[int(0.025 * n)], boots[int(0.975 * n) - 1]   # n=2000 → 정렬된 boots[50], boots[1949]
    return {"n": len(ids), "diff": statistics.fmean(diffs), "lo": lo, "hi": hi,
            "significant": lo > 0 or hi < 0}


def run(split: str | None, tag: str = "") -> dict:
    """PAIRS 의 모든 비교 x 7개 지표에 bootstrap 을 돌린다. split=None 이면 dev+holdout 전체."""
    data = {}
    for nm in {x for p in PAIRS for x in p[:2]}:
        rows = json.loads((RESULTS / f"{nm}{tag}_latest.json").read_text())["rows"]
        if split:
            rows = [r for r in rows if r.get("split") == split]
        data[nm] = _per_query(rows)
    out = []
    for a, b, label in PAIRS:
        res = {m: bootstrap(data[a], data[b], m) for m in
               ("pass", "must", "hit1", "miss", "wrong", "cost", "latency")}
        out.append({"a": a, "b": b, "label": label, **res})
    return {"split": split or "all", "tag": tag, "n_boot": 2000, "pairs": out}


FMT = {"pass": ("평가 Judge 통과", 100, "%p"), "must": ("런북 어구 포함", 100, "%p"),
       "hit1": ("Recall@1", 100, "%p"), "miss": ("정답 런북 누락", 100, "%p"),
       "wrong": ("무관 런북 혼입", 100, "%p"), "cost": ("질의당 비용", 1, "$"),
       "latency": ("질의당 지연", 1, "초")}


def fmt(r: dict | None, metric: str) -> str:
    """'차이 [하한, 상한]' 문자열. 비율은 %p, 비용은 $, 지연은 초. 유의하면 끝에 *."""
    if not r:
        return "-"
    _, k, u = FMT[metric]
    if u == "$":
        s = f"{r['diff']:+.4f} [{r['lo']:+.4f}, {r['hi']:+.4f}]"
    elif u == "초":
        s = f"{r['diff']:+.1f} [{r['lo']:+.1f}, {r['hi']:+.1f}]"
    else:
        s = f"{r['diff'] * k:+.0f} [{r['lo'] * k:+.0f}, {r['hi'] * k:+.0f}]"
    return s + (" *" if r["significant"] else "")


def main():
    """CLI 진입점. --split 범위로 PAIRS 비교를 계산해 results/stats_<split><tag>.json 에 저장하고 표로 출력한다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="holdout", choices=["holdout", "dev", "all"])
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--tag", default="", help="결과 파일 접미사 (예: _latctl = 지연 통제 재측정)")
    args = ap.parse_args()
    res = run(None if args.split == "all" else args.split, args.tag)
    (RESULTS / f"stats_{res['split']}{args.tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    metrics = ["hit1", "miss", "wrong", "must", "pass", "cost", "latency"]
    head = ["비교"] + [f"{FMT[m][0]} ({FMT[m][2]})" for m in metrics]
    lines = [[f"{p['label']}: {p['a']}→{p['b']}"] + [fmt(p[m], m) for m in metrics] for p in res["pairs"]]
    from tabulate import tabulate
    print(f"{'### ' if args.md else ''}구성 간 차이 — {res['split']}, 질의 단위 paired bootstrap 95% CI "
          f"(* = 구간이 0을 포함하지 않음)\n")
    print(tabulate(lines, headers=head, tablefmt="github" if args.md else "simple"))


if __name__ == "__main__":
    main()
