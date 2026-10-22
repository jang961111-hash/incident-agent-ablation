"""오염된 반복을 집계에서 빼고 다시 요약한다. 뺀 행은 지우지 않고 excluded_rows 에 사유와 함께 남긴다.

    python -m eval.exclude_reps --config rag_judge_cost final --reps 2 --reason "..."

배경: v2 실측(2026-10-21)에서 rag_judge_cost, final 의 2회차에만 앞 반복의 캐시가 적중했다
(160, 158회). 반복을 cold 로 다시 잴 API 한도가 없어, 2회차를 빼고 1, 3회차로 집계한다.
반복이 2회라 반복 간 95% CI 는 t(df=1)=12.7 로 넓다. 구성 간 비교는 질의 단위 bootstrap 을 본다.

results/<구성>_latest.json 을 제자리에서 고쳐 쓴다 (summary, rows 교체, excluded_rows, exclusion_reason 추가).
요약은 eval/run_ablation.aggregate 를 그대로 다시 불러 만든다 — 집계 방식이 본 실행과 같다.
다시 실행해도 안전하다: 이전에 뺀 행을 먼저 되돌린 뒤 이번 --reps 로 다시 뺀다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.run_ablation import RESULTS, aggregate


def main():
    """CLI 진입점. --config 구성마다 --reps 반복의 행을 집계에서 빼고 summary 를 다시 만든다.

    뺀 행은 excluded_rows 에, 사유는 summary 의 exclusion_reason 에 남겨 나중에 되돌릴 수 있게 한다.
    """
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
