# 진행판 — 과제1 Ablation

갱신: 10/21 11:25
마감: 2026-10-22 13:00 (Git·보고서), 17:30 (발표)

## 단계

| # | 단계 | 상태 | 메모 |
|---|---|---|---|
| 0 | 레포 ~/projects 이동 | 완료 | ~/projects/incident-agent-ablation |
| 1 | GitHub 푸시 | 완료 | origin/main |
| 2 | 베이스 zip 확보 | 완료 | 슬랙 all_total_vue_student.zip, 5.19MB |
| 3 | 원본 이식 + 1회 실행 | 완료 | 55e15f1, docs/evidence/base_original_fake.txt |
| 4 | 평가셋 24건 | 완료 | 6b1b518, 실제 런북 id, 12/3/3/3/3 |
| 5 | adapter + 개선 3축 코드 | 완료 | src/adapter.py, src/ext/ |
| 6 | 오프라인 테스트 (fake) | 완료 | pytest 10 passed, 96회 실행 오류 0 |
| 7 | OpenAI 키 입력 | 완료 | 인증 HTTP 200, LangSmith 키도 등록 |
| 8 | base 측정 (Before) | 완료 | results/base_latest.json, 24건 오류 0 |
| 9 | human_label 24건 | 병헌 | 지금 가능 — 라벨링 탭 (p/f 입력) |
| 10 | 4구성 Ablation | 진행 | base→rag→rag_judge→rag_judge_cost 순서 실행 중 |
| 11 | 보고서 · 발표자료 | 진행 | 방법론 초안 서브에이전트 작성 중 |

## 작업 로그

- 11:25 base 완료. Recall@1 36%, 평가 Judge 통과율 83% — 런북 틀린 답도 Pass 받는 건이 보여 사람 라벨로 검증 필요
- 11:25 base 규칙 Validator 재작성 0회 (gpt-4o 답은 항상 30자+'1)' 충족 → 규칙이 사실상 무력)
- 11:20 방법론 초안(docs/05_보고서_방법.md) 수령, 임계치 표기 정정
- 11:05 4구성 x 24건 실측 시작 (results/raw/run_all.log), 방법론 초안 병렬 위임
- 11:03 실제 API 2건 스모크 통과 (Q05·Q16, 오류 0)
- 11:00 코드 리뷰 반영: Judge 오류 격리, Recall@3 편향 보정(투입 런북 지표), 라벨 해시. pytest 12 passed
- 10:40 코드 리뷰 서브에이전트 투입 (src/ext, adapter, eval)
- 10:39 fake 백엔드로 24건×4구성 배관 점검, 오류 0. pytest 10 passed
- 10:30 평가 Judge를 gpt-4o로 고정 (파이프라인 Validator gpt-4o-mini와 분리, 자기채점 순환 방지)
- 10:25 adapter: base도 retrieved 채움, context는 write 입력 원문
- 10:14 진행판 표시 방식 변경 (scripts/board.py)
- 10:12 평가셋 v2 커밋. threshold 0.8 → 0.75 (0.8은 4/4만 통과시키는 오류)
- 10:08 원본 1회 실행 성공: route→plan→gate→research→replan(disk-full)→write→validate 반려→재작성→합격
- 10:06 발견: base 런북 선택은 질의가 아니라 모니터링 알림 키워드 규칙, 런북 1개만 가져옴
- 10:06 발견: base는 이미 fast=gpt-4o-mini / quality=gpt-4o 분리 → 비용 축을 캐스케이드+캐싱으로 재정의
- 10:04 원본을 src/에 바이트 동일 이식, 단독 커밋 55e15f1
- 10:03 GitHub 푸시
- 10:02 레포 이동, 진행판 생성

## 병헌 님이 할 일

1. human_label 24건: base 측정 후 `.venv/bin/python scripts/label.py`
