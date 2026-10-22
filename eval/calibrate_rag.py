"""RAG 최소 유사도(rag.min_score)를 dev 질의만으로 정한다. holdout 은 읽지 않는다.

기준: dev 에서 gold 런북이 있는 질의(18건)와 없는 질의(미등록, 모호 6건)를 가장 잘 가르는 값.
균형 정확도 = (gold 있는데 통과한 비율 + gold 없는데 걸러진 비율) / 2 를 최대화하고,
동점이면 gold 있는 질의를 덜 놓치는 쪽(낮은 값)을 고른다.

    python -m eval.calibrate_rag            # 결과를 results/calibrate_rag.json 에 저장
    python -m eval.calibrate_rag --embedding local
        # 로컬 Ollama 데모용. API 없이 로컬 임베더 2종(LocalNgram, LocalTfidf)으로 같은 보정을 한다.
        # 점수 척도가 OpenAI 임베딩과 달라 기준값을 따로 정한다. margin 도 dev 에서만 고르고
        # (넣은 런북 F1 최대, 동점이면 0.05 에 가까운 값), dev 검색 지표(Recall@1, 3, MRR)를 함께 남긴다.
        # 결과: results/calibrate_rag_local_<YYYYMMDD_HHMM>.json, results/calibrate_rag_local_latest.json
    python -m eval.calibrate_rag --embedding ollama:bge-m3
        # 로컬 Ollama 임베딩 모델(bge-m3)을 로컬 임베더 2종과 같은 dev 보정, 같은 선택 규칙으로 비교한다.
        # Ollama(127.0.0.1:11434)에 모델이 받아져 있어야 한다 (ollama pull bge-m3). 기존 보정 파일은 덮지 않는다.
        # 결과: results/calibrate_rag_local_bge_<YYYYMMDD_HHMM>.json, results/calibrate_rag_local_bge_latest.json

왜 dev 만 쓰나: holdout 은 기준값을 정하는 데 한 번도 보지 않아야 '조정에 쓰지 않은 질의'로서
일반화 성능을 보여 줄 수 있다. 여기서 나온 값을 eval/configs/*.yaml 의 rag.min_score, margin 에 옮겨 적는다.
OpenAI 임베딩 결과 파일(results/calibrate_rag.json)은 scripts/claims.py 의 min_score, min_score_gap 출처이기도 하다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from ext.rag import (LocalNgramEmbedder, LocalTfidfEmbedder, OllamaEmbedder,  # noqa: E402
                     OpenAIEmbedder, RunbookRetriever, select_feed)
from eval.retrieval_metrics import summarize  # noqa: E402

MARGINS = (0.02, 0.03, 0.05, 0.08, 0.1)   # 로컬 임베더용 margin 후보 (OpenAI 구성의 0.05 는 측정 전에 고정한 값)


def main():
    """OpenAI 임베딩(text-embedding-3-small)으로 dev 1위 점수를 모아 min_score 를 정한다. API 키 필요."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedding", choices=["openai", "local", "ollama:bge-m3"], default="openai")
    emb = ap.parse_args().embedding
    if emb == "local":
        return main_local()
    if emb.startswith("ollama:"):
        return main_local_ollama(emb.split(":", 1)[1])
    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
          if q.get("split") == "dev"]
    assert len(qs) == 24, "dev 24건만 써야 한다"
    emb = OpenAIEmbedder("text-embedding-3-small", os.environ["OPENAI_API_KEY"], ROOT / ".cache")
    ret = RunbookRetriever(ROOT / "src/data/runbooks", emb)
    rows = []
    for q in qs:
        top = ret.rank(q["query"], top_k=1)[0]
        rows.append({"id": q["id"], "category": q["category"], "has_gold": bool(q["gold_runbooks"]),
                     "top": top[0], "score": round(top[1], 4)})
    pos = [r["score"] for r in rows if r["has_gold"]]
    neg = [r["score"] for r in rows if not r["has_gold"]]
    best = None
    # 후보 기준값 = 관측된 1위 점수들(+0). 오름차순으로 훑으며 '엄격히 더 좋을 때만' 바꾸므로
    # 동점이면 먼저 만난 낮은 값이 남는다 → gold 있는 질의를 덜 놓치는 쪽
    for tau in sorted({r["score"] for r in rows} | {0.0}):
        tpr = sum(s >= tau for s in pos) / len(pos)   # gold 있는 질의 중 통과 (런북을 넣음)
        tnr = sum(s < tau for s in neg) / len(neg)    # gold 없는 질의 중 걸러짐 (런북을 안 넣음)
        bal = (tpr + tnr) / 2   # 18:6 불균형이라 정확도 대신 균형 정확도
        if best is None or bal > best["balanced_acc"] + 1e-9:
            best = {"min_score": tau, "balanced_acc": bal, "gold_kept": tpr, "nogold_filtered": tnr}
    if best["balanced_acc"] == 1.0:   # 완전히 갈리면 경계값 대신 간격의 중간을 쓴다
        best["min_score"] = round((max(neg) + min(pos)) / 2, 4)
        best["gap"] = round(min(pos) - max(neg), 4)   # 간격이 얇을수록 holdout 에서 흔들리기 쉽다
    out = {"split": "dev", "n": len(rows), "best": best, "rows": rows,
           "gold_scores": sorted(pos), "nogold_scores": sorted(neg)}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/calibrate_rag.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: out[k] for k in ("best", "gold_scores", "nogold_scores")}, ensure_ascii=False, indent=1))
    for r in sorted(rows, key=lambda r: r["score"]):
        print(f"  {r['score']:.4f}  {r['id']} {r['category']:12} gold={r['has_gold']}  top={r['top']}")


def _dev_queries():
    """dev 24건만. 개수가 다르면(평가셋 버전이 바뀌면) 멈춘다."""
    qs = [q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]
          if q.get("split") == "dev"]
    assert len(qs) == 24, "dev 24건만 써야 한다"
    return qs


def _best_threshold(rows):
    """main() 과 같은 규칙: 균형 정확도 최대, 동점이면 낮은 값, 완전히 갈리면 간격의 중간."""
    pos = [r["score"] for r in rows if r["has_gold"]]
    neg = [r["score"] for r in rows if not r["has_gold"]]
    best = None
    for tau in sorted({r["score"] for r in rows} | {0.0}):
        tpr = sum(s >= tau for s in pos) / len(pos)
        tnr = sum(s < tau for s in neg) / len(neg)
        bal = (tpr + tnr) / 2
        if best is None or bal > best["balanced_acc"] + 1e-9:
            best = {"min_score": tau, "balanced_acc": bal, "gold_kept": tpr, "nogold_filtered": tnr}
    if best["balanced_acc"] == 1.0:
        best["min_score"] = round((max(neg) + min(pos)) / 2, 4)
        best["gap"] = round(min(pos) - max(neg), 4)
    return best, pos, neg


def _f1(fed, gold):
    """넣은 런북과 정답의 F1. 정답이 없는 질의에 아무것도 안 넣었으면 만점(1.0)."""
    if not fed and not gold:
        return 1.0
    hit = len(set(fed) & set(gold))
    if hit == 0:
        return 0.0
    p, r = hit / len(fed), hit / len(gold)
    return 2 * p * r / (p + r)


def _calibrate(embedder, qs):
    """임베더 1개의 dev 보정: min_score(_best_threshold) → margin 격자 탐색 → dev 검색 지표, 행별 투입 결과."""
    ret = RunbookRetriever(ROOT / "src/data/runbooks", embedder)
    rows, rankings = [], {}
    for q in qs:
        rk = ret.rank(q["query"], top_k=len(ret.ids))
        rankings[q["id"]] = rk
        rows.append({"id": q["id"], "category": q["category"], "has_gold": bool(q["gold_runbooks"]),
                     "gold": q["gold_runbooks"], "top": rk[0][0], "score": round(rk[0][1], 4),
                     "top3": [[rid, round(s, 4)] for rid, s in rk[:3]]})
    best, pos, neg = _best_threshold(rows)
    gold_q = [q for q in qs if q["gold_runbooks"]]
    retrieval = summarize([{"retrieved": [rid for rid, _ in rankings[q["id"]]], "gold": q["gold_runbooks"]}
                           for q in gold_q])
    # margin: 파이프라인과 같은 방식(top 3 → margin → min_score)으로 넣은 런북과 gold 의 F1 (dev 24건 평균)
    margin_rows = []
    for m in MARGINS:
        f1s = []
        for q in qs:
            top3 = rankings[q["id"]][:3]
            fed = [rid for rid, s in top3 if rid in select_feed(top3, m) and s >= best["min_score"]]
            f1s.append(_f1(fed, q["gold_runbooks"]))
        margin_rows.append({"margin": m, "fed_f1_mean": round(sum(f1s) / len(f1s), 4)})
    pick = max(margin_rows, key=lambda r: (r["fed_f1_mean"], -abs(r["margin"] - 0.05)))   # 동점이면 기존 0.05 에 가까운 값
    for r in rows:   # 고른 기준값으로 실제 넣게 될 런북
        top3 = rankings[r["id"]][:3]
        r["fed"] = [rid for rid, s in top3 if rid in select_feed(top3, pick["margin"]) and s >= best["min_score"]]
    return {"embedder": embedder.name, "best": best, "margin": {"pick": pick["margin"], "grid": margin_rows},
            "retrieval_dev_gold": {"n": len(gold_q), **{k: round(v, 4) for k, v in retrieval.items()}},
            "rows": rows, "gold_scores": sorted(pos), "nogold_scores": sorted(neg)}


def main_local():
    """로컬 임베더 2종(LocalNgram, LocalTfidf)을 dev 24건으로 보정, 비교. holdout 은 읽지 않는다. API 키 불필요.

    선택 규칙(결과를 보기 전에 정함): dev 정답 1위 적중(Hit@1)이 높은 쪽, 같으면 균형 정확도가 높은 쪽.
    로컬 데모의 목적이 '맞는 매뉴얼을 고르는 것'이라 Hit@1 을 앞에 둔다.
    """
    qs = _dev_queries()
    cands = {"local": _calibrate(LocalNgramEmbedder(), qs),
             "local-tfidf": _calibrate(LocalTfidfEmbedder(ROOT / "src/data/runbooks"), qs)}
    pick = max(cands, key=lambda k: (cands[k]["retrieval_dev_gold"]["hit@1"], cands[k]["best"]["balanced_acc"]))
    out = {"split": "dev", "n": len(qs),
           "note": "로컬 Ollama 데모 전용 보정. OpenAI 임베딩 보정(results/calibrate_rag.json)과 점수 척도가 달라 따로 정함.",
           "rule": "dev Hit@1 최대 → 균형 정확도 최대. min_score 는 균형 정확도 최대(동점이면 낮은 값), "
                   "margin 은 넣은 런북 F1 최대(동점이면 0.05 에 가까운 값).",
           "pick": {"embedding": pick, "min_score": cands[pick]["best"]["min_score"],
                    "margin": cands[pick]["margin"]["pick"]},
           "candidates": cands}
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    (ROOT / "results").mkdir(exist_ok=True)
    for p in (ROOT / f"results/calibrate_rag_local_{ts}.json", ROOT / "results/calibrate_rag_local_latest.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for k, c in cands.items():
        print(f"== {k}: min_score={c['best']['min_score']} bal_acc={c['best']['balanced_acc']:.3f} "
              f"margin={c['margin']['pick']}  dev gold {c['retrieval_dev_gold']}")
        for r in sorted(c["rows"], key=lambda r: r["score"]):
            print(f"  {r['score']:.4f}  {r['id']} {r['category']:12} gold={r['gold']}  top={r['top']}  fed={r['fed']}")
    print("pick", out["pick"])
    print("saved", f"results/calibrate_rag_local_{ts}.json")

def main_local_ollama(model: str):
    """로컬 임베더 2종 + Ollama 임베딩 모델을 dev 24건으로 보정, 비교. holdout 은 읽지 않는다.

    선택 규칙은 main_local 과 같다 (결과를 보기 전에 정함): dev Hit@1 최대 → 균형 정확도 최대.
    둘 다 같으면 먼저 정해 둔 local-tfidf 를 유지한다 (후보 순서: local, local-tfidf, ollama:<모델>).
    """
    qs = _dev_queries()
    name = f"ollama:{model}"
    cands = {"local": _calibrate(LocalNgramEmbedder(), qs),
             "local-tfidf": _calibrate(LocalTfidfEmbedder(ROOT / "src/data/runbooks"), qs),
             name: _calibrate(OllamaEmbedder(model, ROOT / ".cache"), qs)}
    pick = max(cands, key=lambda k: (cands[k]["retrieval_dev_gold"]["hit@1"], cands[k]["best"]["balanced_acc"]))
    out = {"split": "dev", "n": len(qs),
           "note": "로컬 Ollama 데모 전용 보정. 로컬 임베더 2종과 Ollama 임베딩 모델을 같은 dev 기준으로 비교.",
           "rule": "dev Hit@1 최대 → 균형 정확도 최대 (둘 다 같으면 local-tfidf 유지). min_score 는 균형 정확도 최대"
                   "(동점이면 낮은 값), margin 은 넣은 런북 F1 최대(동점이면 0.05 에 가까운 값).",
           "pick": {"embedding": pick, "min_score": cands[pick]["best"]["min_score"],
                    "margin": cands[pick]["margin"]["pick"]},
           "candidates": cands}
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    (ROOT / "results").mkdir(exist_ok=True)
    for p in (ROOT / f"results/calibrate_rag_local_bge_{ts}.json", ROOT / "results/calibrate_rag_local_bge_latest.json"):
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for k, c in cands.items():
        print(f"== {k}: min_score={c['best']['min_score']} bal_acc={c['best']['balanced_acc']:.3f} "
              f"margin={c['margin']['pick']}  dev gold {c['retrieval_dev_gold']}")
        for r in sorted(c["rows"], key=lambda r: r["score"]):
            print(f"  {r['score']:.4f}  {r['id']} {r['category']:12} gold={r['gold']}  top={r['top']}  fed={r['fed']}")
    print("pick", out["pick"])
    print("saved", f"results/calibrate_rag_local_bge_{ts}.json")


if __name__ == "__main__":
    main()
