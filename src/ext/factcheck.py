"""수치 코드 검증 — 답변에 나온 측정값이 근거(Context)에 실제로 있는지 대조한다.

LLM Judge 를 부르기 전에 코드로 먼저 거른다 (judge.factcheck=true).
근거에 없는 수치가 있으면 Judge 호출 없이 바로 반려하고, 어떤 수치가 문제인지 피드백한다.
같은 함수를 평가 단계에서 모든 구성의 답변에 적용해 '근거 없는 수치 비율'을 낸다 (Judge 무관).

대상: 단위가 붙은 값(%, 초, s, ms, 분, GB, MB, 건, 대, 회)과 소수.
절차 번호(1) 2. ③), 단위 없는 작은 정수는 대상이 아니다.
값만 비교한다 ('2.4s' 와 '2.4초' 는 같은 값). 근거에 있는 값의 반올림(±0.5)도 허용한다.
"""
from __future__ import annotations

import re

_UNIT = r"(?:%|퍼센트|초|s\b|ms\b|분|시간|GB|MB|KB|건|대|회|배|개)"
_NUM_UNIT = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*{_UNIT}")
_DECIMAL = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w.])")
_STEP = re.compile(r"^\s*(?:\d+[).]|[①-⑳])")
_ANY_NUM = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[float]:
    """근거 쪽: 단위와 상관없이 모든 수를 모은다."""
    return {float(x) for x in _ANY_NUM.findall(text or "")}


def claimed_numbers(answer: str) -> list[float]:
    """답변 쪽: 측정값으로 보이는 수만 뽑는다 (절차 번호 제외)."""
    out = []
    for line in (answer or "").splitlines():
        body = _STEP.sub("", line)
        for m in _NUM_UNIT.finditer(body):
            out.append(float(m.group(1)))
        for m in _DECIMAL.finditer(body):
            v = float(m.group(1))
            if v not in out:
                out.append(v)
    return out


def unsupported(answer: str, context: str, tol: float = 0.5) -> list[float]:
    """답변 수치 중 근거에 없는 것. 근거 값의 ±tol 이내(반올림)는 근거 있음으로 본다."""
    ctx = numbers_in(context)
    return [v for v in claimed_numbers(answer)
            if not any(abs(v - c) <= tol for c in ctx)]


def check(answer: str, context: str) -> dict:
    claims = claimed_numbers(answer)
    bad = unsupported(answer, context)
    return {"n_claims": len(claims), "unsupported": bad, "ok": not bad}
