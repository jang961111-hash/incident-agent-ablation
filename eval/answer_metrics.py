"""Judge 와 무관한 결정적 답변 지표 — 저장된 결과(results/*_latest.json)에서 계산한다.

must_include 는 평가셋 v2 작성 때(측정 전) 정답 런북 본문에서 뽑아 둔 핵심 어구다.
답변에 그 어구가 그대로 들어 있는지를 대소문자 무시 문자열 포함으로 본다.
같은 뜻을 다른 말로 쓴 경우(예: failover → 페일오버)는 놓치므로 하한(보수적) 지표다.

평가 Judge 는 Context 가 비어 있으면 '지어낸 게 없다'며 completeness 를 통과시키는 등
관대하게 판정하는 경향이 있어, 이 지표로 런북 절차가 실제로 답에 반영됐는지 따로 본다.

    python -m eval.answer_metrics

참고: 같은 지표(must_phrase_rate·must_all_rate)를 eval/run_ablation.py 가 실행 때 행마다 계산해
요약에 넣는다. 이 파일은 저장된 결과로 질의별 'n/m' 표를 다시 뽑아 보는 사후 점검용이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "rag_judge", "rag_judge_cost"]   # v1 시기 비교 구성 (v2·final 은 run_ablation 요약 사용)


def must_include_scores(rows: list[dict], queries: dict) -> dict:
    """Returns: n_must(어구가 정의된 질의 수), must_phrase_rate(어구 단위), must_all_rate(전부 포함한 답 비율),
    per_query({id: '맞힌 수/어구 수'}). 같은 id 가 반복으로 여러 행이면 per_query 는 마지막 행 값이다."""
    per_q, phrases_hit, phrases_total, all_hit = {}, 0, 0, 0
    for r in rows:
        need = queries.get(r["id"], {}).get("must_include") or []
        if not need or "answer" not in r:
            continue
        ans = r["answer"].lower()
        hit = [p for p in need if p.lower() in ans]
        per_q[r["id"]] = f"{len(hit)}/{len(need)}"
        phrases_hit += len(hit)
        phrases_total += len(need)
        all_hit += len(hit) == len(need)
    n = len(per_q)
    return {"n_must": n,
            "must_phrase_rate": phrases_hit / phrases_total if phrases_total else float("nan"),
            "must_all_rate": all_hit / n if n else float("nan"),
            "per_query": per_q}


def load_all() -> dict:
    queries = {q["id"]: q for q in
               yaml.safe_load((ROOT / "eval" / "queries.yaml").read_text())["queries"]}
    out = {}
    for nm in ORDER:
        p = RESULTS / f"{nm}_latest.json"
        if p.exists():
            out[nm] = must_include_scores(json.loads(p.read_text())["rows"], queries)
    return out


if __name__ == "__main__":
    res = load_all()
    for nm, s in res.items():
        print(f"{nm:15} 어구 포함률 {s['must_phrase_rate']:.0%}  전부 포함 {s['must_all_rate']:.0%}"
              f"  (n={s['n_must']})")
    ids = sorted({i for s in res.values() for i in s["per_query"]})
    print("\nid    " + "  ".join(f"{nm[:10]:>10}" for nm in res))
    for i in ids:
        print(f"{i}  " + "  ".join(f"{res[nm]['per_query'].get(i, '-'):>10}" for nm in res))
