# 진행판 — 과제1 Ablation

갱신: 10/21 10:57
마감: 2026-10-22 13:00 (Git·보고서), 17:30 (발표)

## 단계

| # | 단계 | 상태 | 메모 |
|---|---|---|---|
| 0 | 레포 이동 + GitHub 푸시 | 완료 | ~/projects/incident-agent-ablation, origin/main |
| 1 | 베이스 zip 확보 | 완료 | 슬랙 all_total_vue_student.zip, 5.19MB |
| 2 | 원본 이식 + 1회 실행 | 완료 | 55e15f1, docs/evidence/base_original_fake.txt |
| 3 | 평가셋 24건 | 완료 | 실제 런북 id, 12/3/3/3/3 |
| 4 | adapter + 개선 3축 코드 | 완료 | src/adapter.py, src/ext/ |
| 5 | 테스트 + 코드 리뷰 반영 | 완료 | pytest 12 passed, HIGH 2건 수정 |
| 6 | OpenAI 키 입력 | 완료 | 인증 HTTP 200 |
| 7 | 4구성 실측 | 완료 | 96회 오류 0, results/*_latest.json |
| 8 | 결정적 지표 (Judge 무관) | 완료 | must_include 포함률 36/80/88/84% |
| 9 | 캐시 효과 별도 측정 | 진행 | rag_judge_cost 24건 x 2회 |
| 10 | human_label 24건 | 병헌 | 라벨링 탭에서 p/f 입력 |
| 11 | 결과 분석 · 보고서 · 발표자료 | 진행 | |

## 작업 로그

- 10:57 README 결과 보고서 재작성·푸시, 수치 검증 에이전트 투입
- 10:55 캐시 측정 완료(2회차 적중 64/64, 비용 -31%), 발표 덱 13장 생성
- 10:49 결과 분석 초안 커밋 (docs/06_결과분석.md, docs/04_결과표.md)
- 10:49 진행판 시각 정정: 이전 로그 일부가 추정 시각이었음 → git 커밋 시각 기준으로 다시 씀. 이후는 scripts/log.sh로 실제 시각만 기록
- 10:47 결정적 지표 추가: must_include 어구 포함률 base 36% / rag 80% / rag_judge 88% / cost 84%
- 10:46 평가 Judge 포화 확인: 근거 없는 chat 답, Kafka 질문에 auth-service 얘기만 한 답도 Pass
- 10:45 4구성 실측 완료 (96회 오류 0). 캐시 측정 시작
- 10:33 base 완료. Recall@1 36%, 규칙 Validator 재작성 0회
- 10:30 4구성 실측 시작, 보고서 방법론 초안 서브에이전트 위임 (10:35 수령)
- 10:29 코드 리뷰 반영: Judge 오류 격리, Recall@3 편향 보정(투입 런북 지표), 라벨 해시
- 10:20 adapter + 개선 3축 구현, fake 백엔드로 24건 x 4구성 배관 점검 오류 0
- 10:10 진행판 표시 방식 변경 (scripts/board.py)
- 10:07 평가셋 v2. threshold 0.8 → 0.75 (0.8은 4/4만 통과시키는 오류)
- 10:06 원본 1회 실행 성공 (fake 백엔드)
- 10:05 발견: base 런북 선택은 질의가 아니라 모니터링 알림 키워드 규칙, 런북 1개만 가져옴
- 10:05 발견: base는 이미 fast=gpt-4o-mini / quality=gpt-4o 분리 → 비용 축을 캐스케이드+캐시로 재정의
- 10:04 원본을 src/에 바이트 동일 이식, 단독 커밋
- 10:02 레포 이동, GitHub 푸시, 진행판 생성

## 병헌 님이 할 일

1. human_label 24건: 라벨링 탭에서 p/f 입력 (`.venv/bin/python scripts/label.py`)
