"""LLM-as-a-Judge — 답변 품질 4지표.

Day2 Validator 강의 내용 기준:
  Relevance              Query  <-> Answer    동문서답 여부
  Completeness           Answer <-> Context   환각/누락
  DomainAppropriateness  Answer <-> Context   도메인 내용 반영
  Clarity                Answer 자체          논리적/체계적 작성

하나의 호출에서 4지표에 Pass/Fail이 떨어지고, 통과 비율이 임계치(기본 80%)
미달이면 재작성을 요청한다. 무한 루프 방지를 위해 재시도 횟수와 총 시간
두 조건을 모두 둔다 (먼저 닿는 쪽에서 종료).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

METRICS = ("relevance", "completeness", "domain_appropriateness", "clarity")

JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "당신은 장애 대응 답변을 채점하는 엄격한 평가자입니다.\n"
     "아래 4개 지표를 각각 Pass/Fail로 판정하고, 판정 근거를 한 문장으로 쓰세요.\n\n"
     "1. relevance: 질문이 묻는 것에 답했는가. (Query <-> Answer) "
     "질문 대상(시스템·장애 유형)이 Context에 없으면 그 사실을 밝혀야 Pass이고, "
     "다른 시스템 이야기로 바꿔 답하면 Fail. 질문이 모호하면 대상·증상을 되묻거나 "
     "확인한 범위를 밝혀야 Pass.\n"
     "2. completeness: Context에 있는 필수 정보가 답변에 들어갔는가. "
     "Context에 없는 수치나 사실을 답변이 만들어냈다면 Fail. (Answer <-> Context)\n"
     "3. domain_appropriateness: Context의 도메인 조치/절차 중 질문에 맞는 것이 답변에 "
     "반영됐는가. 질문과 무관한 런북 절차를 섞었다면 Fail. (Answer <-> Context)\n"
     "4. clarity: 답변 자체가 논리적이고 체계적으로 작성됐는가. 질문이 길이·형식(예: 50자 이내, "
     "표로, 3줄 이내)을 지정했다면 그것을 지켜야 Pass. (Answer 단독)\n\n"
     "출력은 아래 JSON 스키마만. 다른 말은 쓰지 마세요.\n"
     '{{"relevance":{{"verdict":"Pass|Fail","reason":"..."}},'
     '"completeness":{{"verdict":"Pass|Fail","reason":"..."}},'
     '"domain_appropriateness":{{"verdict":"Pass|Fail","reason":"..."}},'
     '"clarity":{{"verdict":"Pass|Fail","reason":"..."}}}}'),
    ("human",
     "[Query]\n{query}\n\n"
     "[Context — 에이전트가 수집한 근거]\n{context}\n\n"
     "[Answer — 채점 대상]\n{answer}"),
])


@dataclass
class JudgeResult:
    verdicts: dict = field(default_factory=dict)   # metric -> "Pass"|"Fail"
    reasons: dict = field(default_factory=dict)    # metric -> str
    score: float = 0.0                             # 통과 비율 0.0~1.0
    passed: bool = False                           # score >= threshold
    raw: str = ""

    def as_dict(self):
        return asdict(self)


class Judge:
    def __init__(self, model: str = "gpt-4o", threshold: float = 0.75,
                 temperature: float = 0.0):
        self.threshold = threshold
        self.llm = ChatOpenAI(model=model, temperature=temperature).bind(
            response_format={"type": "json_object"})
        self.chain = JUDGE_PROMPT | self.llm

    def evaluate(self, query: str, context: str, answer: str) -> JudgeResult:
        msg = self.chain.invoke({"query": query, "context": context, "answer": answer})
        text = msg.content if hasattr(msg, "content") else str(msg)
        res = JudgeResult(raw=text)
        try:
            data = json.loads(_strip_fence(text))
        except json.JSONDecodeError:
            # 파싱 실패는 Fail로 처리하지 않고 명시적으로 남긴다.
            # 조용히 0점을 주면 Judge 오류가 모델 성능 저하로 오인된다.
            res.verdicts = {m: "ParseError" for m in METRICS}
            res.score = float("nan")
            return res

        for m in METRICS:
            item = data.get(m, {})
            res.verdicts[m] = item.get("verdict", "Fail")
            res.reasons[m] = item.get("reason", "")
        n_pass = sum(1 for m in METRICS if res.verdicts[m] == "Pass")
        res.score = n_pass / len(METRICS)
        res.passed = res.score >= self.threshold
        return res


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


# --- 무한 루프 가드 --------------------------------------------------------

class RetryGuard:
    """재시도 횟수와 총 경과 시간 중 먼저 닿는 조건에서 종료시킨다."""

    def __init__(self, max_retries: int = 2, max_seconds: float = 120.0):
        self.max_retries = max_retries
        self.max_seconds = max_seconds
        self.attempts = 0
        self._t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def should_continue(self) -> tuple[bool, str]:
        if self.attempts >= self.max_retries:
            return False, f"재시도 상한 {self.max_retries}회 도달"
        if self.elapsed >= self.max_seconds:
            return False, f"시간 상한 {self.max_seconds:.0f}초 도달"
        return True, ""

    def record(self):
        self.attempts += 1
