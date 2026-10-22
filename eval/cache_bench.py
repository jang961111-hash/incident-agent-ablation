"""캐시 효과 별도 측정 — 같은 프로세스에서 평가셋을 두 번 연속 돌린다.

Ablation 본 실행(cold 1회)에서는 질의가 겹치지 않아 캐시가 한 번도 맞지 않는다. 그래서
캐시 효과를 Ablation 표에 섞지 않고 이 스크립트로 따로 잰다. 당직 상황에서 같은 알림을
여러 사람이 반복해 묻는 경우를 흉내 낸 것이며, 문장이 조금만 달라도 캐시는 맞지 않는다
(정규화는 대소문자·공백·문장부호만 흡수).

    python -m eval.cache_bench                     # rag_judge_cost 구성, 24건 x 2회
    python -m eval.cache_bench --ids Q01,Q05

캐시 대상은 route·plan 결과와 질의 임베딩뿐이다 (src/ext/meter.py QueryCache). write·Judge 는
매번 호출되므로 2회차 비용 감소의 상한은 그 단계들의 비용 비중이다 (deck/data.py cacheable_share_final).
같은 프로세스에서 run_once 를 이어 부르므로 src/adapter.py 의 구성별 캐시(_CACHES)가 2회차까지 살아 있다.
결과: results/cache_bench_<YYYYMMDD_HHMM>.json, results/cache_bench_latest.json (fake·--ids 실행은 저장 안 함)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml

from eval.run_ablation import CONFIG_DIR, RESULTS, load_queries


def main():
    """평가셋을 같은 순서로 2회 돌려 회차별 캐시 적중·토큰·비용·지연 p50 을 비교한다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG_DIR / "rag_judge_cost.yaml"))
    ap.add_argument("--ids")
    ap.add_argument("--backend", choices=["openai", "fake"])
    args = ap.parse_args()

    from src.adapter import run_once

    cfg = yaml.safe_load(Path(args.config).read_text())
    if args.backend:
        cfg["backend"] = args.backend
    queries, _ = load_queries()
    if args.ids:
        queries = [q for q in queries if q["id"] in set(args.ids.split(","))]

    passes = []
    for p in (1, 2):
        rows = []
        for q in queries:
            out = run_once(q["query"], cfg)
            rows.append({"id": q["id"], "latency_ms": out["latency_ms"], "cost_usd": out["cost_usd"],
                         "tokens": out["tokens"], "cache": out["cache"],
                         "stages": [c["stage"] for c in out["llm_calls"]]})
            print(f"  pass{p} {q['id']}  hits={out['cache']['hits']}/{out['cache']['lookups']}  "
                  f"{out['latency_ms']:.0f}ms  ${out['cost_usd']:.4f}", flush=True)
        lat = sorted(r["latency_ms"] for r in rows)
        passes.append({
            "pass": p,
            "cache_hits": sum(r["cache"]["hits"] for r in rows),
            "cache_lookups": sum(r["cache"]["lookups"] for r in rows),
            "tokens_prompt": sum(r["tokens"]["prompt"] for r in rows),
            "tokens_completion": sum(r["tokens"]["completion"] for r in rows),
            "cost_usd": sum(r["cost_usd"] for r in rows),
            "latency_p50_ms": lat[len(lat) // 2],   # 단순 중앙값 (짝수 개면 위쪽 값)
            "rows": rows,
        })

    for s in passes:
        print(f"pass{s['pass']}: hit {s['cache_hits']}/{s['cache_lookups']}  "
              f"tokens {s['tokens_prompt']:,}+{s['tokens_completion']:,}  "
              f"${s['cost_usd']:.4f}  p50 {s['latency_p50_ms']:.0f}ms")
    if args.backend != "fake" and not args.ids:
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / f"cache_bench_{datetime.now():%Y%m%d_%H%M}.json"
        out.write_text(json.dumps({"config": cfg["name"], "passes": passes},
                                  ensure_ascii=False, indent=2))
        (RESULTS / "cache_bench_latest.json").write_text(out.read_text())
        print(f"saved {out.name}")


if __name__ == "__main__":
    main()
