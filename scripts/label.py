"""base 답변에 사람 라벨을 지표별 Pass/Fail 로 매긴다. Judge 일치도의 기준이 된다.

    .venv/bin/python scripts/label.py                    # 아직 라벨 없는 건만
    .venv/bin/python scripts/label.py --split holdout    # queries.yaml 의 split 으로 거름
    .venv/bin/python scripts/label.py --only Q01,Q02

판정이 흔들리지 않도록 Judge 판정, 점수는 보여주지 않는다 (블라인드).
지표 4개(relevance / completeness / domain_appropriateness / clarity)를 하나씩 묻고,
overall 은 4개 중 3개 이상 Pass 면 Pass (Judge 임계치 0.75 와 같은 규칙).

입력: p = Pass, f = Fail, s = 이 건 건너뜀, u = 이 건 지표 다시 매기기, q = 종료
한 건을 끝낼 때마다 eval/human_labels.yaml 에 저장한다. 한 번 매긴 라벨은 수정하지 않는다.
라벨은 eval/queries.yaml 에 쓰지 않는다 (그 파일은 고정된 평가셋).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from eval.agreement import LABELS_PATH, METRICS, answer_sha, load_human, overall_label  # noqa: E402

QY = ROOT / "eval" / "queries.yaml"
BASE = ROOT / "results" / "base_latest.json"

HEADER = "# 사람 라벨 — base 답변 기준, 지표별 Pass/Fail. 한 번 매기면 수정하지 않는다.\n"
KO_NAME = {"relevance": "관련성", "completeness": "완전성",
           "domain_appropriateness": "도메인 적합성", "clarity": "명확성"}
CRITERIA = {
    "relevance": "묻는 것에 답했나, 미등록이면 없다고 밝혔나",
    "completeness": "근거에 없는 수치, 사실을 지어내지 않았고, 근거의 핵심 사실이 들어갔나",
    "domain_appropriateness": "질문에 맞는 런북 절차를 반영했나, 무관한 절차를 섞지 않았나",
    "clarity": "요청한 형식, 길이를 지켰고 체계적인가",
}


def _scalar(v: str) -> str:
    """YAML 이 문자열로 다시 읽도록 필요할 때만 따옴표를 붙인다."""
    return v if isinstance(yaml.safe_load(v), str) else f"'{v}'"


def format_labels(labels: dict, source_config: str = "base") -> str:
    lines = [HEADER.rstrip("\n"), f"source_config: {source_config}", "labels:"]
    for qid in sorted(labels):
        e = labels[qid]
        parts = [f"{m}: {e[m]}" for m in METRICS]
        parts += [f"overall: {e['overall']}", f"answer_sha: {_scalar(e['answer_sha'])}",
                  f"labeled_at: '{e['labeled_at']}'"]
        lines.append(f"  {qid}: {{{', '.join(parts)}}}")
    return "\n".join(lines) + "\n"


def save_labels(path: Path, labels: dict, source_config: str = "base") -> None:
    """임시 파일에 쓰고 rename — 중간에 끊겨도 기존 파일이 깨지지 않는다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(format_labels(labels, source_config))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def make_entry(verdicts: dict, answer: str, now: datetime | None = None) -> dict:
    e = {m: verdicts[m] for m in METRICS}
    e["overall"] = overall_label(verdicts)
    e["answer_sha"] = answer_sha(answer)
    e["labeled_at"] = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M")
    return e


def wrap(s: str, indent: str = "    ") -> str:
    return "\n".join(textwrap.fill(line, 96, initial_indent=indent, subsequent_indent=indent)
                     or indent for line in s.splitlines())


def select_rows(rows: list[dict], queries: dict, labels: dict,
                split: str | None = None, only: set[str] | None = None) -> list[dict]:
    """라벨 대상 행. rep 필드가 있으면 rep==1, 오류 행, 이미 라벨 있는 건 제외."""
    out = []
    for r in rows:
        if "error" in r or r.get("rep", 1) != 1 or r["id"] in labels:
            continue
        if only and r["id"] not in only:
            continue
        if split and queries.get(r["id"], {}).get("split") != split:
            continue
        out.append(r)
    return out


def ask(prompt: str, valid: str, input_fn=input) -> str:
    while True:
        k = input_fn(prompt).strip().lower()
        if k and k in valid:
            return k


def main(argv=None, input_fn=input, *, base_path: Path = BASE, labels_path: Path = LABELS_PATH,
         queries_path: Path = QY):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout"])
    ap.add_argument("--only", help="쉼표로 구분한 id (예: Q01,Q02)")
    args = ap.parse_args(argv)

    if not Path(base_path).exists():
        raise SystemExit("results/base_latest.json 이 없습니다. base 측정을 먼저 하세요.")
    qs = yaml.safe_load(Path(queries_path).read_text(encoding="utf-8"))["queries"]
    queries = {q["id"]: q for q in qs}
    legacy = [q["id"] for q in qs if q.get("human_label") in ("Pass", "Fail")]
    if legacy:
        print(f"경고: queries.yaml 에 옛 human_label 값이 {len(legacy)}건 남아 있음 ({', '.join(legacy)}). "
              "새 방식은 지표별 라벨이라 자동 이전하지 않는다 — 이 값은 사용되지 않는다.\n")

    labels = load_human(labels_path)["labels"]
    rows = json.loads(Path(base_path).read_text(encoding="utf-8"))["rows"]
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    todo = select_rows(rows, queries, labels, args.split, only)
    print(f"라벨 대상 {len(todo)}건 (이미 라벨 {len(labels)}건은 수정하지 않음). "
          "p=Pass f=Fail s=건너뜀 u=이 건 다시 q=종료\n")

    quit_ = False
    for i, r in enumerate(todo, 1):
        if quit_:
            break
        q = queries.get(r["id"], {})
        print("=" * 100)
        head = f"[{i}/{len(todo)}] {r['id']}  ({r.get('category', '?')})"
        if q.get("split"):
            head += f"  split={q['split']}"
        print(f"{head}  경로={r.get('route')}")
        print(f"질의\n{wrap(r['query'])}")
        if q.get("expect_behavior"):
            print(f"기대 행동\n{wrap(q['expect_behavior'])}")
        print(f"근거 (write 가 받은 내용)\n{wrap((r.get('context') or '')[:1500])}")
        print(f"답변\n{wrap(r['answer'])}")
        print()
        while True:   # u 로 이 건 지표를 처음부터 다시 매길 수 있다
            verdicts, action = {}, None
            for m in METRICS:
                k = ask(f"[{KO_NAME[m]}] {CRITERIA[m]}\n  p/f/s/u/q > ", "pfsuq", input_fn)
                if k in ("s", "u", "q"):
                    action = k
                    break
                verdicts[m] = "Pass" if k == "p" else "Fail"
            if action == "u":
                print("  이 건 지표를 처음부터 다시 매깁니다.")
                continue
            if action == "q":
                quit_ = True
            if action is None:
                labels[r["id"]] = make_entry(verdicts, r["answer"])
                save_labels(labels_path, labels)   # 매 건 저장
                print(f"  저장: {r['id']} overall={labels[r['id']]['overall']}")
            break   # s/q 는 이 건을 저장하지 않는다
    print(f"\n라벨 완료 {len(labels)}건. 일치도: .venv/bin/python -m eval.agreement")


if __name__ == "__main__":
    main()
