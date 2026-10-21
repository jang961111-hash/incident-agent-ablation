"""Ablation 실행기 — 구성별로 같은 평가셋을 돌려 결과를 results/ 에 남긴다.

사용:
    python -m eval.run_ablation --config eval/configs/base.yaml
    python -m eval.run_ablation --all
    python -m eval.run_ablation --config eval/configs/rag.yaml --ids Q01,Q16 --no-save

평가용 Judge 는 구성과 무관하게 EVAL_JUDGE_MODEL(기본 gpt-4o)로 고정한다. 파이프라인 안의
Validator(rag_judge 이후 gpt-4o-mini)와 같은 모델·같은 기준으로 채점하면, Validator 기준에
맞춰 고친 답이 자동으로 높은 점수를 받는 순환이 생긴다.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from eval.retrieval_metrics import summarize as summarize_retrieval

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "eval" / "configs"
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "rag_judge", "rag_judge_cost"]
EVAL_JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-4o")
METRICS = ("relevance", "completeness", "domain_appropriateness", "clarity")


def load_queries() -> tuple[list[dict], float]:
    data = yaml.safe_load((ROOT / "eval" / "queries.yaml").read_text(encoding="utf-8"))
    return data["queries"], data.get("threshold", 0.75)


def run_config(cfg_path: Path, queries: list[dict], threshold: float,
               use_judge: bool = True, save: bool = True, backend: str | None = None) -> dict:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if backend:
        cfg["backend"] = backend
    name = cfg["name"]
    print(f"\n=== {name} === {cfg.get('description', '')}", flush=True)

    from src.adapter import run_once

    judge = None
    if use_judge:
        from eval.judge import Judge
        judge = Judge(model=EVAL_JUDGE_MODEL, threshold=threshold)

    rows, retrieval_records = [], []
    for q in queries:
        try:
            out = run_once(q["query"], cfg)
        except Exception as e:   # 1건 실패로 전체 실행을 잃지 않는다. 실패는 그대로 기록
            print(f"  {q['id']}  ERROR {type(e).__name__}: {e}", flush=True)
            rows.append({"id": q["id"], "category": q.get("category"), "error": repr(e),
                         "traceback": traceback.format_exc()})
            continue

        jerr = None
        jverd, jreason, jscore, jpass = {}, {}, float("nan"), None
        if judge:
            try:   # 평가 Judge 오류는 '판정 불가'로 남기고 다음 건으로 간다
                jr = judge.evaluate(q["query"], out.get("context", ""), out["answer"])
                jverd, jreason, jscore, jpass = jr.verdicts, jr.reasons, jr.score, jr.passed
            except Exception as e:
                jerr = repr(e)
                print(f"  {q['id']}  JUDGE ERROR {type(e).__name__}: {e}", flush=True)

        row = {
            "id": q["id"],
            "category": q.get("category"),
            "query": q["query"],
            "answer": out["answer"],
            "context": out.get("context", ""),
            "route": out.get("route"),
            "retrieved": out.get("retrieved", []),
            "fed_runbooks": out.get("fed_runbooks", []),
            "gold": q.get("gold_runbooks", []),
            "judge_score": jscore,
            "judge_passed": jpass,
            **{f"judge_{m}": jverd.get(m) for m in METRICS},
            "judge_reasons": jreason,
            "judge_error": jerr,
            "pipeline_judge": out.get("judge_history", []),
            "rewrites": out.get("rewrites", 0),
            "latency_ms": out.get("latency_ms"),
            "tokens": out.get("tokens", {}),
            "tokens_by_model": out.get("tokens_by_model", {}),
            "cost_usd": out.get("cost_usd", float("nan")),
            "cache": out.get("cache", {}),
            "llm_calls": out.get("llm_calls", []),
            "events": out.get("events", []),
            "trace_url": out.get("trace_url"),
        }
        rows.append(row)
        if q.get("gold_runbooks"):
            retrieval_records.append({"retrieved": row["retrieved"], "gold": row["gold"],
                                      "fed": row["fed_runbooks"], "route": row["route"]})
        jtxt = (f"judge={jscore:.2f} {'PASS' if jpass else 'FAIL'}" if jpass is not None
                else "judge=n/a")
        print(f"  {q['id']}  {row['route']:8}  ret={row['retrieved'][:3]}  {jtxt}  "
              f"rw={row['rewrites']}  {row['latency_ms']:.0f}ms  ${row['cost_usd']:.4f}", flush=True)
        if save:   # 매 건 중간 저장 — 도중에 끊겨도 앞선 결과를 잃지 않는다
            RESULTS.mkdir(exist_ok=True)
            (RESULTS / f"{name}_partial.json").write_text(
                json.dumps({"config": cfg, "rows": rows}, ensure_ascii=False, indent=2))

    summary = build_summary(name, rows, retrieval_records)
    summary["eval_judge_model"] = EVAL_JUDGE_MODEL if judge else None
    if save:
        payload = json.dumps({"config": cfg, "summary": summary, "rows": rows},
                             ensure_ascii=False, indent=2)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        (RESULTS / f"{name}_{stamp}.json").write_text(payload, encoding="utf-8")
        (RESULTS / f"{name}_latest.json").write_text(payload, encoding="utf-8")
        (RESULTS / f"{name}_partial.json").unlink(missing_ok=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return summary


def _pct(values: list[float], p: float) -> float:
    """선형 보간 백분위 (numpy 기본과 같음)."""
    if not values:
        return float("nan")
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def build_summary(name: str, rows: list[dict], retrieval_records: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    judged = [r for r in ok if r["judge_passed"] is not None]
    lat = [r["latency_ms"] for r in ok]
    n = len(judged)

    def rate(pred, pool):
        return sum(1 for r in pool if pred(r)) / len(pool) if pool else float("nan")

    s = {
        "config": name,
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "n_judged": n,                      # 지표마다 분모를 밝힌다
        # 답변 품질 — 평가용 Judge 지표별 Pass율
        **{m: rate(lambda r, m=m: r[f"judge_{m}"] == "Pass", judged) for m in METRICS},
        "judge_mean": statistics.fmean(r["judge_score"] for r in judged) if judged else float("nan"),
        "pass_rate": rate(lambda r: r["judge_passed"], judged),
        # 운영
        "latency_p50_ms": _pct(lat, 0.50),
        "latency_p95_ms": _pct(lat, 0.95),
        "rewrites_total": sum(r["rewrites"] for r in ok),
        "cost_usd_total": sum(r["cost_usd"] for r in ok if r["cost_usd"] == r["cost_usd"]),
        "tokens_prompt": sum(r["tokens"].get("prompt", 0) for r in ok),
        "tokens_completion": sum(r["tokens"].get("completion", 0) for r in ok),
        "cache_hits": sum(r["cache"].get("hits", 0) for r in ok),
        "cache_lookups": sum(r["cache"].get("lookups", 0) for r in ok),
        "routed_incident": sum(1 for r in ok if r["route"] == "incident"),
    }
    # 카테고리별 통과율 — 한계 분석 재료
    for cat in sorted({r["category"] for r in judged}):
        sub = [r for r in judged if r["category"] == cat]
        s[f"pass_rate[{cat}]"] = rate(lambda r: r["judge_passed"], sub)
    if retrieval_records:
        s["n_retrieval"] = len(retrieval_records)
        s.update(summarize_retrieval(retrieval_records))
        # chat 으로 빠진 건은 검색 자체가 없다 — 라우팅 실패와 검색 실패를 분리해서 본다
        routed = [r for r in retrieval_records if r["route"] == "incident"]
        s["n_retrieval_incident"] = len(routed)
        if routed:
            s.update({f"{k}|incident": v for k, v in summarize_retrieval(routed).items()})
        # 순위가 아니라 write 에 실제로 넣은 런북 기준. base(1개)와 rag(가변)를 공정하게 비교
        s["fed_recall"] = statistics.fmean(
            len(set(r["fed"]) & set(r["gold"])) / len(r["gold"]) for r in retrieval_records)
        fed_any = [r for r in retrieval_records if r["fed"]]
        s["fed_precision"] = (statistics.fmean(len(set(r["fed"]) & set(r["gold"])) / len(r["fed"])
                                               for r in fed_any) if fed_any else float("nan"))
        s["fed_count_mean"] = statistics.fmean(len(r["fed"]) for r in retrieval_records)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", help="Q01,Q05 처럼 일부만 실행")
    ap.add_argument("--no-judge", action="store_true", help="평가용 Judge 생략 (배관 점검용)")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--backend", choices=["openai", "fake"], help="fake = 키 없이 배관 점검")
    args = ap.parse_args()

    queries, threshold = load_queries()
    if args.ids:
        want = set(args.ids.split(","))
        queries = [q for q in queries if q["id"] in want]
    kw = dict(use_judge=not args.no_judge, backend=args.backend,
              save=(not args.no_save and not args.ids and not args.no_judge
                    and args.backend != "fake"))   # 판정 없는 결과로 _latest 를 덮어쓰지 않는다
    if args.all:
        for nm in ORDER:
            run_config(CONFIG_DIR / f"{nm}.yaml", queries, threshold, **kw)
    elif args.config:
        run_config(Path(args.config), queries, threshold, **kw)
    else:
        ap.error("--config 또는 --all 중 하나가 필요합니다.")


if __name__ == "__main__":
    sys.exit(main())
