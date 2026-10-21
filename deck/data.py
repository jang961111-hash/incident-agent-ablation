"""덱에 들어가는 모든 수치를 results/ 에서 모아 JSON 하나로 낸다. build.js 가 이것만 읽는다.

    ../.venv/bin/python data.py > data.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
R = ROOT / "results"

from eval.extra_metrics import load_all as extra  # noqa: E402

ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]


def load(p):
    return json.loads(p.read_text()) if p.exists() else None


out = {"configs": ORDER, "summary": {}, "holdout": {}, "dev": {}}
for n in ORDER:
    s = load(R / f"{n}_latest.json")["summary"]
    out["summary"][n] = {k: v for k, v in s.items() if not isinstance(v, (dict, list))}
    for sp in ("holdout", "dev"):
        b = s["by_split"][sp]
        out[sp][n] = {**b["mean"], "ci": {k: v["ci95"] for k, v in b["agg"].items()}}
for sp in ("holdout", "dev", None):
    out[f"extra_{sp or 'all'}"] = extra(sp)
out["stats_holdout"] = load(R / "stats_holdout.json")
out["calibrate"] = (load(R / "calibrate_rag.json") or {}).get("best")
out["cache"] = load(R / "cache_bench_latest.json")
out["concurrency"] = load(R / "concurrency_bench_latest.json")
fault = load(R / "fault_bench_latest.json")
if fault:   # 행 본문은 빼고 요약만
    for v in fault["variants"].values():
        v.pop("rows", None)
out["fault"] = fault
try:
    from eval.agreement import summary_dict
    a = summary_dict("base")
    out["agreement"] = {"n_labeled": a["n_labeled"], "n_compared": a["n_compared"],
                        "stale": a["stale"], "metrics": a["metrics"],
                        "by_metric_direction": a["by_metric_direction"]}
except Exception as e:   # 라벨 전이면 비어 있다
    out["agreement"] = {"error": str(e), "n_compared": 0}

print(json.dumps(out, ensure_ascii=False, default=lambda o: None))
