"""사람 라벨(eval/human_labels.yaml)과 평가용 Judge 판정의 지표별 일치도.

    python -m eval.agreement                # 평문 출력
    python -m eval.agreement --md           # 마크다운 표
    python -m eval.agreement --config base

비교 대상은 results/{config}_latest.json 의 judge_* 필드뿐이다 (rep 필드가 있으면 rep==1).
라벨을 매길 때 본 답변과 현재 답변이 다른 건(answer_sha 불일치)은 비교에서 빼고 따로 나열한다.

라벨 파일: eval/human_labels.yaml(사람, scripts/label.py 로 작성) 또는 eval/claude_labels.yaml
(독립 AI 평가자, --labels 로 지정). 지표마다 일치율, Cohen's kappa, 관대도, 엄격도를 낸다.
쓰는 곳: eval/report.py(표 아래 한 줄), scripts/claims.py, deck/data.py(rater_* 수치).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import yaml
from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
LABELS_PATH = ROOT / "eval" / "human_labels.yaml"

METRICS = ("relevance", "completeness", "domain_appropriateness", "clarity")
KEYS = METRICS + ("overall",)
PASS_MIN = 3   # 4지표 중 3개 이상 Pass → overall Pass (Judge 임계치 0.75 와 같은 규칙)

LENIENT = "Judge 관대(사람 Fail, Judge Pass)"
STRICT = "Judge 엄격(사람 Pass, Judge Fail)"


def answer_sha(answer: str) -> str:
    """답 원문 sha1 앞 12자리. 라벨이 '어느 답'에 매겨졌는지 고정해, 재실행으로 답이 바뀌면 비교에서 뺀다."""
    return hashlib.sha1(answer.encode()).hexdigest()[:12]


def overall_label(verdicts: dict) -> str:
    """4지표 Pass/Fail 에서 overall 을 낸다. Pass 가 3개 이상이면 Pass."""
    return "Pass" if sum(1 for m in METRICS if verdicts.get(m) == "Pass") >= PASS_MIN else "Fail"


def load_human(path: Path | str | None = None) -> dict:
    """{'source_config': str, 'labels': {id: {...}}}. 파일이 없으면 빈 구조."""
    p = Path(path) if path else LABELS_PATH
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    labels = data.get("labels") or {}
    for v in labels.values():
        if "answer_sha" in v:
            v["answer_sha"] = str(v["answer_sha"])
    return {"source_config": data.get("source_config", "base"), "labels": labels,
            "rater": data.get("rater", "사람")}


def load_rows(config: str = "base", results_dir: Path | str | None = None) -> dict[str, dict]:
    """id -> row. 오류 행 제외, rep 필드가 있으면 rep==1 만."""
    p = Path(results_dir or RESULTS) / f"{config}_latest.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8"))["rows"]
    return {r["id"]: r for r in rows
            if "error" not in r and r.get("rep", 1) == 1}


def cohen_kappa(hp_jp: int, hp_jf: int, hf_jp: int, hf_jf: int) -> tuple[float, str]:
    """2x2 표(사람 x Judge)에서 Cohen's kappa. 정의 불가면 (nan, 사유).

    kappa = (관측 일치 po - 우연 일치 pe) / (1 - pe). 한쪽이 거의 다 Pass 면 일치율이 높아도
    kappa 는 낮게 나온다 — Judge 가 후한지 볼 때 일치율만 보지 않는 이유.
    """
    n = hp_jp + hp_jf + hf_jp + hf_jf
    if n == 0:
        return math.nan, "표본 없음"
    po = (hp_jp + hf_jf) / n
    pe = ((hp_jp + hp_jf) * (hp_jp + hf_jp) + (hf_jp + hf_jf) * (hp_jf + hf_jf)) / n ** 2
    if pe == 1:
        return math.nan, "기대 일치율 1 (한쪽이 전부 같은 값) — kappa 정의 불가"
    return (po - pe) / (1 - pe), ""


def _stats(pairs: list[tuple[str, str, str]]) -> dict:
    """pairs: (id, human, judge) 모두 Pass/Fail."""
    c = {"hp_jp": 0, "hp_jf": 0, "hf_jp": 0, "hf_jf": 0}
    for _, h, j in pairs:
        c[f"h{h[0].lower()}_j{j[0].lower()}"] += 1   # ('Pass','Fail') → 'hp_jf'
    n = len(pairs)
    kappa, note = cohen_kappa(c["hp_jp"], c["hp_jf"], c["hf_jp"], c["hf_jf"])
    hf, hp = c["hf_jp"] + c["hf_jf"], c["hp_jp"] + c["hp_jf"]
    return {
        "n": n,
        "agreement": (c["hp_jp"] + c["hf_jf"]) / n if n else None,
        "kappa": None if math.isnan(kappa) else kappa,
        "kappa_note": note,
        "confusion": {"사람Pass_JudgePass": c["hp_jp"], "사람Pass_JudgeFail": c["hp_jf"],
                      "사람Fail_JudgePass": c["hf_jp"], "사람Fail_JudgeFail": c["hf_jf"]},
        "human_pass": hp, "human_fail": hf,
        "leniency": c["hf_jp"] / hf if hf else None,     # P(Judge Pass | 사람 Fail)
        "strictness": c["hp_jf"] / hp if hp else None,   # P(Judge Fail | 사람 Pass)
        "disagree_ids": [i for i, h, j in pairs if h != j],
    }


CLAUDE_LABELS_PATH = Path(__file__).resolve().parent / "claude_labels.yaml"


def rater_agreement(path_a: Path | str, path_b: Path | str) -> dict:
    """두 라벨 파일(예: 사람 vs Claude)끼리의 지표별 일치. 같은 답변(answer_sha 일치)에 매긴 것만 비교한다.
    결과의 'human' 자리는 a, 'judge' 자리는 b 다."""
    la, lb = load_human(path_a)["labels"], load_human(path_b)["labels"]
    pairs = {k: [] for k in KEYS}
    sha_mismatch = []
    for qid in sorted(set(la) & set(lb)):
        a, b = la[qid], lb[qid]
        if a.get("answer_sha") and b.get("answer_sha") and a["answer_sha"] != b["answer_sha"]:
            sha_mismatch.append(qid)
            continue
        for m in METRICS:
            if a.get(m) in ("Pass", "Fail") and b.get(m) in ("Pass", "Fail"):
                pairs[m].append((qid, a[m], b[m]))
        if all(a.get(m) in ("Pass", "Fail") for m in METRICS) and \
                all(b.get(m) in ("Pass", "Fail") for m in METRICS):
            pairs["overall"].append((qid, overall_label(a), overall_label(b)))
    return {"a": str(path_a), "b": str(path_b), "n_common": len(set(la) & set(lb)),
            "sha_mismatch": sha_mismatch, "metrics": {k: _stats(pairs[k]) for k in KEYS}}


def _reason(row: dict, metric: str) -> str:
    r = row.get("judge_reasons")
    return str(r.get(metric, "")) if isinstance(r, dict) else ""


def summary_dict(config: str = "base", labels_path: Path | str | None = None,
                 results_dir: Path | str | None = None) -> dict:
    """라벨 x results/<config>_latest.json(rep 1)의 평가 Judge 판정 → 지표별 일치도, 불일치 목록.

    labels_path 를 주지 않으면(=사람 라벨) eval/human_exclude.txt 의 id 를 뺀다. 라벨러가 가이드 예시 등으로
    Judge 판정을 이미 본 건이라 블라인드가 아니기 때문이다.
    """
    human = load_human(labels_path)
    rows = load_rows(config, results_dir)
    labels = human["labels"]
    excluded = []
    ex_file = Path(__file__).resolve().parent / "human_exclude.txt"
    if labels_path is None and ex_file.exists():   # 사람 라벨: 라벨러에게 판정이 노출된 건 제외 (예: 가이드 예시)
        drop = {x.strip() for x in ex_file.read_text().split() if x.strip()}
        excluded = sorted(set(labels) & drop)
        labels = {k: v for k, v in labels.items() if k not in drop}
    stale, missing = [], []
    pairs = {k: [] for k in KEYS}
    disagreements = []
    cat = {}
    for qid in sorted(labels):
        lab, row = labels[qid], rows.get(qid)
        if row is None or "answer" not in row:
            missing.append(qid)
            continue
        if lab.get("answer_sha") != answer_sha(row["answer"]):
            stale.append(qid)
            continue
        hv = {m: lab.get(m) for m in METRICS}
        jv = {m: row.get(f"judge_{m}") for m in METRICS}
        for m in METRICS:
            if hv[m] in ("Pass", "Fail") and jv[m] in ("Pass", "Fail"):
                pairs[m].append((qid, hv[m], jv[m]))
                c = cat.setdefault(row.get("category", "?"),
                                   {"n": 0, "disagree": 0, "lenient": 0, "strict": 0})
                c["n"] += 1
                if hv[m] != jv[m]:
                    d = LENIENT if hv[m] == "Fail" else STRICT
                    c["disagree"] += 1
                    c["lenient" if d == LENIENT else "strict"] += 1
                    disagreements.append({"id": qid, "metric": m, "human": hv[m], "judge": jv[m],
                                          "direction": d, "reason": _reason(row, m),
                                          "category": row.get("category", "?")})
        if all(v in ("Pass", "Fail") for v in hv.values()) and \
                all(v in ("Pass", "Fail") for v in jv.values()):
            pairs["overall"].append((qid, overall_label(hv), overall_label(jv)))
    by_md = {}
    for d in disagreements:
        by_md.setdefault(d["metric"], {}).setdefault(d["direction"], []).append(d["id"])
    return {
        "config": config,
        "rater": human["rater"],
        "source_config": human["source_config"],
        "n_labeled": len(labels),
        "n_compared": len(pairs["overall"]),
        "stale": stale,
        "excluded": excluded,
        "missing": missing,
        "metrics": {k: _stats(pairs[k]) for k in KEYS},
        "disagreements": disagreements,
        "by_metric_direction": by_md,
        "by_category": cat,
    }


# --- 출력 -------------------------------------------------------------------

def _pct(v) -> str:
    return "-" if v is None else f"{v:.0%}"


def render(s: dict, md: bool = False) -> str:
    """summary_dict 결과를 사람이 읽는 표(평문 또는 마크다운)로."""
    fmt = "github" if md else "simple"
    h2 = (lambda t: f"\n### {t}\n") if md else (lambda t: f"\n[{t}]")
    out = [f"Judge 일치도 — config={s['config']}, 라벨 {s['n_labeled']}건, "
           f"비교 {s['n_compared']}건 (사람 라벨 기준 답변: {s['source_config']})"]
    if s["n_labeled"] == 0:
        out.append("사람 라벨 없음 — python scripts/label.py 로 먼저 라벨을 매기세요.")
        return "\n".join(out)
    if s["stale"]:
        out.append(f"경고: 라벨 이후 답변이 바뀐 {len(s['stale'])}건은 제외 — {', '.join(s['stale'])}")
    if s["missing"]:
        out.append(f"경고: 현재 결과에 없거나 오류인 {len(s['missing'])}건은 제외 — {', '.join(s['missing'])}")

    rows, notes = [], []
    for k in KEYS:
        m = s["metrics"][k]
        cf = m["confusion"]
        kap = "n/a" if m["kappa"] is None else f"{m['kappa']:.2f}"
        if m["kappa"] is None and m["n"]:
            notes.append(f"{k}: {m['kappa_note']}")
        rows.append([k, m["n"], _pct(m["agreement"]), kap,
                     cf["사람Pass_JudgePass"], cf["사람Pass_JudgeFail"],
                     cf["사람Fail_JudgePass"], cf["사람Fail_JudgeFail"],
                     _pct(m["leniency"]), _pct(m["strictness"])])
    out.append(h2("지표별 일치도"))
    out.append(tabulate(rows, tablefmt=fmt, headers=[
        "지표", "n", "일치율", "kappa", "P/P", "P/F", "F/P", "F/F", "관대도", "엄격도"]))
    out.append("P/F = 사람 Pass, Judge Fail. 관대도 = P(Judge Pass | 사람 Fail), "
               "엄격도 = P(Judge Fail | 사람 Pass).")
    out.extend(f"kappa 비고 — {n}" for n in notes)

    if s["disagreements"]:
        out.append(h2("불일치 유형 (지표 x 방향)"))
        grid = []
        for m in METRICS:
            for d in (LENIENT, STRICT):
                ids = s["by_metric_direction"].get(m, {}).get(d, [])
                if ids:
                    grid.append([m, d, len(ids), ", ".join(ids)])
        out.append(tabulate(grid, tablefmt=fmt, headers=["지표", "방향", "건수", "id"]))
        out.append(h2("카테고리별 불일치"))
        out.append(tabulate(
            [[c, v["n"], v["disagree"], v["lenient"], v["strict"], _pct(v["disagree"] / v["n"])]
             for c, v in sorted(s["by_category"].items())],
            tablefmt=fmt, headers=["카테고리", "지표쌍", "불일치", "관대", "엄격", "불일치율"]))
        out.append(h2("불일치 상세"))
        out.append(tabulate(
            [[d["id"], d["category"], d["metric"], d["human"], d["judge"], d["direction"],
              d["reason"].replace("\n", " ")] for d in s["disagreements"]],
            tablefmt=fmt, headers=["id", "카테고리", "지표", "사람", "Judge", "방향", "Judge 사유"],
            maxcolwidths=None if md else [None, None, None, None, None, None, 70]))
    else:
        out.append("\n불일치 없음.")
    text = "\n".join(out)
    rater = s.get("rater", "사람")
    if not str(rater).startswith("사람"):   # Claude 등 독립 평가자 라벨이면 '사람'으로 표기하지 않는다
        text = text.replace("사람", "평가자").replace("Judge 일치도 —", f"Judge 일치도 (평가자: {rater}) —")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="base")
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    ap.add_argument("--labels", default=None, help="human_labels.yaml 경로")
    ap.add_argument("--results-dir", default=None)
    a = ap.parse_args(argv)
    print(render(summary_dict(a.config, a.labels, a.results_dir), md=a.md))


if __name__ == "__main__":
    main()
