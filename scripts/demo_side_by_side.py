"""발표 시연 — 같은 장애 질문을 base 와 final 에 동시에 넣고 나란히 보여준다.

    .venv/bin/python scripts/demo_side_by_side.py "DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요."
    .venv/bin/python scripts/demo_side_by_side.py --id Q01        # 평가셋 질의로

화면에 보이는 것: 고른 런북, 답변, 지연, 비용, 재작성 횟수, 근거에 없는 수치.
결과는 results/raw/demo_<시각>.json 에도 남긴다 (발표 캡처의 근거).

API 없이 저장된 JSON 으로 README 그림(docs/figures/fig10_demo.png)만 다시 그리기:

    .venv/bin/python scripts/demo_side_by_side.py --render results/raw/demo_20261021_114804.json
"""
from __future__ import annotations

import argparse
import json
import re
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


# ── README 그림 (fig10) ─────────────────────────────────────────────────
# 저장된 demo JSON 만 읽는다. 숫자·매뉴얼명은 모두 JSON 값에서 계산한다.
# 답 요약은 원문에서 "단어를 잘라내기만" 한다: 아래 조각은 모두 원문 답의 부분 문자열이어야 하고
# (render 시 검사), 하나라도 원문에 없으면 그 구성은 원문 전체를 그대로 보여준다.
SUMMARY = {
    "base": [
        ["p95 지연시간이 2.4초로 임계치(1.0초)를 초과하고,", "커넥션 풀 사용률이 92%"],
        ["풀 크기를 늘리거나 느린 쿼리/외부 호출에 타임아웃을 설정합니다."],
        ["캐시 계층 또는 읽기 복제본으로 트래픽을 분산합니다."],
        ["느린 쿼리 로그를 분석하여 근본 원인을 문서화하고 후속 최적화 티켓을 등록합니다."],
    ],
    "final": [
        ["DB 프라이머리가 다운된 상황을 인지하고,", "auth-service의 상태가 degraded임을 확인한다."],
        ["커넥션 풀 상태를 점검하고,", "필요 시 failover 노드로 전환한다."],
        ["서비스 정상화 후 원인 분석과 재발 방지 대책을 문서화한다."],
    ],
}
# 강조할 핵심 조치 (원문 그대로의 구절). 원문에 있을 때만 강조한다.
KEY_PHRASE = {"base": "풀 크기를 늘리거나 느린 쿼리/외부 호출에 타임아웃을 설정합니다.",
              "final": "failover 노드로 전환한다."}
# 한 줄 해석. 근거 구절이 원문 답에 있을 때만 붙인다.
NOTE = {"base": ("타임아웃", "DB가 죽었는데, 응답 지연 대응 절차를 안내"),
        "final": ("failover", "DB 장애 핵심 조치(failover 전환)를 안내")}


def _font_path() -> str:
    for p in ("/System/Library/Fonts/AppleSDGothicNeo.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(p).exists():
            return p
    from matplotlib import font_manager
    return font_manager.findfont("Apple SD Gothic Neo")


def _runbook_titles(context: str) -> list[str]:
    """context 의 '# Runbook: 응답 지연(High Latency) 대응 절차' → '응답 지연'."""
    out = []
    for t in re.findall(r"# Runbook: (.+?) 대응 절차", context):
        out.append(re.sub(r"\s*\(.*?\)", "", t).strip())
    return out


def _steps(key: str, answer: str) -> tuple[list[list[str]], bool]:
    frags = SUMMARY.get(key)
    if frags and all(f in answer for step in frags for f in step):
        return frags, True
    lines = [re.sub(r"^\d+\)\s*", "", ln.strip()) for ln in answer.splitlines() if ln.strip()]
    return [[ln] for ln in lines], False


def render_png(D: dict, out: Path, src: str, left: str = "base", right: str = "final") -> None:
    from PIL import Image, ImageDraw, ImageFont

    fp = _font_path()
    bold_idx, reg_idx = (6, 0) if fp.endswith("AppleSDGothicNeo.ttc") else (0, 0)

    def F(size, bold=False):
        return ImageFont.truetype(fp, size, index=bold_idx if bold else reg_idx)

    SURF, INK, INK2, LINE = "#fcfcfb", "#111111", "#45443f", "#dcdad3"
    THEME = {  # (진한 색, 연한 배경, 강조 배경)
        False: ("#c2410c", "#fdf3ee", "#fbd9c8"),
        True: ("#1d5fb8", "#eef4fc", "#cfe2fb"),
    }
    W, M, GAP = 2000, 64, 48
    CW = (W - 2 * M - GAP) // 2
    PAD = 40
    gold = set(D.get("gold") or [])

    def text_w(s, f):
        return f.getlength(s)

    def wrap_runs(runs, width, f_reg, f_bold):
        """runs: [(text, emph)] → 줄 목록 [[(word, emph), ...], ...] (공백 기준 줄바꿈)."""
        words = []
        for t, e in runs:
            for w in t.split(" "):
                if w:
                    words.append((w, e))
        lines, cur, cw = [], [], 0.0
        sp = text_w(" ", f_reg)
        for w, e in words:
            ww = text_w(w, f_bold if e else f_reg)
            add = ww if not cur else sp + ww
            if cur and cw + add > width:
                lines.append(cur)
                cur, cw = [(w, e)], ww
            else:
                cur.append((w, e))
                cw += add
        if cur:
            lines.append(cur)
        return lines

    def draw_icon(d, cx, cy, r, ok, col):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white")
        lw = max(4, r // 4)
        if ok:
            d.line([(cx - r * .45, cy + r * .02), (cx - r * .1, cy + r * .38), (cx + r * .5, cy - r * .35)],
                   fill=col, width=lw, joint="curve")
        else:
            k = r * .38
            d.line([(cx - k, cy - k), (cx + k, cy + k)], fill=col, width=lw)
            d.line([(cx - k, cy + k), (cx + k, cy - k)], fill=col, width=lw)

    def chip(d, x, y, label, sub, fg, bg, f1, f2, draw=True):
        w = 24 + text_w(label, f1) + (14 + text_w(sub, f2) if sub else 0) + 24
        h = 56
        if draw:
            d.rounded_rectangle([x, y, x + w, y + h], radius=28, fill=bg)
            d.text((x + 24, y + h / 2), label, font=f1, fill=fg, anchor="lm")
            if sub:
                d.text((x + 24 + text_w(label, f1) + 14, y + h / 2), sub, font=f2, fill=INK2, anchor="lm")
        return w, h

    cost = {k: D[k]["cost_usd"] for k in (left, right)}

    def column(d, key, name, x, y0, height=None, draw=True):
        r = D[key]
        fed = r["fed_runbooks"]
        ok = bool(gold & set(fed))
        dark, light, hl = THEME[ok]
        if draw and height:
            d.rounded_rectangle([x, y0, x + CW, y0 + height], radius=28, fill=light, outline=LINE, width=2)
        ix, iw, y = x + PAD, CW - 2 * PAD, y0 + PAD
        if draw:
            d.text((ix, y), name, font=F(40, True), fill=INK)
        y += 66
        # 판정 배지
        bh = 100
        if draw:
            d.rounded_rectangle([ix, y, ix + iw, y + bh], radius=22, fill=dark)
            draw_icon(d, ix + 56, y + bh / 2, 30, ok, dark)
            d.text((ix + 104, y + bh / 2), "맞는 매뉴얼을 찾음" if ok else "엉뚱한 매뉴얼을 고름",
                   font=F(46, True), fill="white", anchor="lm")
        y += bh + 20
        # 고른 매뉴얼 칩 (매뉴얼 제목은 context 에서 읽음)
        titles = _runbook_titles(r.get("context", ""))
        cx = ix
        for i, rb in enumerate(fed):
            if rb in gold:
                lab, sub, fg, bg = rb, "정답", dark, "white"
            elif ok:
                lab, sub, fg, bg = rb, "함께 들어감", INK2, "white"
            else:
                lab, sub, fg, bg = rb, (titles[i] + " 대응용") if i < len(titles) else "", dark, "white"
            w, h = chip(d, cx, y, lab, sub, fg, bg, F(32, True), F(30), draw)
            cx += w + 14
        y += 56 + 22
        # 한 줄 해석
        note = NOTE.get(key)
        if note and note[0] in r["answer"]:
            if draw:
                d.rectangle([ix, y + 4, ix + 8, y + 46], fill=dark)
                d.text((ix + 24, y + 25), note[1], font=F(34, True), fill=INK, anchor="lm")
            y += 50 + 26
        # 숫자 3칸
        sw = (iw - 2 * 16) / 3
        stats = [("걸린 시간", f"{r['latency_ms'] / 1000:.1f}초", None),
                 ("비용", f"${r['cost_usd']:.5f}", None),
                 ("재작성", f"{r['rewrites']}회", None)]
        if key == right and cost[left] > 0 and cost[right] < cost[left]:
            frac = round(cost[left] / cost[right])
            if frac >= 2:
                stats[1] = (stats[1][0], stats[1][1], f"원본의 약 {frac}분의 1")
        sh = 150
        for i, (lab, val, tag) in enumerate(stats):
            sx = ix + i * (sw + 16)
            if draw:
                d.rounded_rectangle([sx, y, sx + sw, y + sh], radius=18, fill="white", outline=LINE, width=2)
                d.text((sx + 22, y + 20), lab, font=F(28), fill=INK2)
                d.text((sx + 22, y + 58), val, font=F(44, True), fill=INK)
                if tag:
                    d.text((sx + 22, y + 110), tag, font=F(26, True), fill=dark)
        y += sh + 36
        # 답 요약
        steps, cut = _steps(key, r["answer"])
        head = "답 요약 (원문에서 단어만 덜어냄)" if cut else "답 원문"
        if draw:
            d.text((ix, y), head, font=F(28, True), fill=INK2)
        y += 48
        fr, fb = F(34), F(34, True)
        kp = KEY_PHRASE.get(key) if KEY_PHRASE.get(key, "") in r["answer"] else None
        lh = 52
        for n, frags in enumerate(steps, 1):
            text = " … ".join(frags)
            runs = [(text, False)]
            if kp and kp in text:
                a, b = text.split(kp, 1)
                runs = [(a, False), (kp, True), (b, False)]
            num = f"{n}"
            nx = ix + 52
            lines = wrap_runs(runs, iw - 52, fr, fb)
            if draw:
                d.ellipse([ix, y + 4, ix + 38, y + 42], fill=dark)
                d.text((ix + 19, y + 23), num, font=F(24, True), fill="white", anchor="mm")
            for ln in lines:
                px = nx
                sp = text_w(" ", fr)
                for j, (w, e) in enumerate(ln):
                    f = fb if e else fr
                    ww = text_w(w, f)
                    if draw:
                        if e:
                            nxt = j + 1 < len(ln) and ln[j + 1][1]
                            d.rectangle([px - 4, y + 2, px + ww + (sp if nxt else 4), y + lh - 4], fill=hl)
                        d.text((px, y + lh / 2 - 2), w, font=f, fill=INK, anchor="lm")
                    px += ww + sp
                y += lh
            y += 16
        return y + PAD - 16 - y0

    # 1차: 높이 측정
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    names = {left: "원본 (base)" if left == "base" else left, right: "최종 (final)" if right == "final" else right}
    ch = max(column(probe, k, names[k], 0, 0, draw=False) for k in (left, right))

    top_title, top_q = M, M + 92
    qh = 120
    col_y = top_q + qh + 40
    H = col_y + ch + 100
    img = Image.new("RGB", (W, H), SURF)
    d = ImageDraw.Draw(img)
    d.text((M, top_title), "실행 결과: 같은 질문, 원본과 최종의 답", font=F(54, True), fill=INK)
    # 질문 카드
    d.rounded_rectangle([M, top_q, W - M, top_q + qh], radius=24, fill="#f1f0ec", outline=LINE, width=2)
    d.text((M + 36, top_q + qh / 2), "질문", font=F(30, True), fill=INK2, anchor="lm")
    d.text((M + 120, top_q + qh / 2), f"“{D['query']}”", font=F(42, True), fill=INK, anchor="lm")
    if gold:
        g = "정답 매뉴얼: " + ", ".join(D["gold"])
        gw = text_w(g, F(32, True)) + 48
        gx = W - M - 32 - gw
        d.rounded_rectangle([gx, top_q + qh / 2 - 30, gx + gw, top_q + qh / 2 + 30], radius=30,
                            fill="white", outline=THEME[True][0], width=3)
        d.text((gx + gw / 2, top_q + qh / 2), g, font=F(32, True), fill=THEME[True][0], anchor="mm")
    for i, k in enumerate((left, right)):
        column(d, k, names[k], M + i * (CW + GAP), col_y, height=ch)
    foot = f"출처: {src} · scripts/demo_side_by_side.py (실제 API, 1회 실행)"
    if cost[right] > 0:
        foot += f" · 비용 비율 {cost[left]:.5f} ÷ {cost[right]:.5f} = {cost[left] / cost[right]:.1f}"
    d.text((M, H - 60), foot, font=F(28), fill=INK2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--id")
    ap.add_argument("--left", default="base")
    ap.add_argument("--right", default="final")
    ap.add_argument("--render", metavar="JSON", help="API 호출 없이 저장된 demo JSON 으로 그림만 그린다")
    ap.add_argument("--out", default=str(ROOT / "docs/figures/fig10_demo.png"))
    args = ap.parse_args()
    if args.render:
        src = Path(args.render).resolve()
        render_png(json.loads(src.read_text()), Path(args.out), src.relative_to(ROOT).as_posix())
        print(f"저장: {args.out}")
        return

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
