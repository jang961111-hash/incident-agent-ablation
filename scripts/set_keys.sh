#!/usr/bin/env bash
# API 키를 화면에 표시하지 않고 입력받아 레포 루트 .env 에 저장한다.
# .env 는 .gitignore 대상이라 커밋되지 않는다. Claude는 이 값을 보지 않는다.
#   사용: scripts/set_keys.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$ROOT/.env"
touch "$ENV"; chmod 600 "$ENV"

set_kv() {  # 같은 키 줄을 지우고 새 값으로 추가
  local k="$1" v="$2"
  grep -v "^${k}=" "$ENV" > "$ENV.tmp" || true
  printf '%s=%s\n' "$k" "$v" >> "$ENV.tmp"
  mv "$ENV.tmp" "$ENV"; chmod 600 "$ENV"
}

read -r -s -p "OPENAI_API_KEY (입력이 보이지 않습니다, 붙여넣고 Enter): " OAI; echo
[ -n "$OAI" ] && set_kv OPENAI_API_KEY "$OAI"

read -r -s -p "LANGCHAIN_API_KEY (LangSmith, 없으면 그냥 Enter): " LS; echo
if [ -n "$LS" ]; then
  set_kv LANGCHAIN_API_KEY "$LS"
  set_kv LANGCHAIN_TRACING_V2 true
  set_kv LANGCHAIN_PROJECT incident-agent-ablation
fi
unset OAI LS

# 값은 출력하지 않고 등록 여부만 확인
for k in OPENAI_API_KEY LANGCHAIN_API_KEY; do
  if grep -q "^${k}=." "$ENV"; then echo "  ${k}: 등록됨"; else echo "  ${k}: 없음"; fi
done

# 키가 실제로 동작하는지 1회 확인 (모델 목록 조회 — 과금 없음)
if grep -q "^OPENAI_API_KEY=." "$ENV"; then
  set -a; source "$ENV"; set +a
  code=$(curl -s -o /dev/null -w '%{http_code}' https://api.openai.com/v1/models \
         -H "Authorization: Bearer $OPENAI_API_KEY")
  echo "  OpenAI 인증 확인: HTTP $code (200이면 정상)"
fi
