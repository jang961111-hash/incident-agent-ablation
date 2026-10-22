# CLAIMS: 이 저장소가 말하는 모든 수치

`scripts/claims.py` 가 결과 파일에서 계산해 만든다 (손으로 고치지 않는다). 규칙: 퍼센트는 정수, %p 는 원값 차이 후 반올림, ★ 는 95% 신뢰구간이 0을 포함하지 않음. 분모가 다른 수치(표의 비율 vs 짝지은 차이)는 분모를 같이 읽는다.

| id | 값 | 의미 | 분모 | 데이터셋 | 환경 | 결과 파일 | 재현 명령 |
|---|---|---|---|---|---|---|---|
| miss_base_final | 56% → 9% | 맞는 매뉴얼(정답 런북) 누락률, 원본 → 최종 | 장애로 처리되고 정답 런북이 있는 질문 (회당 base 24개 · final 23개) x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| wrong_base_final | 65% → 35% | 엉뚱한 매뉴얼 혼입률, 원본 → 최종 (전체 변화) | 장애로 처리된 질문 (회당 base 30개 · final 29개) x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| wrong_v2 | 59% → 35% | 엉뚱한 매뉴얼 혼입률, v2 보완 단독 (rag_judge → rag_judge_v2) | 장애로 처리된 질문 (회당 29개) x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| must_base_final | 45% → 73% | 매뉴얼 핵심 문구 포함률 (코드로 셈), 원본 → 최종 | 핵심 문구가 정의된 질문 x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| pass_base_final | 77% → 98% | 평가 Judge(gpt-4o) 통과율, 원본 → 최종 (Judge가 후해 결론 근거로 쓰지 않음) | holdout 36문제 x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| recall1_base_final | 33% → 53% | Recall@1 (1순위 런북이 정답) | 정답 런북이 있는 질문 x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| bias_aligned_para | 78% vs 11% | 원본 Recall@1: 알림 문구대로 물을 때 vs 자기 말로 물을 때 (편향 검증) | aligned 9행 · paraphrased 9행 (3회 합) | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| rag_para | 33% | RAG Recall@1, 자기 말로 묻는 질문 | paraphrased 9행 (3회 합) | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| rag_dev_holdout | 72% → 52% | RAG Recall@1 일반화 격차 (dev → holdout) | 정답 런북이 있는 질문 x 3회 | dev / holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| pair_rag_miss | -46%p [-70, -22] ★ | RAG 단독 → 정답 누락, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 23개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_rag_must | +37%p [+22, +55] ★ | RAG 단독 → 핵심 문구 포함, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 22개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_v2_wrong | -24%p [-41, -10] ★ | v2 보완 → 무관 혼입, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 29개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_v2_miss | +0%p [+0, +0] | v2 보완 → 정답 누락 (변화 없음 확인), 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 23개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_all_miss | -46%p [-70, -22] ★ | 전체 → 정답 누락, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 23개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_all_wrong | -29%p [-49, -7] ★ | 전체 → 무관 혼입, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 29개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_all_must | +30%p [+12, +48] ★ | 전체 → 핵심 문구 포함, 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 22개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| pair_cost_must | -5%p [-19, +9] | 캐스케이드 → 핵심 문구 포함 (품질 대가), 짝지은 차이 (켰을 때 − 껐을 때) | 두 구성 모두 해당하는 질문 22개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json` | `python -m eval.stats` |
| miss_raw | 56.28% → 8.57% (차이 48%p) vs 짝지은 -46.38%p | 정답 누락: 표의 원값과 짝지은 차이 원값. 분모가 달라(전체 장애 질문 vs 두 구성 공통 질문 23개) 값이 다르다 | 표: 장애·정답 런북 질문 전체 / 짝: 공통 질문 23개 | holdout | 실제 모델 (OpenAI) | `results/stats_holdout.json · 결과 파일` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| unreg_pass | 83% → 100% | 미등록 시스템 질의의 평가 Judge 통과율, rag_judge → rag_judge_v2 (전체 통과율 차이는 유의하지 않음) | 미등록 질의 4개 x 3회 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| cost_base_final | $0.00343 → $0.00057 (-84%) | 장애 1건 비용, 원본 → 최종 | 반복마다 전체 질의 비용 ÷ 장애로 처리된 질의 수 (평가 Judge 비용 제외, 공개 단가 x 실측 토큰) | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| cost_cascade_only | -73% | 장애 1건 비용, 원본 → 캐스케이드만 켠 구성(rag_judge_cost) | 같은 정의 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| cost_rj_to_cascade | -80% | 장애 1건 비용, rag_judge → rag_judge_cost (캐스케이드 효과) | 같은 정의 | holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| lat_judge | +2.7초 [+1.8, +3.7] ★ | 질의당 지연 차이, Judge 단독 (동일 부하·동시 실행 재측정) | 질문 36개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl` |
| lat_rag_judge | +1.8초 [+1.2, +2.5] ★ | 질의당 지연 차이, RAG 위에 Judge (동일 부하·동시 실행 재측정) | 질문 36개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl` |
| lat_cascade | +0.1초 [-0.1, +0.4] | 질의당 지연 차이, 캐스케이드+캐시 (동일 부하·동시 실행 재측정) | 질문 36개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl` |
| lat_v2_final | +0.3초 [+0.1, +0.5] ★ | 질의당 지연 차이, v2 위에 비용·런타임 (동일 부하·동시 실행 재측정) | 질문 36개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl` |
| lat_all | +2.5초 [+2.0, +3.0] ★ | 질의당 지연 차이, 전체 (동일 부하·동시 실행 재측정) | 질문 36개 (질문별 3회 평균) | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl` |
| p95_base_final | 8.6초 → 12.1초 | p95 지연, 원본 → 최종 (반복별 p95의 3회 평균, 동일 부하 재측정) | holdout 36문제, 회마다 | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/{base,final}_latctl_latest.json` | `scripts/latency_summary.py` |
| latctl_rag_miss | -38%p ★ | 재측정에서 RAG 정답 누락 (방향 재현 확인용) | 질문 24개 | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `python -m eval.stats --tag _latctl` |
| latctl_v2_wrong | -24%p ★ | 재측정에서 v2 무관 혼입 (방향 재현 확인용) | 질문 29개 | holdout | 실제 모델 (OpenAI), 평가 Judge 생략 | `results/stats_holdout_latctl.json` | `python -m eval.stats --tag _latctl` |
| latctl_runs | 756회, 오류 0 | 지연 재측정 실행 수 | 7구성 x 36문제 x 3회 | holdout | 실제 모델 (OpenAI) | `results/*_latctl_latest.json` | `scripts/latency_summary.py` |
| runs_total | 1,260회, 오류 0 | 본 측정 실행 수 | 7구성 x 60문제 x 3회 | dev + holdout | 실제 모델 (OpenAI) | `results/{base,…,final}_latest.json` | `scripts/run_all.sh (전체) · python -m eval.extra_metrics` |
| conc_10 | 62.8초 → 9.2초 (약 6.9배) | 동시 질문 10개 처리 시간, 동기 → 비동기 | 같은 final 구성·같은 벤치, 동기/비동기만 변경, N마다 1회 측정 (신뢰구간 없음) | 벤치 질문 세트 | 실제 모델 (OpenAI) | `results/concurrency_bench_latest.json` | `python -m eval.concurrency_bench` |
| fault | 0/19 → 18/18 | 모니터링 조회 30% 실패 주입 시 고장 맞은 질문 중 끝까지 처리한 수, 원본 → 최종 | 고장 맞은 질문 수(실행마다 다름), 1회 측정, 완주 여부만 (답 품질 미평가) | 벤치 질문 38개 | 실제 모델 (OpenAI) | `results/fault_bench_latest.json` | `python -m eval.fault_bench` |
| cache | 112/160, p50 7.9초 → 5.6초 | 같은 질문 2회차 캐시 적중, 지연 p50 1회차 → 2회차 | 60문제 x 2회, final 구성 | dev + holdout | 실제 모델 (OpenAI) | `results/cache_bench_latest.json` | `python -m eval.cache_bench --config eval/configs/final.yaml` |
| sim_conc_10 | 약 4.2배 | 동시 질문 10개, 동기 → 비동기 (모의 LLM, 호출당 고정 지연) | N마다 1회 | 벤치 질문 세트 | 모의 환경 (API 없음) | `results/concurrency_bench_simulated_latest.json` | `python -m eval.concurrency_bench --backend fake_slow` |
| sim_fault | 0/21 → 21/21 | 장애 주입 완주 (모의 LLM, 코드 경로만) | 고장 맞은 질문 수 | 벤치 질문 세트 | 모의 환경 (API 없음) | `results/fault_bench_fake_latest.json` | `python -m eval.fault_bench --backend fake` |
| rater_agree | 일치 70%, kappa 0.39 | 평가 Judge(gpt-4o) vs 독립 평가자 Claude, 종합 PASS/FAIL | 원본(base) 답 60개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| rater_lenient | 17/29 (59%) | Claude가 불합격으로 본 답 중 평가 Judge가 합격시킨 비율 | Claude 불합격 29개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| human_kappa | 측정 중 (사람 라벨 없음) | 사람 vs 평가 Judge 일치도 | - | - | 사람 | `eval/human_labels.yaml (없음)` | `scripts/label.py → python -m eval.agreement` |
| rater_relevance | 일치 73%, kappa 0.44, 관대 57% | 지표별 평가 Judge vs Claude: 관련성 | 원본 답 60개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| rater_completeness | 일치 78%, kappa 0.02, 관대 83% | 지표별 평가 Judge vs Claude: 완전성 | 원본 답 60개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| rater_domain_appropriateness | 일치 55%, kappa 0.25, 관대 63% | 지표별 평가 Judge vs Claude: 도메인 적합성 | 원본 답 60개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| rater_clarity | 일치 95%, kappa 0.37, 관대 67% | 지표별 평가 Judge vs Claude: 명확성 | 원본 답 60개 | dev + holdout | AI 평가자 (사람 아님) | `eval/claude_labels.yaml` | `python -m eval.agreement --labels eval/claude_labels.yaml` |
| cacheable_share | 21% | final 비용 중 캐시 대상 단계(route·plan·임베딩) 비중 = 캐시로 줄일 수 있는 비용의 상한 | final 180회 전체 호출 | dev + holdout | 실제 모델 (OpenAI) | `results/final_latest.json` | `python deck/data.py` |
| cache_cost | $0.0272 → $0.0233 | 캐시 벤치 1회차 → 2회차 총비용 | 60문제 | dev + holdout | 실제 모델 (OpenAI) | `results/cache_bench_latest.json` | `python -m eval.cache_bench --config eval/configs/final.yaml` |
| min_score | 0.3236 | v2 최소 유사도 기준 | dev 질문만으로 보정 | dev | 실제 모델 (OpenAI) (임베딩) | `results/calibrate_rag.json` | `python -m eval.calibrate_rag` |
| min_score_gap | 0.0023 | dev에서 맞는 매뉴얼이 있는 질문과 없는 질문의 유사도 점수 차이 (경계값이 얇다는 뜻) | dev 질문 | dev | 실제 모델 (OpenAI) (임베딩) | `results/calibrate_rag.json` | `python -m eval.calibrate_rag` |
| ext_uptime | 54% | 최근 중대 장애 비용 10만 달러 초과 응답 (Uptime Institute 2025) | - | - | 외부 출처 | `docs/research/03_논문_근거.md` | `-` |
| ext_gs | 30분 이상 → 약 2분 (93%) | GS리테일 인시던트 분석 시간 [업체 공개 사례] | - | - | 외부 출처 | `docs/research/05_ChatGPT_교차조사.md · AWS 블로그` | `-` |
| ext_foa | 35.5% → 64.0% | Flow-of-Action: SOP 기반 멀티에이전트 vs ReAct RCA 정확도 | - | - | 외부 출처 | `docs/research/03_논문_근거.md` | `-` |
| ext_orchestro | 71.2% | RCA 에이전트 실패 1위 데이터 해석 환각 (오케스트로·한양대, 보도 기준) | - | - | 외부 출처 | `docs/research/02_국내_현황.md` | `-` |
