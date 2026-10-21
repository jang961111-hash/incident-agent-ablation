#!/usr/bin/env bash
# 전체 평가를 명령 하나로 다시 돌린다.
#   scripts/run_all.sh              # 7구성 x 60건 x 3회 + 캐시·동시성·장애 벤치 + 리포트
#   scripts/run_all.sh ablation     # 7구성 실측만
#   scripts/run_all.sh benches      # 벤치 3종만
# 로그: results/raw/<구성>.log   결과: results/*_latest.json
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
REPS="${REPS:-3}"; WORKERS="${WORKERS:-3}"
mkdir -p results/raw
what="${1:-all}"

if [[ "$what" == all || "$what" == ablation ]]; then
  pids=()
  for c in base rag judge rag_judge rag_judge_cost rag_judge_v2 final; do
    $PY -u -m eval.run_ablation --config "eval/configs/$c.yaml" --reps "$REPS" --workers "$WORKERS" \
      > "results/raw/$c.log" 2>&1 &
    pids+=($!)
  done
  fail=0; for p in "${pids[@]}"; do wait "$p" || fail=1; done
  echo "ablation done (fail=$fail)"
fi
if [[ "$what" == all || "$what" == benches ]]; then
  $PY -u -m eval.cache_bench --config eval/configs/final.yaml > results/raw/cache_bench.log 2>&1
  $PY -u -m eval.concurrency_bench > results/raw/concurrency_bench.log 2>&1
  $PY -u -m eval.fault_bench > results/raw/fault_bench.log 2>&1
  echo "benches done"
fi
$PY -m eval.report --split holdout --md > docs/04_결과표.md
$PY -m eval.report --md >> docs/04_결과표.md
echo "report → docs/04_결과표.md"
