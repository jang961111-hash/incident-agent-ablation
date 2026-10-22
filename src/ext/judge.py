"""파이프라인 안의 Validator — 원본 규칙(30자 이상 + "1)" 포함)을 LLM-as-a-Judge 4지표로 교체.

  relevance              Query  <-> Answer   동문서답 여부
  completeness           Answer <-> Context  근거에 없는 수치, 사실을 만들지 않았는가
  domain_appropriateness Answer <-> Context  런북 조치, 절차를 반영했는가
  clarity                Answer 단독         요청한 형식, 길이를 지키며 체계적인가

4지표 중 통과 비율이 threshold 이상이면 합격. 불합격이면 실패 지표의 사유를 피드백으로
넘겨 재작성한다. 재시도 상한과 시간 상한 중 먼저 닿는 쪽에서 멈추고 통과 처리한다.

주의: 이 Judge 는 파이프라인 내부 검증용이다. 평가용 Judge(eval/judge.py)는 다른 모델
(gpt-4o)로 고정해, 자기 기준에 맞춰 고친 답을 같은 기준으로 다시 채점하는 순환을 피한다.

켜는 스위치: validator=judge (Judge 객체 주입은 src/adapter.py, 판정, 가드는 src/ext/graph_ext.py
validate_judge_node). judge.version 으로 SYSTEM(v1), SYSTEM_V2 를 고른다.
모델: models.judge (구성 기본 gpt-4o-mini). 호출은 원본 OpenAILLM 의 요청 형식 그대로이고,
토큰은 MeteredChatMixin 이 stage="judge" 로 Meter 에 적는다.
"""
from __future__ import annotations

import json
import re

from agent.openai_llm import OpenAILLM

from .meter import MeteredChatMixin, stage

METRICS = ("relevance", "completeness", "domain_appropriateness", "clarity")

SYSTEM = (
    "당신은 ICT 장애 대응 답변을 채점하는 엄격한 평가자다. 아래 4개 지표를 각각 Pass/Fail로 "
    "판정하고 근거를 한 문장으로 쓴다.\n"
    "1. relevance: 사용자가 물은 것에 답했는가. 요청 대상이 등록된 시스템·런북에 없으면 "
    "그 사실을 밝혀야 Pass.\n"
    "2. completeness: Context에 없는 수치·원인·사실을 답변이 만들어냈다면 Fail. Context의 "
    "핵심 사실(상태·수치·알림)이 빠졌어도 Fail.\n"
    "3. domain_appropriateness: Context의 런북 조치·절차가 답변에 반영됐는가.\n"
    "4. clarity: 사용자가 요청한 형식·길이 제약을 지켰고 논리적으로 정리됐는가.\n"
    'JSON 객체로만 답한다: {"relevance":{"verdict":"Pass|Fail","reason":"..."},'
    '"completeness":{...},"domain_appropriateness":{...},"clarity":{...}}'
)


# v2 — 1차 실측에서 찾은 문제를 고친 기준 (docs/06_결과분석.md 3절).
# 맞는 런북이 없는 질의에서 completeness, domain 이 '런북 절차를 반영하라'는 압력이 되어
# 재작성된 답이 무관한 절차를 섞었다. v2 는 근거 밖 요구를 하지 않고, 반려가 근거 안에서
# 고칠 수 있는 것인지(fixable)를 함께 판정한다. fixable=false 면 재작성하지 않는다.
SYSTEM_V2 = (
    "당신은 ICT 장애 대응 답변을 채점하는 엄격한 평가자다. 아래 4개 지표를 각각 Pass/Fail로 "
    "판정하고 근거를 한 문장으로 쓴다.\n"
    "1. relevance: 사용자가 물은 것에 답했는가. 요청 대상이 등록된 시스템·런북에 없으면 그 사실을 "
    "밝혀야 Pass. 다른 시스템·장애 이야기로 바꿔 답하면 Fail.\n"
    "2. completeness: Context에 없는 수치·원인·사실을 만들어냈다면 Fail. Context의 핵심 사실이 빠져도 Fail.\n"
    "3. domain_appropriateness: Context의 런북 중 질문에 맞는 절차를 반영했는가. 질문과 무관한 런북 "
    "절차를 섞었다면 Fail. Context에 '일치하는 런북이 없음' 안내가 있으면 런북 절차를 요구하지 말고, "
    "답이 추측한 절차 없이 확인 범위를 밝히고 되물었는지로 판정한다.\n"
    "4. clarity: 요청한 형식·길이 제약을 지켰고 논리적으로 정리됐는가.\n"
    "마지막으로 fixable: Fail 지표를 Context 안의 정보만으로 고칠 수 있으면 true, Context에 없는 "
    "정보가 있어야 고칠 수 있으면 false.\n"
    'JSON 객체로만 답한다: {"relevance":{"verdict":"Pass|Fail","reason":"..."},'
    '"completeness":{...},"domain_appropriateness":{...},"clarity":{...},"fixable":true|false}'
)


def facts_from_prompt(prompt: str | None) -> str | None:
    """write 노드가 받은 프롬프트에서 '## 수집된 사실' 구간만 꺼낸다.

    재작성 프롬프트 뒤에 붙는 '## 이전 초안에 대한 검증 반려 사유' 는 잘라 낸다. 반려 사유는 근거가
    아니므로, Judge, 평가 Judge, factcheck 가 모두 '실제로 수집된 사실'만 근거로 보게 하려는 것이다.
    프롬프트가 없으면(fake 백엔드 등) None.
    """
    if not prompt or "## 수집된 사실" not in prompt:
        return None
    body = prompt.split("## 수집된 사실", 1)[1]
    body = re.split(r"\n\n## 이전 초안에 대한 검증 반려 사유", body, maxsplit=1)[0]
    return body.strip()


def facts_from_collected(collected: list[dict]) -> str:
    """fake 백엔드처럼 프롬프트가 없을 때 쓰는 대체 — openai_llm.write 의 사실 정리와 같은 형식."""
    out = []
    for c in collected:
        if c["source"] == "monitoring":
            d = c["data"]
            out.append(f"- 모니터링 {d['system_name']}: 상태={d['status']}, CPU {d['cpu_percent']}%, "
                       f"메모리 {d['memory_percent']}%, 알림 {len(d['alerts'])}건 {d['alerts']}")
        elif c["source"] == "runbook":
            out.append(f"- runbook 발췌:\n{c['data'].strip()}")
        elif c["source"] == "analysis":
            out.append(f"- 패턴 분석: {c['data'].strip()}")
    return "\n".join(out)


class OpenAIJudge(MeteredChatMixin, OpenAILLM):
    """파이프라인 내부 Judge. 한 번의 JSON 모드 호출로 4지표 Pass/Fail, 사유(+v2 는 fixable)를 받는다."""

    def __init__(self, model: str, usd_per_1k_tokens: float, version: int = 1):
        """version 이 2 이상이면 SYSTEM_V2 프롬프트를 쓰고 응답의 fixable 값을 읽는다."""
        super().__init__(model, usd_per_1k_tokens)
        self.version = version

    def evaluate(self, query: str, context: str, answer: str) -> dict:
        """Returns: {"verdicts": {지표: Pass|Fail}, "reasons": {지표: 문장}, "fixable": bool}."""
        user = f"[Query]\n{query}\n\n[Context]\n{context}\n\n[Answer]\n{answer}"
        with stage("judge"):
            content, _ = self._chat(SYSTEM_V2 if self.version >= 2 else SYSTEM, user, json_mode=True)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {}   # 깨진 응답은 아래에서 전 지표 Fail → 반려, 재작성 (가드가 루프를 끊는다)
        # 빠진 지표도 Fail 로 본다 — 판정이 없으면 합격으로 넘기지 않는다
        verdicts = {m: (data.get(m) or {}).get("verdict", "Fail") for m in METRICS}
        reasons = {m: (data.get(m) or {}).get("reason", "") for m in METRICS}
        # fixable 은 v2 에서만 읽는다. 값이 없거나 이상하면 True(재작성 허용) — 명시적 false 일 때만 생략
        fixable = data.get("fixable", True) if self.version >= 2 else True
        return {"verdicts": verdicts, "reasons": reasons, "fixable": fixable is not False}


class FakeJudge:
    """오프라인 테스트용. 원본 규칙과 같은 기준을 4지표 형식으로 돌려준다.

    backend=fake 에서 쓴다. 원본 validate_node 규칙(30자 이상 + "1)" 포함)을 그대로 4지표에 복사하므로
    fake 로 돌린 judge 구성은 합격, 반려가 원본 규칙과 같다 — 배관(루프, 가드) 점검용이다.
    """

    name = "fake-judge"

    def evaluate(self, query: str, context: str, answer: str) -> dict:
        """답이 30자 이상이고 "1)" 를 포함하면 4지표 모두 Pass, 아니면 모두 Fail 을 돌려준다.

        query, context 는 보지 않는다. fixable 은 항상 True 라 재작성 루프는 가드(횟수, 시간)로만 끝난다.
        """
        ok = len(answer) >= 30 and "1)" in answer
        v = "Pass" if ok else "Fail"
        return {"verdicts": {m: v for m in METRICS},
                "reasons": {m: "" if ok else "짧거나 절차 번호가 없음" for m in METRICS},
                "fixable": True}
