"""RAG 최소 유사도(rag.min_score)를 dev 질의만으로 정한다. holdout 은 읽지 않는다.

기준: dev 에서 gold 런북이 있는 질의(18건)와 없는 질의(미등록·모호 6건)를 가장 잘 가르는 값.
균형 정확도 = (gold 있는데 통과한 비율 + gold 없는데 걸러진 비율) / 2 를 최대화하고,
동점이면 gold 있는 질의를 덜 놓치는 쪽(낮은 값)을 고른다.

    python -m eval.calibrate_rag            # 결과를 results/calibrate_rag.json 에 저장
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from ext.rag import OpenAIEmbedder, RunbookRetriever  # noqa: E402


def main():
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
    for tau in sorted({r["score"] for r in rows} | {0.0}):
        tpr = sum(s >= tau for s in pos) / len(pos)
        tnr = sum(s < tau for s in neg) / len(neg)
        bal = (tpr + tnr) / 2
        if best is None or bal > best["balanced_acc"] + 1e-9:
            best = {"min_score": tau, "balanced_acc": bal, "gold_kept": tpr, "nogold_filtered": tnr}
    if best["balanced_acc"] == 1.0:   # 완전히 갈리면 경계값 대신 간격의 중간을 쓴다
        best["min_score"] = round((max(neg) + min(pos)) / 2, 4)
        best["gap"] = round(min(pos) - max(neg), 4)
    out = {"split": "dev", "n": len(rows), "best": best, "rows": rows,
           "gold_scores": sorted(pos), "nogold_scores": sorted(neg)}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/calibrate_rag.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: out[k] for k in ("best", "gold_scores", "nogold_scores")}, ensure_ascii=False, indent=1))
    for r in sorted(rows, key=lambda r: r["score"]):
        print(f"  {r['score']:.4f}  {r['id']} {r['category']:12} gold={r['has_gold']}  top={r['top']}")


if __name__ == "__main__":
    main()
