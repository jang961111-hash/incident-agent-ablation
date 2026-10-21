"""장애 주입 실측 — 모니터링 도구 호출의 일부를 일부러 실패시켰을 때 끝까지 답하는 비율.

원본 research_node 는 asyncio.gather 로 태스크를 묶어, 한 태스크라도 영구 실패하면 질의 전체가
예외로 끝난다. runtime.tolerant_research=true 는 실패한 태스크만 '조회 실패'로 근거에 남기고
나머지 결과로 답한다. 같은 (seed, 질의, 대상) 이면 같은 호출이 실패하도록 결정적으로 주입한다.

    python -m eval.fault_bench               # rate 0.3, dev+holdout 정상 질의
"""
from __future__ import annotations

import argparse
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--backend", choices=["openai", "fake"])
    args = ap.parse_args()

    from src.adapter import run_once

    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
          if q["category"] in ("normal", "composite")]
    load = lambda n: yaml.safe_load((ROOT / f"eval/configs/{n}.yaml").read_text())
    final_off = copy.deepcopy(load("final"))
    final_off["runtime"]["tolerant_research"] = False
    final_off["name"] = "final_no_tolerance"
    variants = {"base": load("base"), "final_no_tolerance": final_off, "final": load("final")}

    out = {"rate": args.rate, "seed": args.seed, "n_queries": len(qs), "variants": {}}
    for name, cfg in variants.items():
        cfg = copy.deepcopy(cfg)
        cfg["fault_injection"] = {"tool": "get_monitoring_status", "rate": args.rate, "seed": args.seed}
        cfg.setdefault("cost", {})["cache"] = False
        if args.backend:
            cfg["backend"] = args.backend
            cfg["fake_force_incident"] = args.backend == "fake"

        def job(q):
            try:
                o = run_once(q["query"], cfg)
                return {"id": q["id"], "ok": True, "faults": o["faults_injected"],
                        "tool_failures": o["tool_failures"], "answer": o["answer"][:300]}
            except Exception as e:
                return {"id": q["id"], "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

        with ThreadPoolExecutor(args.workers) as ex:
            rows = list(ex.map(job, qs))
        hit = [r for r in rows if (r.get("faults") or 0) > 0 or not r["ok"]]
        res = {"completed": sum(r["ok"] for r in rows), "n": len(rows),
               "queries_with_fault": len(hit),
               "completed_among_faulted": sum(r["ok"] for r in hit), "rows": rows}
        out["variants"][name] = res
        print(f"{name:20} 완주 {res['completed']}/{res['n']}  장애 맞은 질의 {len(hit)}건 중 완주 "
              f"{res['completed_among_faulted']}", flush=True)
    out["backend"] = args.backend or "openai"
    if args.backend == "fake":
        out["note"] = ("LLM 없이(fake 백엔드) 코드 경로만 측정 — 도구 실패 시 완주 여부는 LLM 품질과 무관. "
                       "fake 라우터 대신 모든 질의를 장애 경로로 보냄")
    tag = "_fake" if args.backend == "fake" else ""
    p = ROOT / "results" / f"fault_bench{tag}_{datetime.now():%Y%m%d_%H%M}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (ROOT / f"results/fault_bench{tag}_latest.json").write_text(p.read_text())
    print("saved", p.name)


if __name__ == "__main__":
    main()
