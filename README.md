# incident-agent-ablation

SKALA 4기 AI Agent Mini-Project · 선택과제 1 (Base AI Agent 개선) · 광주 2반 장병헌 (G062)

교수님 베이스 인시던트 대응 에이전트에 **RAG · LLM-as-a-Judge · 비용 최적화**를 붙이고,
개선을 하나씩 켜는 4구성 Ablation으로 **어떤 개선이 실제로 효과였는지** 분리해 측정했다.

## 결론

| | base | +RAG | +Judge | +비용최적화 |
|---|---|---|---|---|
| 런북 검색 Recall@1 (gold 18건) | 36% | **72%** | 72% | 72% |
| write에 넣은 런북 정밀도 | 53% | 78% | 78% | 78% |
| 런북 핵심 어구 포함률 (Judge 무관, 13건) | 36% | **80%** | 88% | 84% |
| 평가 Judge(gpt-4o) 통과율 | 83% | 100% | 96% | 96% |
| 재작성 합계 | 0 | 0 | 6 | 3 |
| 지연 p95 | 6.8초 | 7.3초 | 18.1초 | 11.7초 |
| 추정 비용 (24건) | $0.0647 | $0.0731 | $0.1118 | **$0.0264** |

출처: `results/{구성}_latest.json` (2026-10-21, 4구성 x 24건 = 96회, 실행 오류 0), `eval/answer_metrics.py`.
비용은 OpenAI 공개 단가 x 실측 prompt/completion 토큰 추정치이며 평가용 Judge 비용은 뺐다.

1. **품질 개선은 RAG에서 나왔다.** base는 질의가 아니라 모니터링 알림 키워드로 런북을 고른다. 장애로 처리한 20건 중 15건에 응답 지연 런북이 붙었다. RAG로 바꾸자 Recall@1이 36%에서 72%로 올랐다.
2. **파이프라인 Judge는 이 평가셋에서 측정 가능한 이득이 없었다.** 반려 6회가 모두 맞는 런북이 없는 질의(Kafka, SSL, 모호한 요청)에서 나왔다. 재작성된 답은 무관한 런북 절차를 섞는 쪽으로 바뀌었고(Q20은 평가 Judge Fail), Q21은 재시도 상한에서 멈췄다. 남은 것은 비용 +53%와 p95 2.5배다.
3. **캐스케이드가 비용을 줄였다.** 1차 초안을 gpt-4o-mini로 쓰고 반려될 때만 gpt-4o로 다시 쓴다. rag_judge 대비 비용이 76%, base 대비 59% 줄었고 품질 지표는 노이즈 범위 안에서 같았다.
4. **캐시는 반복 질의에서만 효과가 있다.** 같은 24건을 두 번 돌리면 2회차에 route·plan·임베딩 호출 64건이 모두 캐시로 대체되고 p50 지연이 7.2초에서 5.2초로 줄었다 (`results/cache_bench_latest.json`). 캐시 대상 단계의 비용은 전체의 약 8%라 비용 절감 효과는 작다. 측정된 총비용 -31%에는 재작성 횟수 차이가 섞여 있어 캐시 효과로 쓰지 않는다. 각 질의를 1회씩 돌리는 Ablation 본 실행에서는 한 번도 적중하지 않았다.

자세한 분석은 [docs/06_결과분석.md](docs/06_결과분석.md), 방법은 [docs/05_보고서_방법.md](docs/05_보고서_방법.md), 전체 표는 [docs/04_결과표.md](docs/04_결과표.md)에 있다.
발표 자료: [deck/incident-agent-ablation.pptx](deck/incident-agent-ablation.pptx)

## 무엇을 바꿨나

원본 노드 함수는 그대로 두고 3개 노드만 config 플래그로 교체했다 (`src/ext/graph_ext.py`).
`base` 구성은 원본 `build_graph`를 그대로 호출한다. 원본 파일은 이식 커밋(`55e15f1`) 이후 바뀌지 않았다.

| 플래그 | 교체 노드 | 원본 | 개선 |
|---|---|---|---|
| `runbook_selection: rag` | replan_check | 모니터링 알림 키워드 규칙, 런북 1개 | 질의 임베딩 순위 top 3, 1위 -0.05 이내만 투입 (`src/ext/rag.py`) |
| `validator: judge` | validate | 30자 이상 + "1)" 포함 | 4지표 LLM Judge, 3/4 통과, 재시도 2회 또는 120초 가드 (`src/ext/judge.py`) |
| `cost.model_tiering` | write | 항상 gpt-4o | 1차 gpt-4o-mini, 반려 시에만 gpt-4o |
| `cost.cache` | route · plan · 임베딩 | 없음 | 정규화 질의 키 TTL 캐시. 모니터링 값과 답변은 캐시하지 않음 (`src/ext/meter.py`) |

처음 계획한 "역할별 모델 분리"는 base에 이미 있었다 (fast=gpt-4o-mini, quality=gpt-4o). 그래서 비용 축을 캐스케이드로 다시 정했다.

## 어떻게 쟀나

- **평가셋 24건** (`eval/queries.yaml`): 정상 12 (런북 6종 x 2) · 형식 제약 3 · 복합 장애 3 · 미등록 3 · 모호 3
- **검색 품질**: Recall@1/@3, MRR, write에 넣은 런북의 재현율·정밀도. base는 런북을 1개만 고르므로 Recall@3 비교는 공정하지 않아 투입 런북 기준을 같이 본다.
- **답변 품질**: 평가 Judge 4지표(관련성·완전성·도메인 적합성·명확성)와, Judge와 무관한 결정적 지표(측정 전에 정답 런북에서 뽑아 둔 핵심 어구가 답에 있는지)
- **평가자 분리**: 평가 Judge는 gpt-4o로 고정했다. 파이프라인 Judge(gpt-4o-mini)와 같은 모델로 채점하면 그 기준에 맞춰 고친 답이 자동으로 높게 나온다.
- **사람 라벨**: base 답변 24건에 사람이 Pass/Fail을 매겨 평가 Judge와의 일치율을 내도록 도구를 갖췄다 (`scripts/label.py`, Judge 판정은 가린 채로 매김). 라벨 입력 후 `eval.report` 가 일치율을 낸다.

## 한계

- 평가 Judge가 관대했다. 근거가 빈 답과 질문을 비껴간 답도 통과시켜 RAG 이후 통과율이 포화됐다. 그래서 결정적 지표를 함께 본다.
- RAG에 최소 유사도 기준이 없어 미등록 질의에도 런북을 넣는다.
- 라우터는 개선하지 않았다. '50자 이내', '표로' 같은 형식 제약 질의 3건이 4구성 모두 chat 경로로 빠졌다.
- n=24, 1회 실행이다. 질의 1건 = 4.2%p다. 반복 실행을 하지 않았다. 재작성 없이 같은 조건에서 나온 rag와 rag_judge의 1차 답 차이(어구 25개 중 2개, 8%p)를 실행 간 변동의 간접 추정치로 쓴다.
- 비용은 공개 단가 기준 추정치다.

## 실행

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
scripts/set_keys.sh                                    # 키 입력 (화면에 표시되지 않음, .env 는 커밋 안 됨)

scripts/run_base_original.sh                           # 베이스 원본 그대로 1회 실행 (fake 백엔드, 키 불필요)
.venv/bin/python -m pytest -q                          # 오프라인 테스트 12개 (키 불필요)
.venv/bin/python -m eval.run_ablation --all            # 4구성 x 24건 실측
.venv/bin/python -m eval.cache_bench                   # 캐시 효과 (같은 24건 2회)
.venv/bin/python scripts/label.py                      # 사람 라벨 (블라인드)
.venv/bin/python -m eval.report --md                   # 비교표 + Judge 일치율
(cd deck && npm install && node build.js)              # 발표 덱 재생성 (수치는 results/ 에서 읽음)
```

## 디렉터리

```
src/            교수님 베이스 원본 (변경 없음) + 개선
  agent/          원본 LangGraph 노드·LLM·MCP 클라이언트
  ext/            개선: graph_ext · rag · judge · meter
  adapter.py      평가 하네스 단일 진입점 run_once()
eval/           평가 하네스 (queries.yaml, configs/, run_ablation, report, answer_metrics, cache_bench)
results/        실행 결과 json (보고서 수치의 출처)
docs/           계획 · 평가설계 · 방법 · 결과 분석 · 실행 증빙
deck/           발표 덱 생성기 + pptx
tests/          오프라인 테스트 (fake 백엔드)
scripts/        키 입력 · 라벨링 · 원본 실행 · 진행판
```
