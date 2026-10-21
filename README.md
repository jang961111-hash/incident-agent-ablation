# incident-agent-ablation

SKALA 4기 AI Agent Mini-Project · 선택과제 1 (Base AI Agent 개선) · 광주 2반 장병헌 (G062)

교수님 베이스 인시던트 대응 에이전트에 개선을 하나씩 켜는 **7구성 Ablation**을 돌려,
**어떤 개선이 실제로 효과였는지 통계로 분리하고, 그 판정을 한 AI 평가자(Judge)까지 검증**했다.

## 결론 (holdout 36건 — 기준값 조정에 쓰지 않은 질의, 3회 반복 평균)

| | base | +RAG | +Judge만 | RAG+Judge | +비용 | +v2 보완 | **final** |
|---|---|---|---|---|---|---|---|
| 정답 런북 누락률 ↓ | 56% | 9% | 54% | 9% | 8% | 10% | **9%** |
| 무관 런북 혼입률 ↓ | 65% | 59% | 63% | 59% | 57% | 35% | **34%** |
| 런북 핵심 어구 포함 (Judge 무관) | 45% | 81% | 46% | 78% | 70% | 75% | **75%** |
| 평가 Judge 통과 (gpt-4o) | 77% | 97% | 80% | 97% | 94% | 99% | **98%** |
| Recall@1 | 33% | 52% | 34% | 52% | 54% | 53% | **53%** |
| 장애 1건당 비용 (USD) | 0.00343 | 0.00397 | 0.00460 | 0.00464 | 0.00087 | 0.00415 | **0.00058** |
| p95 지연 | 8.3초 | 8.9초 | 17.1초 | 12.0초 | 10.3초 | 11.8초 | **9.9초** |

출처: `results/{구성}_latest.json` (7구성 x 60건 x 3회 = 1,260회, 실행 오류 0), `python -m eval.report --split holdout`, `python -m eval.extra_metrics`.
비용은 OpenAI 공개 단가 x 실측 토큰 추정치 (평가 Judge 제외). 지연은 7구성을 동시에 돌린 부하에서 측정했다.

**개선별 기여도** — 같은 질의끼리 짝지은 bootstrap 95% CI, holdout (`results/stats_holdout.json`)

| 켠 것 | 정답 누락 | 무관 혼입 | 어구 포함 | 질의당 비용 | 질의당 지연 |
|---|---|---|---|---|---|
| RAG 단독 | **-46%p** [-70, -22] | -6%p [-24, +14] | **+37%p** [+22, +55] | +$0.0004 ★ | +0.4초 ★ |
| Judge 단독 | -1%p [-4, 0] | -1%p [-3, 0] | +2%p [-2, +6] | +$0.0009 ★ | **+2.3초** ★ |
| RAG 위에 Judge | 0 | 0 | -3%p [-7, 0] | +$0.0005 ★ | +1.8초 ★ |
| 캐스케이드+캐시 | 0 | 0 | -7%p [-21, +7] | **-$0.0030** ★ | -0.8초 ★ |
| v2 보완 | 0 | **-24%p** [-41, -10] | -3%p [-9, +2] | -$0.0003 | +0.1초 |
| **base → final** | **-46%p** ★ | **-30%p** ★ | **+32%p** ★ | **-$0.0024** ★ | +1.2초 ★ |

굵은 글씨·★ = 95% 신뢰구간이 0을 포함하지 않음. 나머지는 차이가 있다고 말할 수 없다.

1. **조치 정확도는 RAG가 만들었다.** base는 질의가 아니라 모니터링 알림 키워드로 런북을 고른다. 알림 문구대로 물으면 Recall@1 78%, 자기 말로 물으면 11%다. RAG로 바꾸자 정답 런북 누락이 56%에서 9%로 줄었다.
2. **LLM Judge는 단독으로도, RAG 위에서도 품질을 유의하게 바꾸지 못했다.** 비용과 지연(+1.8~2.3초)만 유의하게 늘었다.
3. **1차 실측에서 찾은 약점을 고친 v2가 무관 런북 혼입을 24%p 줄였다.** 최소 유사도 기준은 dev 24건으로만 정했고 holdout에서 확인했다. 미등록 질의 평가 통과는 83%에서 100%가 됐다.
4. **캐스케이드(1차 초안 gpt-4o-mini, 반려될 때만 gpt-4o)가 장애 1건당 비용을 base 대비 83% 줄였다.** 대가로 런북 어구 포함이 7%p 내려갔고, 이 차이는 유의하지 않다.

자세한 분석: [docs/06_결과분석.md](docs/06_결과분석.md) · 방법: [docs/05_보고서_방법.md](docs/05_보고서_방법.md) · 전체 표: [docs/04_결과표.md](docs/04_결과표.md) · 발표: [deck/incident-agent-ablation.pptx](deck/incident-agent-ablation.pptx)

## 무엇을 바꿨나

원본 노드 함수는 그대로 두고, 노드 일부만 config 플래그로 교체했다 (`src/ext/graph_ext.py`).
`base` 구성은 원본 `build_graph`를 그대로 호출한다. 원본 `src/agent`는 이식 커밋(`55e15f1`) 이후 바뀌지 않았다.

| 플래그 | 교체 노드 | 원본 | 개선 |
|---|---|---|---|
| `runbook_selection: rag` | replan_check | 모니터링 알림 키워드 규칙, 런북 1개 | 질의 임베딩 순위 top 3, 1위 -0.05 이내 투입 |
| `validator: judge` | validate | 30자 이상 + "1)" 포함 | 4지표 LLM Judge, 3/4 통과, 재시도 2회 또는 120초 가드 |
| `cost.model_tiering` / `cost.cache` | write · route · plan | 항상 gpt-4o / 없음 | 1차 gpt-4o-mini, 반려 시에만 gpt-4o / 반복 질의 캐시 |
| `rag.min_score`, `rag.notices` (v2) | replan_check | 늘 런북 투입 | 최소 유사도 미만이면 '일치 런북 없음' 안내, 폴백 조회 사실 명시 |
| `judge.version: 2`, `judge.factcheck` (v2) | validate | - | 근거 밖 요구 금지·고칠 수 없는 반려는 재작성 생략, 근거 없는 수치는 코드로 먼저 반려 |
| `runtime.async_io`, `runtime.tolerant_research` | route · plan · write · research | 동기 LLM 호출이 이벤트 루프를 막음, 도구 하나 실패 시 전체 실패 | 스레드로 분리, 실패한 태스크만 근거에 표시하고 나머지로 답함 |

처음 계획한 "역할별 모델 분리"는 base에 이미 있었다 (fast=gpt-4o-mini, quality=gpt-4o). 그래서 비용 축을 캐스케이드로 다시 정했다.

## 어떻게 쟀나

- **평가셋 60건** (`eval/queries.yaml` v3): dev 24건은 v2 기준값 조정에만, holdout 36건은 v2 구현 전에 고정(커밋 `6eb9482`)해 최종 보고에만 썼다. 정상 30 · 형식 제약 8 · 복합 8 · 미등록 7 · 모호 7.
- **반복과 유의성**: 7구성 x 3회. 반복 간 95% CI(t 분포)와 질의 단위 paired bootstrap(2,000회).
- **지표 축 분리**: 검색(Recall@k, 정답 누락, 무관 혼입) / 답변(평가 Judge 4지표, 런북 어구 포함) / 운영(건당 비용, 지연, 재작성).
- **평가자 분리**: 평가 Judge는 gpt-4o로 고정, 파이프라인 Judge(gpt-4o-mini)와 분리. Judge 무관 결정적 지표를 함께 본다.
- **사람 라벨**: base 답변을 지표별로 블라인드 라벨 (`scripts/label.py` → `eval/human_labels.yaml`), `eval/agreement.py`가 지표별 kappa와 오판 유형을 낸다.
- **편향 검증**: 알림 문구대로 묻는 질의(aligned)와 자기 말로 묻는 질의(paraphrased), dev와 holdout을 나눠 본다.

## 한계

- **일반화 격차**: RAG Recall@1이 dev 72%에서 holdout 52%로 떨어진다. 자기 말로 묻는 holdout 질의는 33%다.
- **무관 런북 혼입이 남는다** (final 34%). 1위 점수와 가까운 런북을 함께 넣는 규칙 때문이다.
- **최소 유사도는 경계값이다.** dev에서 정답 있는 질의와 없는 질의의 간격이 0.0023뿐이었다.
- **평가 Judge가 포화됐다.** RAG 이후 97% 이상이라 구성 차이를 잘 보지 못한다. 결론은 Judge 무관 지표로 냈다.
- 라우터는 개선 범위 밖이다. holdout 36건 x 3회라 질의 1건이 2.8%p다. 비용은 공개 단가 기준 추정치다.

## 실행

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
scripts/set_keys.sh                                 # 키 입력 (화면에 표시되지 않음, .env 는 커밋 안 됨)

.venv/bin/python -m pytest -q                       # 오프라인 테스트 (키 불필요)
scripts/run_all.sh                                  # 7구성 x 60건 x 3회 + 캐시·동시성·장애 벤치 + 리포트
.venv/bin/python -m eval.report --split holdout     # holdout 표 (±95% CI)
.venv/bin/python -m eval.stats                      # 구성 간 paired bootstrap
.venv/bin/python -m eval.extra_metrics              # 정답 누락·혼입·건당 비용·편향 검증
.venv/bin/python scripts/label.py                   # 사람 라벨 (지표별, 블라인드)
.venv/bin/python -m eval.agreement                  # Judge-사람 지표별 kappa
.venv/bin/python scripts/demo_side_by_side.py --id Q01   # base vs final 나란히 시연
(cd deck && ../.venv/bin/python data.py > data.json && node build.js)   # 발표 덱 재생성
```

## 디렉터리

```
src/            교수님 베이스 원본 (변경 없음) + 개선
  agent/          원본 LangGraph 노드·LLM·MCP 클라이언트
  ext/            개선: graph_ext · rag · judge · factcheck · faults · meter
  adapter.py      평가 하네스 단일 진입점 run_once()
eval/           평가 하네스 (queries.yaml, configs/ 7개, run_ablation, report, stats, extra_metrics,
                agreement, calibrate_rag, cache_bench, concurrency_bench, fault_bench)
results/        실행 결과 json (보고서 수치의 출처), v1/ = 1차 실측
docs/           계획 · 평가설계 · 방법 · 결과 분석 · 실행 증빙
deck/           발표 덱 생성기 (data.py → build.js) + pptx
tests/          오프라인 테스트 (fake 백엔드)
scripts/        원커맨드 실행 · 키 입력 · 라벨링 · 시연 · 원본 실행 · 진행판
```
