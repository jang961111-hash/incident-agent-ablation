"""검색 품질 지표.

Validator 4지표가 '답변 품질'이라면, 이쪽은 '검색 품질'이다.
두 축을 분리해서 재야 "검색이 좋아져서 답변이 좋아졌다"는 인과를 말할 수 있다.

base 구성(키워드 규칙)에서도 선택된 런북이 기록되므로 같은 지표로 비교 가능하다.
"""
from __future__ import annotations


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """상위 k건 안에 정답 런북이 몇 비율 포함됐는지.

    gold가 여러 건인 경우(복합 장애) 포함된 정답 수 / 전체 정답 수.
    """
    if not gold:
        return float("nan")
    top = set(retrieved[:k])
    return len(top & set(gold)) / len(gold)


def hit_at_k(retrieved: list[str], gold: list[str], k: int) -> int:
    """상위 k건에 정답이 하나라도 들어있으면 1."""
    if not gold:
        return 0
    return int(bool(set(retrieved[:k]) & set(gold)))


def mrr(retrieved: list[str], gold: list[str]) -> float:
    """첫 정답의 역순위. 1위면 1.0, 3위면 0.333."""
    gold_set = set(gold)
    for i, r in enumerate(retrieved, start=1):
        if r in gold_set:
            return 1.0 / i
    return 0.0


def summarize(records: list[dict], ks=(1, 3)) -> dict:
    """records: [{"retrieved": [...], "gold": [...]}, ...]"""
    out = {}
    n = len(records) or 1
    for k in ks:
        out[f"recall@{k}"] = sum(recall_at_k(r["retrieved"], r["gold"], k) for r in records) / n
        out[f"hit@{k}"] = sum(hit_at_k(r["retrieved"], r["gold"], k) for r in records) / n
    out["mrr"] = sum(mrr(r["retrieved"], r["gold"]) for r in records) / n
    return out
