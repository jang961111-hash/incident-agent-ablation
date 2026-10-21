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
out["excluded"] = {n: load(R / f"{n}_latest.json")["summary"].get("excluded_reps") for n in ORDER}
try:
    from eval.agreement import summary_dict as _sd
    c = _sd("base", labels_path=ROOT / "eval/claude_labels.yaml")
    out["claude_agreement"] = {"n_compared": c["n_compared"], "metrics": c["metrics"]}
except Exception as e:
    out["claude_agreement"] = {"error": str(e)}
out["calibrate"] = (load(R / "calibrate_rag.json") or {}).get("best")
out["cache"] = load(R / "cache_bench_latest.json")
# 캐시 대상 단계(route·plan·임베딩)가 final cold 비용에서 차지하는 비중 — 캐시 비용 절감의 상한
_P = {"gpt-4o-mini": (0.00015, 0.0006), "gpt-4o": (0.0025, 0.01), "text-embedding-3-small": (0.00002, 0)}
_tot = _cache = 0.0
for _r in load(R / "final_latest.json")["rows"]:
    for _c in _r.get("llm_calls", []):
        _v = _c["prompt"] / 1000 * _P[_c["model"]][0] + _c["completion"] / 1000 * _P[_c["model"]][1]
        _tot += _v
        if _c["stage"].split("#")[0] in ("route", "plan", "embed"):
            _cache += _v
out["cacheable_share_final"] = _cache / _tot if _tot else None
out["concurrency"] = load(R / "concurrency_bench_latest.json") or load(R / "concurrency_bench_simulated_latest.json")
fault = load(R / "fault_bench_latest.json") or load(R / "fault_bench_fake_latest.json")
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
