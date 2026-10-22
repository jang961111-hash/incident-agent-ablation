"""PROGRESS.md 를 터미널용으로 읽기 좋게 그린다.

    python scripts/board.py           # 한 번 출력
    python scripts/board.py --watch   # 3초마다 다시 그림 (Ctrl-C로 종료)
"""
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "PROGRESS.md"
DEADLINE = datetime(2026, 10, 22, 13, 0)
LOG_LINES = 5

C = {"완료": "\033[32m", "진행": "\033[33;1m", "대기": "\033[90m", "병헌": "\033[36;1m"}
DIM, BOLD, RESET = "\033[90m", "\033[1m", "\033[0m"


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def fit(s: str, w: int) -> str:
    """표시 폭 w에 맞춰 자르거나 공백으로 채운다 (한글 2칸 계산)."""
    if width(s) <= w:
        return s + " " * (w - width(s))
    out, used = "", 0
    for ch in s:
        if used + width(ch) > w - 1:   # 말줄임표 1칸 남김
            break
        out, used = out + ch, used + width(ch)
    return out + "…" + " " * (w - used - 1)


def parse(text: str):
    steps, logs, todo, section = [], [], [], None
    updated = re.search(r"갱신:\s*(.+)", text)
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section == "단계" and re.match(r"\|\s*\d+", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            steps.append(cells + [""] * (4 - len(cells)))
        elif section == "작업 로그" and line.startswith("- "):
            logs.append(line[2:])
        elif section and section.startswith("병헌") and re.match(r"\d+\.", line):
            todo.append(line)
    return (updated.group(1) if updated else "-"), steps, logs, todo


def render() -> str:
    cols = min(shutil.get_terminal_size((100, 30)).columns, 110)
    updated, steps, logs, todo = parse(SRC.read_text(encoding="utf-8"))
    left = DEADLINE - datetime.now()
    h, m = divmod(max(int(left.total_seconds()), 0) // 60, 60)
    done = sum(1 for s in steps if s[2] == "완료")

    lines = [f"{BOLD}과제1 Ablation{RESET}  {done}/{len(steps)} 완료"
             f"   {DIM}갱신 {updated}, 마감까지 {h}시간 {m}분{RESET}", ""]
    name_w = 24
    for num, name, status, memo in steps:
        tag = f"{C.get(status, '')}{fit(status, 4)}{RESET}"
        memo_w = max(cols - name_w - 12, 10)
        lines.append(f" {tag}  {fit(num, 2)} {fit(name, name_w)} {DIM}{fit(memo, memo_w).rstrip()}{RESET}")
    lines += ["", f"{BOLD}최근 작업{RESET}"]
    lines += [f" {fit(l, cols - 2).rstrip()}" for l in logs[:LOG_LINES]]
    if todo:
        lines += ["", f"{C['병헌']}병헌 님이 할 일{RESET}"]
        lines += [f" {fit(t.replace('`', ''), cols - 2).rstrip()}" for t in todo]
    return "\n".join(lines)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        try:
            while True:
                sys.stdout.write("\033[2J\033[H" + render() + "\n")
                sys.stdout.flush()
                time.sleep(3)
        except KeyboardInterrupt:
            pass
    else:
        print(render())
