"""장애 주입 실측 — 모니터링 도구 호출의 일부를 일부러 실패시켰을 때 끝까지 답하는 비율.

원본 research_node 는 asyncio.gather 로 태스크를 묶어, 한 태스크라도 영구 실패하면 질의 전체가
예외로 끝난다. runtime.tolerant_research=true 는 실패한 태스크만 '조회 실패'로 근거에 남기고
나머지 결과로 답한다. 같은 (seed, 질의, 대상) 이면 같은 호출이 실패하도록 결정적으로 주입한다.

    python -m eval.fault_bench               # rate 0.3, dev+holdout 정상 질의
    python -m eval.fault_bench --seed 11 --tag _seed11   # 고장 위치를 바꿔 반복 측정

변형 3개: base(원본 research), final_no_tolerance(final 에서 tolerant_research 만 끔), final.
가운데 변형이 있어야 '완주율 차이가 tolerant_research 덕'임을 다른 개선과 분리해 말할 수 있다.
질의: normal, composite 카테고리 (dev+holdout). 완주 여부만 재고 답 품질은 평가하지 않는다.
주입 방식은 src/ext/faults.py(FaultyMCP), 켜는 곳은 cfg["fault_injection"] → src/adapter.py.
결과: results/fault_bench[_fake][<tag>]_<YYYYMMDD_HHMM>.json 과 _latest.json
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
    ap.add_argument("--tag", default="", help="결과 파일 접미사 (반복 측정 시 기존 결과 보존, 예: _seed11)")
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
        cfg.setdefault("cost", {})["cache"] = False   # 모든 변형이 질의마다 route, plan 을 새로 부르게 (base 와 같은 조건)
        if args.backend:
            cfg["backend"] = args.backend
            cfg["fake_force_incident"] = args.backend == "fake"   # fake 라우터의 판정과 무관하게 모두 장애 경로로 (도구 호출이 일어나야 주입이 된다)

        def job(q):
            try:
                o = run_once(q["query"], cfg)
                return {"id": q["id"], "ok": True, "faults": o["faults_injected"],
                        "tool_failures": o["tool_failures"], "answer": o["answer"][:300]}
            except Exception as e:
                return {"id": q["id"], "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

        with ThreadPoolExecutor(args.workers) as ex:
            rows = list(ex.map(job, qs))
        # '장애 맞은 질의' = 주입이 1번이라도 일어났거나 실패한 질의 (실패 행은 주입 수를 알 수 없어 포함)
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
    tag = ("_fake" if args.backend == "fake" else "") + args.tag
    p = ROOT / "results" / f"fault_bench{tag}_{datetime.now():%Y%m%d_%H%M}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (ROOT / f"results/fault_bench{tag}_latest.json").write_text(p.read_text())
    print("saved", p.name)


if __name__ == "__main__":
    main()
