# 진행판 — 과제1 Ablation

갱신: 10/21 10:14
마감: 2026-10-22 13:00 (Git·보고서), 17:30 (발표)

## 단계

| # | 단계 | 상태 | 메모 |
|---|---|---|---|
| 0 | 레포 ~/projects 이동 | 완료 | ~/projects/incident-agent-ablation |
| 1 | GitHub 푸시 | 완료 | origin/main |
| 2 | 베이스 zip 확보 | 완료 | 슬랙 all_total_vue_student.zip, 5.19MB |
| 3 | 원본 이식 + 1회 실행 | 완료 | 55e15f1, docs/evidence/base_original_fake.txt |
| 4 | 평가셋 24건 | 완료 | 6b1b518, 실제 런북 id, 12/3/3/3/3 |
| 5 | adapter + 개선 3축 코드 | 진행 | src/adapter.py, src/ext/ |
| 6 | 오프라인 테스트 (fake) | 대기 | 키 없이 전 구성 배관 검증 |
| 7 | OpenAI 키 입력 | 병헌 | scripts/set_keys.sh |
| 8 | base 측정 (Before) | 대기 | 키 필요 |
| 9 | human_label 24건 | 병헌 | scripts/label.py |
| 10 | 4구성 Ablation | 대기 | rag, rag_judge, rag_judge_cost |
| 11 | 보고서 · 발표자료 | 대기 | |

## 작업 로그

- 10:14 진행판 표시 방식 변경 (scripts/board.py)
- 10:12 평가셋 v2 커밋. threshold 0.8 → 0.75 (0.8은 4/4만 통과시키는 오류)
- 10:08 원본 1회 실행 성공: route→plan→gate→research→replan(disk-full)→write→validate 반려→재작성→합격
- 10:06 발견: base 런북 선택은 질의가 아니라 모니터링 알림 키워드 규칙, 런북 1개만 가져옴
- 10:06 발견: base는 이미 fast=gpt-4o-mini / quality=gpt-4o 분리 → 비용 축을 캐스케이드+캐싱으로 재정의
- 10:04 원본을 src/에 바이트 동일 이식, 단독 커밋 55e15f1
- 10:03 GitHub 푸시
- 10:02 레포 이동, 진행판 생성

## 병헌 님이 할 일

1. OpenAI 키 입력: 터미널에서 `scripts/set_keys.sh` (입력이 화면에 안 보임, Claude는 값을 보지 않음)
2. human_label 24건: base 측정 후 `.venv/bin/python scripts/label.py`
