# incident-agent-ablation

SKALA 4기 AI Agent Mini-Project (선택과제 1: Base AI Agent 개선)
장병헌 (G062, 광주 2반)

## 한 줄 요약

베이스 인시던트 대응 에이전트에 RAG · LLM-as-a-Judge · 비용 최적화를 적용하고,
**각 개선이 어느 지표를 얼마나 올렸는지 Ablation으로 분해**한다.

## 왜 Ablation인가

개선 항목을 나열하면 "정확도가 올랐다"까지만 말할 수 있다.
올라간 원인이 RAG인지 프롬프트 수정인지 구분되지 않기 때문이다.

이 프로젝트는 개선을 하나씩 켜가며 같은 평가셋을 4번 돌린다.

| 구성 | RAG | Judge | 비용최적화 |
|---|---|---|---|
| `base` | | | |
| `rag` | O | | |
| `rag_judge` | O | O | |
| `rag_judge_cost` | O | O | O |

## 측정 축 2개를 분리한다

수업에서 Validator 4지표(관련성·완전성·도메인 적합성·명확성)는 **답변 품질**이고,
Context Precision은 **검색 품질**로 따로 분류된다.

이 둘을 분리해서 재면 인과가 연결된다.

> Recall@3 54% → 91% 로 올라서 완전성이 62% → 89% 가 되었다

반대로 검색은 좋아졌는데 답변이 안 좋아진 구간이 나오면
그것이 그대로 한계·트레이드오프 분석의 재료가 된다.

## 지표

**답변 품질 (LLM-as-a-Judge, 임계치 80%)**

| 지표 | 보는 관계 | 의미 |
|---|---|---|
| Relevance | Query ↔ Answer | 동문서답 여부 |
| Completeness | Answer ↔ Context | 환각·누락 |
| Domain Appropriateness | Answer ↔ Context | 도메인 내용 반영 |
| Clarity | Answer 자체 | 논리적·체계적 작성 |

**검색 품질**

- Recall@1 / Recall@3 — 정답 런북이 상위 k건에 포함되는 비율

**운영 지표**

- p50 / p95 지연, 토큰 수, 추정 비용, 재작성 횟수

**평가자 검증**

- 평가셋 전건에 사람(본인) Pass/Fail 라벨을 달고 Judge 판정과의 일치율을 측정한다.
  일치율이 85%면 위 수치는 ±15% 오차 안에서 읽어야 한다는 뜻이고, 보고서에 그대로 쓴다.

## 디렉터리

```
src/          베이스 에이전트 코드 (교수님 제공분 + 개선)
eval/         평가 하네스
  queries.yaml        평가셋
  judge.py            LLM-as-a-Judge 4지표
  retrieval_metrics.py 검색 품질
  run_ablation.py     4구성 비교 실행
  configs/            구성별 on/off
results/      실행 결과 (json, csv)
docs/         계획 · 평가설계 · 실험로그
```

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env     # OPENAI_API_KEY 입력

python -m eval.run_ablation --config eval/configs/base.yaml
python -m eval.run_ablation --all          # 4구성 연속 실행
python -m eval.report                      # 비교표 생성
```

## 진행 상황

- [ ] 베이스 코드 이식 및 동작 확인
- [ ] 평가셋 24건 작성 + 사람 라벨
- [ ] Judge 노드 구현
- [ ] base 구성 측정 (Before 확정)
- [ ] RAG 적용 + Recall@k 계측
- [ ] 모델 티어링 + 캐싱
- [ ] Ablation 4구성 실행
- [ ] Judge 일치율 측정
- [ ] 보고서 · 발표자료
