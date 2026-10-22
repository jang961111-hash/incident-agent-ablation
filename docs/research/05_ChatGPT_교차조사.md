# ChatGPT 웹 교차 조사 (2026-10-22 09:3x, 웹 검색 사용, 대화 "시장 조사 및 차별화 분석")

## 요지
- 2025~2026 흐름: 런북 RAG → 로그, 메트릭, 트레이스, 배포 이력까지 결합한 증거 기반 조사, 질문형 챗봇 → 알림 기반 능동 조사, 개별 API → MCP 표준 연동. 실제 인프라 변경은 승인 게이트를 두는 제품이 많음.
- 기능 단계 프레임(ChatGPT 제안, 공인 표준 아님): 1 지식 검색형(런북 RAG) → 2 검증형 대응 지원(RAG+Judge+캐스케이드+MCP, 우리 프로젝트) → 3 능동형 조사(텔레메트리, 가설 검증) → 4 통제형 자율 대응.
- 공통 흐름 5: ① 검색형 RAG → 증거 기반 추론(Datadog, Rootly) ② 수동 질문 → 알림 기반 자동 조사(PagerDuty, AWS, Resolve AI) ③ API별 통합 → MCP 표준화(Azure, Dynatrace, ServiceNow, incident.io 공식 MCP) ④ 자율 실행 → 통제 가능한 실행(Azure 승인 게이트, Rootly 인간 승인) ⑤ 단일 정확도 → 오답 위험, 비용, 지연, 불확실성까지 복합 평가(incident.io 대립 가설, Datadog 판단 유보).
- 핵심 문장: "정답을 빨리 내놓는 AI보다, 불충분한 근거로 잘못된 조치를 권하지 않는 AI가 운영 현장에서 더 가치 있다. 예: DB 연결 장애에 커넥션 풀 크기 조절을 성급히 권고하는 것보다 DB 가용성을 먼저 확인하도록 안내" → 우리 base 실패 사례와 동일.
- 차별화 제안 3: 잘못된 런북 선택을 막는 검증형 RAG / 캐스케이드의 비용 대비 품질 / 안전 중심 Human-in-the-Loop. 공통 조언: "기능 보유보다 통제된 실험으로 효과를 입증하라" → 우리 Ablation이 이미 하는 일.
- 공개 수치(서로 다른 지표, 대부분 업체 주장): GS리테일 인시던트 조사 30분 → 약 2분(AWS 블로그), Resolve AI 조사 시간 72% 단축(업체 주장), Datadog Bits AI 조사 엔진 2배(업체 발표), 엑셈/한전KDN 조치 시간 90% 단축(과거 IR).
- 시장 규모(엑셈 증권신고서 인용 추정, 전통 AIOps 포함): 세계 AIOps 2024 약 49.9억 달러, 국내 AIOps 플랫폼 2024 약 3.5억 달러.
- 한계(ChatGPT 명시): 업체 내부 구조, Judge 사용, 라우팅, 비용은 대부분 비공개.

## ChatGPT가 단 출처 (우리가 별도 검증할 것)
- PagerDuty release notes https://docs.pagerduty.com/get-started/release-notes
- Datadog Bits AI SRE https://www.datadoghq.com/ko/blog/bits-ai-sre-deeper-reasoning/
- incident.io AI SRE https://incident.io/solution/ai-sre, MCP https://incident.io/changelog/remote-mcp-server
- Rootly AI SRE https://rootly.com/ai-sre, MCP GA https://rootly.com/changelog/rootly-mcp-server-is-ga
- Azure SRE Agent https://learn.microsoft.com/en-us/azure/sre-agent/incident-response, MCP https://learn.microsoft.com/ko-kr/azure/sre-agent/mcp-connectors
- AWS DevOps Agent GA https://aws.amazon.com/about-aws/whats-new/2026/03/aws-devops-agent-generally-available/
- CloudWatch investigations GA https://aws.amazon.com/about-aws/whats-new/2025/06/ga-accelerate-troubleshooting-amazon-cloudwatch-investigations/
- Gemini Cloud Assist https://cloud.google.com/products/gemini/cloud-assist, MCP https://docs.cloud.google.com/cloud-assist/configure-mcp
- ServiceNow ITOM MCP https://www.servicenow.com/docs/r/it-operations-management/now-assist-for-it-operations-management/activate-itom-mcp-server.html
- Dynatrace MCP https://docs.dynatrace.com/docs/dynatrace-intelligence/dynatrace-mcp
- Resolve AI https://resolve.ai/product/ai-sre
- SK AX 운영혁신 https://www.skax.co.kr/ax-services/new-paradigm-operation
- 와탭 x ilert https://whatap.io/ko/blog/whatap-ilert-integration-ai-incident-response
- 엑셈 공시(KIND) https://kind.krx.co.kr/external/2026/07/09/000412/20260709001119/00591.htm
- 제니퍼 AI https://jennifersoft.com/ko/blog/tech/2025-12-22-jenniferai-jenniferinsights/
- 브레인즈컴퍼니 https://brainzcompany.com/articles/view/id/464
- LG CNS https://www.lgcns.com/kr/newsroom/press/detail.250825001
- 삼성SDS AI Agent https://www.samsungsds.com/kr/ai-agent/ai-agent.html
- GS리테일 AWS 사례 https://aws.amazon.com/ko/blogs/tech/gsretail-aiops-sre-agent/
- HYBE AWS DevOps Agent + MCP https://aws.amazon.com/ko/blogs/tech/aws-devops-agent-mcp-hybe-auto-incident/
