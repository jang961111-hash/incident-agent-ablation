"""오염된 반복을 집계에서 빼고 다시 요약한다. 뺀 행은 지우지 않고 excluded_rows 에 사유와 함께 남긴다.

    python -m eval.exclude_reps --config rag_judge_cost final --reps 2 --reason "..."

배경: v2 실측(2026-10-21)에서 rag_judge_cost·final 의 2회차에만 앞 반복의 캐시가 적중했다
(160·158회). 반복을 cold 로 다시 잴 API 한도가 없어, 2회차를 빼고 1·3회차로 집계한다.
반복이 2회라 반복 간 95% CI 는 t(df=1)=12.7 로 넓다. 구성 간 비교는 질의 단위 bootstrap 을 본다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.run_ablation import RESULTS, aggregate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--reps", nargs="+", type=int, required=True)
    ap.add_argument("--reason", required=True)
    a = ap.parse_args()
    for name in a.config:
        p = RESULTS / f"{name}_latest.json"
        d = json.loads(p.read_text())
        rows = d["rows"] + d.get("excluded_rows", [])          # 이미 뺀 적이 있으면 원상 복구 후 다시
        keep = [r for r in rows if r.get("rep") not in a.reps]
        drop = [r for r in rows if r.get("rep") in a.reps]
        reps = d["summary"].get("reps", 3)
        summary = aggregate(name, keep, reps)
        summary["eval_judge_model"] = d["summary"].get("eval_judge_model")
        summary["excluded_reps"] = a.reps
        summary["exclusion_reason"] = a.reason
        d.update({"summary": summary, "rows": keep, "excluded_rows": drop})
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        hits = {rep: sum(r["cache"].get("hits", 0) for r in keep if r["rep"] == rep) for rep in sorted({r["rep"] for r in keep})}
        print(f"{name}: 남은 반복 {sorted({r['rep'] for r in keep})}, 뺀 행 {len(drop)}, 남은 반복 캐시 적중 {hits}")


if __name__ == "__main__":
    main()
