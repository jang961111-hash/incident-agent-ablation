"""외부 블라인드 문항(eval/external/queries_external_v1.yaml)으로 base 와 final 을 같은 조건에서 돌린다.

문항과 정답 라벨은 개발에 관여하지 않은 AI(Gemini)가 만들었고, 실행 전에 커밋으로 고정했다 (fa943a3).
기준값, 프롬프트, 코드는 본 실험과 같다. 결과는 좋든 나쁘든 그대로 싣는다 (재실행으로 고르지 않는다).

    python -m eval.external_blind --backend fake --reps 1      # 키 없이 배관 점검 (저장 안 함)
    python -m eval.external_blind --reps 3                     # 실제 API: 15문항 x 2구성 x 3회 + 평가 Judge
    python -m eval.external_blind --summary-only               # 저장된 결과로 요약만 다시 계산

결과: results/{base,final}_external_latest.json (run_ablation 과 같은 형식, 이름 꼬리표 _external),
      results/external_blind_summary_latest.{json,md}
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
R = ROOT / "results"
QFILE = ROOT / "eval" / "external" / "queries_external_v1.yaml"
CONFIGS = ("base", "final")
TAG = "_external"


def load() -> list[dict]:
    return yaml.safe_load(QFILE.read_text(encoding="utf-8"))["queries"]


def row_metrics(r: dict) -> dict:
    """행 하나의 코드 지표. 정의는 eval/extra_metrics.py 와 같다.
    누락 = 정답이 있는 문항에서 정답 매뉴얼을 하나도 넣지 못함, 혼입 = 정답이 아닌 매뉴얼을 하나라도 넣음,
    1위 적중 = 검색 1위가 정답 중 하나, 매뉴얼 없음 판정 = 정답이 [] 인 문항에서 아무것도 넣지 않음."""
    gold, fed, ret = set(r.get("gold") or []), set(r.get("fed_runbooks") or []), r.get("retrieved") or []
    return {"miss": (not (gold & fed)) if gold else None,
            "wrong": bool(fed - gold),
            "hit1": (bool(ret) and ret[0] in gold) if gold else None,
            "abstain_ok": (not fed) if not gold else None,
            "judge_pass": r.get("judge_passed"),
            "cost": r.get("cost_usd"), "latency_s": (r.get("latency_ms") or 0) / 1000}


def _rate(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs), sum(xs), len(xs)) if xs else (float("nan"), 0, 0)


def paired_ci(a: dict, b: dict, key: str, n_boot: int = 2000, seed: int = 0):
    """질문 단위 paired bootstrap 95% CI (final − base). 반복 평균을 질문 값으로 쓴다."""
    ids = [i for i in a if a[i].get(key) is not None and b.get(i, {}).get(key) is not None]
    if not ids:
        return None
    d = [b[i][key] - a[i][key] for i in ids]
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n_boot))
    lo, hi = boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]
    return {"diff": sum(d) / len(d), "lo": lo, "hi": hi, "n": len(ids), "significant": lo > 0 or hi < 0}


def per_query(rows: list[dict]) -> dict:
    """질문별로 반복 평균을 낸다 (bool 은 비율로)."""
    acc: dict[str, dict[str, list]] = {}
    for r in rows:
        if "error" in r:
            continue
        m = row_metrics(r)
        for k, v in m.items():
            if v is not None:
                acc.setdefault(r["id"], {}).setdefault(k, []).append(float(v))
    return {i: {k: sum(v) / len(v) for k, v in d.items()} for i, d in acc.items()}


def summarize() -> dict:
    out = {"source": str(QFILE.relative_to(ROOT)), "frozen_commit": "fa943a3", "configs": {}}
    pq = {}
    for c in CONFIGS:
        data = json.loads((R / f"{c}{TAG}_latest.json").read_text())
        rows = data["rows"]
        ms = [row_metrics(r) for r in rows if "error" not in r]
        lat = sorted(m["latency_s"] for m in ms)
        out["configs"][c] = {
            "runs": len(rows), "errors": sum("error" in r for r in rows),
            **{k: _rate([m[k] for m in ms]) for k in ("miss", "wrong", "hit1", "abstain_ok", "judge_pass")},
            "cost_per_query": sum(m["cost"] for m in ms) / len(ms),
            "latency_median_s": lat[len(lat) // 2],
        }
        pq[c] = per_query(rows)
    out["paired"] = {k: paired_ci(pq["base"], pq["final"], k) for k in ("miss", "wrong", "hit1", "judge_pass", "cost", "latency_s")}
    out["by_query"] = {i: {c: pq[c].get(i) for c in CONFIGS} for i in pq["base"]}
    return out


def to_md(s: dict) -> str:
    def pct(t):
        return f"{t[0] * 100:.0f}% ({t[1]:.0f}/{t[2]})" if t[2] else "-"
    b, f = s["configs"]["base"], s["configs"]["final"]
    lines = ["# 외부 블라인드 문항 결과 (Gemini 작성 15문항)", "",
             f"문항: `{s['source']}` (실행 전 고정 커밋 {s['frozen_commit']}). 실행 수 base {b['runs']}, final {f['runs']}, 오류 base {b['errors']}, final {f['errors']}.", "",
             "| 지표 | base | final | 차이 (final − base, 95% CI) |", "|---|---|---|---|"]
    names = {"miss": "맞는 매뉴얼 누락 ↓", "wrong": "엉뚱한 매뉴얼 혼입 ↓", "hit1": "정답 매뉴얼 1위",
             "abstain_ok": "매뉴얼 없는 문항에서 넣지 않음", "judge_pass": "평가 Judge(gpt-4o) 합격"}
    for k, lab in names.items():
        p = s["paired"].get(k)
        ci = (f"{p['diff'] * 100:+.0f}%p [{p['lo'] * 100:+.0f}, {p['hi'] * 100:+.0f}]{' ★' if p['significant'] else ''}" if p else "")
        lines.append(f"| {lab} | {pct(b[k])} | {pct(f[k])} | {ci} |")
    pc, pl = s["paired"]["cost"], s["paired"]["latency_s"]
    lines.append(f"| 질의당 비용 | ${b['cost_per_query']:.5f} | ${f['cost_per_query']:.5f} | {pc['diff']:+.5f}{' ★' if pc['significant'] else ''} |")
    lines.append(f"| 지연 중앙값 | {b['latency_median_s']:.1f}초 | {f['latency_median_s']:.1f}초 | {pl['diff']:+.1f}초{' ★' if pl['significant'] else ''} |")
    lines += ["", "★ = 질문 단위 paired bootstrap 95% CI 가 0을 포함하지 않음. 15문항이라 구간이 넓다.", "",
              "| 문항 | base 누락, 혼입 | final 누락, 혼입 |", "|---|---|---|"]
    for i, d in s["by_query"].items():
        def mi(x):
            if not x:
                return "-"
            return f"{'-' if 'miss' not in x else round(x['miss'], 2)}, {round(x['wrong'], 2)}"
        lines.append(f"| {i} | {mi(d['base'])} | {mi(d['final'])} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--backend", choices=["openai", "fake"])
    ap.add_argument("--summary-only", action="store_true")
    a = ap.parse_args()
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    if not a.summary_only:
        from eval.run_ablation import run_config
        qs = load()
        fake = a.backend == "fake"
        for c in CONFIGS:
            run_config(ROOT / "eval" / "configs" / f"{c}.yaml", qs, threshold=0.75, use_judge=not fake,
                       save=not fake, backend=a.backend, reps=a.reps, workers=a.workers, tag=TAG)
        if fake:
            print("fake 배관 점검 끝 (저장 안 함)")
            return
    s = summarize()
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    for p in (R / f"external_blind_summary_{ts}.json", R / "external_blind_summary_latest.json"):
        p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    md = to_md(s)
    for p in (R / f"external_blind_summary_{ts}.md", R / "external_blind_summary_latest.md"):
        p.write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
