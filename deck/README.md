# deck/ 발표 자료

## 최종 (2026-10-22 발표에 쓴 버전)

| 파일 | 내용 |
|---|---|
| `final/incident-agent-ablation_skala_canva.pptx` | Canva 최종본을 PPTX로 내보낸 것. 8장, 발표자 노트 포함 |
| `pdf/incident-agent-ablation_skala.pdf` | 같은 8장 PDF (제출 시트에 등록한 링크라 경로 고정) |
| Canva | https://canva.link/44pmzc1kme81p56 (편집·발표 원본) |

발표 스크립트·용어집·시연 가이드는 `docs/발표/` 에 있다.

## 만드는 코드

| 파일 | 내용 |
|---|---|
| `build_skala.js` | 최종 8장 초안 생성기 (pptxgenjs). `cd deck && NODE_PATH=node_modules node build_skala.js` |
| `data.py` → `data.json` | 덱에 들어가는 숫자를 결과 파일에서 뽑는다 |
| `concepts/` | 디자인 시안 5종과 비교표 (`contact_sheet.png`) |
| `skala_preview/` | 최종 초안 미리보기 이미지 |

Canva 에 올린 뒤 손으로 고친 내용(4장 그림 크기, 3장 카드 순서·이름표, 5장 Judge 포스트잇, 발표자 노트)은
`build_skala.js` 에도 반영했지만, 최종본은 `final/` 의 Canva 내보내기 파일이 기준이다.

## 이전 버전

| 파일 | 내용 |
|---|---|
| `incident-agent-ablation.pptx` | 전체 18장 (`build.js`) |
| `incident-agent-ablation_5min.pptx` | 5분용 8장 |
| `incident-agent-ablation_5min_canva.pptx` | 5분용 8장, Canva 글꼴판 |
| `incident-agent-ablation_skala.pptx` | 최종 8장 초안 (Canva 수정 전) |
