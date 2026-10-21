"""발표 시연 — 같은 장애 질문을 base 와 final 에 동시에 넣고 나란히 보여준다.

    .venv/bin/python scripts/demo_side_by_side.py "DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요."
    .venv/bin/python scripts/demo_side_by_side.py --id Q01        # 평가셋 질의로

화면에 보이는 것: 고른 런북, 답변, 지연, 비용, 재작성 횟수, 근거에 없는 수치.
결과는 results/raw/demo_<시각>.json 에도 남긴다 (발표 캡처의 근거).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

BOLD, DIM, RED, GRN, RST = "\033[1m", "\033[90m", "\033[31m", "\033[32m", "\033[0m"


def dw(s: str) -> int:
    """터미널 표시 폭 (한글 2칸, 색 코드 0칸)."""
    import re
    import unicodedata
    s = re.sub(r"\033\[[0-9;]*m", "", s)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def wrap(text: str, w: int) -> list[str]:
    out = []
    for para in text.splitlines() or [""]:
        line = ""
        for ch in para:
            if dw(line + ch) > w:
                out.append(line)
                line = ""
            line += ch
        out.append(line)
    return out


def run(name: str, query: str) -> dict:
    from src.adapter import run_once
    cfg = yaml.safe_load((ROOT / f"eval/configs/{name}.yaml").read_text())
    return run_once(query, cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--id")
    ap.add_argument("--left", default="base")
    ap.add_argument("--right", default="final")
    args = ap.parse_args()

    qs = {q["id"]: q for q in yaml.safe_load((ROOT / "eval/queries.yaml").read_text())["queries"]}
    gold = []
    if args.id:
        query, gold = qs[args.id]["query"], qs[args.id]["gold_runbooks"]
    elif args.query:
        query = args.query
    else:
        ap.error("질문 문장 또는 --id 가 필요합니다")

    from ext.factcheck import check
    with ThreadPoolExecutor(2) as ex:   # 두 구성을 동시에 실행
        fl, fr = ex.submit(run, args.left, query), ex.submit(run, args.right, query)
        out = {args.left: fl.result(), args.right: fr.result()}

    w = max(min(shutil.get_terminal_size((160, 40)).columns // 2 - 3, 80), 40)
    print(f"\n{BOLD}질문{RST} {query}" + (f"   {DIM}정답 런북 {gold}{RST}" if gold else ""))
    cols = []
    for name, o in out.items():
        fed = o["fed_runbooks"]
        mark = ""
        if gold:
            mark = f" {GRN}정답{RST}" if set(gold) & set(fed) else f" {RED}오답{RST}"
        fc = check(o["answer"], o["context"])
        head = [f"{BOLD}[{name}]{RST}",
                f"런북   {fed or '없음'}{mark}",
                f"지연   {o['latency_ms'] / 1000:.1f}초   비용 ${o['cost_usd']:.4f}   재작성 {o['rewrites']}회",
                f"근거 없는 수치 {fc['unsupported'] or '없음'}",
                "─" * w]
        body = wrap(o["answer"], w)
        cols.append(head + body)
    for i in range(max(map(len, cols))):
        left = cols[0][i] if i < len(cols[0]) else ""
        right = cols[1][i] if i < len(cols[1]) else ""
        pad = w - len(left.replace(BOLD, "").replace(RST, "").replace(GRN, "").replace(RED, "").replace(DIM, "")) \
            - sum(1 for ch in left if "가" <= ch <= "힣")   # 한글 2칸 보정
        print(f"{left}{' ' * max(pad, 1)} │ {right}")

    (ROOT / "results/raw").mkdir(parents=True, exist_ok=True)
    p = ROOT / "results/raw" / f"demo_{datetime.now():%Y%m%d_%H%M%S}.json"
    p.write_text(json.dumps({"query": query, "gold": gold, **{k: {kk: v[kk] for kk in
                 ("answer", "fed_runbooks", "latency_ms", "cost_usd", "rewrites", "context")}
                 for k, v in out.items()}}, ensure_ascii=False, indent=1))
    print(f"\n{DIM}저장: {p.relative_to(ROOT)}{RST}")


if __name__ == "__main__":
    main()
