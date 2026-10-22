"""문서에 나온 단위 붙은 수치(%, %p, 초, 배, $)를 모두 뽑아 CLAIMS 와 결과 파일에서 나온 값과 대조한다.

    .venv/bin/python scripts/check_claims.py            # 불일치 목록 출력, 있으면 exit 1
    .venv/bin/python scripts/check_claims.py --show     # 파일별 추출 수치 전체
    .venv/bin/python scripts/check_claims.py --strict   # CI: 못 읽은 문서(덱 등)가 있어도 exit 1

허용 값 = CLAIMS.md 의 값 + README AUTO 표(결과 파일에서 생성) + 구성별 표 값 + 지연 재측정 집계 + 설계 상수.
허용 목록에 없는 수치는 '확인 필요'로 보고한다. 히스토리를 일부러 남긴 줄(철회·처음 측정·부록)은 빼고 본다.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
NUM = re.compile(r"[+\-−]?\$?\d[\d,]*(?:\.\d+)?\s?(?:%p|%|초|배)|\$\d+\.\d+")
# 설계 상수·조건 (결과가 아니라 실험 조건이라 허용)
CONST = {"30%", "-0.05", "0.05", "2.8%p", "100%", "0%", "0%p", "+0%p", "+0.0초", "120초", "300초", "60초", "1.0초", "2.4초", "2초",
         "92%", "90%", "83.6%", "63.8%", "50%", "30%", "20%p", "40%", "1%",
         "10초", "30초", "50초"}   # 마지막 줄: 대본의 말하기 시간 표기
HISTORY = re.compile(r"처음 측정|철회|부하 조건이 달라|처음 보였던|처음엔|처음에는|1차 측정|이전|중간판|최초 판|업체|주장|외부|보도|Uptime|GS리테일|Flow-of-Action|"
                     r"Self-Refine|Zheng|FrugalGPT|DPR|Resolve|Datadog|PagerDuty|incident\.io|AION|LG유플러스|엑셈|와탭|오케스트로|Thakur|Huang|Kamoi|"
                     r"예:|예시|50%에서 30%")


def norm(t: str) -> str:
    return t.replace("−", "-").replace(" ", "").replace(",", "")


def tokens(text: str) -> list[str]:
    return [norm(m.group(0)) for m in NUM.finditer(text)]


def allowed() -> set[str]:
    a = set(map(norm, CONST))
    a |= set(tokens((ROOT / "CLAIMS.md").read_text()))
    readme = (ROOT / "README.md").read_text()
    for blk in re.findall(r"<!-- AUTO:\w+ -->(.*?)<!-- /AUTO:\w+ -->", readme, flags=re.S):
        a |= set(tokens(blk))
    for f in sorted(R.glob("latctl_summary_*.md"))[-1:]:
        a |= set(tokens(f.read_text()))
    # 구성별 표 값 (덱 표·그림에 쓰임)
    sys.path.insert(0, str(ROOT))
    from eval.extra_metrics import load_all
    X = load_all("holdout")
    for n, d in X.items():
        for k in ("miss_runbook_rate", "wrong_runbook_rate"):
            a.add(f"{round(d[k] * 100)}%")
    for n in ["base", "rag", "judge", "rag_judge", "rag_judge_cost", "rag_judge_v2", "final"]:
        h = json.loads((R / f"{n}_latest.json").read_text())["summary"]["by_split"]["holdout"]["mean"]
        for k in ("must_phrase_rate", "pass_rate", "recall@1"):
            a.add(f"{round(h[k] * 100)}%")
        a.add(f"${X[n]['cost_per_incident']:.5f}")
    for p in json.loads((R / "stats_holdout.json").read_text())["pairs"]:   # 덱 기여도 표의 Judge 통과·Recall 열
        for m in ("pass", "hit1", "must", "miss", "wrong"):
            if p[m]:
                a.add(f"{round(p[m]['diff'] * 100):+d}%p")
        if p["cost"]:
            a.add(norm(f"{p['cost']['diff']:+.4f}".replace("+", "+$").replace("-", "-$")))
    cr = json.loads((R / "concurrency_bench_latest.json").read_text())["runs"]
    a |= {f"{r['wall_ms'] / 1000:.1f}초" for r in cr}
    cb = json.loads((R / "cache_bench_latest.json").read_text())["passes"]
    a |= {f"${p['cost_usd']:.4f}" for p in cb}
    a |= {t.lstrip("+-") for t in a}   # 부호 없이 쓴 같은 값 (예: "84% 줄었다", "+1.8~2.7초")
    return a


def deck_text() -> str:
    for cmd in (["markitdown"], [str(ROOT / ".venv/bin/python"), "-m", "markitdown"]):
        try:
            return "\n".join(subprocess.run(cmd + [str(ROOT / f"deck/{f}")], capture_output=True, text=True, check=True).stdout
                             for f in ("incident-agent-ablation.pptx", "incident-agent-ablation_5min.pptx"))
        except Exception:
            continue
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="CI용: 대조할 문서를 하나라도 못 읽으면(빈 텍스트, 예: markitdown 미설치로 덱 누락) 실패")
    a = ap.parse_args(argv)
    ok = allowed()
    docs = {"README.md": (ROOT / "README.md").read_text(),
            "docs/발표/발표_대본_이전안.md": (ROOT / "docs/발표/발표_대본_이전안.md").read_text(),
            "docs/submission_sheet_draft.md": (ROOT / "docs/submission_sheet_draft.md").read_text(),
            "docs/research/00_요약_실태현황.md": (ROOT / "docs/research/00_요약_실태현황.md").read_text(),
            "deck (pptx 2종)": deck_text()}
    for extra in ("docs/sheet_entry.txt",):
        if (ROOT / extra).exists():
            docs[extra] = (ROOT / extra).read_text()
    bad = []
    for name, text in docs.items():
        text = re.sub(r"<!-- AUTO:latency_old -->.*?<!-- /AUTO:latency_old -->", "", text, flags=re.S)
        for ln, line in enumerate(text.splitlines(), 1):
            ts = tokens(line)
            if a.show and ts:
                print(f"{name}:{ln}: {ts}")
            if HISTORY.search(line):
                continue
            for t in ts:
                if t not in ok:
                    bad.append((name, ln, t, line.strip()[:110]))
    for b in bad:
        print(f"확인 필요  {b[0]}:{b[1]}  {b[2]}  | {b[3]}")
    print(f"\n대조 문서 {len(docs)}개, 확인 필요 {len(bad)}건")
    unread = [name for name, text in docs.items() if not text.strip()] if a.strict else []
    for name in unread:
        print(f"읽기 실패  {name}  (--strict: 대조하지 못한 문서는 실패로 본다)")
    sys.exit(1 if bad or unread else 0)


if __name__ == "__main__":
    main()
