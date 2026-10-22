"""운영 언어 지표 + 평가셋 편향 검증 — 저장된 결과(rows)에서 사후 계산한다. 재실행 없음.

운영 지표 (질의 1건 = 1회 반복 기준, 반복 평균)
  miss_runbook_rate    장애로 처리한 답 중 정답 런북을 근거에 못 넣은 비율 (정답 런북이 있는 질의만)
                       → 맞는 조치를 권고하지 못할 위험
  wrong_runbook_rate   장애로 처리한 답 중 무관한 런북이 근거에 섞인 비율
                       (정답 런북이 없는 질의에 런북을 넣은 것 포함) → 잘못된 조치를 권고할 위험
  cost_per_incident    장애 1건당 처리 비용 (USD) = 총 추정 비용 / 장애 경로 건수

편향 검증 (평가셋이 특정 방식에 유리하게 짜였는지)
  design_note 별 Recall@1 — aligned(알림 문구와 같은 말로 물음) vs paraphrased(자기 말로 물음)
  split 별 Recall@1 — dev(기준값 조정에 씀) vs holdout(조정에 안 씀)

    python -m eval.extra_metrics

쓰는 곳: scripts/claims.py · scripts/gen_readme_tables.py · scripts/make_figs.py · deck/data.py 가
load_all(split) 으로 이 값을 읽는다 (README 주요 표의 누락률·혼입률·건당 비용 출처).
계산 순서: 반복마다 비율을 구한 뒤 반복 평균 (run_ablation 요약과 같은 방식).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]


def _queries() -> dict:
    return {q["id"]: q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]}


def _wrong(r: dict) -> bool:
    """혼입: 정답 아닌 런북이 하나라도 들어감. 정답이 없는 질의(미등록·모호)는 무엇이든 넣으면 혼입."""
    fed = set(r.get("fed_runbooks") or [])
    gold = set(r.get("gold") or [])
    return bool(fed - gold) if gold else bool(fed)


def _miss(r: dict) -> bool:
    """누락: 넣은 런북에 정답이 하나도 없음. 정답 있는 질의에만 쓴다 (호출하는 쪽이 거른다)."""
    return not (set(r.get("fed_runbooks") or []) & set(r["gold"]))


def _hit1(r: dict) -> float:
    """1순위(retrieved[0])가 정답이면 1.0."""
    return float(bool(r.get("retrieved")) and r["retrieved"][0] in set(r["gold"]))


def compute(rows: list[dict], qs: dict, split: str | None = None) -> dict:
    """한 구성의 rows → 지표 dict (반복별로 계산해 평균). 분모는 '장애 경로로 처리된 질의'.

    chat 경로로 빠진 질의는 런북을 넣을 기회가 없으므로 누락·혼입 분모에서 뺀다.
    비용은 반복 전체 질의 비용(chat 포함) ÷ 장애 경로 건수 — '장애 1건 처리에 드는 돈'.
    """
    rows = [r for r in rows if "error" not in r and (split is None or r.get("split") == split)]
    reps = sorted({r.get("rep", 1) for r in rows})
    per = []
    for rep in reps:
        sub = [r for r in rows if r.get("rep", 1) == rep]
        inc = [r for r in sub if r["route"] == "incident"]
        cost = sum(r["cost_usd"] for r in sub if r["cost_usd"] == r["cost_usd"])
        inc_gold = [r for r in inc if r["gold"]]
        g = {"miss_runbook_rate": sum(map(_miss, inc_gold)) / len(inc_gold) if inc_gold else float("nan"),
             "wrong_runbook_rate": sum(map(_wrong, inc)) / len(inc) if inc else float("nan"),
             "wrong_runbook_n": sum(map(_wrong, inc)),
             "incident_n": len(inc),
             "cost_per_incident": cost / len(inc) if inc else float("nan")}
        for key, val in (("aligned", "aligned"), ("paraphrased", "paraphrased")):
            grp = [r for r in sub if r["gold"] and qs[r["id"]].get("design_note") == val]
            g[f"recall@1[{key}]"] = statistics.fmean(map(_hit1, grp)) if grp else float("nan")
            g[f"n[{key}]"] = len(grp)
        per.append(g)
    out = {}
    for k in per[0] if per else {}:
        vals = [p[k] for p in per if p[k] == p[k]]
        out[k] = statistics.fmean(vals) if vals else float("nan")
    return out


def load_all(split: str | None = None) -> dict:
    """ORDER 의 각 구성 results/<구성>_latest.json → compute(). split=None 이면 전체."""
    qs = _queries()
    res = {}
    for nm in ORDER:
        p = RESULTS / f"{nm}_latest.json"
        if p.exists():
            res[nm] = compute(json.loads(p.read_text())["rows"], qs, split)
    return res


if __name__ == "__main__":
    for sp in (None, "dev", "holdout"):
        print(f"\n== {sp or '전체'} ==")
        for nm, m in load_all(sp).items():
            print(f"{nm:15} 누락 {m['miss_runbook_rate']:.0%}  혼입 {m['wrong_runbook_rate']:.0%} ({m['wrong_runbook_n']:.1f}/{m['incident_n']:.0f})  "
                  f"건당 ${m['cost_per_incident']:.5f}  "
                  f"R@1 aligned {m['recall@1[aligned]']:.0%}(n={m['n[aligned]']:.0f}) "
                  f"paraphrased {m['recall@1[paraphrased]']:.0%}(n={m['n[paraphrased]']:.0f})")
