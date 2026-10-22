#!/usr/bin/env bash
# 동시성·장애 주입 벤치 반복 측정 (실제 API). 서로 부하를 주지 않도록 순서대로 실행한다.
# 기존 결과(_latest)는 덮어쓰지 않고 --tag 접미사로 따로 저장한다.
#   동시성: 같은 조건 4회 추가 (_rep2.._rep5)   장애: 고장 위치(seed)를 바꿔 4회 추가
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
# LangSmith 월 기록 한도 초과(429) 재시도가 측정을 오염시키므로 반복 측정에서는 기록을 끈다
export LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false
for i in 2 3 4 5; do
  echo "=== concurrency rep $i $(date +%H:%M:%S)"
  $PY -m eval.concurrency_bench --tag "_rep$i"
done
for s in 11 23 42 101; do
  echo "=== fault seed $s $(date +%H:%M:%S)"
  $PY -m eval.fault_bench --seed "$s" --tag "_seed$s"
done
echo "=== done $(date +%H:%M:%S)"
