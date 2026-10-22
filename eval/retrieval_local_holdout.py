"""로컬 임베더 3종(local, local-tfidf, ollama:bge-m3)의 holdout 검색 품질 — 평가만, 튜닝 아님. LLM 호출 없음.

기준값(min_score, margin)은 dev 24건 보정 결과(results/calibrate_rag_local_bge_latest.json)를 그대로 쓴다.
holdout 36건은 여기서 처음 읽고, 결과를 보고 기준값을 바꾸지 않는다.

지표 (파이프라인 라우팅은 거치지 않은 검색 단독 값)
  hit@1, recall@3, mrr   정답 런북이 있는 holdout 질문(28건) 기준
  balanced_acc             '매뉴얼이 있는 질문인가' 판정 = 1위 점수 >= min_score. (gold 있음 통과율 + gold 없음 걸러짐 비율) / 2
  miss_rate                정답 있는 질문 중, 넣은 런북(top3 → margin → min_score)에 정답이 하나도 없는 비율
  wrong_rate               전체 36건 중, 넣은 런북에 정답 아닌 런북이 섞인 비율 (정답 없는 질문에 런북을 넣은 것 포함)

    python -m eval.retrieval_local_holdout
결과: results/retrieval_local_holdout_<YYYYMMDD_HHMM>.json

넣는 런북 계산은 파이프라인(src/ext/graph_ext.replan_check_rag_node)과 같다:
top3 → select_feed(margin) → min_score 이상만. 라우팅(chat/장애)을 거치지 않으므로 분모가 파이프라인 지표와 다르다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from ext.rag import (LocalNgramEmbedder, LocalTfidfEmbedder, OllamaEmbedder,  # noqa: E402
                     RunbookRetriever, select_feed)
from eval.retrieval_metrics import summarize  # noqa: E402

CAL = ROOT / "results/calibrate_rag_local_bge_latest.json"


def _embedder(name: str):
    """보정 파일의 후보 이름 → 임베더 객체."""
    if name == "local":
        return LocalNgramEmbedder()
    if name == "local-tfidf":
        return LocalTfidfEmbedder(ROOT / "src/data/runbooks")
    if name.startswith("ollama:"):
        return OllamaEmbedder(name.split(":", 1)[1], ROOT / ".cache")
    raise ValueError(name)


def evaluate(name: str, min_score: float, margin: float, qs: list[dict]) -> dict:
    """임베더 1개를 dev 에서 정한 기준값 그대로 holdout 에 적용해 검색 지표, 투입 결과를 낸다."""
    ret = RunbookRetriever(ROOT / "src/data/runbooks", _embedder(name))
    rows = []
    for q in qs:
        rk = ret.rank(q["query"], top_k=len(ret.ids))
        top3 = rk[:3]
        fed = [rid for rid, s in top3 if rid in select_feed(top3, margin) and s >= min_score]
        gold = q["gold_runbooks"]
        rows.append({"id": q["id"], "category": q["category"], "gold": gold,
                     "ranking": [[rid, round(s, 4)] for rid, s in rk], "top": rk[0][0],
                     "score": round(rk[0][1], 4), "fed": fed,
                     "miss": (not set(fed) & set(gold)) if gold else None,
                     "wrong": bool(set(fed) - set(gold)) if gold else bool(fed)})
    gq = [r for r in rows if r["gold"]]
    ng = [r for r in rows if not r["gold"]]
    ret_m = summarize([{"retrieved": [rid for rid, _ in r["ranking"]], "gold": r["gold"]} for r in gq])
    tpr = sum(r["score"] >= min_score for r in gq) / len(gq)
    tnr = sum(r["score"] < min_score for r in ng) / len(ng)
    return {"embedder": name, "min_score": min_score, "margin": margin,
            "n": len(rows), "n_gold": len(gq), "n_nogold": len(ng),
            **{k: round(v, 4) for k, v in ret_m.items()},
            "hit@1_n": sum(r["top"] in r["gold"] for r in gq),
            "hit@3_n": round(ret_m["hit@3"] * len(gq)),
            "gold_kept": round(tpr, 4), "nogold_filtered": round(tnr, 4),
            "balanced_acc": round((tpr + tnr) / 2, 4),
            "miss_n": sum(r["miss"] for r in gq), "miss_rate": round(sum(r["miss"] for r in gq) / len(gq), 4),
            "wrong_n": sum(r["wrong"] for r in rows), "wrong_rate": round(sum(r["wrong"] for r in rows) / len(rows), 4),
            "rows": rows}


def main():
    """dev 보정 결과(CAL)의 임베더별 기준값으로 holdout 36건 검색 품질을 계산해 results/ 에 저장하고 출력한다."""
    cal = json.loads(CAL.read_text())
    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
          if q.get("split") == "holdout"]
    assert len(qs) == 36, "holdout 36건"
    res = {}
    for name, c in cal["candidates"].items():
        res[name] = evaluate(name, c["best"]["min_score"], c["margin"]["pick"], qs)
    out = {"split": "holdout", "n": len(qs),
           "note": "검색 단독 평가 (LLM, 라우팅 없음). 기준값은 dev 보정값 그대로 — holdout 으로 튜닝하지 않음.",
           "thresholds_from": f"results/{CAL.name}", "dev_pick": cal["pick"], "embedders": res}
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    p = ROOT / f"results/retrieval_local_holdout_{ts}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for name, m in res.items():
        print(f"{name:15} min={m['min_score']} margin={m['margin']}  Hit@1 {m['hit@1_n']}/{m['n_gold']}  "
              f"Recall@3 {m['recall@3']:.3f}  MRR {m['mrr']:.3f}  bal_acc {m['balanced_acc']:.3f} "
              f"(kept {m['gold_kept']:.3f}, filtered {m['nogold_filtered']:.3f})  "
              f"miss {m['miss_n']}/{m['n_gold']}  wrong {m['wrong_n']}/{m['n']}")
    print("saved", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
