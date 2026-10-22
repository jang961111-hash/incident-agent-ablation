"""로컬 Ollama holdout 실행(eval/ollama_holdout.py) 결과를 본문과 같은 코드 지표로 요약한다. 재실행 없음.

지표 정의는 본문과 같다 (eval/extra_metrics.py · eval/stats.py).
  맞는 매뉴얼 누락(miss)   장애 경로 + 정답 런북 있는 질문 중, 넣은 런북에 정답이 하나도 없는 비율
  엉뚱한 매뉴얼 혼입(wrong) 장애 경로 질문 중, 정답 아닌 런북이 섞인 비율 (정답 없는 질문에 런북을 넣은 것 포함)
  매뉴얼 핵심 문구 포함    must_include 어구 포함률 (대소문자 무시 문자열 포함, 하한 지표)
  완료                     오류 없이 빈 답이 아닌 답을 낸 비율
  지연                     그래프 실행 시간(latency_ms) 중앙값·p95
  파이프라인 Judge         qwen3:8b Judge 기록 — 첫 판정 통과, 가드 없이 최종 통과, 가드(재시도·시간 상한) 종료
짝지은 차이는 질문 단위 paired bootstrap 95% CI (eval/stats.py 의 bootstrap, 2,000회, seed 0). 1회 실행이라 실행 간 변동은 못 본다.

    python -m eval.ollama_holdout_summary --a base_local --b final_local_bge
결과: results/ollama_holdout_summary_<YYYYMMDD_HHMM>.json / .md

입력은 구성마다 가장 최근 results/ollama_holdout_<구성>_<시각>.json (파일 이름 정렬 마지막).
scripts/claims.py 의 local_ho_* 수치가 이 요약 파일에서 나온다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.extra_metrics import _miss, _wrong  # noqa: E402
from eval.run_ablation import _pct  # noqa: E402
from eval.stats import _per_query, bootstrap  # noqa: E402

R = ROOT / "results"
THRESHOLD = 0.75   # 파이프라인 Judge 합격 기준 (구성 judge.threshold 와 같은 값, 4지표 중 3개)


def latest(cfg: str) -> Path:
    """완료된 실행 파일 중 가장 최근 것. '_2*' 로 시각이 붙은 파일만 골라 _partial 은 제외된다."""
    fs = sorted(p for p in R.glob(f"ollama_holdout_{cfg}_2*.json"))
    if not fs:
        raise SystemExit(f"results/ollama_holdout_{cfg}_<ts>.json 없음")
    return fs[-1]


def summarize(rows: list[dict]) -> dict:
    """한 구성 rows → 분자·분모를 함께 남긴 요약 (1회 실행이라 비율보다 'n/m' 을 보여 주려고)."""
    ok = [r for r in rows if "error" not in r]
    inc = [r for r in ok if r["route"] == "incident"]
    inc_gold = [r for r in inc if r["gold"]]
    gold = [r for r in ok if r["gold"]]
    withm = [r for r in ok if r["must_total"]]
    lat = [r["latency_ms"] / 1000 for r in ok]
    judged = [r for r in ok if r.get("pipeline_judge")]
    first_pass = [r for r in judged if r["pipeline_judge"][0]["score"] >= THRESHOLD]
    # '최종 통과' 는 가드로 통과 처리된 것을 빼고, 마지막 판정이 실제로 기준을 넘은 것만 센다
    final_pass = [r for r in judged if r["pipeline_judge"][-1]["guard"] is None
                  and r["pipeline_judge"][-1]["score"] >= THRESHOLD]
    guards: dict[str, int] = {}
    for r in judged:
        g = r["pipeline_judge"][-1]["guard"]
        if g:
            guards[g] = guards.get(g, 0) + 1
    return {
        "n": len(rows), "errors": len(rows) - len(ok),
        "error_ids": [r["id"] for r in rows if "error" in r],
        "completed_n": sum(1 for r in ok if (r.get("answer") or "").strip()),
        "routed_incident": len(inc),
        "miss_n": sum(map(_miss, inc_gold)), "miss_den": len(inc_gold),
        "miss_rate": sum(map(_miss, inc_gold)) / len(inc_gold) if inc_gold else float("nan"),
        "wrong_n": sum(map(_wrong, inc)), "wrong_den": len(inc),
        "wrong_rate": sum(map(_wrong, inc)) / len(inc) if inc else float("nan"),
        "hit1_n": sum(1 for r in gold if r["retrieved"] and r["retrieved"][0] in r["gold"]), "hit1_den": len(gold),
        "must_phrase_rate": (sum(r["must_hit"] for r in withm) / sum(r["must_total"] for r in withm)
                             if withm else float("nan")),
        "must_all_n": sum(r["must_hit"] == r["must_total"] for r in withm), "must_den": len(withm),
        "unsupported_answer_n": sum(1 for r in ok if r["unsupported_numbers"]),
        "latency_median_s": statistics.median(lat) if lat else float("nan"),
        "latency_p95_s": _pct(lat, 0.95),
        "latency_max_s": max(lat) if lat else float("nan"),
        "wall_median_s": statistics.median([r["wall_s"] for r in ok]) if ok else float("nan"),
        "rewrites_total": sum(r["rewrites"] for r in ok),
        "rewritten_n": sum(1 for r in ok if r["rewrites"]),
        "judge_judged_n": len(judged), "judge_first_pass_n": len(first_pass),
        "judge_final_pass_n": len(final_pass), "judge_guard": guards,
    }


def main():
    """두 구성(a=기준, b=비교)의 요약과 질문 단위 paired bootstrap 차이를 json·md 로 쓴다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="base_local")
    ap.add_argument("--b", default="final_local_bge")
    a = ap.parse_args()
    files = {a.a: latest(a.a), a.b: latest(a.b)}
    data = {k: json.loads(p.read_text()) for k, p in files.items()}
    summ = {k: summarize(d["rows"]) for k, d in data.items()}
    pq = {k: _per_query([r for r in d["rows"] if "error" not in r]) for k, d in data.items()}
    diffs = {m: bootstrap(pq[a.a], pq[a.b], m) for m in ("miss", "wrong", "must", "hit1", "latency")}
    out = {"environment": "로컬 Ollama qwen3:8b, holdout 36문제, 구성별 1회, API 비용 0. OpenAI 수치와 비교 대상 아님.",
           "files": {k: f"results/{p.name}" for k, p in files.items()},
           "configs": {k: {"embedding": d["config"].get("rag", {}).get("embedding")
                           if d["config"].get("runbook_selection") == "rag" else None,
                           "min_score": d["config"].get("rag", {}).get("min_score")
                           if d["config"].get("runbook_selection") == "rag" else None,
                           "selection": d["config"].get("runbook_selection", "keyword"),
                           "validator": d["config"].get("validator", "rule")} for k, d in data.items()},
           "summary": summ, "paired_bootstrap": {"a": a.a, "b": a.b, "n_boot": 2000, "seed": 0, **diffs}}
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    (R / f"ollama_holdout_summary_{ts}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    def pct(x):
        return f"{round(x * 100)}%"

    def ci(d, k=100, unit="%p", nd=0):
        if not d:
            return "-"
        f = (lambda v: f"{v * k:+.{nd}f}")
        return f"{f(d['diff'])}{unit} [{f(d['lo'])}, {f(d['hi'])}]" + (" ★" if d["significant"] else "")

    A, B = summ[a.a], summ[a.b]
    lines = [f"# 로컬 Ollama holdout 요약 ({ts})", "", out["environment"], "",
             f"| 지표 | {a.a} | {a.b} | 차이 {a.b}−{a.a} (paired bootstrap 95% CI) |", "|---|---|---|---|",
             f"| 완료 (오류 없이 답) | {A['completed_n']}/{A['n']} | {B['completed_n']}/{B['n']} | |",
             f"| 장애 경로로 처리 | {A['routed_incident']}/{A['n'] - A['errors']} | {B['routed_incident']}/{B['n'] - B['errors']} | |",
             f"| 맞는 매뉴얼 누락 | {pct(A['miss_rate'])} ({A['miss_n']}/{A['miss_den']}) | {pct(B['miss_rate'])} ({B['miss_n']}/{B['miss_den']}) | {ci(diffs['miss'])} |",
             f"| 엉뚱한 매뉴얼 혼입 | {pct(A['wrong_rate'])} ({A['wrong_n']}/{A['wrong_den']}) | {pct(B['wrong_rate'])} ({B['wrong_n']}/{B['wrong_den']}) | {ci(diffs['wrong'])} |",
             f"| 정답 매뉴얼 1위 (Hit@1) | {A['hit1_n']}/{A['hit1_den']} | {B['hit1_n']}/{B['hit1_den']} | {ci(diffs['hit1'])} |",
             f"| 매뉴얼 핵심 문구 포함 | {pct(A['must_phrase_rate'])} | {pct(B['must_phrase_rate'])} | {ci(diffs['must'])} |",
             f"| 핵심 문구 전부 포함 | {A['must_all_n']}/{A['must_den']} | {B['must_all_n']}/{B['must_den']} | |",
             f"| 지연 중앙값 · p95 | {A['latency_median_s']:.1f}초 · {A['latency_p95_s']:.1f}초 | {B['latency_median_s']:.1f}초 · {B['latency_p95_s']:.1f}초 | {ci(diffs['latency'], 1, '초', 1)} |",
             f"| 재작성 (질문 수 · 총 횟수) | {A['rewritten_n']} · {A['rewrites_total']} | {B['rewritten_n']} · {B['rewrites_total']} | |",
             f"| 파이프라인 Judge 첫 판정 통과 | - | {B['judge_first_pass_n']}/{B['judge_judged_n']} | |",
             f"| 파이프라인 Judge 최종 통과 (가드 없이) | - | {B['judge_final_pass_n']}/{B['judge_judged_n']} | |",
             f"| 가드로 종료 | - | {', '.join(f'{k} {v}' for k, v in B['judge_guard'].items()) or '없음'} | |",
             "", "★ = 95% 구간이 0을 포함하지 않음. 결과 파일: " + ", ".join(out["files"].values())]
    (R / f"ollama_holdout_summary_{ts}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("saved", f"results/ollama_holdout_summary_{ts}.json / .md")


if __name__ == "__main__":
    main()
