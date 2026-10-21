"""파이프라인 안의 Validator — 원본 규칙(30자 이상 + "1)" 포함)을 LLM-as-a-Judge 4지표로 교체.

  relevance              Query  <-> Answer   동문서답 여부
  completeness           Answer <-> Context  근거에 없는 수치·사실을 만들지 않았는가
  domain_appropriateness Answer <-> Context  런북 조치·절차를 반영했는가
  clarity                Answer 단독         요청한 형식·길이를 지키며 체계적인가

4지표 중 통과 비율이 threshold 이상이면 합격. 불합격이면 실패 지표의 사유를 피드백으로
넘겨 재작성한다. 재시도 상한과 시간 상한 중 먼저 닿는 쪽에서 멈추고 통과 처리한다.

주의: 이 Judge 는 파이프라인 내부 검증용이다. 평가용 Judge(eval/judge.py)는 다른 모델
(gpt-4o)로 고정해, 자기 기준에 맞춰 고친 답을 같은 기준으로 다시 채점하는 순환을 피한다.
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


def facts_from_prompt(prompt: str | None) -> str | None:
    """write 노드가 받은 프롬프트에서 '## 수집된 사실' 구간만 꺼낸다."""
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
    def evaluate(self, query: str, context: str, answer: str) -> dict:
        user = f"[Query]\n{query}\n\n[Context]\n{context}\n\n[Answer]\n{answer}"
        with stage("judge"):
            content, _ = self._chat(SYSTEM, user, json_mode=True)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {}
        verdicts = {m: (data.get(m) or {}).get("verdict", "Fail") for m in METRICS}
        reasons = {m: (data.get(m) or {}).get("reason", "") for m in METRICS}
        return {"verdicts": verdicts, "reasons": reasons}


class FakeJudge:
    """오프라인 테스트용. 원본 규칙과 같은 기준을 4지표 형식으로 돌려준다."""

    name = "fake-judge"

    def evaluate(self, query: str, context: str, answer: str) -> dict:
        ok = len(answer) >= 30 and "1)" in answer
        v = "Pass" if ok else "Fail"
        return {"verdicts": {m: v for m in METRICS},
                "reasons": {m: "" if ok else "짧거나 절차 번호가 없음" for m in METRICS}}
