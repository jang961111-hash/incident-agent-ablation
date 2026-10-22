# 재현 명령 두 갈래. 수치별 명령은 CLAIMS.md 의 '재현 명령' 열.
PY := .venv/bin/python
OFF := LANGCHAIN_TRACING_V2=false

.PHONY: reproduce-offline reproduce-offline-bench reproduce-full check

# API 없이: 테스트 + 저장된 결과에서 통계·표·그림·CLAIMS 를 다시 계산하고 문서 수치를 대조 (비용 0)
reproduce-offline:
	$(OFF) $(PY) -m pytest -q
	$(OFF) $(PY) -m eval.stats --split holdout
	$(OFF) $(PY) -m eval.stats --tag _latctl
	$(OFF) $(PY) -m eval.extra_metrics > /dev/null
	$(OFF) $(PY) -m eval.agreement --labels eval/claude_labels.yaml > /dev/null
	$(OFF) $(PY) scripts/latency_summary.py > /dev/null
	$(OFF) $(PY) scripts/make_figs.py
	$(OFF) $(PY) scripts/gen_readme_tables.py
	$(OFF) $(PY) scripts/claims.py
	$(OFF) $(PY) scripts/check_claims.py

# API 없이 모의 LLM 으로 동시성·장애 주입 벤치 (결과는 *_simulated / *_fake + 시각별 파일, 실제 모델 수치와 분리)
reproduce-offline-bench:
	$(OFF) $(PY) -m eval.concurrency_bench --backend fake_slow
	$(OFF) $(PY) -m eval.fault_bench --backend fake

# 실제 API (개인 OpenAI 키 필요). 비용 추정(results 실측 기준): 본 측정 7구성 x 60 x 3 약 $10(평가 Judge 포함),
# 지연 통제 재측정 약 $2, 벤치 3종 약 $1 미만. 실수로 돌리지 않게 CONFIRM=yes 를 요구한다.
reproduce-full:
	@test "$(CONFIRM)" = "yes" || (echo "실제 API 비용이 듭니다(약 \$$13). 진행하려면: make reproduce-full CONFIRM=yes"; exit 1)
	scripts/run_all.sh
	scripts/run_latency_ctrl.sh
	$(MAKE) reproduce-offline

check:
	$(OFF) $(PY) scripts/claims.py && $(OFF) $(PY) scripts/check_claims.py
