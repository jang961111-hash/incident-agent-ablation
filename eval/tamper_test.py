"""근거 검증 조작 테스트: 답변을 일부러 조작해 코드 검증(factcheck)과 Judge 가 몇 건을 잡는지 잰다.

대상: holdout 최종(final) 1회차 답 중 장애로 처리된 답. 조작 3종 + 원본(오탐 확인용).
  num   근거에 없는 수치로 바꾸기 (답의 첫 측정값을 근거 어디에도 ±0.5 안에 없는 값으로)
  name  없는 시스템명을 넣은 조치 한 줄 추가
  both  둘 다
'잡았다' 의 정의
  코드  : src/ext/factcheck.check(answer, context) 가 근거 없는 수치를 찾음 (파이프라인과 같은 함수)
  Judge : 파이프라인 Judge v2(gpt-4o-mini)가 4지표 중 3개 미만 통과 → 반려 (파이프라인과 같은 기준)

    python -m eval.tamper_test              # 코드 검증만 (API 없음, 비용 0)
    python -m eval.tamper_test --judge      # Judge 도 호출 (실제 API, 실행 전 비용 추정 출력)
결과: results/tamper_<YYYYMMDD_HHMM>.json·.md, results/tamper_latest.json

목적: '코드 검증과 Judge 중 무엇이 어떤 환각을 잡나'를 같은 답으로 나눠 본다. 수치 조작은 코드가,
없는 시스템명은 Judge 가 맡는 식으로 서로 보완하는지 확인한다. original 은 조작하지 않은 답이라
여기서 '잡았다'는 오탐(멀쩡한 답을 반려)이다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from ext.factcheck import _NUM_UNIT, _STEP, check, numbers_in  # noqa: E402

R = ROOT / "results"
FAKE_SYSTEM = "billing-ledger-9"   # 등록 시스템·런북 어디에도 없는 이름 (근거에 있으면 그 답은 건너뜀)


def tamper_number(answer: str, context: str) -> str | None:
    """답의 첫 측정값(절차 번호 뒤, 단위 붙은 값)을 근거 어디에도 ±0.5 안에 없는 값으로 바꾼다. 없으면 None.

    factcheck 와 같은 정규식(_NUM_UNIT·_STEP)으로 찾으므로, 바꾼 값은 factcheck 가 '측정값'으로 보는 자리에 있다.
    """
    ctx = numbers_in(context)
    lines = answer.splitlines()
    for i, line in enumerate(lines):
        m_step = _STEP.match(line)
        start = m_step.end() if m_step else 0
        m = _NUM_UNIT.search(line, start)
        if not m:
            continue
        v = float(m.group(1))
        new = round(v * 1.37 + 3.1, 1)   # 원값과 그럴듯하게 다른 값
        while any(abs(new - c) <= 0.5 for c in ctx):   # factcheck 허용 오차(±0.5) 밖으로 밀어낸다
            new = round(new + 7.3, 1)
        s = f"{new:g}"
        lines[i] = line[:m.start(1)] + s + line[m.end(1):]
        return "\n".join(lines)
    return None


def tamper_name(answer: str) -> str:
    """없는 시스템을 대상으로 한 조치 한 줄을 끝에 붙인다 (수치는 건드리지 않음)."""
    return answer.rstrip() + f"\n추가 조치) {FAKE_SYSTEM} 서비스도 재시작해 영향 범위를 확인한다."


def main():
    """조작 답 목록을 만들고 코드 검증(항상)과 Judge(--judge 일 때)가 잡은 수를 종류별로 센다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true", help="파이프라인 Judge(gpt-4o-mini)도 호출 (실제 API)")
    ap.add_argument("--yes", action="store_true", help="비용 확인 없이 진행")
    a = ap.parse_args()
    rows = [r for r in json.loads((R / "final_latest.json").read_text())["rows"]
            if r.get("split") == "holdout" and r.get("rep") == 1 and r.get("route") == "incident" and "error" not in r]
    items = []
    for r in rows:
        ctx, ans = r.get("context", ""), r["answer"]
        if FAKE_SYSTEM in ctx:
            continue
        num = tamper_number(ans, ctx)
        items.append({"id": r["id"], "kind": "original", "answer": ans, "query": r["query"], "context": ctx})
        items.append({"id": r["id"], "kind": "name", "answer": tamper_name(ans), "query": r["query"], "context": ctx})
        if num:
            items.append({"id": r["id"], "kind": "num", "answer": num, "query": r["query"], "context": ctx})
            items.append({"id": r["id"], "kind": "both", "answer": tamper_name(num), "query": r["query"], "context": ctx})
    for it in items:
        it["code_caught"] = not check(it["answer"], it["context"])["ok"]
    judge_meta = None
    if a.judge:
        est_calls = len(items)
        print(f"Judge 호출 {est_calls}회 (gpt-4o-mini, 호출당 입력 약 2천 토큰) → 예상 비용 약 ${est_calls * 0.0004:.2f}")
        if not a.yes and input("진행할까요? [y/N] ").strip().lower() != "y":
            print("중단")
            return
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from ext.judge import OpenAIJudge
        from ext.meter import start_meter
        j = OpenAIJudge("gpt-4o-mini", 0.00015, version=2)
        meter = start_meter()
        for it in items:
            v = j.evaluate(it["query"], it["context"], it["answer"])["verdicts"]
            it["judge_verdicts"] = v
            it["judge_caught"] = sum(x == "Pass" for x in v.values()) < 3   # 파이프라인과 같은 3/4 규칙으로 반려
        judge_meta = {"model": "gpt-4o-mini", "version": 2, "calls": len(items), "cost_usd": round(meter.cost_usd(), 4)}
    kinds = ["original", "num", "name", "both"]
    summ = {}
    for k in kinds:
        xs = [i for i in items if i["kind"] == k]
        s = {"n": len(xs), "code": sum(i["code_caught"] for i in xs)}
        if a.judge:
            s["judge"] = sum(i["judge_caught"] for i in xs)
            s["either"] = sum(i["code_caught"] or i["judge_caught"] for i in xs)
        summ[k] = s
    ts = f"{datetime.now():%Y%m%d_%H%M}"
    out = {"created": ts, "source": "results/final_latest.json (holdout, rep 1, incident)", "fake_system": FAKE_SYSTEM,
           "judge": judge_meta, "summary": summ, "items": items}
    (R / f"tamper_{ts}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (R / "tamper_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ko = {"original": "원본 (오탐 확인)", "num": "근거에 없는 수치", "name": "없는 시스템명", "both": "둘 다"}
    head = "| 조작 | 답 수 | 코드 검증이 잡음 |" + (" Judge가 잡음 | 둘 중 하나라도 |" if a.judge else "")
    sep = "|---|---|---|" + ("---|---|" if a.judge else "")
    lines = ["# 근거 검증 조작 테스트", "", f"대상: {out['source']}. 실제 모델 답에 조작을 가함. Judge: {judge_meta or '호출 안 함'}", "", head, sep]
    for k in kinds:
        s = summ[k]
        lines.append(f"| {ko[k]} | {s['n']} | {s['code']}/{s['n']} |" + (f" {s['judge']}/{s['n']} | {s['either']}/{s['n']} |" if a.judge else ""))
    (R / f"tamper_{ts}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
