"""수치 코드 검증 — 답변에 나온 측정값이 근거(Context)에 실제로 있는지 대조한다.

LLM Judge 를 부르기 전에 코드로 먼저 거른다 (judge.factcheck=true).
근거에 없는 수치가 있으면 Judge 호출 없이 바로 반려하고, 어떤 수치가 문제인지 피드백한다.
같은 함수를 평가 단계에서 모든 구성의 답변에 적용해 '근거 없는 수치 비율'을 낸다 (Judge 무관).

대상: 단위가 붙은 값(%, 퍼센트, 초, s, ms, 분, 시간, GB, MB, KB, 건, 대, 회, 배, 개 — _UNIT)과 소수.
절차 번호(1) 2. ③), 단위 없는 작은 정수는 대상이 아니다.
값만 비교한다 ('2.4s' 와 '2.4초' 는 같은 값). 근거에 있는 값의 반올림(±0.5)도 허용한다.

쓰는 곳
  - src/ext/graph_ext.py validate_judge_node: judge.factcheck=true 일 때 Judge 앞단 필터
  - eval/run_ablation.py: 모든 구성의 답에 적용 → unsupported_numbers, unsupported_answer_rate
  - eval/tamper_test.py: 수치 조작을 코드가 잡는지 시험
한계: 값만 보고 '무슨 값인지'(CPU 인지 메모리인지)는 보지 않는다. 근거의 다른 항목 값과 우연히
같으면 통과한다. 시스템 이름 같은 비수치 환각은 잡지 못한다 (그쪽은 Judge 몫).
"""
from __future__ import annotations

import re

# 측정값으로 볼 단위. s, ms 는 단어 경계(\b)를 둬 'sql', 'msg' 같은 영단어 앞부분을 잡지 않는다
_UNIT = r"(?:%|퍼센트|초|s\b|ms\b|분|시간|GB|MB|KB|건|대|회|배|개)"
# (?<![\w.]) : 'v2.4', '1.2.3' 처럼 글자나 점에 붙은 숫자(버전, 식별자)는 측정값이 아니다
_NUM_UNIT = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*{_UNIT}")
_DECIMAL = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w.])")
# 줄 머리의 절차 번호 '1)' '2.' '③' — 측정값이 아니므로 먼저 떼어 낸다
_STEP = re.compile(r"^\s*(?:\d+[).]|[①-⑳])")
# 근거 쪽은 넓게: 단위가 없어도 수가 있으면 근거로 인정한다 (오탐보다 미탐 쪽을 택함)
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
            if v not in out:   # '2.4초' 는 위에서 이미 셌다 — 단위 없는 소수만 더한다
                out.append(v)
    return out


def unsupported(answer: str, context: str, tol: float = 0.5) -> list[float]:
    """답변 수치 중 근거에 없는 것. 근거 값의 ±tol 이내(반올림)는 근거 있음으로 본다."""
    ctx = numbers_in(context)
    return [v for v in claimed_numbers(answer)
            if not any(abs(v - c) <= tol for c in ctx)]


def check(answer: str, context: str) -> dict:
    """답 1건 검사 결과.

    Returns:
        n_claims    답에서 뽑은 측정값 수
        unsupported 근거에 없는 값 목록 (비어 있으면 통과)
        ok          unsupported 가 비었는지. False 면 파이프라인은 Judge 없이 바로 반려한다.
    """
    claims = claimed_numbers(answer)
    bad = unsupported(answer, context)
    return {"n_claims": len(claims), "unsupported": bad, "ok": not bad}
