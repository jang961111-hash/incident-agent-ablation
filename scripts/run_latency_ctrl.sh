#!/usr/bin/env bash
# 지연 통제 재측정: 7구성을 같은 부하(동시에 7프로세스 x workers 2)로 holdout 만 3회 다시 잰다.
# 평가 Judge 는 생략(--no-judge)해 비용을 줄이고, 결과는 results/{구성}_latctl_latest.json 에 따로 저장한다.
#   scripts/run_latency_ctrl.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p results/raw
for c in base rag judge rag_judge rag_judge_cost rag_judge_v2 final; do
  $PY -u -m eval.run_ablation --config "eval/configs/$c.yaml" --split holdout --reps 3 --workers 2 \
      --no-judge --tag _latctl > "results/raw/${c}_latctl.log" 2>&1 &
done
wait
echo "latency control done"
