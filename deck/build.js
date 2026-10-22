// 발표 덱 생성기 v2 — 모든 수치를 deck/data.json (data.py 가 results/ 에서 추출)에서 읽는다.
//   ../.venv/bin/python data.py > data.json && NODE_PATH=node_modules node build.js
// 1차(4구성 x 24건) 덱 생성기는 build_v1.js 로 보존.
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const D = JSON.parse(fs.readFileSync(path.join(__dirname, "data.json")));
const CFG = D.configs;
const LABEL = { base: "base", rag: "+RAG", judge: "+Judge만", rag_judge: "RAG+Judge",
  rag_judge_cost: "+비용", rag_judge_v2: "+v2 보완", final: "final" };
const H = D.holdout, X = D.extra_holdout;
const pct = (v) => `${Math.round(v * 100)}%`;
const pp = (v) => `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%p`;
const usd = (v, d = 4) => `$${v.toFixed(d)}`;
const sec = (ms) => `${(ms / 1000).toFixed(1)}초`;

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
const FONT = "Arial";   // 차트 글꼴: LibreOffice·PowerPoint 모두에서 안전 (한글은 시스템 글꼴로 대체)
const BAR = { base: HEX.accent3, rag: HEX.accent2, judge: "B9A15A", rag_judge: HEX.accent4,
  rag_judge_cost: "6E9C8F", rag_judge_v2: "2C7A99", final: HEX.accent6 };

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
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.8,
      fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 1.8,
      fontSize: 18, color: C.background2, valign: "top", align: "left" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85,
      fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } },
    { text: { text: "SKALA 4기 AI Mini-Project · 과제1 · 장병헌", options: {
      x: 0.6, y: 7.0, w: 7, h: 0.3, fontSize: 10, color: C.accent3, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent3, align: "right" },
});

let curSec = "";
const slide = (master, section) => {
  if (section !== curSec) { pres.addSection({ title: section }); curSec = section; }
  return pres.addSlide({ masterName: master, sectionTitle: section });
};
const T = (s, text, o) => s.addText(text, { isTextBox: true, margin: 0, fontSize: 15, color: C.text1, ...o });
const card = (s, x, y, w, h, fill, name) => s.addShape(pres.shapes.ROUNDED_RECTANGLE,
  { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name });
const stat = (s, x, y, w, big, small, color, name, h = 2.0) => {
  card(s, x, y, w, h, C.background2, name);
  T(s, big, { x: x + 0.3, y: y + 0.22, w: w - 0.6, h: 0.95, fontSize: 36, bold: true, color });
  T(s, small, { x: x + 0.3, y: y + 1.2, w: w - 0.6, h: h - 1.3, fontSize: 13.5, color: C.text1, valign: "top" });
};
const src = (s, text, y = 6.62) => T(s, text, { x: 0.6, y, w: 12.1, h: 0.3, fontSize: 10.5, color: C.accent3 });
const chartBase = (title, colors) => ({
  showTitle: true, title, titleFontSize: 13, titleColor: HEX.dk2, titleFontFace: FONT,
  showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: HEX.dk1,
  dataLabelFontFace: FONT, catAxisLabelFontFace: FONT, valAxisLabelFontFace: FONT,
  catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 11, valAxisHidden: true,
  valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
  chartColors: colors, barGapWidthPct: 50,
});
const bar = (s, x, y, w, h, title, vals, fmt, name) => s.addChart(pres.charts.BAR, [{
  name: title, labels: CFG.map((n) => LABEL[n]), values: vals }], {
  x, y, w, h, barDir: "col", ...chartBase(title, CFG.map((n) => BAR[n])), dataLabelFormatCode: fmt,
  valAxisMinVal: 0, objectName: name });
const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.lt1, fill: { color: HEX.dk2 } } });
const TBL = { fontSize: 12.5, color: HEX.dk1, border: { type: "solid", color: "D5DCE4", pt: 0.75 },
  align: "left", valign: "middle" };

const nHold = 36, nDev = 24;
const agree = D.agreement || {};
const hasLabels = (agree.n_compared || 0) > 0;
const st = (D.stats_holdout || { pairs: [] }).pairs;
const pair = (a, b) => st.find((p) => p.a === a && p.b === b);

// ── 1. 표지 ──────────────────────────────────────────────────────────
let s = slide("DARK", "표지");
s.addText("개선 효과를 통계로 분리하고, AI 평가자의 관대함까지 쟀다", { placeholder: "title" });
s.addText([
  { text: "인시던트 대응 에이전트 개선을 하나씩 켠 7구성 Ablation · 조정에 쓰지 않은 holdout 36건 · 3회 반복", options: { breakLine: true } },
  { text: "SKALA 4기 AI Mini-Project 과제1 · 광주 2반 장병헌 (G062)", options: { fontSize: 14, color: C.accent3 } },
], { placeholder: "body" });
s.addNotes("개선을 많이 붙인 게 아니라, 어떤 개선이 실제로 효과였는지를 통계로 분리했고, 채점한 AI 평가자가 얼마나 관대한지도 다른 평가자와 대조해 쟀습니다.");

// ── 1-1. 한 장 요약 (ChatGPT 그림, 수치는 results/ 실측) ─────────────────
s = slide("CONTENT", "요약");
s.addText("한 장 요약: 무엇을 고쳤고, 무엇이 효과였나", { placeholder: "title" });
{
  const FIG = path.join(__dirname, "..", "docs", "figures");
  const h = 4.85, wW = h, iW = h * 1122 / 1402, gap = 0.45;
  const x0 = (13.333 - (wW + gap + iW)) / 2;
  s.addImage({ path: path.join(FIG, "gpt_webtoon.png"), x: x0, y: 1.35, w: wW, h, altText: "4컷 웹툰: 새벽 당직, 스위치 켜기, 맞는 매뉴얼, 채점관 검사", objectName: "summary-webtoon" });
  s.addImage({ path: path.join(FIG, "gpt_infographic.png"), x: x0 + wW + gap, y: 1.35, w: iW, h, altText: "결과 숫자 5개 인포그래픽", objectName: "summary-infographic" });
}
src(s, "그림은 ChatGPT로 생성 · 그림 속 숫자는 results/*_latest.json, 실제 API 벤치 실측값", 6.4);
s.addNotes("새벽 당직자가 DB가 죽었다고 물어도 원본은 응답 지연 매뉴얼을 꺼냈습니다. 고친 부분을 하나씩 켜고 끄며 효과를 쟀고, 채점하는 AI도 검사했습니다. 결과 숫자는 오른쪽 다섯 개입니다.");

// ── 2. 결론 ──────────────────────────────────────────────────────────
s = slide("CONTENT", "요약");
s.addText("결론: 조치 정확도는 RAG가, 비용은 캐스케이드가 낮췄다", { placeholder: "title" });
stat(s, 0.6, 1.5, 3.85, `${pct(X.base.miss_runbook_rate)} → ${pct(X.final.miss_runbook_rate)}`,
  "정답 런북 누락률 (base → final)\n= 맞는 조치를 권고하지 못할 위험", C.accent2, "stat-miss");
stat(s, 4.74, 1.5, 3.85, `-${Math.round((1 - X.final.cost_per_incident / X.base.cost_per_incident) * 100)}%`,
  `장애 1건당 처리 비용 ${usd(X.base.cost_per_incident, 5)} → ${usd(X.final.cost_per_incident, 5)}\n(캐스케이드만 켜면 -${Math.round((1 - X.rag_judge_cost.cost_per_incident / X.base.cost_per_incident) * 100)}%)`, C.accent6, "stat-cost");
const pj = pair("base", "judge");
stat(s, 8.88, 1.5, 3.85, "개선 미확인",
  `LLM Judge 단독: 품질 향상 확인 안 됨\n지연은 +${pj.latency.diff.toFixed(1)}초 (유의)`, C.accent1, "stat-judge");
card(s, 0.6, 3.85, 12.1, 1.95, C.background2, "method");
T(s, [
  { text: "어떻게 증명했나", options: { bold: true, fontSize: 16, color: HEX.dk2, breakLine: true } },
  { text: `평가셋 60건을 dev ${nDev}건(기준값 조정용)과 holdout ${nHold}건(조정 전에 고정, 최종 보고용)으로 나눴다. 이 덱의 수치는 모두 holdout.`, options: { bullet: true, breakLine: true } },
  { text: "개선을 하나씩 켠 7구성을 각 3회 반복하고, 구성 간 차이는 같은 질의끼리 짝지은 bootstrap 95% 신뢰구간으로 판정했다.", options: { bullet: true, breakLine: true } },
  { text: hasLabels ? `평가자(LLM Judge) 판정은 사람 지표별 라벨 ${agree.n_compared}건과 대조했다 (종합 kappa ${agree.metrics.overall.kappa != null ? agree.metrics.overall.kappa.toFixed(2) : "-"}).`
    : "평가자(LLM Judge)가 관대할 수 있어, Judge와 무관한 결정적 지표(정답 런북 누락·혼입, 런북 어구 포함)로 결론을 냈다.", options: { bullet: true } },
], { x: 0.9, y: 4.0, w: 11.5, h: 1.75, fontSize: 14.5, paraSpaceAfter: 5, valign: "top" });
src(s, "출처: results/*_latest.json (7구성 x 60건 x 3회 = 1,260회, 실행 오류 0), results/stats_holdout.json, eval/extra_metrics.py");
s.addNotes("세 숫자가 결론입니다. 그리고 이 숫자를 어떻게 믿을 수 있는지가 이 발표의 나머지입니다.");

// ── 3. 왜 중요한가 (운영 시나리오) ───────────────────────────────────
s = slide("CONTENT", "문제");
s.addText("운영팀이 AI 에이전트 도입을 결정하려면 세 가지를 알아야 한다", { placeholder: "title" });
const q3 = [
  ["맞는 조치를 권고하나", "새벽 2시 당직자가 \"DB 프라이머리가 죽었다\"고 물었는데 응답 지연 절차를 주면, 그 답은 장애를 키운다.",
    "정답 런북 누락률 · 무관 런북 혼입률", C.accent1],
  ["그 판정을 믿어도 되나", "\"AI가 채점했더니 97점\"은 채점한 AI가 관대하면 의미가 없다. 평가자 자체를 검증해야 한다.",
    "독립 평가자와의 일치도 (kappa, 사람 표본은 예정) · Judge 무관 지표", C.accent4],
  ["얼마에, 얼마나 빨리", "품질을 올린 대가로 비용과 지연이 얼마나 늘었는지, 장애가 겹쳐 들어오거나 도구가 죽어도 버티는지.",
    "장애 1건당 비용 · p95 지연 · 동시 처리 · 장애 주입", C.accent2],
];
q3.forEach(([h, body, metric, color], i) => {
  const x = 0.6 + i * 4.14;
  card(s, x, 1.5, 3.85, 3.55, C.background2, `q3-${i}`);
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.75, w: 0.55, h: 0.55, fill: { color }, line: { color }, objectName: `q3-dot-${i}` });
  T(s, String(i + 1), { x: x + 0.3, y: 1.75, w: 0.55, h: 0.55, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
  T(s, h, { x: x + 1.0, y: 1.75, w: 2.7, h: 0.55, fontSize: 17, bold: true, color: C.text2, valign: "middle" });
  T(s, body, { x: x + 0.3, y: 2.55, w: 3.3, h: 2.0, fontSize: 14, valign: "top" });
  T(s, `→ ${metric}`, { x: x + 0.3, y: 4.05, w: 3.3, h: 0.9, fontSize: 13, bold: true, color: C.accent6, valign: "top" });
});
T(s, "이 프로젝트는 기능을 더하는 것보다, 도입 판단에 쓸 수 있는 평가 체계를 만드는 데 무게를 뒀다.",
  { x: 0.6, y: 5.4, w: 12.1, h: 0.5, fontSize: 16, bold: true, color: C.text2 });
s.addNotes("SK AX가 고객사에 에이전트를 넣을 때 받는 질문 세 가지입니다. 이후 모든 지표는 이 세 질문에 대한 답입니다.");

// ── 4. 문제 1 ─────────────────────────────────────────────────────────
s = slide("CONTENT", "문제");
s.addText("문제 1: base는 질문을 읽지 않고, 알림 키워드로 런북을 고른다", { placeholder: "title" });
const flow = [
  ["사용자 질의", "\"DB 프라이머리가\n다운됐습니다\"", C.background2],
  ["planner", "시스템명 없음\n→ auth-service 폴백", C.background2],
  ["모니터링 알림", "\"p95 latency 2.4s\"\n키워드 'latency' 일치", C.background2],
  ["선택된 런북", "high-latency\n(응답 지연 절차)", C.accent1],
];
flow.forEach(([h, b, fill], i) => {
  const x = 0.6 + i * 3.1;
  card(s, x, 1.5, 2.7, 1.9, fill, `flow-${i}`);
  T(s, h, { x: x + 0.2, y: 1.65, w: 2.3, h: 0.4, fontSize: 14, bold: true, color: fill === C.accent1 ? C.background1 : C.text2 });
  T(s, b, { x: x + 0.2, y: 2.1, w: 2.3, h: 1.2, fontSize: 15, color: fill === C.accent1 ? C.background1 : C.text1, valign: "top" });
  if (i < 3) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + 2.75, y: 2.25, w: 0.3, h: 0.4,
    fill: { color: C.accent3 }, line: { color: C.accent3 }, objectName: `arrow-${i}` });
});
stat(s, 0.6, 3.75, 3.85, pct(X.base.miss_runbook_rate), "holdout에서 base가 정답 런북을\n근거에 못 넣은 비율", C.accent1, "stat-basemiss");
stat(s, 4.74, 3.75, 3.85, `${pct(X.base["recall@1[aligned]"])} vs ${pct(X.base["recall@1[paraphrased]"])}`,
  "알림 문구대로 물을 때 vs 자기 말로\n물을 때 base Recall@1 (편향 검증)", C.accent1, "stat-bias");
T(s, [
  { text: "원인 (src/agent/graph.py:192-213)", options: { bold: true, breakLine: true } },
  { text: "조사한 시스템의 알림 문구에서 키워드를 순서대로 찾아 첫 일치로 런북 1개를 고른다.", options: { bullet: true, breakLine: true } },
  { text: "질의 문장은 쓰지 않는다. 당직자가 알림과 다른 말로 물으면 거의 맞히지 못한다.", options: { bullet: true } },
], { x: 9.0, y: 3.75, w: 3.73, h: 2.6, fontSize: 13.5, paraSpaceAfter: 5, valign: "top" });
src(s, `holdout 정상 질의 aligned ${X.base["n[aligned]"]}건 / paraphrased ${X.base["n[paraphrased]"]}건, 3회 평균`);
s.addNotes("평가셋을 알림 문구와 같은 말로 묻는 질문과 자기 말로 묻는 질문으로 나눠 봤습니다. base는 자기 말로 물으면 거의 못 맞힙니다.");

// ── 5. 문제 2 ─────────────────────────────────────────────────────────
s = slide("CONTENT", "문제");
s.addText("문제 2: 검증은 형식만 보고, 모델 분리는 이미 돼 있었다", { placeholder: "title" });
card(s, 0.6, 1.5, 5.9, 3.8, C.background2, "validator-card");
T(s, "규칙 Validator", { x: 0.9, y: 1.7, w: 5.3, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
T(s, "len(draft) >= 30 and \"1)\" in draft", { x: 0.9, y: 2.3, w: 5.3, h: 0.5, fontSize: 15, fontFace: "Courier New", color: C.accent1 });
T(s, [
  { text: "질문과 맞는지, 근거에 있는지는 보지 않는다.", options: { bullet: true, breakLine: true } },
  { text: `실측: base 60건 x 3회에서 반려 ${D.summary.base.rewrites_total}회. 응답 지연 절차로 DB 다운에 답해도 통과한다.`, options: { bullet: true } },
], { x: 0.9, y: 3.0, w: 5.3, h: 2.2, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
card(s, 6.83, 1.5, 5.9, 3.8, C.background2, "tiering-card");
T(s, "계획했던 비용 개선", { x: 7.13, y: 1.7, w: 5.3, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
T(s, "fast = gpt-4o-mini / quality = gpt-4o", { x: 7.13, y: 2.3, w: 5.3, h: 0.5, fontSize: 15, fontFace: "Courier New", color: C.accent2 });
T(s, [
  { text: "'역할별 모델 분리'는 base에 이미 있었다 (src/server.py:50-56).", options: { bullet: true, breakLine: true } },
  { text: "그래서 비용 축을 다시 정했다: 1차 초안은 저가 모델, 반려될 때만 gpt-4o (캐스케이드) + 반복 질의 캐시.", options: { bullet: true } },
], { x: 7.13, y: 3.0, w: 5.3, h: 2.2, fontSize: 15, paraSpaceAfter: 8, valign: "top" });
T(s, "→ 개선 대상: 런북 선택(RAG) · 검증 기준(LLM Judge) · 비용(캐스케이드·캐시) · 운영 안정성(비동기·부분 실패)",
  { x: 0.6, y: 5.65, w: 12.1, h: 0.6, fontSize: 16, bold: true, color: C.accent6 });

// ── 6. 개선: 7구성 ───────────────────────────────────────────────────
s = slide("CONTENT", "개선");
s.addText("개선: 원본 노드는 그대로, 플래그로 하나씩 켜는 7구성", { placeholder: "title" });
const O = "O", N = "";
s.addTable([
  [hdr("구성"), hdr("RAG"), hdr("Judge"), hdr("캐스케이드·캐시"), hdr("v2 보완"), hdr("런타임"), hdr("알 수 있는 것")],
  ["base", N, N, N, N, N, "원본 (Before)"],
  ["+RAG", O, N, N, N, N, "RAG 단독"],
  ["+Judge만", N, O, N, N, N, "Judge 단독"],
  ["RAG+Judge", O, O, N, N, N, "RAG 위 Judge"],
  ["+비용", O, O, O, N, N, "절감의 품질 대가"],
  ["+v2 보완", O, O, N, O, N, "약점 보완 효과"],
  ["final", O, O, O, O, O, "최종 (After)"],
], { ...TBL, x: 0.6, y: 1.45, w: 7.4, colW: [1.25, 0.7, 0.75, 1.4, 0.9, 0.85, 1.55], fontSize: 12, rowH: 0.42, objectName: "config-table" });
T(s, [
  { text: "v2 보완 = 1차 실측(24건)에서 찾은 약점", options: { bold: true, breakLine: true } },
  { text: "RAG 최소 유사도: 맞는 런북이 없으면 넣지 않고 '없음'을 알림", options: { bullet: true, breakLine: true } },
  { text: "Judge v2: 근거 밖 요구 금지, 고칠 수 없는 반려는 재작성 생략", options: { bullet: true, breakLine: true } },
  { text: "수치 코드 검증: 근거에 없는 수치는 Judge 호출 전에 반려", options: { bullet: true, breakLine: true } },
  { text: " ", options: { fontSize: 6, breakLine: true } },
  { text: "런타임", options: { bold: true, breakLine: true } },
  { text: "비동기 I/O: 동기 LLM 호출을 스레드로 빼 이벤트 루프 블로킹 제거", options: { bullet: true, breakLine: true } },
  { text: "부분 실패 허용: 도구 하나가 죽어도 나머지 결과로 답함", options: { bullet: true } },
], { x: 8.35, y: 1.45, w: 4.4, h: 4.6, fontSize: 13, paraSpaceAfter: 4, valign: "top" });
src(s, "원본 src/agent 는 이식 커밋(55e15f1) 이후 변경 0. base 는 원본 build_graph 를 그대로 호출. 개선은 src/ext/ 에 플래그로.", 6.35);

// ── 7. 평가 설계 ─────────────────────────────────────────────────────
s = slide("CONTENT", "평가 설계");
s.addText("평가: 조정에 쓰지 않은 질의로, 반복해서, 짝지어 비교했다", { placeholder: "title" });
const ev = [
  ["평가셋 60건", `dev ${nDev}건: v2 기준값(RAG 최소 유사도) 조정에만 사용\nholdout ${nHold}건: v2 구현 전에 고정해 커밋, 최종 보고에만 사용\n정상 30 · 형식 제약 8 · 복합 8 · 미등록 7 · 모호 7`],
  ["반복과 유의성", "7구성 x 60건 x 3회 = 1,260회 실행\n반복 간 95% CI (t 분포)\n구성 간 차이는 질의 단위 paired bootstrap 2,000회"],
  ["측정 축 분리", "검색: Recall@k, 정답 런북 누락·혼입\n답변: 평가 Judge 4지표 + 런북 어구 포함(결정적)\n운영: 건당 비용, p50/p95 지연, 재작성, 동시성, 장애 주입"],
  ["평가자 검증", hasLabels ? "평가 Judge는 gpt-4o로 고정 (파이프라인 Judge gpt-4o-mini와 분리)\n독립 평가자(Claude) 블라인드 60건 + 사람 표본 블라인드 라벨\n→ 지표별 kappa, 오판 유형"
    : "평가 Judge는 gpt-4o로 고정 (파이프라인 Judge gpt-4o-mini와 분리)\n독립 평가자(Claude, LLM) 블라인드 60건 → 지표별 kappa, 오판 유형\n사람 표본 20건 라벨은 아직 없음"],
];
ev.forEach(([h, body], i) => {
  const x = 0.6 + (i % 2) * 6.13, y = 1.45 + Math.floor(i / 2) * 2.55;
  card(s, x, y, 5.97, 2.35, C.background2, `ev-${i}`);
  T(s, h, { x: x + 0.3, y: y + 0.2, w: 5.4, h: 0.45, fontSize: 17, bold: true, color: C.text2 });
  T(s, body, { x: x + 0.3, y: y + 0.75, w: 5.4, h: 1.5, fontSize: 13.5, valign: "top" });
});
s.addNotes("holdout은 개선 v2를 만들기 전에 커밋해 고정했습니다. 커밋 시각으로 증명됩니다.");

// ── 8. B/A 1: 조치 정확도 ────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 1: 누락은 RAG가, 무관 런북 혼입은 v2가 줄였다", { placeholder: "title" });
bar(s, 0.6, 1.4, 6.0, 4.7, "정답 런북 누락률 (낮을수록 좋음)", CFG.map((n) => X[n].miss_runbook_rate), "0%", "chart-miss");
bar(s, 6.73, 1.4, 6.0, 4.7, "무관 런북 혼입률 (낮을수록 좋음)", CFG.map((n) => X[n].wrong_runbook_rate), "0%", "chart-wrong");
src(s, `holdout, 3회 평균. 누락·혼입은 장애 경로 질의 기준. Recall@1·MRR은 gold 있는 holdout 질의 전체 기준: ${pct(H.base["recall@1"])} → ${pct(H.rag["recall@1"])}, MRR ${H.base.mrr.toFixed(2)} → ${H.rag.mrr.toFixed(2)}. 누락 = 맞는 조치를 못 줄 위험, 혼입 = 잘못된 조치를 섞을 위험`, 6.25);
s.addNotes("왼쪽은 RAG를 켜는 순간 떨어지고, 오른쪽은 v2의 최소 유사도 기준을 켜는 순간 떨어집니다. 개선마다 고친 문제가 다릅니다.");

// ── 9. B/A 2: 기여도 분해 ────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 2: 개선별 기여도 — 같은 질의끼리 짝지어 비교했다", { placeholder: "title" });
const cellOf = (r, k, u) => {
  if (!r) return { text: "-" };
  const v = u === "$" ? `${r.diff >= 0 ? "+" : ""}${r.diff.toFixed(4)}` : u === "s" ? `${r.diff >= 0 ? "+" : ""}${r.diff.toFixed(1)}초`
    : `${r.diff >= 0 ? "+" : ""}${Math.round(r.diff * 100)}%p`;
  const good = { hit1: 1, must: 1, pass: 1, miss: -1, wrong: -1, cost: -1, latency: -1 }[k];
  const fill = !r.significant ? null : (Math.sign(r.diff) === good ? "D7EFE6" : "FBE3D3");
  return { text: v + (r.significant ? " ★" : ""), options: fill ? { fill: { color: fill }, bold: true } : {} };
};
const keys = [["miss", "%"], ["wrong", "%"], ["must", "%"], ["pass", "%"], ["cost", "$"], ["latency", "s"]];
const rowsT = [[hdr("켠 것"), hdr("정답 누락"), hdr("무관 혼입"), hdr("어구 포함"), hdr("Judge 통과"), hdr("질의당 비용"), hdr("질의당 지연")]];
st.forEach((p) => rowsT.push([{ text: p.label, options: { bold: p.a === "base" && p.b === "final" } },
  ...keys.map(([k, u]) => cellOf(p[k], k, u))]));
s.addTable(rowsT, { ...TBL, x: 0.6, y: 1.4, w: 12.1, colW: [3.1, 1.45, 1.45, 1.45, 1.45, 1.6, 1.6], rowH: 0.5, objectName: "contrib-table" });
T(s, "★ = 95% 신뢰구간이 0을 포함하지 않음 (holdout 36건, 질의 단위 paired bootstrap 2,000회). 초록 = 좋아짐, 주황 = 나빠짐. 표시 없는 칸은 차이가 있다고 말할 수 없음. 캐스케이드·v2 위 비용·전체 행의 지연은 재측정 부하(2프로세스 vs 7프로세스) 차이가 섞였을 수 있음.",
  { x: 0.6, y: 5.55, w: 12.1, h: 0.7, fontSize: 11.5 });
src(s, "results/stats_holdout.json · eval/stats.py", 6.3);
s.addNotes("이 표가 핵심입니다. RAG 행에 품질 별표가 몰려 있고, Judge 행에는 비용과 지연 별표만 있습니다.");

// ── 10. 트레이드오프 한 장 ───────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("Before/After 3: 품질을 얻은 대가 — 트레이드오프 한 장", { placeholder: "title" });
const trow = (n) => [{ text: LABEL[n], options: { bold: n === "final" || n === "base" } },
  pct(X[n].miss_runbook_rate), pct(X[n].wrong_runbook_rate), pct(H[n].must_phrase_rate), pct(H[n].pass_rate),
  usd(X[n].cost_per_incident, 5), sec(H[n].latency_p95_ms), H[n].rewrites_total.toFixed(1)];
s.addTable([[hdr("구성"), hdr("정답 누락"), hdr("무관 혼입"), hdr("어구 포함"), hdr("Judge 통과"), hdr("장애 1건당 비용"), hdr("p95 지연"), hdr("재작성")],
  ...CFG.map(trow)], { ...TBL, x: 0.6, y: 1.4, w: 12.1, colW: [1.9, 1.35, 1.35, 1.35, 1.35, 1.9, 1.5, 1.4], fontSize: 13, rowH: 0.48, objectName: "tradeoff-table" });
T(s, [
  { text: "읽는 법", options: { bold: true, breakLine: true } },
  { text: "Judge를 붙이면 비용과 지연이 오르지만, 품질 지표는 신뢰구간 안에서 움직이지 않았다.", options: { bullet: true, breakLine: true } },
  { text: `캐스케이드는 장애 1건당 비용을 크게 줄이는 대신 런북 어구 포함이 내려갔다 (${pp(pair("rag_judge", "rag_judge_cost").must.diff)}, 유의하지 않음). 이 대가를 받아들일지는 운영 정책의 선택이다.`, options: { bullet: true } },
], { x: 0.6, y: 5.45, w: 12.1, h: 1.15, fontSize: 13.5, paraSpaceAfter: 4, valign: "top" });
src(s, "holdout 36건, 3회 평균. 비용은 OpenAI 공개 단가 x 실측 토큰 추정치 (평가 Judge 제외). 지연: 5구성은 7프로세스 동시 부하, +비용·final은 캐시 버그 수정 뒤 2프로세스로 재측정 → 두 구성의 지연 차이엔 부하 차이가 섞였을 수 있음", 6.68);

// ── 11. v2 보완 ──────────────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("1차 실측이 찾은 약점을 v2가 고쳤고, holdout에서 확인했다", { placeholder: "title" });
stat(s, 0.6, 1.5, 3.85, `${pct(H.rag_judge["pass_rate[unregistered]"])} → ${pct(H.rag_judge_v2["pass_rate[unregistered]"])}`,
  "미등록 질의 평가 통과율 (4건 x 3회)\n전체 통과율 차이는 유의하지 않음", C.accent2, "stat-unreg");
stat(s, 4.74, 1.5, 3.85, `${pct(X.rag_judge.wrong_runbook_rate)} → ${pct(X.rag_judge_v2.wrong_runbook_rate)}`,
  "무관 런북 혼입률\n최소 유사도 기준 (dev로만 정함)", C.accent2, "stat-wrong");
stat(s, 8.88, 1.5, 3.85, `${H.rag_judge.rewrites_total.toFixed(1)} → ${H.rag_judge_v2.rewrites_total.toFixed(1)}`,
  "Judge 재작성 (holdout 36건, 회당)\n근거 밖 요구를 하지 않게 함", C.accent2, "stat-rw");
T(s, [
  { text: "1차 실측(dev 24건)에서 본 문제", options: { bold: true, breakLine: true } },
  { text: "Kafka처럼 런북이 없는 질문에 Judge가 '런북 절차를 반영하라'며 반려 → 답이 무관한 절차를 섞는 쪽으로 바뀜", options: { bullet: true, breakLine: true } },
  { text: "RAG가 유사도와 상관없이 늘 런북을 넣음", options: { bullet: true, breakLine: true } },
  { text: " ", options: { fontSize: 6, breakLine: true } },
  { text: `주의: 최소 유사도 ${D.calibrate ? D.calibrate.min_score : "-"}는 dev에서 정답 있는 질의와 없는 질의의 간격이 ${D.calibrate ? D.calibrate.gap : "-"}뿐인 경계값이다. holdout에서 정답 누락은 ${pct(X.rag_judge.miss_runbook_rate)} → ${pct(X.rag_judge_v2.miss_runbook_rate)}로 거의 늘지 않았다.`, options: { bullet: true, color: HEX.accent1 } },
], { x: 0.6, y: 3.8, w: 12.1, h: 2.6, fontSize: 14, paraSpaceAfter: 5, valign: "top" });

// ── 12. 운영 안정성 ──────────────────────────────────────────────────
s = slide("CONTENT", "Before/After");
s.addText("운영 안정성: 동시 요청, 도구 장애, 반복 질문", { placeholder: "title" });
if (D.concurrency) {
  const runs = D.concurrency.runs;
  const ns = [...new Set(runs.map((r) => r.n))];
  const wall = (a) => ns.map((n) => runs.find((r) => r.n === n && r.async_io === a).wall_ms / 1000);
  s.addChart(pres.charts.BAR, [
    { name: "동기 (원본 방식)", labels: ns.map((n) => `동시 ${n}건`), values: wall(false) },
    { name: "비동기 I/O", labels: ns.map((n) => `동시 ${n}건`), values: wall(true) },
  ], { x: 0.6, y: 1.4, w: 6.2, h: 4.4, barDir: "col", ...chartBase(D.concurrency.backend === "fake_slow" ? "동시 N건 처리 시간 (초) — 모의 LLM, 호출당 0.5초 동기 지연" : "동시 N건 처리에 걸린 시간 (초)", [HEX.accent3, HEX.accent6]),
    showLegend: true, legendPos: "b", legendFontFace: FONT, legendFontSize: 11,
    dataLabelFormatCode: "0.0", valAxisMinVal: 0, objectName: "chart-conc" });
} else {
  T(s, "동시성 벤치 결과 없음 (python -m eval.concurrency_bench)", { x: 0.6, y: 1.4, w: 6.2, h: 1 });
}
const fv = D.fault && D.fault.variants;
if (fv) {
  card(s, 7.1, 1.4, 5.63, 2.25, C.background2, "fault-card");
  T(s, [
    { text: `도구 장애 주입 (모니터링 호출 ${Math.round(D.fault.rate * 100)}% 실패)`, options: { bold: true, color: HEX.dk2, breakLine: true } },
    { text: D.fault.backend === "fake" ? "장애를 맞은 질의 중 끝까지 답한 건수 (LLM 없이 코드 경로만 측정)" : "장애를 맞은 질의 중 끝까지 답한 건수", options: { fontSize: 12, color: HEX.accent3, breakLine: true } },
    { text: `base ${fv.base.completed_among_faulted}/${fv.base.queries_with_fault} · 허용 끔 ${fv.final_no_tolerance.completed_among_faulted}/${fv.final_no_tolerance.queries_with_fault} · final ${fv.final.completed_among_faulted}/${fv.final.queries_with_fault}`, options: { fontSize: 17, bold: true, color: HEX.accent6 } },
  ], { x: 7.4, y: 1.55, w: 5.1, h: 2.0, fontSize: 14, valign: "top" });
}
if (D.cache) {
  const [c1, c2] = D.cache.passes;
  card(s, 7.1, 3.85, 5.63, 1.95, C.background2, "cache-card");
  T(s, [
    { text: "반복 질문 캐시 (같은 60건 2회, 실제 API)", options: { bold: true, color: HEX.dk2, breakLine: true } },
    { text: `2회차 적중 ${c2.cache_hits}/${c2.cache_lookups}, 지연 p50 ${sec(c1.latency_p50_ms)} → ${sec(c2.latency_p50_ms)}`, options: { fontSize: 16, bold: true, color: HEX.accent6, breakLine: true } },
    { text: `route·plan·임베딩만 캐시 (final 비용의 ${pct(D.cacheable_share_final)}). 1회차 → 2회차 비용 ${usd(c1.cost_usd)} → ${usd(c2.cost_usd)}. 모니터링·답변은 캐시하지 않음.`, options: { fontSize: 12 } },
  ], { x: 7.4, y: 4.0, w: 5.1, h: 1.7, fontSize: 14, valign: "top" });
}
src(s, (D.concurrency && D.concurrency.backend === "fake_slow" ? "동시성·장애 주입은 API 없이 측정 (results/*_simulated·_fake_latest.json)" : "동시성·장애 주입·캐시 모두 실제 API (results/concurrency_bench_latest.json · fault_bench_latest.json · cache_bench_latest.json). 동시성은 N마다 1회 측정"), 6.1);
s.addNotes("원본은 노드가 async여도 LLM 호출이 동기라 동시 요청이 줄을 섭니다. 도구 하나가 죽으면 질의 전체가 실패합니다. 둘 다 고쳤습니다.");

// ── 13. 평가자 검증 ──────────────────────────────────────────────────
s = slide("CONTENT", "평가자 검증");
s.addText("평가자 검증: AI 채점을 그대로 믿지 않았다", { placeholder: "title" });
bar(s, 0.6, 1.4, 6.0, 4.3, "평가 Judge 통과율 (holdout)", CFG.map((n) => H[n].pass_rate), "0%", "chart-pass");
if (hasLabels) {
  const m = agree.metrics;
  const kv = (k) => (m[k] && m[k].kappa != null ? m[k].kappa.toFixed(2) : "-");
  const ag = (k) => (m[k] && m[k].agreement != null ? pct(m[k].agreement) : "-");
  const len = (k) => (m[k] && m[k].leniency != null ? pct(m[k].leniency) : "-");
  s.addTable([[hdr("지표"), hdr("일치율"), hdr("kappa"), hdr("관대함*")],
    ["관련성", ag("relevance"), kv("relevance"), len("relevance")],
    ["완전성", ag("completeness"), kv("completeness"), len("completeness")],
    ["도메인 적합성", ag("domain_appropriateness"), kv("domain_appropriateness"), len("domain_appropriateness")],
    ["명확성", ag("clarity"), kv("clarity"), len("clarity")],
    [{ text: "종합 (3/4)", options: { bold: true } }, ag("overall"), kv("overall"), len("overall")]],
  { ...TBL, x: 6.9, y: 1.5, w: 5.83, colW: [1.9, 1.3, 1.3, 1.33], fontSize: 13, rowH: 0.45, objectName: "kappa-table" });
  T(s, `사람 라벨 ${agree.n_compared}건 (base 답변, 지표별 블라인드). * 관대함 = 사람이 Fail로 본 답을 Judge가 Pass로 준 비율`,
    { x: 6.9, y: 4.35, w: 5.83, h: 0.7, fontSize: 11.5, color: C.accent3 });
} else if (D.claude_agreement && D.claude_agreement.metrics) {
  const m = D.claude_agreement.metrics;
  const kv = (k) => (m[k] && m[k].kappa != null ? m[k].kappa.toFixed(2) : "-");
  const ag = (k) => (m[k] && m[k].agreement != null ? pct(m[k].agreement) : "-");
  const len = (k) => (m[k] && m[k].leniency != null ? pct(m[k].leniency) : "-");
  s.addTable([[hdr("지표"), hdr("일치율"), hdr("kappa"), hdr("Judge 관대도*")],
    ["관련성", ag("relevance"), kv("relevance"), len("relevance")],
    ["완전성", ag("completeness"), kv("completeness"), len("completeness")],
    ["도메인 적합성", ag("domain_appropriateness"), kv("domain_appropriateness"), len("domain_appropriateness")],
    ["명확성", ag("clarity"), kv("clarity"), len("clarity")],
    [{ text: "종합 (3/4)", options: { bold: true } }, ag("overall"), kv("overall"), len("overall")]],
  { ...TBL, x: 6.9, y: 1.5, w: 5.83, colW: [1.9, 1.2, 1.2, 1.53], fontSize: 13, rowH: 0.45, objectName: "claude-kappa-table" });
  T(s, `평가 Judge vs 독립 평가자(Claude, Judge 판정을 가린 블라인드 채점) base 답변 ${D.claude_agreement.n_compared}건. 사람 라벨이 아니다. * 독립 평가자가 Fail로 본 답을 Judge가 Pass로 준 비율. 사람 표본 라벨은 아직 없다.`,
    { x: 6.9, y: 4.3, w: 5.83, h: 1.0, fontSize: 11.5, color: C.accent3 });
}
T(s, `평가 Judge는 RAG가 들어간 구성에서 ${pct(Math.min(...["rag","rag_judge","rag_judge_cost","rag_judge_v2","final"].map((n) => H[n].pass_rate)))}~${pct(Math.max(...["rag","rag_judge","rag_judge_cost","rag_judge_v2","final"].map((n) => H[n].pass_rate)))}로 포화돼 구성 차이를 잘 보지 못했다. 그래서 Judge 무관 지표(정답 누락·혼입, 런북 어구 포함)로 결론을 냈다.`,
  { x: 0.6, y: 5.85, w: 12.1, h: 0.7, fontSize: 13.5 });

// ── 14. 시연 ─────────────────────────────────────────────────────────
s = slide("CONTENT", "시연");
s.addText("시연: 같은 질문, base와 final을 나란히", { placeholder: "title" });
card(s, 0.6, 1.5, 12.1, 1.0, C.text2, "demo-cmd");
T(s, ".venv/bin/python scripts/demo_side_by_side.py --id Q01",
  { x: 0.9, y: 1.6, w: 11.5, h: 0.8, fontSize: 16, fontFace: "Courier New", color: C.background1, valign: "middle" });
const demo = [["base", "high-latency (응답 지연 절차)", "오답", C.accent1, "커넥션 풀 늘리기, 트래픽 분산…"],
  ["final", "db-down (+disk-full 혼입)", "정답 포함", C.accent2, "커넥션 풀 점검, 필요 시 failover 노드로 전환…"]];
demo.forEach(([n, rb, ok, color, gist], i) => {
  const x = 0.6 + i * 6.13;
  card(s, x, 2.8, 5.97, 3.2, C.background2, `demo-${n}`);
  T(s, `[${n}]`, { x: x + 0.3, y: 3.0, w: 2, h: 0.45, fontSize: 18, bold: true, color: C.text2 });
  T(s, ok, { x: x + 4.4, y: 3.0, w: 1.3, h: 0.45, fontSize: 16, bold: true, color, align: "right" });
  T(s, [{ text: "고른 런북  ", options: { color: HEX.accent3 } }, { text: rb, options: { bold: true, breakLine: true } },
    { text: "답의 핵심  ", options: { color: HEX.accent3 } }, { text: gist }],
  { x: x + 0.3, y: 3.6, w: 5.4, h: 2.2, fontSize: 14.5, paraSpaceAfter: 8, valign: "top" });
});
src(s, "질문: \"DB 프라이머리가 다운됐습니다. 대응 절차를 알려주세요.\" 화면 하나에 런북 정오·답변·지연·비용·근거 없는 수치. 기록 results/raw/demo_*.json", 6.25);

// ── 15. 한계 ─────────────────────────────────────────────────────────
s = slide("CONTENT", "한계");
s.addText("한계와 다음 개선", { placeholder: "title" });
const lim = [
  ["일반화 격차", `RAG Recall@1이 dev ${pct(D.dev.rag["recall@1"])} → holdout ${pct(H.rag["recall@1"])}. 자기 말로 묻는 holdout 질의는 ${pct(X.rag["recall@1[paraphrased]"])}`, "런북 본문 외에 증상 예시 문장을 색인해 질문과 문서의 표현 차이를 줄임"],
  ["무관 런북 혼입이 남음", `final 혼입 ${pct(X.final.wrong_runbook_rate)}. 1위와 점수가 가까운 런북을 함께 넣는 규칙, 맞는 런북이 없는 질문에도 런북이 들어가는 경우`, "재순위(reranker), 질문 속 증상 수에 맞춘 투입 개수"],
  ["캐스케이드의 품질 대가", `어구 포함 ${pp(pair("rag_judge", "rag_judge_cost").must.diff)} (유의하지 않음). 저가 초안이 런북 문구를 덜 인용하는 것으로 추정 (미검증)`, "Judge 대신 결정적 어구 대조로 승급 기준을 정함"],
  ["평가 규모와 범위", "holdout 36건 x 3회 (1건 = 2.8%p). 평가 Judge 포화. 라우터는 개선 범위 밖", "질의 확대, 라우팅 개선을 같은 체계로 재측정"],
];
lim.forEach(([h, why, next], i) => {
  const y = 1.4 + i * 1.32;
  card(s, 0.6, y, 12.1, 1.18, C.background2, `lim-${i}`);
  s.addShape(pres.shapes.OVAL, { x: 0.85, y: y + 0.36, w: 0.45, h: 0.45, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `lim-dot-${i}` });
  T(s, "!", { x: 0.85, y: y + 0.36, w: 0.45, h: 0.45, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle" });
  T(s, h, { x: 1.55, y: y + 0.12, w: 5.3, h: 0.42, fontSize: 16, bold: true, color: C.text2 });
  T(s, why, { x: 1.55, y: y + 0.56, w: 5.3, h: 0.55, fontSize: 12.5 });
  T(s, `다음: ${next}`, { x: 7.1, y: y + 0.12, w: 5.4, h: 0.95, fontSize: 13.5, color: C.accent6, valign: "middle" });
});

// ── 16. 마무리 ───────────────────────────────────────────────────────
s = slide("DARK", "마무리");
s.addText("기능을 더하기 전에, 효과를 재는 법부터", { placeholder: "title" });
s.addText([
  { text: "RAG가 조치 정확도를 올렸고, Judge는 품질 향상이 확인되지 않은 채 비용·지연만 늘렸으며, 캐스케이드로 장애 1건당 비용을 낮췄다. 모두 holdout에서, 반복과 짝지은 비교로 확인했다.", options: { breakLine: true } },
  { text: "github.com/jang961111-hash/incident-agent-ablation", options: { fontSize: 14, color: C.accent3 } },
], { placeholder: "body" });

(async () => {
  const out = path.join(__dirname, "incident-agent-ablation.pptx");
  await pres.writeFile({ fileName: out });
  if (process.env.PPTX_SKILL_DIR) {
    const { applyTheme } = require(path.join(process.env.PPTX_SKILL_DIR, "scripts", "apply_theme.js"));
    await applyTheme(out, THEME);
  }
  console.log("wrote", out);
})();
