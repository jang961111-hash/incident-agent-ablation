"""발표·README·덱·대본·노션에 나오는 수치를 결과 파일에서 계산해 CLAIMS.md 와 results/claims.json 으로 낸다.

    .venv/bin/python scripts/claims.py

규칙: 퍼센트는 정수 반올림, %p 는 원값 차이를 계산한 뒤 반올림, 초는 소수 1자리, 달러는 소수 5자리(질의당 차이는 4자리).
수치는 손으로 적지 않는다. 외부 출처(조사)는 docs/research 파일을 근거로 적고 '외부 출처'로 표시한다.
"""
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.extra_metrics import load_all  # noqa: E402

R = ROOT / "results"
ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]


def js(p):
    return json.loads((R / p).read_text())


def pct(v):
    return f"{round(v * 100)}%"


def pp(v):
    return f"{round(v * 100):+d}%p"


SUM = {n: js(f"{n}_latest.json")["summary"] for n in ORDER}
H = {n: SUM[n]["by_split"]["holdout"]["mean"] for n in ORDER}
DEV = {n: SUM[n]["by_split"]["dev"]["mean"] for n in ORDER}
LC = {n: js(f"{n}_latctl_latest.json")["summary"]["by_split"]["holdout"]["mean"] for n in ORDER}
X = load_all("holdout")
ST = {(p["a"], p["b"]): p for p in js("stats_holdout.json")["pairs"]}
STL = {(p["a"], p["b"]): p for p in js("stats_holdout_latctl.json")["pairs"]}


def rows(n, split="holdout"):
    return [r for r in js(f"{n}_latest.json")["rows"] if r.get("split") == split and "error" not in r]


def denom_miss(n):
    rs = rows(n)
    return sum(1 for r in rs if r["route"] == "incident" and r["gold"]) / 3


def denom_wrong(n):
    return sum(1 for r in rows(n) if r["route"] == "incident") / 3


REAL = "실제 모델 (OpenAI)"
MAIN = "results/{base,…,final}_latest.json"
C = []   # (id, 표시값, 의미, 분모, 데이터셋, 환경, 결과 파일, 재현 명령)


def add(*a):
    C.append(dict(zip(["id", "값", "의미", "분모", "데이터셋", "환경", "결과 파일", "재현 명령"], a)))


RUN = "scripts/run_all.sh (전체) · python -m eval.extra_metrics"
STATS = "python -m eval.stats"

# ── 품질: 표의 비율 (반복마다 해당 행 전체에서 계산) ──
add("miss_base_final", f"{pct(X['base']['miss_runbook_rate'])} → {pct(X['final']['miss_runbook_rate'])}",
    "맞는 매뉴얼(정답 런북) 누락률, 원본 → 최종",
    f"장애로 처리되고 정답 런북이 있는 질문 (회당 base {denom_miss('base'):.0f}개 · final {denom_miss('final'):.0f}개) x 3회",
    "holdout", REAL, MAIN, RUN)
add("wrong_base_final", f"{pct(X['base']['wrong_runbook_rate'])} → {pct(X['final']['wrong_runbook_rate'])}",
    "엉뚱한 매뉴얼 혼입률, 원본 → 최종 (전체 변화)",
    f"장애로 처리된 질문 (회당 base {denom_wrong('base'):.0f}개 · final {denom_wrong('final'):.0f}개) x 3회",
    "holdout", REAL, MAIN, RUN)
add("wrong_v2", f"{pct(X['rag_judge']['wrong_runbook_rate'])} → {pct(X['rag_judge_v2']['wrong_runbook_rate'])}",
    "엉뚱한 매뉴얼 혼입률, v2 보완 단독 (rag_judge → rag_judge_v2)",
    f"장애로 처리된 질문 (회당 {denom_wrong('rag_judge'):.0f}개) x 3회", "holdout", REAL, MAIN, RUN)
add("must_base_final", f"{pct(H['base']['must_phrase_rate'])} → {pct(H['final']['must_phrase_rate'])}",
    "매뉴얼 핵심 문구 포함률 (코드로 셈), 원본 → 최종", "핵심 문구가 정의된 질문 x 3회", "holdout", REAL, MAIN, RUN)
add("pass_base_final", f"{pct(H['base']['pass_rate'])} → {pct(H['final']['pass_rate'])}",
    "평가 Judge(gpt-4o) 통과율, 원본 → 최종 (Judge가 후해 결론 근거로 쓰지 않음)", "holdout 36문제 x 3회", "holdout", REAL, MAIN, RUN)
add("recall1_base_final", f"{pct(H['base']['recall@1'])} → {pct(H['final']['recall@1'])}",
    "Recall@1 (1순위 런북이 정답)", "정답 런북이 있는 질문 x 3회", "holdout", REAL, MAIN, RUN)
add("bias_aligned_para", f"{pct(X['base']['recall@1[aligned]'])} vs {pct(X['base']['recall@1[paraphrased]'])}",
    "원본 Recall@1: 알림 문구대로 물을 때 vs 자기 말로 물을 때 (편향 검증)",
    f"aligned {X['base']['n[aligned]']:.0f}행 · paraphrased {X['base']['n[paraphrased]']:.0f}행 (3회 합)", "holdout", REAL, MAIN, RUN)
add("rag_para", pct(X['rag']['recall@1[paraphrased]']), "RAG Recall@1, 자기 말로 묻는 질문",
    f"paraphrased {X['rag']['n[paraphrased]']:.0f}행 (3회 합)", "holdout", REAL, MAIN, RUN)
add("rag_dev_holdout", f"{pct(DEV['rag']['recall@1'])} → {pct(H['rag']['recall@1'])}", "RAG Recall@1 일반화 격차 (dev → holdout)",
    "정답 런북이 있는 질문 x 3회", "dev / holdout", REAL, MAIN, RUN)

# ── 품질: 짝지은 기여도 (질문 단위, 두 구성 모두 해당하는 질문만) ──
for key, (a, b), m, lab in [("pair_rag_miss", ("base", "rag"), "miss", "RAG 단독 → 정답 누락"),
                             ("pair_rag_must", ("base", "rag"), "must", "RAG 단독 → 핵심 문구 포함"),
                             ("pair_v2_wrong", ("rag_judge", "rag_judge_v2"), "wrong", "v2 보완 → 무관 혼입"),
                             ("pair_v2_miss", ("rag_judge", "rag_judge_v2"), "miss", "v2 보완 → 정답 누락 (변화 없음 확인)"),
                             ("pair_all_miss", ("base", "final"), "miss", "전체 → 정답 누락"),
                             ("pair_all_wrong", ("base", "final"), "wrong", "전체 → 무관 혼입"),
                             ("pair_all_must", ("base", "final"), "must", "전체 → 핵심 문구 포함"),
                             ("pair_cost_must", ("rag_judge", "rag_judge_cost"), "must", "캐스케이드 → 핵심 문구 포함 (품질 대가)")]:
    q = ST[(a, b)][m]
    add(key, f"{pp(q['diff'])} [{round(q['lo'] * 100):+d}, {round(q['hi'] * 100):+d}]{' ★' if q['significant'] else ''}",
        f"{lab}, 짝지은 차이 (켰을 때 − 껐을 때)", f"두 구성 모두 해당하는 질문 {q['n']}개 (질문별 3회 평균)",
        "holdout", REAL, "results/stats_holdout.json", STATS)

# 분모 설명용 원값 (표의 비율과 짝지은 차이가 왜 다른가)
mb, mf = X["base"]["miss_runbook_rate"] * 100, X["final"]["miss_runbook_rate"] * 100
add("miss_raw", f"{mb:.2f}% → {mf:.2f}% (차이 {round(mb - mf):d}%p) vs 짝지은 {ST[('base', 'final')]['miss']['diff'] * 100:+.2f}%p",
    "정답 누락: 표의 원값과 짝지은 차이 원값. 분모가 달라(전체 장애 질문 vs 두 구성 공통 질문 23개) 값이 다르다",
    "표: 장애·정답 런북 질문 전체 / 짝: 공통 질문 23개", "holdout", REAL, "results/stats_holdout.json · 결과 파일", RUN)
add("unreg_pass", f"{pct(H['rag_judge']['pass_rate[unregistered]'])} → {pct(H['rag_judge_v2']['pass_rate[unregistered]'])}",
    "미등록 시스템 질의의 평가 Judge 통과율, rag_judge → rag_judge_v2 (전체 통과율 차이는 유의하지 않음)",
    "미등록 질의 4개 x 3회", "holdout", REAL, MAIN, RUN)

# ── 비용 ──
cb, cf, cc, crj = (X[n]["cost_per_incident"] for n in ("base", "final", "rag_judge_cost", "rag_judge"))
add("cost_base_final", f"${cb:.5f} → ${cf:.5f} ({round((cf / cb - 1) * 100):+d}%)", "장애 1건 비용, 원본 → 최종",
    "반복마다 전체 질의 비용 ÷ 장애로 처리된 질의 수 (평가 Judge 비용 제외, 공개 단가 x 실측 토큰)", "holdout", REAL, MAIN, RUN)
add("cost_cascade_only", f"{round((cc / cb - 1) * 100):+d}%", "장애 1건 비용, 원본 → 캐스케이드만 켠 구성(rag_judge_cost)",
    "같은 정의", "holdout", REAL, MAIN, RUN)
add("cost_rj_to_cascade", f"{round((cc / crj - 1) * 100):+d}%", "장애 1건 비용, rag_judge → rag_judge_cost (캐스케이드 효과)",
    "같은 정의", "holdout", REAL, MAIN, RUN)

# ── 지연 (동일 부하 재측정) ──
for key, (a, b), lab in [("lat_judge", ("base", "judge"), "Judge 단독"), ("lat_rag_judge", ("rag", "rag_judge"), "RAG 위에 Judge"),
                         ("lat_cascade", ("rag_judge", "rag_judge_cost"), "캐스케이드+캐시"),
                         ("lat_v2_final", ("rag_judge_v2", "final"), "v2 위에 비용·런타임"), ("lat_all", ("base", "final"), "전체")]:
    q = STL[(a, b)]["latency"]
    add(key, f"{q['diff']:+.1f}초 [{q['lo']:+.1f}, {q['hi']:+.1f}]{' ★' if q['significant'] else ''}",
        f"질의당 지연 차이, {lab} (동일 부하·동시 실행 재측정)", f"질문 {q['n']}개 (질문별 3회 평균)", "holdout",
        REAL + ", 평가 Judge 생략", "results/stats_holdout_latctl.json", "scripts/run_latency_ctrl.sh · python -m eval.stats --tag _latctl")
add("p95_base_final", f"{LC['base']['latency_p95_ms'] / 1000:.1f}초 → {LC['final']['latency_p95_ms'] / 1000:.1f}초",
    "p95 지연, 원본 → 최종 (반복별 p95의 3회 평균, 동일 부하 재측정)", "holdout 36문제, 회마다", "holdout",
    REAL + ", 평가 Judge 생략", "results/{base,final}_latctl_latest.json", "scripts/latency_summary.py")
for key, m, lab in [("latctl_rag_miss", ("base", "rag", "miss"), "재측정에서 RAG 정답 누락"),
                    ("latctl_v2_wrong", ("rag_judge", "rag_judge_v2", "wrong"), "재측정에서 v2 무관 혼입")]:
    q = STL[(m[0], m[1])][m[2]]
    add(key, f"{pp(q['diff'])}{' ★' if q['significant'] else ''}", f"{lab} (방향 재현 확인용)",
        f"질문 {q['n']}개", "holdout", REAL + ", 평가 Judge 생략", "results/stats_holdout_latctl.json", "python -m eval.stats --tag _latctl")
n_lc = sum(len(js(f"{n}_latctl_latest.json")["rows"]) for n in ORDER)
add("latctl_runs", f"{n_lc}회, 오류 0", "지연 재측정 실행 수", "7구성 x 36문제 x 3회", "holdout", REAL, "results/*_latctl_latest.json", "scripts/latency_summary.py")

# ── 실행 규모 ──
n_all = sum(len(js(f"{n}_latest.json")["rows"]) for n in ORDER)
err = sum(1 for n in ORDER for r in js(f"{n}_latest.json")["rows"] if "error" in r)
add("runs_total", f"{n_all:,}회, 오류 {err}", "본 측정 실행 수", "7구성 x 60문제 x 3회", "dev + holdout", REAL, MAIN, RUN)

# ── 벤치 (실제 API, 1회 측정) ──
cr = js("concurrency_bench_latest.json")["runs"]
s10 = next(r for r in cr if r["n"] == 10 and not r["async_io"])["wall_ms"] / 1000
a10 = next(r for r in cr if r["n"] == 10 and r["async_io"])["wall_ms"] / 1000
add("conc_10", f"{s10:.1f}초 → {a10:.1f}초 (약 {s10 / a10:.1f}배)", "동시 질문 10개 처리 시간, 동기 → 비동기",
    "같은 final 구성·같은 벤치, 동기/비동기만 변경, N마다 1회 측정 (신뢰구간 없음)", "벤치 질문 세트", REAL, "results/concurrency_bench_latest.json", "python -m eval.concurrency_bench")
fv = js("fault_bench_latest.json")["variants"]
add("fault", f"{fv['base']['completed_among_faulted']}/{fv['base']['queries_with_fault']} → {fv['final']['completed_among_faulted']}/{fv['final']['queries_with_fault']}",
    "모니터링 조회 30% 실패 주입 시 고장 맞은 질문 중 끝까지 처리한 수, 원본 → 최종",
    "고장 맞은 질문 수(실행마다 다름), 1회 측정, 완주 여부만 (답 품질 미평가)", "벤치 질문 38개", REAL, "results/fault_bench_latest.json", "python -m eval.fault_bench")
# 반복 측정 (1회차 + _rep2.._rep5, LangSmith tracing off). 1회차와 조건이 조금 다를 수 있어 범위로만 쓴다.
ratios, syncs, asyncs = [], [], []
for f in ["concurrency_bench_latest.json"] + [f"concurrency_bench_rep{i}_latest.json" for i in range(2, 6)]:
    rr = js(f)["runs"]
    s = next(r for r in rr if r["n"] == 10 and not r["async_io"])["wall_ms"] / 1000
    a = next(r for r in rr if r["n"] == 10 and r["async_io"])["wall_ms"] / 1000
    syncs.append(s); asyncs.append(a); ratios.append(s / a)
add("conc_10_reps", f"{min(ratios):.1f}~{max(ratios):.1f}배 (중앙값 {statistics.median(ratios):.1f}배)",
    "동시 질문 10개, 동기 → 비동기 배수의 5회 범위",
    f"같은 벤치 5회 (동기 {min(syncs):.1f}~{max(syncs):.1f}초, 비동기 {min(asyncs):.1f}~{max(asyncs):.1f}초)", "벤치 질문 세트", REAL,
    "results/concurrency_bench_latest.json, results/concurrency_bench_rep{2..5}_latest.json", "scripts/run_bench_reps.sh")
fb = {"base": [0, 0], "final": [0, 0]}
for f in ["fault_bench_latest.json"] + [f"fault_bench_seed{s}_latest.json" for s in (11, 23, 42, 101)]:
    v = js(f)["variants"]
    for k in fb:
        fb[k][0] += v[k]["completed_among_faulted"]; fb[k][1] += v[k]["queries_with_fault"]
add("fault_reps", f"{fb['base'][0]}/{fb['base'][1]} → {fb['final'][0]}/{fb['final'][1]}",
    "고장 위치(seed) 5가지 합계: 고장 맞은 질문 중 끝까지 처리한 수, 원본 → 최종",
    "seed 7·11·23·42·101 합계, 완주 여부만 (답 품질 미평가)", "벤치 질문 38개 x 5", REAL,
    "results/fault_bench_latest.json, results/fault_bench_seed{11,23,42,101}_latest.json", "scripts/run_bench_reps.sh")
cbm = js("cache_bench_latest.json")["passes"]
add("cache", f"{cbm[1]['cache_hits']}/{cbm[1]['cache_lookups']}, p50 {cbm[0]['latency_p50_ms'] / 1000:.1f}초 → {cbm[1]['latency_p50_ms'] / 1000:.1f}초",
    "같은 질문 2회차 캐시 적중, 지연 p50 1회차 → 2회차", "60문제 x 2회, final 구성", "dev + holdout", REAL, "results/cache_bench_latest.json",
    "python -m eval.cache_bench --config eval/configs/final.yaml")

# ── 모의 환경 (API 없음) ──
sim = js("concurrency_bench_simulated_latest.json")["runs"]
ss = next(r for r in sim if r["n"] == 10 and not r["async_io"])["wall_ms"]
sa = next(r for r in sim if r["n"] == 10 and r["async_io"])["wall_ms"]
add("sim_conc_10", f"약 {ss / sa:.1f}배", "동시 질문 10개, 동기 → 비동기 (모의 LLM, 호출당 고정 지연)", "N마다 1회", "벤치 질문 세트",
    "모의 환경 (API 없음)", "results/concurrency_bench_simulated_latest.json", "python -m eval.concurrency_bench --backend fake_slow")
ff = js("fault_bench_fake_latest.json")["variants"]
add("sim_fault", f"{ff['base']['completed_among_faulted']}/{ff['base']['queries_with_fault']} → {ff['final']['completed_among_faulted']}/{ff['final']['queries_with_fault']}",
    "장애 주입 완주 (모의 LLM, 코드 경로만)", "고장 맞은 질문 수", "벤치 질문 세트", "모의 환경 (API 없음)", "results/fault_bench_fake_latest.json",
    "python -m eval.fault_bench --backend fake")

mk = js("mock_llm_bench_latest.json")["results"]
for sc, lab in [("e503", "LLM 호출 30%가 503"), ("badjson", "JSON 요청 30%가 깨진 JSON"), ("hang", "LLM 호출 15%가 65초 멈춤(클라이언트 60초 타임아웃)")]:
    b, f = mk[f"{sc}/base"], mk[f"{sc}/final"]
    add(f"mock_{sc}", f"완주 원본 {b['completed']}/{b['n']} · 최종 {f['completed']}/{f['n']}, 지연 중앙값 {b['latency_median_s']:.1f}초 · {f['latency_median_s']:.1f}초, 최대 {b['latency_max_s']:.1f}초 · {f['latency_max_s']:.1f}초",
        f"모의 LLM 서버 장애 주입: {lab}. 완주 여부와 지연만 측정 (답 품질 미측정)", f"holdout normal 질문 {f['n']}개, 1회",
        "holdout", "모의 환경 (로컬 모의 OpenAI 서버, API 없음)", "results/mock_llm_bench_latest.json", "python -m eval.mock_llm_bench")

# ── 평가자 대조 (AI 독립 평가자, 사람 아님) ──
sys.path.insert(0, str(ROOT))
from eval.agreement import summary_dict  # noqa: E402
ag = summary_dict("base", labels_path=ROOT / "eval/claude_labels.yaml")
o = ag["metrics"]["overall"]
add("rater_agree", f"일치 {pct(o['agreement'])}, kappa {o['kappa']:.2f}", "평가 Judge(gpt-4o) vs 독립 평가자 Claude, 종합 PASS/FAIL",
    f"원본(base) 답 {o['n']}개", "dev + holdout", "AI 평가자 (사람 아님)", "eval/claude_labels.yaml", "python -m eval.agreement --labels eval/claude_labels.yaml")
cf_ = o["confusion"]
add("rater_lenient", f"{cf_['사람Fail_JudgePass']}/{o['human_fail']} ({pct(o['leniency'])})", "Claude가 불합격으로 본 답 중 평가 Judge가 합격시킨 비율",
    f"Claude 불합격 {o['human_fail']}개", "dev + holdout", "AI 평가자 (사람 아님)", "eval/claude_labels.yaml", "python -m eval.agreement --labels eval/claude_labels.yaml")
add("human_kappa", "측정 중 (사람 라벨 없음)", "사람 vs 평가 Judge 일치도", "-", "-", "사람", "eval/human_labels.yaml (없음)", "scripts/label.py → python -m eval.agreement")

for mk, lab in [("relevance", "관련성"), ("completeness", "완전성"), ("domain_appropriateness", "도메인 적합성"), ("clarity", "명확성")]:
    mm = ag["metrics"].get(mk)
    if mm:
        add(f"rater_{mk}", f"일치 {pct(mm['agreement'])}, kappa {mm['kappa']:.2f}, 관대 {pct(mm['leniency'])}" if mm.get("leniency") is not None
            else f"일치 {pct(mm['agreement'])}, kappa {mm['kappa']:.2f}",
            f"지표별 평가 Judge vs Claude: {lab}", f"원본 답 {mm['n']}개", "dev + holdout", "AI 평가자 (사람 아님)",
            "eval/claude_labels.yaml", "python -m eval.agreement --labels eval/claude_labels.yaml")
_P = {"gpt-4o-mini": (0.00015, 0.0006), "gpt-4o": (0.0025, 0.01), "text-embedding-3-small": (0.00002, 0)}
_t = _c = 0.0
for _r in js("final_latest.json")["rows"]:
    for _x in _r.get("llm_calls", []):
        _v = _x["prompt"] / 1000 * _P[_x["model"]][0] + _x["completion"] / 1000 * _P[_x["model"]][1]
        _t += _v
        _c += _v if _x["stage"].split("#")[0] in ("route", "plan", "embed") else 0
add("cacheable_share", pct(_c / _t), "final 비용 중 캐시 대상 단계(route·plan·임베딩) 비중 = 캐시로 줄일 수 있는 비용의 상한",
    "final 180회 전체 호출", "dev + holdout", REAL, "results/final_latest.json", "python deck/data.py")
cbp = js("cache_bench_latest.json")["passes"]
add("cache_cost", f"${cbp[0]['cost_usd']:.4f} → ${cbp[1]['cost_usd']:.4f}", "캐시 벤치 1회차 → 2회차 총비용", "60문제", "dev + holdout",
    REAL, "results/cache_bench_latest.json", "python -m eval.cache_bench --config eval/configs/final.yaml")

# ── 근거 검증 조작 테스트 (실제 모델 답에 조작을 가함) ──
tp = js("tamper_latest.json")
ts_ = tp["summary"]
_cmd = "python -m eval.tamper_test --judge"
for k, lab in [("num", "근거에 없는 수치"), ("name", "없는 시스템명"), ("both", "수치+시스템명"), ("original", "원본 답 (오탐)")]:
    x = ts_[k]
    val = f"코드 {x['code']}/{x['n']}" + (f" · Judge {x['judge']}/{x['n']} · 둘 중 하나 {x['either']}/{x['n']}" if "judge" in x else "")
    add(f"tamper_{k}", val, f"조작 테스트: {lab}을(를) 잡은 수 (Judge = 파이프라인 Judge v2 gpt-4o-mini, 4지표 중 3개 미만 통과면 반려)",
        f"holdout final 1회차 장애 답 {x['n']}개", "holdout", REAL + " 답 + 인위 조작", "results/tamper_latest.json", _cmd)
if tp.get("judge"):
    add("tamper_cost", f"${tp['judge']['cost_usd']:.2f} ({tp['judge']['calls']}회)", "조작 테스트 Judge 호출 비용 (공개 단가 x 실측 토큰)",
        "-", "holdout", REAL, "results/tamper_latest.json", _cmd)

# ── RAG 기준값 ──
cal = js("calibrate_rag.json")["best"]
add("min_score", f"{cal['min_score']}", "v2 최소 유사도 기준", "dev 질문만으로 보정", "dev", REAL + " (임베딩)", "results/calibrate_rag.json", "python -m eval.calibrate_rag")
add("min_score_gap", f"{cal['gap']}", "dev에서 맞는 매뉴얼이 있는 질문과 없는 질문의 유사도 점수 차이 (경계값이 얇다는 뜻)", "dev 질문",
    "dev", REAL + " (임베딩)", "results/calibrate_rag.json", "python -m eval.calibrate_rag")

# ── 로컬 Ollama 데모 (정량 비교 대상 아님) ──
LOCAL = "로컬 Ollama qwen3:8b (데모, 정량 비교 대상 아님)"
cl = js("calibrate_rag_local_latest.json")
for k in ("local", "local-tfidf"):
    c = cl["candidates"][k]
    hits = round(c["retrieval_dev_gold"]["hit@1"] * c["retrieval_dev_gold"]["n"])
    add(f"local_cal_{k}", f"Hit@1 {hits}/{c['retrieval_dev_gold']['n']} · min_score {c['best']['min_score']} · margin {c['margin']['pick']}",
        f"로컬 임베더 {k}: dev 정답 매뉴얼 1위 적중 수와 보정한 기준값", "dev 중 정답 매뉴얼이 있는 질문", "dev",
        "로컬 임베더 (API 없음)", "results/calibrate_rag_local_latest.json", "python -m eval.calibrate_rag --embedding local")
d0 = js("ollama_demo_20261022_1247.json")["runs"]["final"]
add("local_first_final", f"{d0['latency_s']}초 · 매뉴얼 {len(d0['runbooks'])}개", "처음 로컬 실행 (LocalNgram + OpenAI용 기준값 0.3236): 끝까지 돌았으나 매뉴얼 미선택",
    "Q01 1건", "dev", LOCAL, "results/ollama_demo_20261022_1247.json", "python -m eval.ollama_demo --configs final")
for f in sorted(R.glob("ollama_demo_q*_2026*.json")):
    d = json.loads(f.read_text())
    for cfg, r in d["runs"].items():
        jh = r.get("judge_history") or []
        add(f"local_{d['qid']}_{cfg}", f"{r['latency_s']}초 · {','.join(r.get('runbooks') or []) or '없음'} (정답 {','.join(d['gold_runbooks'])})"
            + (f" · Judge 재작성 {r.get('rewrites')}회" if jh else ""),
            f"로컬 실행 {cfg}: 지연·고른 매뉴얼", f"{d['qid']} 1건", "dev" if d["qid"] <= "Q24" else "holdout", LOCAL,
            f"results/{f.name}", f"python -m eval.ollama_demo --configs {cfg} --qid {d['qid']}")

# ── 외부 출처 (조사) ──
for key, val, mean, src in [
        ("ext_uptime", "54%", "최근 중대 장애 비용 10만 달러 초과 응답 (Uptime Institute 2025)", "docs/research/03_논문_근거.md"),
        ("ext_gs", "30분 이상 → 약 2분 (93%)", "GS리테일 인시던트 분석 시간 [업체 공개 사례]", "docs/research/05_ChatGPT_교차조사.md · AWS 블로그"),
        ("ext_foa", "35.5% → 64.0%", "Flow-of-Action: SOP 기반 멀티에이전트 vs ReAct RCA 정확도", "docs/research/03_논문_근거.md"),
        ("ext_orchestro", "71.2%", "RCA 에이전트 실패 1위 데이터 해석 환각 (오케스트로·한양대, 보도 기준)", "docs/research/02_국내_현황.md")]:
    add(key, val, mean, "-", "-", "외부 출처", src, "-")

# ── 출력 ──
(R / "claims.json").write_text(json.dumps(C, ensure_ascii=False, indent=1), encoding="utf-8")
head = ["# CLAIMS: 이 저장소가 말하는 모든 수치", "",
        "`scripts/claims.py` 가 결과 파일에서 계산해 만든다 (손으로 고치지 않는다). 규칙: 퍼센트는 정수, %p 는 원값 차이 후 반올림, "
        "★ 는 95% 신뢰구간이 0을 포함하지 않음. 분모가 다른 수치(표의 비율 vs 짝지은 차이)는 분모를 같이 읽는다.", "",
        "| id | 값 | 의미 | 분모 | 데이터셋 | 환경 | 결과 파일 | 재현 명령 |", "|---|---|---|---|---|---|---|---|"]
body = [f"| {c['id']} | {c['값']} | {c['의미']} | {c['분모']} | {c['데이터셋']} | {c['환경']} | `{c['결과 파일']}` | `{c['재현 명령']}` |" for c in C]
(ROOT / "CLAIMS.md").write_text("\n".join(head + body) + "\n", encoding="utf-8")
print(f"CLAIMS.md: {len(C)}개 수치")
