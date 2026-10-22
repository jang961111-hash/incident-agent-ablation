"""사람 라벨링: 채점 파일 만들기와, 채운 파일로 평가 Judge 와의 일치도 계산.

    .venv/bin/python scripts/human_labels.py make     # eval/human_labels_todo.csv (72행) + _sample.csv (20행, 층화)
    .venv/bin/python scripts/human_labels.py score eval/human_labels_todo_sample.csv
        → results/judge_vs_human_<YYYYMMDD_HHMM>.md + results/judge_vs_human_latest.json

채점 파일에는 Judge 판정을 넣지 않는다(보면 따라가게 되므로). 4지표 칸에 p(통과) / f(실패)를 적는다. 빈 칸은 건너뛴 것으로 본다.
대상: holdout 36문항의 원본(base)과 최종(final) 답, 1회차. 판정 기준은 docs/라벨링_가이드.md.
"""
import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
METRICS = ["relevance", "completeness", "domain_appropriateness", "clarity"]
KO = {"relevance": "관련성", "completeness": "완전성", "domain_appropriateness": "도메인 적합성", "clarity": "명확성"}
COLS = ["key", "id", "config", "category", "question", "evidence", "answer"] + KO_COLS if (KO_COLS := [KO[m] for m in METRICS]) else []


def rows_for(cfg):
    return {r["id"]: r for r in json.loads((R / f"{cfg}_latest.json").read_text())["rows"]
            if r.get("split") == "holdout" and r.get("rep") == 1 and "error" not in r}


def make():
    data = {c: rows_for(c) for c in ("base", "final")}
    out, meta = [], []
    for c in ("base", "final"):
        for qid, r in sorted(data[c].items()):
            out.append({"key": f"{qid}:{c}", "id": qid, "config": c, "category": r.get("category", ""),
                        "question": r["query"], "evidence": r.get("context", "")[:1200], "answer": r["answer"],
                        **{KO[m]: "" for m in METRICS}})
            meta.append((f"{qid}:{c}", c, r.get("category", ""), bool(r.get("judge_passed"))))
    full = ROOT / "eval/human_labels_todo.csv"
    with full.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    # 층화 표본 20행: 구성(base/final) 10행씩, 유형 비율 유지, 각 층 안에서 Judge 통과/불합격을 섞는다 (판정은 파일에 안 넣음)
    rnd = random.Random(20261022)
    want = {"normal": 4, "constrained": 2, "composite": 2, "unregistered": 1, "ambiguous": 1}
    pick = []
    for c in ("base", "final"):
        for cat, k in want.items():
            pool = [m for m in meta if m[1] == c and m[2] == cat]
            fails, passes = [m for m in pool if not m[3]], [m for m in pool if m[3]]
            rnd.shuffle(fails)
            rnd.shuffle(passes)
            mixed = [x for pair in zip(fails, passes) for x in pair] + fails[len(passes):] + passes[len(fails):]
            pick += [m[0] for m in mixed[:k]]
    sample = [o for o in out if o["key"] in set(pick)]
    rnd.shuffle(sample)
    sp = ROOT / "eval/human_labels_todo_sample.csv"
    with sp.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(sample)
    print(f"{full.relative_to(ROOT)}: {len(out)}행, {sp.relative_to(ROOT)}: {len(sample)}행 (층화: 구성 10+10, 유형 {want})")


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else (po - pe) / (1 - pe)


def val(s):
    s = (s or "").strip().lower()
    return True if s in ("p", "pass", "1", "o", "통과") else False if s in ("f", "fail", "0", "x", "실패") else None


def score(path):
    labels = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    data = {c: rows_for(c) for c in ("base", "final")}
    per = {m: [] for m in METRICS}
    overall, kinds = [], defaultdict(Counter)
    for row in labels:
        r = data[row["config"]][row["id"]]
        hv = {m: val(row[KO[m]]) for m in METRICS}
        for m in METRICS:
            j = r.get(f"judge_{m}")
            if hv[m] is None or j not in ("Pass", "Fail"):
                continue
            jv = j == "Pass"
            per[m].append((hv[m], jv))
            if hv[m] != jv:
                kinds[m]["Judge 관대 (사람 실패, Judge 통과)" if jv else "Judge 엄격 (사람 통과, Judge 실패)"] += 1
                kinds["유형별"][row["category"]] += 1
        if all(hv[m] is not None for m in METRICS) and r.get("judge_passed") is not None:
            overall.append((sum(hv.values()) >= 3, bool(r["judge_passed"])))
    res = {"n_rows": len(labels), "metrics": {}, "overall": None}
    lines = [f"# 사람 vs 평가 Judge 일치도 ({Path(path).name})", "",
             "사람 라벨은 장병헌이 Judge 판정을 보지 않고 매겼다. 종합 통과 = 4지표 중 3개 이상 통과.", "",
             "| 지표 | 비교 수 | 일치율 | Cohen's kappa | Judge 관대 | Judge 엄격 |", "|---|---|---|---|---|---|"]
    for m in METRICS + ["overall"]:
        pr = overall if m == "overall" else per[m]
        if not pr:
            continue
        k = kappa(pr)
        agree = sum(a == b for a, b in pr) / len(pr)
        len_ = sum(1 for h, j in pr if not h and j)
        str_ = sum(1 for h, j in pr if h and not j)
        res["metrics" if m != "overall" else "overall_m"] = res.get("metrics", {})
        entry = {"n": len(pr), "agreement": agree, "kappa": k, "judge_lenient": len_, "judge_strict": str_}
        if m == "overall":
            res["overall"] = entry
        else:
            res["metrics"][m] = entry
        lines.append(f"| {'종합' if m == 'overall' else KO[m]} | {len(pr)} | {round(agree * 100)}% | "
                     f"{'-' if k is None else f'{k:.2f}'} | {len_} | {str_} |")
    lines += ["", "불일치 유형:", ""] + [f"- {KO.get(m, m)}: {dict(c)}" for m, c in kinds.items()]
    out = R / f"judge_vs_human_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (R / "judge_vs_human_latest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out.relative_to(ROOT)}, results/judge_vs_human_latest.json")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "make":
        make()
    elif len(sys.argv) >= 3 and sys.argv[1] == "score":
        score(sys.argv[2])
    else:
        print(__doc__)
