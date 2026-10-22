"""설명용 그림: 모든 수치를 results/ 에서 읽어 docs/figures/*.png 로 그린다.

    .venv/bin/python scripts/make_figs.py

색: 파랑 = 개선(강조), 주황 = 문제·원본, 회색 = 나머지. 글자는 무채색. 값은 막대 위에 직접 표시.
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.extra_metrics import load_all  # noqa: E402

R = ROOT / "results"
OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
BLUE, ORANGE, GRAY, AQUA = "#2a78d6", "#eb6834", "#b4b2a9", "#1baf7a"
plt.rcParams.update({"font.family": "Apple SD Gothic Neo", "font.size": 12, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
                     "axes.unicode_minus": False})

ORDER = ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]
LABEL = {"base": "원본\n(base)", "rag": "+RAG", "judge": "+Judge만", "rag_judge": "RAG\n+Judge",
         "rag_judge_cost": "+비용\n절감", "rag_judge_v2": "+v2\n보완", "final": "최종\n(final)"}
H = {n: json.loads((R / f"{n}_latest.json").read_text())["summary"]["by_split"]["holdout"]["mean"] for n in ORDER}
X = load_all("holdout")


def frame(ax, title, sub):
    ax.set_title(title, loc="left", fontsize=15, color=INK, pad=26, fontweight="bold")
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=10.5, color=INK2, va="bottom")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(left=False)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def bars(name, title, sub, vals, fmt, colors, ylim=None):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    xs = range(len(ORDER))
    b = ax.bar(xs, vals, width=0.58, color=colors, edgecolor=SURF, linewidth=2)
    for rect, v in zip(b, vals):
        ax.text(rect.get_x() + rect.get_width() / 2, rect.get_height(), fmt(v), ha="center", va="bottom",
                fontsize=11, color=INK, fontweight="bold")
    ax.set_xticks(list(xs), [LABEL[n] for n in ORDER])
    ax.set_yticks([])
    if ylim:
        ax.set_ylim(*ylim)
    frame(ax, title, sub)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=180)
    plt.close(fig)


def color_by(good):
    return [ORANGE if n == "base" else (BLUE if n in good else GRAY) for n in ORDER]


# 1. 에이전트가 하는 일 (흐름도) — 개선이 들어간 자리 표시
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.set_xlim(0, 10)
ax.set_ylim(0, 3.4)
ax.axis("off")
steps = [("질문 받기", "당직자 질문", GRAY), ("상황판 확인", "모니터링 수치", GRAY),
         ("매뉴얼 고르기", "RAG로 교체 · v2", BLUE), ("답변 쓰기", "저가 초안 먼저", BLUE),
         ("답변 검사", "AI 채점관 · v2", BLUE)]
for i, (h, s, c) in enumerate(steps):
    x = 0.15 + i * 1.98
    ax.add_patch(FancyBboxPatch((x, 1.15), 1.7, 1.25, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=c if c != GRAY else "#f1efe8", ec=c, lw=1.2, alpha=0.18 if c != GRAY else 1))
    ax.text(x + 0.85, 2.0, h, ha="center", va="center", fontsize=13, color=INK, fontweight="bold")
    ax.text(x + 0.85, 1.55, s, ha="center", va="center", fontsize=10.5, color=INK2)
    if i < 4:
        ax.annotate("", xy=(x + 1.95, 1.78), xytext=(x + 1.72, 1.78),
                    arrowprops=dict(arrowstyle="->", color=INK2, lw=1.2))
ax.text(0.15, 3.05, "AI 에이전트가 하는 일과, 이번에 바꾼 곳 (파란 칸)", fontsize=15, color=INK, fontweight="bold")
ax.text(0.15, 0.55, "원본 코드는 그대로 두고, 파란 칸만 스위치로 켜고 끄며 효과를 쟀다", fontsize=11, color=INK2)
fig.savefig(OUT / "fig1_flow.png", dpi=180, bbox_inches="tight")
plt.close(fig)

# 2. 편향 검증 — 원본은 질문 표현에 좌우된다
fig, ax = plt.subplots(figsize=(8, 4.4))
groups = ["알림 문구대로 물을 때", "자기 말로 물을 때"]
bv = [X["base"]["recall@1[aligned]"], X["base"]["recall@1[paraphrased]"]]
rv = [X["rag"]["recall@1[aligned]"], X["rag"]["recall@1[paraphrased]"]]
w = 0.32
for i, (vals, c, lab) in enumerate(((bv, ORANGE, "원본 (키워드 규칙)"), (rv, BLUE, "RAG (질문 의미로 검색)"))):
    xs = [g + (i - 0.5) * (w + 0.04) for g in range(2)]
    bb = ax.bar(xs, vals, width=w, color=c, edgecolor=SURF, linewidth=2, label=lab)
    for rect, v in zip(bb, vals):
        ax.text(rect.get_x() + w / 2, v, f"{round(v * 100)}%", ha="center", va="bottom", fontsize=11, color=INK, fontweight="bold")
ax.set_xticks([0, 1], groups)
ax.set_yticks([])
ax.set_ylim(0, 1.15)
ax.legend(frameon=False, loc="upper right", fontsize=10.5)
frame(ax, "원본은 '알림 문구 그대로' 물을 때 주로 맞는 매뉴얼을 찾는다",
      "맞는 매뉴얼을 1순위로 고른 비율 · 조정에 안 쓴 holdout 정상 질의, 3회 평균")
fig.tight_layout()
fig.savefig(OUT / "fig2_bias.png", dpi=180)
plt.close(fig)

# 3. 정답 런북 누락 / 4. 무관 런북 혼입
bars("fig3_miss.png", "맞는 매뉴얼을 놓치는 비율: RAG가 크게 줄였다",
     "정답 런북을 근거에 못 넣은 비율 (낮을수록 좋음) · holdout, 3회 평균",
     [X[n]["miss_runbook_rate"] for n in ORDER], lambda v: f"{round(v * 100)}%",
     color_by({"rag", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"}), (0, 0.7))
bars("fig4_wrong.png", "엉뚱한 매뉴얼이 섞이는 비율: v2 보완이 줄였다",
     "질문과 무관한 런북이 근거에 섞인 비율 (낮을수록 좋음) · holdout, 3회 평균",
     [X[n]["wrong_runbook_rate"] for n in ORDER], lambda v: f"{round(v * 100)}%",
     color_by({"rag_judge_v2", "final"}), (0, 0.8))

# 5. 비용
bars("fig5_cost.png", "장애 1건 처리 비용: 최종 구성이 가장 싸다",
     "OpenAI 공개 단가 x 실측 토큰 (USD, 추정) · holdout, 3회 평균",
     [X[n]["cost_per_incident"] for n in ORDER], lambda v: f"${v:.4f}",
     color_by({"rag_judge_cost", "final"}), None)

# 6. 기여도 — 같은 질문끼리 비교한 차이와 95% 신뢰구간 (정답 누락 · 엉뚱한 매뉴얼 혼입)
st = json.loads((R / "stats_holdout.json").read_text())["pairs"]
fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True)
ys = list(range(len(st)))[::-1]
lo_all = min(min(p[k]["lo"] for p in st) for k in ("miss", "wrong")) * 100
hi_all = max(max(p[k]["hi"] for p in st) for k in ("miss", "wrong")) * 100
XL = (min(lo_all, 0) - 8, max(hi_all, 0) + 28)   # 두 패널 같은 눈금, 오른쪽은 글자 자리
for ax, key, ptitle in ((axes[0], "miss", "① 맞는 매뉴얼 누락"), (axes[1], "wrong", "② 엉뚱한 매뉴얼 혼입")):
    ax.axvspan(XL[0], 0, color=BLUE, alpha=0.06, lw=0)
    ax.axvspan(0, XL[1], color=ORANGE, alpha=0.06, lw=0)
    ax.text(XL[0] + 1.5, len(st) - 0.35, "← 좋아짐", fontsize=11, color=BLUE, fontweight="bold", va="center")
    ax.text(XL[1] - 1.5, len(st) - 0.35, "나빠짐 →", fontsize=11, color=ORANGE, fontweight="bold", va="center", ha="right")
    for y, p in zip(ys, st):
        r = p[key]
        d = round(r["diff"] * 100)
        c = BLUE if r["significant"] and r["diff"] < 0 else (ORANGE if r["significant"] else GRAY)
        ax.plot([r["lo"] * 100, r["hi"] * 100], [y, y], color=c, lw=4 if r["significant"] else 3, solid_capstyle="round")
        ax.plot(r["diff"] * 100, y, "o", color=c if r["significant"] else SURF, ms=10, mec=c if not r["significant"] else SURF,
                mew=2)
        if r["significant"]:
            lab, kw = f"{d:+d}%p 효과 확인", dict(color=c, fontweight="bold", fontsize=12)
        elif d == 0 and r["lo"] <= 0 <= r["hi"]:
            lab, kw = "변화 없음", dict(color=INK2, fontsize=11)
        else:
            lab, kw = f"{d:+d}%p (불확실)", dict(color=INK2, fontsize=11)
        ax.text(max(r["hi"] * 100, 0) + 3, y, lab, va="center", **kw)
    ax.axvline(0, color=INK2, lw=1.2)
    ax.set_xlim(*XL)
    ax.set_ylim(-0.6, len(st) - 0.1)
    ax.set_title(ptitle, loc="left", fontsize=14, color=INK, fontweight="bold", pad=10)
    ax.set_xlabel("변화 (%p) · 왼쪽일수록 좋아짐", fontsize=11.5)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(left=False, labelsize=11)
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
axes[0].set_yticks(ys, [p["label"] for p in st], fontsize=13, color=INK)
fig.suptitle("어떤 개선이 효과였나: 같은 질문끼리 짝지어 비교", x=0.01, ha="left", fontsize=16, color=INK, fontweight="bold")
fig.text(0.01, 0.905, "점 = 평균 변화, 막대 = 95% 신뢰구간(진짜 효과가 있을 법한 범위). "
         "막대가 0선에 닿지 않으면 '효과 확인'. holdout 36문제 × 3회", fontsize=11, color=INK2)
fig.tight_layout(rect=(0, 0, 1, 0.9))
fig.savefig(OUT / "fig6_contrib.png", dpi=180)
plt.close(fig)

# 7. 동시성 (실제 API)
cc = json.loads((R / "concurrency_bench_latest.json").read_text())
ns = sorted({r["n"] for r in cc["runs"]})
fig, ax = plt.subplots(figsize=(8, 4.4))
for a, c, lab in ((False, ORANGE, "원본 방식 (동기)"), (True, BLUE, "비동기 I/O")):
    ws = [next(r["wall_ms"] for r in cc["runs"] if r["n"] == n and r["async_io"] == a) / 1000 for n in ns]
    ax.plot(ns, ws, "-o", color=c, lw=2, ms=8, mec=SURF, mew=2, label=lab)
    ax.text(ns[-1] + 0.3, ws[-1], f"{ws[-1]:.1f}초", va="center", fontsize=11, color=INK, fontweight="bold")
ax.set_xticks(ns, [f"동시 {n}건" for n in ns])
ax.set_xlim(0.5, ns[-1] + 1.8)
ax.set_ylabel("모두 끝날 때까지 걸린 시간 (초)")
ax.legend(frameon=False, loc="upper left", fontsize=10.5)
frame(ax, "장애 질문이 한꺼번에 몰려도 버틴다", "동시 요청 N건 처리 시간 · 실제 OpenAI API, 최종 구성(캐시 끔)")
fig.tight_layout()
fig.savefig(OUT / "fig7_concurrency.png", dpi=180)
plt.close(fig)

# 8. 장애 주입 (실제 API)
fb = json.loads((R / "fault_bench_latest.json").read_text())["variants"]
names = [("base", "원본"), ("final_no_tolerance", "최종\n(부분 실패 허용 끔)"), ("final", "최종")]
fig, ax = plt.subplots(figsize=(7.5, 4.2))
vals = [fb[k]["completed_among_faulted"] / fb[k]["queries_with_fault"] for k, _ in names]
bb = ax.bar(range(3), vals, width=0.5, color=[ORANGE, GRAY, BLUE], edgecolor=SURF, linewidth=2)
for i, (k, _) in enumerate(names):
    ax.text(i, vals[i] + 0.02, f"{fb[k]['completed_among_faulted']}/{fb[k]['queries_with_fault']}건", ha="center",
            fontsize=12, color=INK, fontweight="bold")
ax.set_xticks(range(3), [n for _, n in names])
ax.set_yticks([])
ax.set_ylim(0, 1.15)
frame(ax, "도구 하나가 고장나도 끝까지 답한다", "모니터링 호출 30%를 일부러 실패시켰을 때, 고장을 맞은 질문 중 답을 끝낸 수 · 실제 API")
fig.tight_layout()
fig.savefig(OUT / "fig8_fault.png", dpi=180)
plt.close(fig)

# 9. AI 채점관이 후하다 — Judge 통과율 vs Judge 무관 지표
fig, ax = plt.subplots(figsize=(9, 4.6))
w = 0.36
jv = [H[n]["pass_rate"] for n in ORDER]
mv = [H[n]["must_phrase_rate"] for n in ORDER]
for i, (vals, c, lab) in enumerate(((jv, GRAY, "AI 채점관 통과율"), (mv, BLUE, "매뉴얼 핵심 문구가 답에 들어간 비율 (코드로 셈)"))):
    xs = [g + (i - 0.5) * (w + 0.03) for g in range(len(ORDER))]
    bb = ax.bar(xs, vals, width=w, color=c, edgecolor=SURF, linewidth=2, label=lab)
    for rect, v in zip(bb, vals):
        ax.text(rect.get_x() + w / 2, v, f"{round(v * 100)}", ha="center", va="bottom", fontsize=9.5, color=INK2)
ax.set_xticks(range(len(ORDER)), [LABEL[n] for n in ORDER])
ax.set_yticks([])
ax.set_ylim(0, 1.18)
ax.legend(frameon=False, loc="upper left", fontsize=10, ncol=2)
frame(ax, "AI 채점관은 후하다: 그래서 코드로 센 지표를 함께 봤다", "holdout, 3회 평균 (%)")
fig.tight_layout()
fig.savefig(OUT / "fig9_judge.png", dpi=180)
plt.close(fig)

# 10·11. 실행 결과 화면 — 같은 질문에 원본과 최종이 낸 답 (results/demo/*.json, 실제 API 1회 실행 기록)
# 그리는 코드는 scripts/demo_side_by_side.py 의 render_png 하나뿐이다 (--render 로도 같은 그림).
sys.path.insert(0, str(ROOT / "scripts"))
from demo_side_by_side import render_png  # noqa: E402
# 입력은 커밋된 고정 경로 (results/raw 는 git 에 없고, 리허설 기록이 덮어쓰면 안 된다)
for demo_path, fig in ((R / "demo" / "demo_q01_20261021_114804.json", "fig10_demo.png"),
                       (R / "demo" / "demo_q19_20261022_134437.json", "fig11_demo_noRunbook.png")):
    render_png(json.loads(demo_path.read_text()), OUT / fig, demo_path.relative_to(ROOT).as_posix())

print("wrote", sorted(p.name for p in OUT.glob("*.png")))
