"""base 답변에 사람 라벨(Pass/Fail)을 매긴다. Judge 일치율의 기준이 된다.

    .venv/bin/python scripts/label.py           # 아직 라벨 없는 건만
    .venv/bin/python scripts/label.py --all     # 전부 다시 보기 (이미 매긴 라벨은 덮어쓰지 않음)

판정이 흔들리지 않도록 Judge 판정·점수는 보여주지 않는다 (블라인드).
기준은 Judge 와 같은 4지표: 묻는 것에 답했나 / 근거에 없는 걸 지어냈나 /
런북 절차를 반영했나 / 요청 형식을 지켰나. 3개 이상 만족이면 Pass.

입력: p = Pass, f = Fail, s = 건너뜀, q = 저장 후 종료
결과는 eval/queries.yaml 의 해당 id human_label: 줄에 바로 기록된다.
"""
import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QY = ROOT / "eval" / "queries.yaml"
BASE = ROOT / "results" / "base_latest.json"


def set_label(text: str, qid: str, label: str) -> str:
    """'- id: Qxx' 블록 안의 첫 human_label 줄만 바꾼다. 다른 서식·주석은 그대로 둔다."""
    pat = re.compile(rf"(- id: {qid}\n(?:(?!\s*- id:).*\n)*?\s*human_label:)\s*\S+")
    new, n = pat.subn(rf"\1 {label}", text, count=1)
    if n != 1:
        raise SystemExit(f"{qid} 의 human_label 줄을 찾지 못함")
    return new


def wrap(s: str, indent: str = "    ") -> str:
    return "\n".join(textwrap.fill(line, 96, initial_indent=indent, subsequent_indent=indent)
                     or indent for line in s.splitlines())


def main():
    if not BASE.exists():
        raise SystemExit("results/base_latest.json 이 없습니다. base 측정을 먼저 하세요.")
    import yaml
    queries = {q["id"]: q for q in yaml.safe_load(QY.read_text())["queries"]}
    rows = json.loads(BASE.read_text())["rows"]
    todo = [r for r in rows if "error" not in r and
            ("--all" in sys.argv or queries[r["id"]].get("human_label") not in ("Pass", "Fail"))]
    print(f"라벨 대상 {len(todo)}건. p=Pass f=Fail s=건너뜀 q=종료\n")

    text = QY.read_text()
    for i, r in enumerate(todo, 1):
        q = queries[r["id"]]
        if q.get("human_label") in ("Pass", "Fail"):
            print(f"[{r['id']}] 이미 {q['human_label']} — 건너뜀 (라벨은 수정하지 않는다)")
            continue
        print("=" * 100)
        print(f"[{i}/{len(todo)}] {r['id']}  ({r['category']})  경로={r['route']}")
        print(f"질의\n{wrap(r['query'])}")
        if q.get("expect_behavior"):
            print(f"기대 행동\n{wrap(q['expect_behavior'])}")
        print(f"근거 (write 가 받은 내용)\n{wrap(r['context'][:1500])}")
        print(f"답변\n{wrap(r['answer'])}")
        while True:
            k = input("판정 [p/f/s/q] > ").strip().lower()
            if k in ("p", "f", "s", "q"):
                break
        if k == "q":
            break
        if k == "s":
            continue
        text = set_label(text, r["id"], "Pass" if k == "p" else "Fail")
        QY.write_text(text)   # 매 건 저장 — 중간에 끊겨도 잃지 않는다
    done = sum(1 for q in yaml.safe_load(QY.read_text())["queries"]
               if q.get("human_label") in ("Pass", "Fail"))
    print(f"\n라벨 완료 {done}/{len(queries)}건. 일치율: .venv/bin/python -m eval.report")


if __name__ == "__main__":
    main()
