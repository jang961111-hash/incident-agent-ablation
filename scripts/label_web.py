"""사람 채점 페이지 (로컬 웹). scripts/label.py 와 같은 규칙, 같은 파일(eval/human_labels.yaml)에 저장한다.

    .venv/bin/python scripts/label_web.py            # http://127.0.0.1:8765 에서 연다 (이 컴퓨터에서만 접속)

- 블라인드: 평가 Judge 의 판정, 점수, 이유는 보여주지 않는다.
- 순서: 표본 20건(eval/human_sample_ids.txt, 카테고리 층화) 먼저, 그다음 나머지 base 답변.
  Q01 은 라벨링 가이드에 예시 판정이 실려 있어 목록에서 뺀다 (eval/human_exclude.txt).
- 지표 4개를 Pass/Fail 로 고르면 overall 은 3개 이상 Pass 일 때 Pass (Judge 임계치 0.75 와 같은 규칙).
- 한 번 저장한 라벨은 고치지 않는다 (CLI 와 같은 규칙). 저장할 때마다 파일에 바로 쓴다.
- 일치도(사람 vs 평가 Judge)는 표본을 다 채점한 뒤에만 볼 수 있다. 채점 중에 보면 블라인드가 깨진다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from eval.agreement import LABELS_PATH, METRICS, load_human, render, summary_dict  # noqa: E402
from label import BASE, CRITERIA, KO_NAME, QY, make_entry, save_labels  # noqa: E402

LOCK = threading.Lock()
# 전문 지식 없이 근거 상자와 비교만으로 판단하는 방법 (docs/라벨링_가이드.md 와 같은 기준)
HOWTO = {
    "relevance": "질문 속 시스템 이름과 증상(예: 504, 패킷 손실, DB 응답 없음)이 답의 앞부분에서 다뤄지나 보세요. 다른 증상 이야기로 흘렀으면 Fail.",
    "completeness": "답에 나온 숫자와 시스템 이름을 근거 상자에서 찾아보세요 (Cmd+F). 근거에 없는 숫자나 원인을 지어냈으면 Fail.",
    "domain_appropriateness": "근거 상자의 굵은 '# Runbook:' 제목이 질문의 증상과 맞나, 답의 조치가 그 런북 단계에서 왔나 보세요. 다른 장애의 런북이면 Fail.",
    "clarity": "번호 매긴 단계로 읽히나, 질문이 요구한 형식(길이, 표 등)을 지켰나 보세요.",
}
LABELS = LABELS_PATH   # --labels 로 바꿀 수 있다 (시험용)


def _ids(name: str) -> list[str]:
    """eval/ 아래 id 목록 파일(쉼표나 줄바꿈 구분)을 읽는다. 파일이 없으면 빈 목록."""
    p = ROOT / "eval" / name
    return [x.strip() for x in p.read_text().replace("\n", ",").split(",") if x.strip()] if p.exists() else []


def load_items() -> tuple[list[dict], set[str]]:
    """채점 대상 목록 (rep 1 의 base 답변). Judge 관련 필드는 넣지 않는다."""
    queries = {q["id"]: q for q in yaml.safe_load(QY.read_text(encoding="utf-8"))["queries"]}
    rows = {r["id"]: r for r in json.loads(BASE.read_text(encoding="utf-8"))["rows"]
            if r.get("rep", 1) == 1 and "error" not in r}
    sample, exclude = _ids("human_sample_ids.txt"), set(_ids("human_exclude.txt"))
    order = [i for i in sample if i in rows] + sorted(i for i in rows if i not in sample)
    items = []
    for i in order:
        if i in exclude:
            continue
        r, q = rows[i], queries.get(i, {})
        items.append({"id": i, "sample": i in sample, "category": r.get("category"), "split": q.get("split"),
                      "route": r.get("route"), "query": r["query"], "expect": q.get("expect_behavior", ""),
                      "context": (r.get("context") or "")[:2500], "answer": r["answer"]})
    return items, {it["id"] for it in items if it["sample"]}


ITEMS, SAMPLE = load_items()
ANSWERS = {it["id"]: it["answer"] for it in ITEMS}


def state() -> dict:
    """지금 라벨 파일 기준 진행 상황. 저장할 때마다 파일을 다시 읽어, 터미널 도구(label.py)와 함께 써도 어긋나지 않는다."""
    labels = load_human(LABELS)["labels"]
    done = {i: labels[i]["overall"] for i in labels}
    return {"done": done, "sample_total": len(SAMPLE), "sample_done": sum(1 for i in SAMPLE if i in labels),
            "total": len(ITEMS), "labels_path": str(LABELS)}


class H(BaseHTTPRequestHandler):
    """채점 페이지의 HTTP 처리. GET 은 페이지, 목록, 일치도를 주고 POST 는 라벨 1건을 저장한다."""
    def _send(self, code: int, body: bytes, ctype: str):
        """상태 코드와 본문을 그대로 돌려준다."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        """객체를 JSON 으로 돌려준다 (한글 그대로)."""
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def log_message(self, fmt, *args):   # 터미널을 조용히
        """요청마다 찍히는 접속 로그를 끈다."""
        pass

    def do_GET(self):
        """/ 는 페이지, /api/items 는 채점 대상(평가 Judge 정보 없음), /api/agreement 는 표본을 다 채점했을 때만 일치도를 준다."""
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/items":
            self._json({"items": ITEMS, "metrics": [{"key": m, "name": KO_NAME[m], "criteria": CRITERIA[m], "howto": HOWTO[m]}
                                                    for m in METRICS],
                        **state()})
        elif self.path == "/api/agreement":
            st = state()
            if st["sample_done"] < st["sample_total"]:
                self._json({"error": f"표본 {st['sample_total']}건을 다 채점한 뒤에 볼 수 있습니다 (지금 {st['sample_done']}건)."}, 400)
                return
            self._json({"text": render(summary_dict("base", str(LABELS), None), md=False)})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        """/api/label 로 받은 지표 4개 판정을 검증하고 저장한다. 이미 채점한 건은 409 로 거부한다 (라벨은 고치지 않는다)."""
        if self.path != "/api/label":
            self._send(404, b"not found", "text/plain")
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        qid, verdicts = body.get("id"), body.get("verdicts") or {}
        if qid not in ANSWERS or set(verdicts) != set(METRICS) or not all(v in ("Pass", "Fail") for v in verdicts.values()):
            self._json({"error": "잘못된 요청"}, 400)
            return
        with LOCK:
            labels = load_human(LABELS)["labels"]
            if qid in labels:
                self._json({"error": f"{qid} 는 이미 채점했습니다 (한 번 매긴 라벨은 고치지 않음)."}, 409)
                return
            labels[qid] = make_entry(verdicts, ANSWERS[qid])
            save_labels(LABELS, labels)
        self._json({"ok": True, "overall": labels[qid]["overall"], **state()})


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>사람 채점</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#16181d;--ink2:#5b6070;--line:#e2e2dd;--blue:#1d5fb8;--blue-bg:#e8f0fb;--red:#b4381f;--red-bg:#fbeae5;--ok:#1f7a4d}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--card:#1d2026;--ink:#e9eaee;--ink2:#a3a8b5;--line:#2e323a;--blue:#7fb0f5;--blue-bg:#1d2a3d;--red:#f08f78;--red-bg:#3a2320;--ok:#6fd0a0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}.bar{flex:1;min-width:160px;height:8px;background:var(--line);border-radius:4px;overflow:hidden}.bar>i{display:block;height:100%;background:var(--blue)}
.meta{color:var(--ink2);font-size:13px}
main{display:grid;grid-template-columns:240px 1fr 360px;gap:14px;padding:14px 16px;max-width:1500px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.list{max-height:calc(100vh - 90px);overflow:auto;padding:6px}
.list button{display:flex;width:100%;justify-content:space-between;border:0;background:none;color:var(--ink);padding:6px 8px;border-radius:6px;cursor:pointer;font:inherit;text-align:left}
.list button.cur{background:var(--blue-bg)}.list .sec{font-size:12px;color:var(--ink2);margin:8px 8px 2px}
.tag{font-size:12px;padding:1px 7px;border-radius:9px;background:var(--line);color:var(--ink2)}.tag.P{background:var(--blue-bg);color:var(--blue)}.tag.F{background:var(--red-bg);color:var(--red)}
h2{font-size:13px;color:var(--ink2);margin:14px 0 4px;font-weight:600}h2:first-child{margin-top:0}
.q{font-size:18px;font-weight:600}.pre{white-space:pre-wrap;word-break:break-word}.ctx{font-size:13px;color:var(--ink2);max-height:260px;overflow:auto;background:var(--bg);padding:10px;border-radius:8px}
.ans{background:var(--bg);padding:12px;border-radius:8px}
.m{border-top:1px solid var(--line);padding:10px 0}.m:first-of-type{border-top:0}.m b{display:block}.m small{color:var(--ink2);display:block;margin:2px 0 8px}
.seg{display:flex;gap:8px}.seg button{flex:1;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer;font:inherit}
.seg button.on.P{background:var(--blue);border-color:var(--blue);color:#fff}.seg button.on.F{background:var(--red);border-color:var(--red);color:#fff}
.go{width:100%;margin-top:12px;padding:11px;border:0;border-radius:8px;background:var(--ink);color:var(--card);font:inherit;font-weight:600;cursor:pointer}.go:disabled{opacity:.35;cursor:default}
.skip{width:100%;margin-top:6px;padding:8px;border:1px solid var(--line);border-radius:8px;background:none;color:var(--ink2);cursor:pointer;font:inherit}
.overall{margin-top:10px;font-size:14px}.msg{margin-top:8px;font-size:13px;color:var(--ok)}.err{color:var(--red)}
.keys{font-size:12px;color:var(--ink2);margin-top:10px}kbd{border:1px solid var(--line);border-radius:4px;padding:0 5px;font-size:11px}
.how{font-size:12px;color:var(--ink2);background:var(--bg);border-radius:6px;padding:6px 8px;margin:0 0 8px}
.guide table{border-collapse:collapse;width:100%;font-size:14px}.guide td,.guide th{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}.guide .P{color:var(--blue);font-weight:600}.guide .F{color:var(--red);font-weight:600}
.rb{color:var(--ink);font-weight:700}
#agr{white-space:pre-wrap;font:12px/1.5 ui-monospace,Menlo,monospace;overflow:auto}
@media (max-width:1100px){main{grid-template-columns:1fr}.list{max-height:none;display:flex;flex-wrap:nowrap;overflow-x:auto;gap:4px}.list button{width:auto;flex:0 0 auto;gap:6px}.list .sec{display:none}.list .meta{display:none}}
</style></head><body>
<header><h1>사람 채점 (블라인드)</h1><div class="bar"><i id="pb" style="width:0"></i></div><span class="meta" id="prog"></span>
<button class="skip" style="width:auto;margin:0" id="guideBtn">채점 가이드</button><button class="skip" style="width:auto;margin:0" id="agrBtn">일치도 보기</button></header>
<main>
<nav class="card list" id="list" aria-label="채점 목록"></nav>
<section class="card" id="view"></section>
<aside class="card" id="panel"></aside>
</main>
<script>
let D, cur = 0, pick = {};
const $ = s => document.querySelector(s);
const esc = s => (s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
async function load(){ D = await (await fetch("/api/items")).json(); const i = D.items.findIndex(x => !(x.id in D.done)); cur = i < 0 ? 0 : i; draw(); if (!Object.keys(D.done).length) showGuide(); }
function prog(){ $("#prog").textContent = `표본 ${D.sample_done}/${D.sample_total}, 전체 ${Object.keys(D.done).length}/${D.total}`;
  $("#pb").style.width = (100 * D.sample_done / D.sample_total) + "%"; }
function draw(){
  prog();
  let h = '<div class="sec">표본 (먼저)</div>', sec = true;
  D.items.forEach((it, k) => { if (sec && !it.sample){ h += '<div class="sec">추가 (선택)</div>'; sec = false; }
    const d = D.done[it.id]; h += `<button class="${k===cur?'cur':''}" data-k="${k}"><span>${it.id} <span class="meta">${esc(it.category||'')}</span></span>${d?`<span class="tag ${d[0]}">${d}</span>`:''}</button>`; });
  $("#list").innerHTML = h; $("#list").querySelectorAll("button").forEach(b => b.onclick = () => { cur = +b.dataset.k; pick = {}; draw(); });
  const it = D.items[cur], done = D.done[it.id];
  $("#view").innerHTML = `<h2>${it.id}, ${esc(it.category||'')}${it.split?', '+it.split:''}, 경로 ${esc(it.route||'')}</h2>`
    + `<div class="q">${esc(it.query)}</div>` + (it.expect?`<h2>기대 행동</h2><div class="pre">${esc(it.expect)}</div>`:'')
    + `<h2>에이전트 답변</h2><div class="ans pre">${esc(it.answer)}</div><h2>근거 (작성 단계가 받은 자료)</h2><div class="ctx pre">${esc(it.context).replace(/^(# Runbook:.*)$/gm, '<span class="rb">$1</span>')}</div>`;
  if (done){ $("#panel").innerHTML = `<h2>채점 완료</h2><p>overall <span class="tag ${done[0]}">${done}</span></p><p class="meta">한 번 매긴 라벨은 고치지 않습니다.</p><button class="go" id="nx">다음 미채점 건 →</button>`; $("#nx").onclick = next; return; }
  let p = '<h2>지표별로 고르세요</h2>';
  D.metrics.forEach((m, i) => { const v = pick[m.key];
    p += `<div class="m"><b>${i+1}. ${m.name}</b><small>${esc(m.criteria)}</small><div class="how">확인 방법: ${esc(m.howto)}</div><div class="seg">`
      + `<button class="P ${v==='Pass'?'on':''}" data-m="${m.key}" data-v="Pass">Pass</button><button class="F ${v==='Fail'?'on':''}" data-m="${m.key}" data-v="Fail">Fail</button></div></div>`; });
  const n = Object.keys(pick).length, np = Object.values(pick).filter(v => v==='Pass').length;
  p += `<div class="overall">overall: ${n<4?'<span class="meta">4개를 모두 고르면 표시</span>':`<span class="tag ${np>=3?'P':'F'}">${np>=3?'Pass':'Fail'}</span> (Pass ${np}/4, 3개 이상이면 Pass)`}</div>`
    + `<button class="go" id="save" ${n<4?'disabled':''}>저장하고 다음 (Enter)</button><button class="skip" id="skip">건너뛰기</button><div id="msg" class="msg"></div>`
    + `<div class="keys">단축키: <kbd>1</kbd>~<kbd>4</kbd> 지표 선택 후 <kbd>P</kbd>/<kbd>F</kbd>, <kbd>Enter</kbd> 저장, <kbd>→</kbd> 건너뛰기</div>`;
  $("#panel").innerHTML = p;
  $("#panel").querySelectorAll(".seg button").forEach(b => b.onclick = () => { pick[b.dataset.m] = b.dataset.v; draw(); });
  $("#save").onclick = save; $("#skip").onclick = next;
}
function next(){ pick = {}; const n = D.items.length; for (let s = 1; s <= n; s++){ const k = (cur + s) % n; if (!(D.items[k].id in D.done)){ cur = k; break; } } draw(); }
async function save(){
  if (Object.keys(pick).length < 4) return;
  const it = D.items[cur], r = await fetch("/api/label", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({id: it.id, verdicts: pick})});
  const j = await r.json(); if (!r.ok){ $("#msg").innerHTML = `<span class="err">${esc(j.error)}</span>`; return; }
  D.done[it.id] = j.overall; D.sample_done = j.sample_done; next();
}
let focusM = 0;
document.addEventListener("keydown", e => {
  if (!D || D.items[cur].id in D.done) return;
  if (/^[1-4]$/.test(e.key)) focusM = +e.key - 1;
  else if (e.key === "p" || e.key === "f"){ pick[D.metrics[focusM].key] = e.key === "p" ? "Pass" : "Fail"; focusM = Math.min(3, focusM + 1); draw(); }
  else if (e.key === "Enter") save(); else if (e.key === "ArrowRight") next();
});
const GUIDE = `<div class="guide"><h2>채점 가이드</h2>
<p><b>장애 대응 지식이 없어도 됩니다.</b> 4개 지표는 모두 "답이 질문과 근거 상자에 맞게 쓰였나"를 보는 독해 문제입니다. 정답을 알아야 하는 게 아니라, 화면에 있는 <b>질문, 답, 근거</b>를 서로 대조하면 됩니다.</p>
<table><tr><th>지표</th><th>질문</th><th>Fail인 경우</th></tr>
<tr><td>관련성</td><td>물어본 것에 답했나?</td><td>다른 장애 이야기로 답함. 등록 안 된 시스템인데 "없다"고 안 하고 엉뚱하게 진단함</td></tr>
<tr><td>완전성</td><td>근거에 없는 숫자, 사실을 지어내지 않았나?</td><td>근거에 없는 수치나 원인을 만들어냄. 근거의 핵심 수치가 빠짐</td></tr>
<tr><td>도메인 적합성</td><td>질문에 맞는 런북(대처 매뉴얼) 절차를 썼나?</td><td>질문과 무관한 런북 절차를 씀 (예: DB 다운에 응답 지연 절차)</td></tr>
<tr><td>명확성</td><td>요청한 형식, 길이를 지켰고 정리돼 있나?</td><td>"50자 이내", "표로" 같은 요청을 어김. 뒤죽박죽</td></tr></table>
<h2>예시: Q02 (표본에는 없는 문항)</h2>
<p><b>질문</b>: auth-service DB 커넥션이 다 끊겼고 DB 프라이머리가 응답이 없습니다. 어떻게 복구하죠?<br>
<b>근거</b>: auth-service 모니터링 (p95 latency 2.4s, connection pool 92%) + <b>응답 지연(High Latency) 런북</b><br>
<b>답</b>: 1) p95 2.4초, 커넥션 풀 92% 확인 2) 풀 크기 늘리기, 타임아웃 3) 캐시, 읽기 복제본으로 트래픽 분산</p>
<table><tr><th>지표</th><th>판정</th><th>이유</th></tr>
<tr><td>관련성</td><td class="F">Fail</td><td>DB가 응답이 없다고 물었는데 응답 지연 대응을 답했다</td></tr>
<tr><td>완전성</td><td class="P">Pass</td><td>2.4초, 92% 모두 근거에 있는 숫자다. 지어낸 건 없다</td></tr>
<tr><td>도메인 적합성</td><td class="F">Fail</td><td>근거의 런북 제목이 "응답 지연"이다. DB 다운 절차가 아니다</td></tr>
<tr><td>명확성</td><td class="P">Pass</td><td>번호 매겨 정리돼 있다</td></tr></table>
<p>→ 2/4 통과라 종합 Fail.</p>
<h2>헷갈릴 때</h2><ul>
<li><b>맞는 런북이 없는 질문</b>: "등록된 런북, 모니터링에 없다"고 밝히고 추측하지 않았으면 관련성, 도메인 Pass. 엉뚱한 런북 절차를 그럴듯하게 붙였으면 Fail.</li>
<li><b>모호한 질문</b>("서버가 이상해요"): 무엇을 확인했는지 밝히거나 대상, 증상을 되물었으면 관련성 Pass.</li>
<li><b>완전성</b>은 "틀린 말을 지어냈나"만 봅니다. 근거가 빈약해도 지어낸 게 없으면 Pass.</li>
<li>그래도 모르겠으면 이렇게 물어보세요: <b>"당직자가 이 답만 보고 바로 움직여도 되나?"</b> 아니면 Fail. 첫 판단으로, 한 건에 1분이면 충분합니다.</li></ul>
<p class="meta">전체 문서: docs/라벨링_가이드.md</p><button class="go" id="startBtn">채점 화면으로</button></div>`;
function showGuide(){ $("#view").innerHTML = GUIDE; $("#startBtn").onclick = () => draw(); window.scrollTo(0, 0); }
$("#guideBtn").onclick = showGuide;
$("#agrBtn").onclick = async () => { const r = await fetch("/api/agreement"), j = await r.json();
  $("#view").innerHTML = r.ok ? `<h2>사람 vs 평가 Judge 일치도</h2><div id="agr">${esc(j.text)}</div>` : `<p class="err">${esc(j.error)}</p>`; };
load();
</script></body></html>"""


def main():
    """--port, --labels 를 받아 127.0.0.1 에서만 서버를 연다 (같은 컴퓨터에서만 접속)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--labels", default=None, help="라벨 파일 경로 (기본 eval/human_labels.yaml)")
    a = ap.parse_args()
    global LABELS
    if a.labels:
        LABELS = Path(a.labels)
    print(f"사람 채점 페이지: http://127.0.0.1:{a.port}  (대상 {len(ITEMS)}건, 표본 {len(SAMPLE)}건, 저장 {LABELS})")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
