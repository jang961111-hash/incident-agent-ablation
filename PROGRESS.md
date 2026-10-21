# 진행판 — 과제1 Ablation (Claude Code 자동 진행)

마지막 갱신: 10/21 10:08 · 마감 Day3 13:00 (Git·보고서) / 17:30 (발표)

## 단계

| # | 단계 | 상태 | 메모 |
|---|---|---|---|
| 0 | 레포 ~/projects 이동 | ✅ 완료 | `~/projects/incident-agent-ablation` |
| 1 | GitHub 푸시 | ✅ 완료 | origin/main 79c0345 |
| 2 | 베이스 zip 확보 (슬랙 all_total_vue_student.zip) | ✅ 완료 | Chrome으로 다운로드, 5.19MB |
| 3 | src/ 원본 이식 + 원본 1회 실행 | ✅ 완료 | 커밋 55e15f1, docs/evidence/base_original_fake.txt |
| 4 | src/adapter.py (base에서도 retrieved 채움) | 🔄 진행 중 | |
| 5 | 평가셋 24건 (실제 런북 id) | 🔄 서브에이전트 작성 중 | eval/queries.yaml |
| 6 | base 측정 → Before | ⏳ 대기 | human_label은 병헌 님이 직접 |
| 7 | Judge · RAG · 티어링+캐싱 → 4구성 Ablation | ⏳ 대기 | |
| 8 | 보고서 · 발표자료 | ⏳ 대기 | |

## 작업 로그 (최신이 위)

- 10:08 원본 1회 실행 성공(fake 백엔드): route→plan→gate→research(재시도1)→replan(disk-full)→write→validate 반려→재작성→합격
- 10:06 발견: base 런북 선택은 '질의'가 아니라 '모니터링 알림 문구' 키워드 규칙, 런북 1개만 가져옴 → base retrieved = [그 1개]
- 10:06 발견: base는 이미 fast=gpt-4o-mini / quality=gpt-4o 모델 분리 상태 → 비용 개선 축을 '캐스케이드+캐싱'으로 재정의 필요
- 10:05 평가셋 24건 작성을 서브에이전트에 병렬 위임
- 10:04 원본을 src/에 바이트 동일 이식 후 단독 커밋(55e15f1), .venv 설치(uv)
- 10:03 GitHub 푸시 완료
- 10:02 레포를 ~/projects로 이동, 진행판 생성

## 병헌 님이 직접 해야 하는 것 (Claude가 대신 못 함)

1. **OpenAI API 키 입력** — 실측에 필요. 키는 Claude가 받지 않음. 터미널에서 `scripts/set_keys.sh` 실행 → 화면에 안 보이게 입력됨
2. **human_label 24건** — base 답변을 읽고 Pass/Fail. `python scripts/label.py` (Judge 일치율의 기준)
