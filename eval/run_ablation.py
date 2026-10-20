"""Ablation 실행기 — 구성별로 같은 평가셋을 돌려 결과를 results/ 에 남긴다.

사용:
    python -m eval.run_ablation --config eval/configs/base.yaml
    python -m eval.run_ablation --all
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import yaml

from eval.judge import Judge, METRICS
from eval.retrieval_metrics import summarize as summarize_retrieval

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "eval" / "configs"
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "rag_judge", "rag_judge_cost"]

# 1K 토큰당 USD. 보고서에 '추정'임을 반드시 표기한다.
PRICE = {
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
    "gpt-4o":      {"prompt": 0.0025,  "completion": 0.01},
}


def load_queries() -> tuple[list[dict], float]:
    data = yaml.safe_load((ROOT / "eval" / "queries.yaml").read_text(encoding="utf-8"))
    return data["queries"], data.get("threshold", 0.8)


def estimate_cost(tokens: dict, model: str) -> float:
    p = PRICE.get(model)
    if not p:
        return float("nan")
    return (tokens.get("prompt", 0) / 1000 * p["prompt"]
            + tokens.get("completion", 0) / 1000 * p["completion"])


def run_config(cfg_path: Path, queries: list[dict], threshold: float) -> dict:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    name = cfg["name"]
    print(f"\n=== {name} === {cfg.get('description', '')}")

    # 베이스 코드를 넣은 뒤 src/adapter.py 를 만들면 이 import가 살아난다.
    from src.adapter import run_once

    judge = Judge(model=cfg["models"].get("judge", "gpt-4o-mini"),
                  threshold=cfg.get("judge", {}).get("threshold", threshold))

    rows, retrieval_records = [], []
    for q in queries:
        t0 = time.monotonic()
        out = run_once(q["query"], cfg)
        wall_ms = (time.monotonic() - t0) * 1000

        jr = judge.evaluate(q["query"], out.get("context", ""), out["answer"])

        model_used = cfg["models"].get("quality") or cfg["models"].get("default", "gpt-4o-mini")
        row = {
            "id": q["id"],
            "category": q.get("category"),
            "answer": out["answer"],
            "retrieved": out.get("retrieved", []),
            "gold": q.get("gold_runbooks", []),
            "judge_score": jr.score,
            "judge_passed": jr.passed,
            **{f"judge_{m}": jr.verdicts.get(m) for m in METRICS},
            "rewrites": out.get("rewrites", 0),
            "latency_ms": out.get("latency_ms", wall_ms),
            "tokens": out.get("tokens", {}),
            "cost_usd": estimate_cost(out.get("tokens", {}), model_used),
            "human_label": q.get("human_label"),
            "trace_url": out.get("trace_url"),
        }
        rows.append(row)
        if q.get("gold_runbooks"):
            retrieval_records.append({"retrieved": row["retrieved"], "gold": row["gold"]})
        print(f"  {q['id']}  judge={jr.score:.2f}  "
              f"{'PASS' if jr.passed else 'FAIL'}  {row['latency_ms']:.0f}ms")

    summary = build_summary(name, rows, retrieval_records)
    RESULTS.mkdir(exist_ok=True)
    payload = json.dumps({"config": cfg, "summary": summary, "rows": rows},
                         ensure_ascii=False, indent=2)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    (RESULTS / f"{name}_{stamp}.json").write_text(payload, encoding="utf-8")
    (RESULTS / f"{name}_latest.json").write_text(payload, encoding="utf-8")
    return summary


def build_summary(name: str, rows: list[dict], retrieval_records: list[dict]) -> dict:
    lat_sorted = sorted(r["latency_ms"] for r in rows)
    n = len(rows) or 1

    s = {
        "config": name,
        "n": len(rows),
        # 답변 품질 — 지표별 Pass율
        **{m: sum(1 for r in rows if r[f"judge_{m}"] == "Pass") / n for m in METRICS},
        "judge_mean": statistics.fmean(r["judge_score"] for r in rows) if rows else 0.0,
        "pass_rate": sum(1 for r in rows if r["judge_passed"]) / n,
        # 운영
        "latency_p50_ms": lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0.0,
        "latency_p95_ms": lat_sorted[max(int(len(lat_sorted) * 0.95) - 1, 0)] if lat_sorted else 0.0,
        "rewrites_total": sum(r["rewrites"] for r in rows),
        "cost_usd_total": sum(r["cost_usd"] for r in rows if r["cost_usd"] == r["cost_usd"]),
    }
    # 검색 품질
    if retrieval_records:
        s.update(summarize_retrieval(retrieval_records))
    # 평가자 검증 — 사람 라벨이 있는 건만
    labeled = [r for r in rows if r["human_label"] in ("Pass", "Fail")]
    if labeled:
        agree = sum(1 for r in labeled
                    if (r["human_label"] == "Pass") == bool(r["judge_passed"]))
        s["judge_agreement"] = agree / len(labeled)
        s["judge_agreement_n"] = len(labeled)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    queries, threshold = load_queries()
    if args.all:
        for nm in ORDER:
            run_config(CONFIG_DIR / f"{nm}.yaml", queries, threshold)
    elif args.config:
        run_config(Path(args.config), queries, threshold)
    else:
        ap.error("--config 또는 --all 중 하나가 필요합니다.")


if __name__ == "__main__":
    main()
