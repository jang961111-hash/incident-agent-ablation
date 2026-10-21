#!/usr/bin/env bash
# 베이스 원본을 손대지 않고 1회 실행해 동작을 확인한다 (fake 백엔드 — API 키 불필요).
# 교수님 sh/run_agent_openai.sh 와 같은 방식: src/ 에서 server.py 를 띄우고 /chat 호출.
# 출력은 docs/evidence/base_original_<backend>.txt 에 남긴다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="${LLM_BACKEND:-fake}"
PORT=8100
OUT="$ROOT/docs/evidence/base_original_${BACKEND}.txt"
mkdir -p "$ROOT/docs/evidence"
cd "$ROOT/src"
export PATH="$ROOT/.venv/bin:$PATH"

lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
rm -f session.db
LLM_BACKEND="$BACKEND" SUPERVISOR_VERSION=v2 LANGCHAIN_TRACING_V2=false python server.py &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -f "$ROOT/src/session.db"' EXIT
for _ in $(seq 1 60); do curl -s localhost:$PORT/health >/dev/null 2>&1 && break; sleep 0.5; done

{
  echo "# 베이스 원본 실행 기록 — $(date '+%Y-%m-%d %H:%M:%S') / LLM_BACKEND=$BACKEND"
  echo "## GET /health"
  curl -s localhost:$PORT/health | python -m json.tool --no-ensure-ascii
  for q in "auth-service 로그인 응답이 느려졌어요. 원인 확인해주세요" \
           "log-service 디스크 공간이 부족하다는 알림이 왔어요. 장애 진단 부탁해요" \
           "안녕, 너는 누구야?"; do
    echo; echo "## POST /chat — $q"
    curl -s -X POST localhost:$PORT/chat -H 'Content-Type: application/json' \
      -d "{\"message\":\"$q\",\"thread_id\":\"t-base\"}" | python -m json.tool --no-ensure-ascii
  done
} | tee "$OUT"
