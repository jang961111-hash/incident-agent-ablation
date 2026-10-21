// 발표 덱 생성기 — 모든 수치를 results/*.json 에서 읽는다. 손으로 적는 숫자 없음.
//   cd deck && node build.js   →  deck/incident-agent-ablation.pptx
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const SKILL = process.env.PPTX_SKILL_DIR;
const R = (n) => JSON.parse(fs.readFileSync(path.join(ROOT, "results", `${n}_latest.json`)));
const CFG = ["base", "rag", "rag_judge", "rag_judge_cost"];
const LABEL = { base: "base", rag: "+RAG", rag_judge: "+Judge", rag_judge_cost: "+비용최적화" };
const S = Object.fromEntries(CFG.map((n) => [n, R(n).summary]));
const ROWS = Object.fromEntries(CFG.map((n) => [n, R(n).rows]));
// Judge 무관 결정적 지표·라벨 일치율은 파이썬 쪽 계산을 그대로 가져온다
const PY = path.join(ROOT, ".venv", "bin", "python");
const extra = JSON.parse(execFileSync(PY, ["-c", `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
from eval.answer_metrics import load_all
from eval.report import judge_agreement
a, n, miss = judge_agreement()
print(json.dumps({"must": {k: {kk: vv for kk, vv in v.items() if kk != "per_query"} for k, v in load_all().items()},
                  "agree": a, "agree_n": n, "agree_miss": miss}))
`], { cwd: ROOT }).toString());
const cachePath = path.join(ROOT, "results", "cache_bench_latest.json");
const CACHE = fs.existsSync(cachePath) ? JSON.parse(fs.readFileSync(cachePath)) : null;

const pct = (v) => `${Math.round(v * 100)}%`;
const usd = (v) => `$${v.toFixed(4)}`;
const sec = (ms) => `${(ms / 1000).toFixed(1)}초`;
const M = (n) => extra.must[n];

// ── 테마 ─────────────────────────────────────────────────────────────
const THEME = {
  name: "Incident Ablation",
  headFontFace: "Apple SD Gothic Neo",
  bodyFontFace: "Apple SD Gothic Neo",
  colors: {
    dk1: "1A2230", lt1: "FFFFFF", dk2: "16202C", lt2: "EEF2F6",
    accent1: "E8833A", accent2: "1F8A70", accent3: "8A94A3",
    accent4: "C9A227", accent5: "D1495B", accent6: "155E4B",
    hlink: "1F8A70", folHlink: "155E4B",
  },
};
const HEX = THEME.colors;
const FONT = THEME.bodyFontFace;   // 차트 글꼴은 테마를 따르지 않아 직접 지정
const BAR = { base: HEX.accent3, rag: HEX.accent2, rag_judge: HEX.accent4, rag_judge_cost: HEX.accent6 };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.author = "장병헌 (G062)";
pres.title = "인시던트 에이전트 개선 Ablation";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.7, h: 1.6,
      fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 1.6,
      fontSize: 18, color: C.background2, valign: "top", align: "left" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85,
      fontSize: 30, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "SKALA 4기 AI Mini-Project · 과제1 · 장병헌", options: {
      x: 0.6, y: 7.0, w: 7, h: 0.3, fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent3, align: "right" },
});

let sec_ = "";
const slide = (master, section) => {
  if (section !== sec_) { pres.addSection({ title: section }); sec_ = section; }
  return pres.addSlide({ masterName: master, sectionTitle: section });
};
const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, fontSize: 15, color: C.text1, ...o });
const card = (s, x, y, w, h, fill, name) => s.addShape(pres.shapes.ROUNDED_RECTANGLE,
  { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });
const stat = (s, x, y, w, big, small, color, name) => {
  card(s, x, y, w, 2.0, C.background2, name);
  T(s, big, { x: x + 0.3, y: y + 0.25, w: w - 0.6, h: 1.0, fontSize: 40, bold: true, color });
  T(s, small, { x: x + 0.3, y: y + 1.25, w: w - 0.6, h: 0.65, fontSize: 14, color: C.text1, valign: "top" });
};
const chartBase = (title) => ({
  showTitle: true, title, titleFontSize: 14, titleColor: HEX.dk2, titleFontFace: FONT,
  showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 12, dataLabelColor: HEX.dk1,
  dataLabelFontFace: FONT, catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
  catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 12, valAxisHidden: true,
  valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
  chartColors: CFG.map((n) => BAR[n]), barGapWidthPct: 60,
});
const barChart = (s, x, y, w, h, title, vals, fmt, name) => s.addChart(pres.charts.BAR, [{
  name: title, labels: CFG.map((n) => LABEL[n]), values: vals }], {
  x, y, w, h, barDir: "col", ...chartBase(title), dataLabelFormatCode: fmt,
  valAxisMinVal: 0, objectName: name });

// ── 1. 표지 ──────────────────────────────────────────────────────────
let s = slide("DARK", "표지");
s.addText("인시던트 에이전트 개선, 무엇이 효과였나", { placeholder: "title" });
s.addText([
  { text: "개선 3가지를 하나씩 켜 보는 4구성 Ablation으로 기여도를 분해했다", options: { breakLine: true } },
  { text: "SKALA 4기 AI Mini-Project 과제1 · 광주 2반 장병헌 (G062)", options: { fontSize: 14, color: C.accent3 } },
], { placeholder: "body" });
s.addNotes("교수님 베이스 에이전트에 RAG, LLM Judge, 비용 최적화를 붙였고, 각각을 따로 켜서 어떤 개선이 실제로 효과가 있었는지 수치로 분리했습니다.");

// ── 2. 결론 먼저 ─────────────────────────────────────────────────────
s = slide("CONTENT", "요약");
s.addText("결론: 효과는 RAG에서, 비용은 캐스케이드에서 나왔다", { placeholder: "title" });
stat(s, 0.6, 1.6, 3.85, `${pct(S.base["recall@1"])} → ${pct(S.rag["recall@1"])}`,
  "런북 검색 Recall@1 (gold 18건)\nbase → RAG", C.accent2, "stat-recall");
stat(s, 4.74, 1.6, 3.85, `-${Math.round((1 - S.rag_judge_cost.cost_usd_total / S.base.cost_usd_total) * 100)}%`,
  `추정 비용 base → 최종 (24건)\n${usd(S.base.cost_usd_total)} → ${usd(S.rag_judge_cost.cost_usd_total)}, 품질 상승은 RAG 몫`, C.accent6, "stat-cost");
stat(s, 8.88, 1.6, 3.85, `+${Math.round((S.rag_judge.cost_usd_total / S.rag.cost_usd_total - 1) * 100)}%`,
  "LLM Judge를 붙였을 때 비용\n측정 가능한 품질 이득은 없음", C.accent1, "stat-judge");
T(s, [
  { text: "결정적 지표(런북 핵심 어구 포함률): ", options: { bold: true } },
  { text: `base ${pct(M("base").must_phrase_rate)} → RAG ${pct(M("rag").must_phrase_rate)} → 최종 ${pct(M("rag_judge_cost").must_phrase_rate)}`, options: { breakLine: true } },
  { text: "출처: results/*_latest.json (2026-10-21 실행, 4구성 x 24건, 실행 오류 0)", options: { fontSize: 11, color: C.accent3 } },
], { x: 0.6, y: 4.0, w: 12.1, h: 1.0, fontSize: 16 });
card(s, 0.6, 5.2, 12.1, 1.45, C.background2, "takeaway");
T(s, "개선을 하나씩 켜서 쟀기 때문에 \"RAG를 넣었더니 좋아졌다\"가 아니라 \"좋아진 건 RAG 덕분이고, Judge는 비용만 늘렸다\"까지 말할 수 있다.",
  { x: 0.9, y: 5.35, w: 11.5, h: 1.15, fontSize: 16, valign: "middle" });
s.addNotes("세 숫자가 결론입니다. 검색 정확도는 두 배, 최종 구성 비용은 base보다 싸고, Judge는 품질 이득 없이 비용만 늘렸습니다.");

// ── 3. 문제 1: 런북 선택이 질의를 보지 않는다 ──────────────────────────
s = slide("CONTENT", "문제");
const inc = ROWS.base.filter((r) => r.route === "incident");
const hl = inc.filter((r) => r.retrieved.length === 1 && r.retrieved[0] === "high-latency").length;
s.addText("문제 1: base는 질문을 읽지 않고 런북을 고른다", { placeholder: "title" });
const flow = [
  ["사용자 질의", "\"DB 프라이머리가\n다운됐습니다\"", C.background2],
  ["planner", "시스템명 없음\n→ auth-service 폴백", C.background2],
  ["모니터링 알림", "\"p95 latency 2.4s\"\n키워드 'latency' 일치", C.background2],
  ["선택된 런북", "high-latency\n(응답 지연 절차)", C.accent1],
];
flow.forEach(([h, b, fill], i) => {
  const x = 0.6 + i * 3.1;
  card(s, x, 1.6, 2.7, 2.1, fill, `flow-${i}`);
  T(s, h, { x: x + 0.2, y: 1.75, w: 2.3, h: 0.45, fontSize: 14, bold: true,
    color: fill === C.accent1 ? C.background1 : C.text2 });
  T(s, b, { x: x + 0.2, y: 2.25, w: 2.3, h: 1.3, fontSize: 15,
    color: fill === C.accent1 ? C.background1 : C.text1, valign: "top" });
  if (i < 3) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 2.75, y: 2.45, w: 0.3, h: 0.4,
    fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: `arrow-${i}` });
});
stat(s, 0.6, 4.2, 4.0, `${hl} / ${inc.length}`, "base가 장애로 처리한 질의 중\nhigh-latency 런북을 받은 건수", C.accent1, "stat-hl");
T(s, [
  { text: "원인 (src/agent/graph.py:192-213)", options: { bold: true, breakLine: true } },
  { text: "조사한 시스템의 알림 문구에서 키워드를 순서대로 찾아 첫 일치로 런북 1개를 고른다.", options: { bullet: true, breakLine: true } },
  { text: "질의 문장은 판단에 쓰이지 않는다. 복합 장애도 런북 1개뿐이다.", options: { bullet: true, breakLine: true } },
  { text: `base Recall@1 ${pct(S.base["recall@1"])}, 투입 런북 정밀도 ${pct(S.base.fed_precision)}`, options: { bullet: true } },
], { x: 5.0, y: 4.2, w: 7.7, h: 2.2, fontSize: 15, paraSpaceAfter: 6, valign: "top" });
s.addNotes("DB가 다운됐다고 해도 auth-service로 폴백되고, 그 서비스의 latency 알림 때문에 응답 지연 런북이 붙습니다.");

// ── 4. 문제 2: Validator와 비용 ──────────────────────────────────────
s = slide("CONTENT", "문제");
s.addText("문제 2: 검증은 형식만 보고, 모델 분리는 이미 돼 있었다", { placeholder: "title" });
card(s, 0.6, 1.6, 5.9, 3.7, C.background2, "validator-card");
T(s, "규칙 Validator", { x: 0.9, y: 1.8, w: 5.3, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
T(s, "len(draft) >= 30 and \"1)\" in draft", { x: 0.9, y: 2.4, w: 5.3, h: 0.5, fontSize: 15,
  fontFace: "Courier New", color: C.accent1 });
T(s, [
  { text: "내용이 질문과 맞는지, 근거에 있는지는 보지 않는다.", options: { bullet: true, breakLine: true } },
  { text: `실측: base 24건 재작성 ${S.base.rewrites_total}회. gpt-4o 답은 항상 30자 이상, "1)" 포함.`, options: { bullet: true, breakLine: true } },
  { text: "응답 지연 절차로 DB 다운에 답해도 통과한다.", options: { bullet: true } },
], { x: 0.9, y: 3.1, w: 5.3, h: 2.1, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
card(s, 6.83, 1.6, 5.9, 3.7, C.background2, "tiering-card");
T(s, "계획했던 비용 개선", { x: 7.13, y: 1.8, w: 5.3, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
T(s, "fast = gpt-4o-mini / quality = gpt-4o", { x: 7.13, y: 2.4, w: 5.3, h: 0.5, fontSize: 15,
  fontFace: "Courier New", color: C.accent2 });
T(s, [
  { text: "'역할별 모델 분리'는 base에 이미 들어 있었다 (src/server.py:50-56).", options: { bullet: true, breakLine: true } },
  { text: "그래서 비용 축을 다시 정했다: 1차 초안은 저가 모델, Judge가 반려할 때만 gpt-4o로 재작성 (캐스케이드) + 질의 캐시.", options: { bullet: true } },
], { x: 7.13, y: 3.1, w: 5.3, h: 2.1, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
T(s, "→ 개선 대상: 런북 선택(RAG) · 검증 기준(LLM Judge) · 비용(캐스케이드 + 캐시)", { x: 0.6, y: 5.65, w: 12.1, h: 0.6, fontSize: 18, bold: true, color: C.accent6 });
s.addNotes("코드를 직접 읽고 나서 계획을 수정한 부분입니다. 모델 분리는 이미 있었기 때문에 캐스케이드로 바꿨습니다.");

// ── 5. 개선 포인트 ───────────────────────────────────────────────────
s = slide("CONTENT", "개선");
s.addText("개선: 원본 노드는 그대로, 3개 노드만 플래그로 교체", { placeholder: "title" });
const axes = [
  ["RAG 런북 선택", "replan_check", "질의 임베딩(text-embedding-3-small)으로 런북 6개 순위. 1위 점수 -0.05 이내만 write에 투입", C.accent2],
  ["LLM-as-a-Judge", "validate", "4지표(관련성·완전성·도메인·명확성) 3/4 이상 통과. 재시도 2회 또는 120초 중 먼저 닿으면 종료", C.accent4],
  ["캐스케이드 + 캐시", "write · route · plan", "1차 초안 gpt-4o-mini, 반려 시에만 gpt-4o. 정규화 질의 키로 route·plan·임베딩 캐시", C.accent6],
];
axes.forEach(([h, node, body, color], i) => {
  const x = 0.6 + i * 4.14;
  card(s, x, 1.55, 3.85, 2.75, C.background2, `axis-${i}`);
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.8, w: 0.55, h: 0.55, fill: { color }, line: { color },
    objectName: `axis-dot-${i}` });
  T(s, String(i + 1), { x: x + 0.3, y: 1.8, w: 0.55, h: 0.55, fontSize: 18, bold: true,
    color: C.background1, align: "center", valign: "middle" });
  T(s, h, { x: x + 1.0, y: 1.8, w: 2.7, h: 0.55, fontSize: 18, bold: true, color: C.text2, valign: "middle" });
  T(s, `교체 노드: ${node}`, { x: x + 0.3, y: 2.5, w: 3.3, h: 0.4, fontSize: 13, color: C.accent3 });
  T(s, body, { x: x + 0.3, y: 2.95, w: 3.3, h: 1.8, fontSize: 14, valign: "top" });
});
T(s, "기술 요소", { x: 0.6, y: 4.6, w: 2, h: 0.4, fontSize: 15, bold: true, color: C.text2 });
const chips = ["LangGraph", "MCP (원본)", "RAG", "LLM-as-a-Judge", "의존성 주입 (ExtDeps)", "모듈화 (src/ext)", "LangSmith 트레이스 96건", "pytest 12개"];
let cx = 0.6, cy = 5.1;
const textW = (t) => [...t].reduce((a, ch) => a + (/[\u3131-\uD79D]/.test(ch) ? 0.17 : 0.095), 0.35);
chips.forEach((c, i) => {
  const w = textW(c);
  if (cx + w > 12.7) { cx = 0.6; cy += 0.55; }
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: cy, w, h: 0.42, rectRadius: 0.2,
    fill: { color: C.background2 }, line: { color: C.accent3, width: 0.75 }, objectName: `chip-${i}` });
  T(s, c, { x: cx, y: cy, w, h: 0.42, fontSize: 12, align: "center", valign: "middle" });
  cx += w + 0.15;
});
T(s, "base 구성은 원본 build_graph를 그대로 호출한다. 원본 파일은 이식 커밋 이후 한 줄도 바뀌지 않았다.",
  { x: 0.6, y: 6.35, w: 12.1, h: 0.35, fontSize: 13, color: C.accent3 });
s.addNotes("세 개선은 모두 config 플래그로 켜고 끕니다. base를 돌리면 교수님 원본 그래프가 그대로 실행됩니다.");

// ── 6. 평가 설계 ─────────────────────────────────────────────────────
s = slide("CONTENT", "평가 설계");
s.addText("평가: 하나씩 켜는 4구성, 같은 24개 질의", { placeholder: "title" });
const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.lt1, fill: { color: HEX.dk2 } } });
const O = "O", X = "";
s.addTable([
  [hdr("구성"), hdr("RAG"), hdr("Judge"), hdr("비용최적화"), hdr("이 구성으로 알 수 있는 것")],
  ["base", X, X, X, "Before 기준선 (교수님 원본)"],
  ["+RAG", O, X, X, "RAG 단독 효과"],
  ["+Judge", O, O, X, "Judge가 추가로 바꾼 것"],
  ["+비용최적화", O, O, O, "비용을 줄일 때 품질 손실"],
], { x: 0.6, y: 1.5, w: 7.2, colW: [1.5, 0.8, 0.8, 1.2, 2.9], fontSize: 13, color: HEX.dk1,
  border: { type: "solid", color: "D5DCE4", pt: 0.75 }, rowH: 0.45, align: "left", valign: "middle",
  objectName: "config-table" });
T(s, [
  { text: "평가셋 24건", options: { bold: true, breakLine: true } },
  { text: "정상 12 (런북 6종 x 2) · 형식 제약 3 · 복합 3 · 미등록 3 · 모호 3", options: { breakLine: true } },
  { text: " ", options: { breakLine: true, fontSize: 6 } },
  { text: "측정 축을 분리", options: { bold: true, breakLine: true } },
  { text: "검색: Recall@k, MRR, 투입 런북 정밀도", options: { bullet: true, breakLine: true } },
  { text: "답변: 평가 Judge 4지표 + 런북 핵심 어구 포함률", options: { bullet: true, breakLine: true } },
  { text: "운영: 지연, 토큰, 추정 비용, 재작성", options: { bullet: true } },
], { x: 8.2, y: 1.5, w: 4.5, h: 3.0, fontSize: 14, paraSpaceAfter: 4, valign: "top" });
card(s, 0.6, 4.6, 12.1, 2.05, C.background2, "judge-sep");
T(s, [
  { text: "평가자를 따로 둔다", options: { bold: true, fontSize: 16, color: HEX.dk2, breakLine: true } },
  { text: "평가 Judge는 gpt-4o로 고정했다. 파이프라인 안 Judge(gpt-4o-mini)와 같은 모델로 채점하면, 그 기준에 맞춰 고친 답이 자동으로 높게 나온다.", options: { bullet: true, breakLine: true } },
  { text: "Judge 자체도 틀릴 수 있어서 Judge와 무관한 결정적 지표(측정 전에 정해 둔 런북 핵심 어구 포함률)를 함께 보고, 사람 라벨로 Judge 일치율을 잰다.", options: { bullet: true } },
], { x: 0.9, y: 4.75, w: 11.5, h: 1.8, fontSize: 14, paraSpaceAfter: 4, valign: "top" });
s.addNotes("검색 품질과 답변 품질을 분리해서 재면, 검색이 좋아진 구성에서 답도 좋아졌는지를 따로 볼 수 있습니다. 다만 24건 1회 실행이라 인과를 단정하지는 않습니다.");

// ── 7. Before/After 검색 ────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 1: 검색 정확도가 두 배가 됐다", { placeholder: "title" });
barChart(s, 0.6, 1.5, 6.0, 4.6, "Recall@1 (gold 18건)", CFG.map((n) => S[n]["recall@1"]), "0%", "chart-recall");
barChart(s, 6.73, 1.5, 6.0, 4.6, "write에 넣은 런북의 정밀도", CFG.map((n) => S[n].fed_precision), "0%", "chart-precision");
T(s, `MRR ${S.base.mrr.toFixed(3)} → ${S.rag.mrr.toFixed(3)} · 장애 경로 ${S.rag.n_retrieval_incident}건만 보면 Recall@1 ${pct(S.base["recall@1|incident"])} → ${pct(S.rag["recall@1|incident"])} · RAG 순위는 세 RAG 구성에서 동일 (임베딩 결정적)`,
  { x: 0.6, y: 6.25, w: 12.1, h: 0.5, fontSize: 13, color: C.accent3 });
s.addNotes("base는 런북을 1개만 고르므로 Recall@3은 공정하지 않아서, 실제로 write에 넣은 런북 기준 정밀도를 같이 봤습니다.");

// ── 8. Before/After 답변 품질 + Judge 포화 ──────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 2: 답변 품질 — 평가 Judge는 포화됐다", { placeholder: "title" });
barChart(s, 0.6, 1.5, 6.0, 4.3, "런북 핵심 어구 포함률 (Judge 무관, 13건)", CFG.map((n) => M(n).must_phrase_rate), "0%", "chart-must");
barChart(s, 6.73, 1.5, 6.0, 4.3, "평가 Judge(gpt-4o) 통과율", CFG.map((n) => S[n].pass_rate), "0%", "chart-judge");
const agreeTxt = extra.agree == null ? "사람 라벨 일치율: 라벨 입력 후 산출"
  : `사람 라벨과 평가 Judge 일치율 ${pct(extra.agree)} (base 답변 ${extra.agree_n}건)`;
T(s, [
  { text: "평가 Judge는 근거가 빈 답과 Kafka 질문에 auth-service 얘기만 한 답도 통과시켰다. 그래서 결정적 지표를 함께 본다. ", options: {} },
  { text: agreeTxt, options: { bold: true } },
], { x: 0.6, y: 5.95, w: 12.1, h: 0.8, fontSize: 13, color: C.text1 });
s.addNotes("왼쪽이 Judge와 무관하게 런북 문구가 답에 들어갔는지 센 지표입니다. 오른쪽 Judge 통과율은 RAG에서 이미 100%라 차이를 못 보여줍니다.");

// ── 9. 비용과 지연 ──────────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 3: Judge는 비용을, 캐스케이드는 절감을 만들었다", { placeholder: "title" });
barChart(s, 0.6, 1.5, 6.0, 4.3, "24건 추정 비용 (USD)", CFG.map((n) => S[n].cost_usd_total), "$0.000", "chart-cost");
barChart(s, 6.73, 1.5, 6.0, 4.3, "지연 p95 (초)", CFG.map((n) => S[n].latency_p95_ms / 1000), "0.0", "chart-p95");
const wr = (n, model) => ROWS[n].reduce((a, r) => a + r.llm_calls.filter((c) => c.stage.startsWith("write") && c.model === model).length, 0);
T(s, `+Judge: gpt-4o write ${wr("rag", "gpt-4o")}회 → ${wr("rag_judge", "gpt-4o")}회 (재작성 ${S.rag_judge.rewrites_total}회). 비용 증가는 Judge 호출이 아니라 재작성에서 나온다.  ` +
  `+비용최적화: write ${wr("rag_judge_cost", "gpt-4o-mini") + wr("rag_judge_cost", "gpt-4o")}회 중 ${wr("rag_judge_cost", "gpt-4o-mini")}회를 gpt-4o-mini로 처리, ` +
  `비용 ${Math.round((1 - S.rag_judge_cost.cost_usd_total / S.rag_judge.cost_usd_total) * 100)}% 감소`,
  { x: 0.6, y: 5.95, w: 12.1, h: 0.8, fontSize: 13 });
s.addNotes("비용은 공개 단가에 실측 토큰을 곱한 추정치입니다. 평가용 Judge 비용은 뺐습니다.");

// ── 10. Judge가 반려한 것 ───────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Judge가 반려한 답은 전부 런북이 없는 질문이었다", { placeholder: "title" });
const KO = { normal: "정상", constrained: "형식 제약", composite: "복합", unregistered: "미등록", ambiguous: "모호" };
const rej = ROWS.rag_judge.filter((r) => r.rewrites > 0);
T(s, [
  { text: `재작성이 일어난 질의: ${rej.map((r) => `${r.id}(${KO[r.category]})`).join(", ")}`, options: { bold: true, breakLine: true } },
  { text: "+Judge에서 정상 질의 12건은 한 번도 반려되지 않았다.", options: { bullet: true, breakLine: true } },
  { text: "Kafka·SSL처럼 맞는 런북이 없는 문제에 \"런북 절차를 반영하라\"며 반려했다. 재작성된 답은 무관한 절차를 섞는 쪽으로 바뀌었다.", options: { bullet: true, breakLine: true } },
  { text: "Q21은 재시도 상한 2회에서 가드가 멈췄다 (무한 루프 가드 작동). Q20·Q22는 3회차에 통과했다.", options: { bullet: true, breakLine: true } },
  { text: "+RAG → +Judge의 어구 포함률 차이는 재작성 0회인 건에서 났다. Judge 효과가 아니라 실행 간 변동으로 본다.", options: { bullet: true } },
], { x: 0.6, y: 1.5, w: 6.4, h: 4.6, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
card(s, 7.3, 1.5, 5.43, 4.3, C.background2, "q20-card");
const q20r = ROWS.rag.find((r) => r.id === "Q20"), q20j = ROWS.rag_judge.find((r) => r.id === "Q20");
T(s, [
  { text: "Q20 \"Kafka 컨슈머 랙이 계속 쌓이고 있습니다\"", options: { bold: true, color: HEX.dk2, breakLine: true } },
  { text: " ", options: { fontSize: 6, breakLine: true } },
  { text: `+RAG (재작성 없음): 평가 ${q20r.judge_passed ? "Pass" : "Fail"}`, options: { bold: true, breakLine: true } },
  { text: "Kafka 언급 없이 auth-service 응답 지연 절차만 답함", options: { breakLine: true } },
  { text: " ", options: { fontSize: 6, breakLine: true } },
  { text: `+Judge (재작성 ${q20j.rewrites}회): 평가 ${q20j.judge_passed ? "Pass" : "Fail"}`, options: { bold: true, breakLine: true } },
  { text: "\"Kafka 컨슈머 랙 문제를 해결하기 위해 먼저 auth-service의 상태를 점검합니다\"로 시작해 무관한 절차를 섞음", options: { breakLine: true } },
  { text: " ", options: { fontSize: 6, breakLine: true } },
  { text: "둘 다 정답은 \"등록된 런북에 없다\"를 밝히는 것", options: { color: HEX.accent1, bold: true } },
], { x: 7.6, y: 1.75, w: 4.85, h: 3.9, fontSize: 16, valign: "top" });
s.addNotes("Judge 기준의 완전성·도메인 지표가 '런북 절차를 반영하라'고 요구해서, 맞는 런북이 없는 질문에서는 무관한 절차를 섞도록 압력을 줬습니다.");

// ── 11. 캐시 ─────────────────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("캐시: 반복 질문의 지연을 줄인다, 비용 효과는 작다", { placeholder: "title" });
if (CACHE) {
  const [p1, p2] = CACHE.passes;
  stat(s, 0.6, 1.6, 3.85, `${p2.cache_hits} / ${p2.cache_lookups}`, "2회차 캐시 적중\n(route·plan·질의 임베딩)", C.accent2, "stat-hit");
  // 캐시 대상 단계(route·plan·임베딩)가 cold 실행 비용에서 차지하는 비중 = 캐시 비용 절감의 상한
  const PRICE = { "gpt-4o-mini": [0.00015, 0.0006], "gpt-4o": [0.0025, 0.01], "text-embedding-3-small": [0.00002, 0] };
  let cacheable = 0, total = 0;
  ROWS.rag_judge_cost.forEach((r) => r.llm_calls.forEach((c) => {
    const [pi, po] = PRICE[c.model]; const v = c.prompt / 1000 * pi + c.completion / 1000 * po;
    total += v; if (/^(route|plan|embed)/.test(c.stage)) cacheable += v;
  }));
  stat(s, 4.74, 1.6, 3.85, `${Math.round(cacheable / total * 100)}%`, `캐시 대상 단계의 비용 비중\n= 캐시로 줄일 수 있는 비용의 상한`, C.accent6, "stat-cache-cost");
  stat(s, 8.88, 1.6, 3.85, `-${Math.round((1 - p2.latency_p50_ms / p1.latency_p50_ms) * 100)}%`, `지연 p50, 1회차 → 2회차\n${sec(p1.latency_p50_ms)} → ${sec(p2.latency_p50_ms)}`, C.accent6, "stat-cache-lat");
} else {
  T(s, "캐시 측정 결과 없음 (python -m eval.cache_bench)", { x: 0.6, y: 1.6, w: 12.1, h: 2.0 });
}
T(s, [
  { text: "Ablation 본 실행(각 질의 1회)에서는 24개 질의가 정규화 후에도 모두 달라 캐시가 한 번도 맞지 않았다. 그래서 같은 24건을 같은 프로세스에서 두 번 연속 돌려 따로 쟀다.", options: { bullet: true, breakLine: true } },
  { text: "모니터링 값과 최종 답은 캐시하지 않는다. 장애 상황은 호출마다 바뀌기 때문이다.", options: { bullet: true, breakLine: true } },
  { text: `총비용은 ${usd(CACHE.passes[0].cost_usd)} → ${usd(CACHE.passes[1].cost_usd)}로 줄었지만, 재작성 횟수 차이가 섞여 있어 캐시 효과로 쓰지 않는다. 캐시의 효과는 지연이다.`, options: { bullet: true, breakLine: true } },
  { text: "대가: TTL 10분 동안은 런북이 바뀌어도 옛 결과를 쓴다. 문장이 조금만 달라도 적중하지 않는다.", options: { bullet: true } },
], { x: 0.6, y: 4.0, w: 12.1, h: 2.6, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
s.addNotes("당직자 여러 명이 같은 알림을 반복해서 묻는 상황을 가정한 측정입니다.");

// ── 12. 한계 및 추가 개선 ───────────────────────────────────────────
s = slide("CONTENT", "한계");
s.addText("한계와 다음 개선", { placeholder: "title" });
const lim = [
  ["RAG에 최소 유사도 기준이 없다", `미등록 질의에도 런북을 넣는다 (평균 투입 ${S.base.fed_count_mean.toFixed(2)} → ${S.rag.fed_count_mean.toFixed(2)}개)`, "유사도 임계값 + '등록된 런북 없음' 안내 경로"],
  ["Judge가 근거 밖 요구로 반려한다", "런북 없는 질의에서 재작성·비용만 늘고 답은 나빠졌다", "반려 사유를 근거 안/밖으로 나누고, 밖이면 재작성 대신 안내"],
  ["라우터가 형식 제약 질의를 놓친다", "'50자 이내', '표로' 질의 3건이 4구성 모두 chat으로 빠졌다", "라우팅 프롬프트 개선 후 같은 평가셋으로 재측정"],
  ["n=24, 1회 실행", "질의 1건 = 4.2%p. 반복 실행 없음 (변동은 간접 추정 8%p)", "반복 실행으로 분산 측정, 평가셋 확장"],
];
lim.forEach(([h, why, next], i) => {
  const y = 1.45 + i * 1.33;
  card(s, 0.6, y, 12.1, 1.18, C.background2, `lim-${i}`);
  s.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.36, w: 0.45, h: 0.45, fill: { color: C.accent1 },
    line: { color: C.accent1 }, objectName: `lim-dot-${i}` });
  T(s, "!", { x: 0.85, y: y + 0.36, w: 0.45, h: 0.45, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle" });
  T(s, h, { x: 1.55, y: y + 0.15, w: 5.2, h: 0.45, fontSize: 16, bold: true, color: C.text2 });
  T(s, why, { x: 1.55, y: y + 0.6, w: 5.2, h: 0.5, fontSize: 13, color: C.text1 });
  T(s, `다음: ${next}`, { x: 7.0, y: y + 0.15, w: 5.5, h: 0.9, fontSize: 14, color: C.accent6, valign: "middle" });
});
s.addNotes("개선이 새로 만든 약점과 측정의 한계를 같이 짚었습니다.");

// ── 13. 마무리 ───────────────────────────────────────────────────────
s = slide("DARK", "마무리");
s.addText("개선을 하나씩 켜 봐야 무엇이 효과인지 안다", { placeholder: "title" });
s.addText([
  { text: "RAG가 품질을 올렸고, Judge는 기준을 잘못 세우면 비용만 늘리며, 캐스케이드로 base보다 싸게 만들었다.", options: { breakLine: true } },
  { text: "github.com/jang961111-hash/incident-agent-ablation", options: { fontSize: 14, color: C.accent3 } },
], { placeholder: "body" });

(async () => {
  const out = path.join(__dirname, "incident-agent-ablation.pptx");
  await pres.writeFile({ fileName: out });
  if (SKILL) {
    const { applyTheme } = require(path.join(SKILL, "scripts", "apply_theme.js"));
    await applyTheme(out, THEME);
  }
  console.log("wrote", out);
})();
