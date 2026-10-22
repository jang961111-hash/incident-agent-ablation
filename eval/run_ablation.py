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
ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]
EVAL_JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-4o")
METRICS = ("relevance", "completeness", "domain_appropriateness", "clarity")


def load_queries() -> tuple[list[dict], float]:
    data = yaml.safe_load((ROOT / "eval" / "queries.yaml").read_text(encoding="utf-8"))
    return data["queries"], data.get("threshold", 0.75)


def _evaluate_one(q: dict, rep: int, cfg: dict, run_once, judge) -> dict:
    """질의 1건 x 반복 1회 실행 + 평가. 예외는 행에 기록하고 올리지 않는다."""
    from ext.factcheck import check as factcheck
    try:
        out = run_once(q["query"], cfg)
    except Exception as e:   # 1건 실패로 전체 실행을 잃지 않는다. 실패는 그대로 기록
        return {"id": q["id"], "rep": rep, "split": q.get("split"), "category": q.get("category"),
                "error": repr(e), "traceback": traceback.format_exc()}
    jerr = None
    jverd, jreason, jscore, jpass = {}, {}, float("nan"), None
    if judge:
        try:   # 평가 Judge 오류는 '판정 불가'로 남긴다
            jr = judge.evaluate(q["query"], out.get("context", ""), out["answer"])
            jverd, jreason, jscore, jpass = jr.verdicts, jr.reasons, jr.score, jr.passed
        except Exception as e:
            jerr = repr(e)
    need = q.get("must_include") or []
    ans = out["answer"].lower()
    fc = factcheck(out["answer"], out.get("context", ""))
    return {
        "id": q["id"], "rep": rep, "split": q.get("split"), "category": q.get("category"),
        "query": q["query"], "answer": out["answer"], "context": out.get("context", ""),
        "route": out.get("route"), "retrieved": out.get("retrieved", []),
        "fed_runbooks": out.get("fed_runbooks", []), "gold": q.get("gold_runbooks", []),
        "judge_score": jscore, "judge_passed": jpass,
        **{f"judge_{m}": jverd.get(m) for m in METRICS},
        "judge_reasons": jreason, "judge_error": jerr,
        "must_total": len(need), "must_hit": sum(1 for m in need if m.lower() in ans),
        "unsupported_numbers": fc["unsupported"], "n_number_claims": fc["n_claims"],
        "pipeline_judge": out.get("judge_history", []), "rewrites": out.get("rewrites", 0),
        "latency_ms": out.get("latency_ms"), "tokens": out.get("tokens", {}),
        "tokens_by_model": out.get("tokens_by_model", {}),
        "cost_usd": out.get("cost_usd", float("nan")), "cache": out.get("cache", {}),
        "llm_calls": out.get("llm_calls", []), "events": out.get("events", []),
        "notices": out.get("notices", []), "tool_failures": out.get("tool_failures", 0),
        "faults_injected": out.get("faults_injected", 0), "api_retries": out.get("api_retries", 0),
        "trace_url": out.get("trace_url"),
    }


def run_config(cfg_path: Path, queries: list[dict], threshold: float, use_judge: bool = True,
               save: bool = True, backend: str | None = None, reps: int = 1,
               workers: int = 1, tag: str = "") -> dict:
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if backend:
        cfg["backend"] = backend
    name = cfg["name"] + tag
    print(f"\n=== {name} === reps={reps} workers={workers} n={len(queries)} {cfg.get('description', '')}",
          flush=True)

    from src.adapter import run_once

    judge = None
    if use_judge:
        from eval.judge import Judge
        judge = Judge(model=EVAL_JUDGE_MODEL, threshold=threshold)

    import src.adapter as adapter_mod

    jobs = [(rep, q) for rep in range(1, reps + 1) for q in queries]
    rows, lock = [], threading.Lock()

    def run_rep(rep: int):
        # 반복마다 캐시를 비운다 — 각 반복을 처음 실행(cold)으로 재야 공정하다.
        # (v2 1차 실측에서 2회차에 앞 반복의 캐시가 적중해 비용·지연이 유리하게 섞인 문제 수정)
        adapter_mod._CACHES.clear()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_evaluate_one, q, r, cfg, run_once, judge) for r, q in jobs if r == rep]
            for f in as_completed(futs):
                yield f

    for f in (f for rep in range(1, reps + 1) for f in run_rep(rep)):
        row = f.result()
        with lock:
            rows.append(row)
            if "error" in row:
                print(f"  r{row['rep']} {row['id']}  ERROR {row['error'][:120]}", flush=True)
            else:
                jtxt = (f"judge={row['judge_score']:.2f} {'PASS' if row['judge_passed'] else 'FAIL'}"
                        if row["judge_passed"] is not None else "judge=n/a")
                print(f"  r{row['rep']} {row['id']}  {row['route']:8}  ret={row['retrieved'][:2]}  {jtxt}  "
                      f"rw={row['rewrites']}  {row['latency_ms']:.0f}ms  ${row['cost_usd']:.4f}"
                      f"  [{len(rows)}/{len(jobs)}]", flush=True)
            if save:   # 중간 저장 — 도중에 끊겨도 앞선 결과를 잃지 않는다
                RESULTS.mkdir(exist_ok=True)
                (RESULTS / f"{name}_partial.json").write_text(
                    json.dumps({"config": cfg, "rows": rows}, ensure_ascii=False))
    rows.sort(key=lambda r: (r["rep"], r["id"]))

    summary = aggregate(name, rows, reps)
    summary["eval_judge_model"] = EVAL_JUDGE_MODEL if judge else None
    if save:
        payload = json.dumps({"config": cfg, "summary": summary, "rows": rows},
                             ensure_ascii=False, indent=1)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        (RESULTS / f"{name}_{stamp}.json").write_text(payload, encoding="utf-8")
        (RESULTS / f"{name}_latest.json").write_text(payload, encoding="utf-8")
        (RESULTS / f"{name}_partial.json").unlink(missing_ok=True)
    keys = ("n", "errors", "pass_rate", "must_phrase_rate", "recall@1", "fed_precision",
            "unsupported_answer_rate", "latency_p95_ms", "cost_usd_total", "rewrites_total")
    print(json.dumps({k: summary.get(k) for k in keys}, ensure_ascii=False), flush=True)
    return summary


_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}


def _agg(per_rep: list[dict]) -> dict:
    """반복별 summary 들의 평균·표준편차·95% 신뢰구간 반폭 (t 분포)."""
    out = {}
    keys = {k for s in per_rep for k, v in s.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for k in keys:
        vals = [s[k] for s in per_rep if isinstance(s.get(k), (int, float)) and s[k] == s[k]]
        if not vals:
            continue
        m = statistics.fmean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        ci = _T95.get(len(vals) - 1, 1.96) * sd / len(vals) ** 0.5 if len(vals) > 1 else float("nan")
        out[k] = {"mean": m, "sd": sd, "ci95": ci, "n_reps": len(vals)}
    return out


def aggregate(name: str, rows: list[dict], reps: int) -> dict:
    """반복별·split 별 summary 를 만들고, 전체 평균을 최상위 키로 둔다 (report 호환)."""
    def summarize(sub):
        ok = [r for r in sub if "error" not in r]
        rec = [{"retrieved": r["retrieved"], "gold": r["gold"], "fed": r["fed_runbooks"],
                "route": r["route"]} for r in ok if r["gold"]]
        s = build_summary(name, sub, rec)
        tot = sum(r["must_total"] for r in ok)
        s["must_phrase_rate"] = sum(r["must_hit"] for r in ok) / tot if tot else float("nan")
        withm = [r for r in ok if r["must_total"]]
        s["must_all_rate"] = (sum(r["must_hit"] == r["must_total"] for r in withm) / len(withm)
                              if withm else float("nan"))
        s["unsupported_answer_rate"] = (sum(1 for r in ok if r["unsupported_numbers"]) / len(ok)
                                        if ok else float("nan"))
        s["judge_calls"] = sum(1 for r in ok for c in r["llm_calls"] if c["stage"] == "judge")
        s["factcheck_rejects"] = sum(1 for r in ok for h in r["pipeline_judge"] if h.get("by") == "factcheck")
        s["tool_failures"] = sum(r.get("tool_failures", 0) for r in ok)
        s["api_retries"] = sum(r.get("api_retries", 0) for r in ok)
        return s

    by_rep = {rep: [r for r in rows if r["rep"] == rep] for rep in range(1, reps + 1)}
    per_rep = [summarize(v) for v in by_rep.values() if v]
    agg = _agg(per_rep)
    top = {k: v["mean"] for k, v in agg.items()}
    top.update({"config": name, "reps": reps, "agg": agg, "per_rep": per_rep})
    top["by_split"] = {}
    for sp in sorted({r.get("split") for r in rows if r.get("split")}):
        pr = [summarize([r for r in v if r.get("split") == sp]) for v in by_rep.values() if v]
        a = _agg(pr)
        top["by_split"][sp] = {"mean": {k: v["mean"] for k, v in a.items()}, "agg": a}
    return top


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
    ap.add_argument("--reps", type=int, default=1, help="반복 횟수 (평균·표준편차·95%% CI)")
    ap.add_argument("--workers", type=int, default=1, help="질의 병렬 실행 수")
    ap.add_argument("--split", choices=["dev", "holdout"], help="해당 split 만 실행")
    ap.add_argument("--tag", default="", help="결과 파일 이름 뒤에 붙일 접미사")
    args = ap.parse_args()

    queries, threshold = load_queries()
    if args.ids:
        want = set(args.ids.split(","))
        queries = [q for q in queries if q["id"] in want]
    if args.split:
        queries = [q for q in queries if q.get("split") == args.split]
    kw = dict(use_judge=not args.no_judge, backend=args.backend, reps=args.reps,
              workers=args.workers, tag=args.tag,
              save=(not args.no_save and not args.ids and (not args.no_judge or bool(args.tag))
                    and args.backend != "fake"))   # 판정 없는 결과는 --tag 를 붙여 별도 파일로만 저장 (_latest 보호)
    if args.all:
        for nm in ORDER:
            run_config(CONFIG_DIR / f"{nm}.yaml", queries, threshold, **kw)
    elif args.config:
        run_config(Path(args.config), queries, threshold, **kw)
    else:
        ap.error("--config 또는 --all 중 하나가 필요합니다.")


if __name__ == "__main__":
    sys.exit(main())
