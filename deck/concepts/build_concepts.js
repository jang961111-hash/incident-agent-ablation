// 스타일 시안 5종 x 3장. 수치는 results/claims.json 에서 읽는다 (손으로 적지 않음).
//   cd deck && NODE_PATH=node_modules node concepts/build_concepts.js
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.join(__dirname, "..", "..");
const CL = JSON.parse(fs.readFileSync(path.join(ROOT, "results", "claims.json")));
const claim = (id) => { const c = CL.find((x) => x.id === id); if (!c) throw new Error(id); return c["값"]; };
const ab = (s) => { const m = s.match(/^([^→]+?)\s*→\s*([^\s(]+)/); return [m[1].trim(), m[2].trim()]; };
const MISS = ab(claim("miss_base_final"));
const WRONG = ab(claim("wrong_base_final"));
const COST = claim("cost_base_final").match(/\((-\d+%)\)/)[1];
const CONC = ab(claim("conc_10"));
const FAULT = ab(claim("fault"));
const D = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "data.json")));
const NCFG = D.configs.length;
console.log({ MISS, WRONG, COST, CONC, FAULT, NCFG });

const F = process.env.DECK_FONT || "Noto Sans KR"; // 미리보기 렌더만 DECK_FONT="Apple SD Gothic Neo"
const TITLE = "장애 대응 AI 비서, 무엇이 진짜 효과였나";
const SUB = `개선 5가지를 하나씩 켜고 끄며 실측한 ${NCFG}개 구성 비교`;
const WHO = "SKALA 4기 · 광주 2반 · G062 장병헌";
const MSG = "같은 질문, 같은 채점으로 원본과 최종을 비교";
const M3 = [
  { k: "맞는 매뉴얼 누락", a: MISS[0], b: MISS[1] },
  { k: "엉뚱한 매뉴얼 혼입", a: WRONG[0], b: WRONG[1] },
  { k: "장애 1건 비용", a: null, b: COST },
];
const M2 = [
  { k: "동시 질문 10개", a: CONC[0], b: CONC[1] },
  { k: "고장 시 완주", a: FAULT[0], b: FAULT[1] },
];
const NODES = ["route", "plan", "research", "analysis", "write", "validate"];
const NODE_KO = ["질문 분류", "계획", "MCP 도구 조회", "분석", "답 작성", "검수"];
// 끼워 넣는 곳: src/ext/graph_ext.py build_graph_ext
const SW = [
  { n: "RAG 매뉴얼 검색", d: "뜻으로 매뉴얼 찾기", at: [2], row: "top" },
  { n: "캐스케이드", d: "작은 모델 먼저", at: [4], row: "top" },
  { n: "LLM Judge 검수", d: "점수 미달이면 다시 쓰기", at: [5], row: "top" },
  { n: "비동기 · 도구 고장 허용", d: "기다림 줄이고 끝까지", at: [0, 1, 2], row: "bot" },
  { n: "v2 보완", d: "최소 유사도 · 수치 검증", at: [2, 5], row: "bot" },
];

const W = 10, H = 5.625;
function newPres() { const p = new pptxgen(); p.layout = "LAYOUT_16x9"; p.author = "장병헌 (G062)"; p.theme = { headFontFace: F, bodyFontFace: F }; return p; }
const T = (s, text, o) => s.addText(text, Object.assign({ fontFace: F, margin: 0, lang: "ko-KR" }, o));
const R = (s, p, o) => s.addShape(p.shapes.RECTANGLE, o);
const RR = (s, p, o) => s.addShape(p.shapes.ROUNDED_RECTANGLE, o);
const OV = (s, p, o) => s.addShape(p.shapes.OVAL, o);
const LN = (s, p, x, y, w, h, color, wt = 1, extra = {}) => s.addShape(p.shapes.LINE, Object.assign({ x, y, w, h, line: { color, width: wt } }, extra));

// 공통 흐름도(가로). st: 스타일 파라미터
function flowH(s, p, st) {
  const x0 = st.x0 ?? 0.5, y = st.y ?? 2.45, nw = st.nw ?? 1.22, nh = st.nh ?? 0.72, gap = st.gap ?? 0.31;
  const cx = (i) => x0 + i * (nw + gap) + nw / 2;
  for (let i = 0; i < NODES.length; i++) {
    const x = x0 + i * (nw + gap);
    const shape = st.nodeShape === "oval" ? p.shapes.OVAL : st.nodeShape === "rr" ? p.shapes.ROUNDED_RECTANGLE : p.shapes.RECTANGLE;
    s.addShape(shape, { x, y, w: nw, h: nh, fill: { color: st.nodeFill }, line: { color: st.nodeLine, width: st.nodeLineW ?? 1 }, rectRadius: 0.12 });
    T(s, [{ text: NODES[i], options: { fontSize: 11, bold: true, color: st.nodeText, breakLine: true } },
      { text: NODE_KO[i], options: { fontSize: 8, color: st.nodeSub } }], { x, y, w: nw, h: nh, align: "center", valign: "middle" });
    if (i < NODES.length - 1) LN(s, p, x + nw + 0.03, y + nh / 2, gap - 0.06, 0, st.edge, 1.5, { line: { color: st.edge, width: 1.5, endArrowType: "triangle" } });
  }
  const tops = SW.filter((w) => w.row === "top"), bots = SW.filter((w) => w.row === "bot");
  const cw = st.cw ?? 1.75, ch = st.ch ?? 0.78;
  const place = (w, row) => {
    const mid = w.at.reduce((a, i) => a + cx(i), 0) / w.at.length;
    let x = Math.min(Math.max(mid - cw / 2, 0.3), W - 0.3 - cw);
    if (w.n === "LLM Judge 검수") x = W - 0.3 - cw;
    if (w.n === "캐스케이드") x = W - 0.3 - 2 * cw - 0.08;
    if (w.n === "v2 보완") x = cx(4) - cw / 2 + 0.25;
    const yy = row === "top" ? y - ch - 0.42 : y + nh + 0.42;
    // 버스형 연결선: 노드 → 버스 → 콜아웃
    const busY = row === "top" ? y - 0.21 : y + nh + 0.21;
    const ccx = x + cw / 2;
    const xs = w.at.map(cx).concat([ccx]);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const ls = { color: st.callLine, width: 1, dashType: st.dash ?? "dash" };
    if (hi - lo > 0.01) s.addShape(p.shapes.LINE, { x: lo, y: busY, w: hi - lo, h: 0, line: ls });
    for (const i of w.at) { const ny = row === "top" ? y : y + nh; s.addShape(p.shapes.LINE, { x: cx(i), y: Math.min(ny, busY), w: 0, h: Math.abs(ny - busY), line: ls }); }
    const cy = row === "top" ? yy + ch : yy;
    s.addShape(p.shapes.LINE, { x: ccx, y: Math.min(cy, busY), w: 0, h: Math.abs(cy - busY), line: ls });
    st.callout(s, p, w, x, yy, cw, ch);
  };
  tops.forEach((w) => place(w, "top"));
  bots.forEach((w) => place(w, "bot"));
}

// ───────────────────────── 1. Corporate Red Executive
function c1() {
  const p = newPres(); const RED = "C8102E", OR = "F26B21", INK = "1A1A1A", G = "6B7280", L = "D9D9D9";
  const foot = (s, n) => { LN(s, p, 0.5, 5.2, 9, 0, L, 0.75); T(s, WHO, { x: 0.5, y: 5.25, w: 6, h: 0.25, fontSize: 8, color: G }); T(s, String(n).padStart(2, "0"), { x: 8.9, y: 5.25, w: 0.6, h: 0.25, fontSize: 8, color: RED, bold: true, align: "right" }); };
  const head = (s, no, t) => { T(s, no, { x: 0.5, y: 0.35, w: 0.6, h: 0.45, fontSize: 20, bold: true, color: RED }); T(s, t, { x: 1.1, y: 0.35, w: 8, h: 0.45, fontSize: 20, bold: true, color: INK }); LN(s, p, 0.5, 0.9, 9, 0, INK, 1.25); };
  // A
  let s = p.addSlide(); s.background = { color: "FFFFFF" };
  R(s, p, { x: 0, y: 0, w: 0.18, h: H, fill: { color: RED }, line: { color: RED } });
  T(s, "AI AGENT MINI-PROJECT  |  ABLATION REPORT", { x: 0.7, y: 0.6, w: 7, h: 0.3, fontSize: 9, bold: true, color: RED, charSpacing: 2 });
  T(s, TITLE, { x: 0.7, y: 1.55, w: 7.2, h: 1.5, fontSize: 32, bold: true, color: INK, valign: "top" });
  LN(s, p, 0.7, 3.25, 1.2, 0, RED, 3);
  T(s, SUB, { x: 0.7, y: 3.45, w: 8, h: 0.4, fontSize: 14, color: G });
  T(s, WHO, { x: 0.7, y: 4.8, w: 6, h: 0.3, fontSize: 11, color: INK, bold: true });
  R(s, p, { x: 8.6, y: 4.4, w: 0.9, h: 0.9, fill: { color: RED }, line: { color: RED } });
  R(s, p, { x: 8.6, y: 4.4, w: 0.45, h: 0.45, fill: { color: OR }, line: { color: OR } });
  // B
  s = p.addSlide(); s.background = { color: "FFFFFF" }; head(s, "01", "핵심 결과");
  T(s, MSG, { x: 0.5, y: 1.0, w: 9, h: 0.35, fontSize: 12, color: G });
  M3.forEach((m, i) => {
    const x = 0.5 + i * 3.05;
    LN(s, p, x, 1.55, 2.85, 0, RED, 2.5);
    T(s, m.k, { x, y: 1.65, w: 2.85, h: 0.3, fontSize: 11, bold: true, color: INK });
    T(s, m.b, { x, y: 1.95, w: 2.85, h: 1.0, fontSize: 48, bold: true, color: RED, valign: "middle" });
    T(s, m.a ? `원본 ${m.a}` : "원본 대비", { x, y: 2.95, w: 2.85, h: 0.3, fontSize: 11, color: G });
  });
  R(s, p, { x: 0.5, y: 3.6, w: 9, h: 1.35, fill: { color: "F6F6F6" }, line: { color: "F6F6F6" } });
  M2.forEach((m, i) => {
    const x = 0.8 + i * 4.5;
    T(s, m.k, { x, y: 3.75, w: 3.9, h: 0.3, fontSize: 11, bold: true, color: INK });
    T(s, [{ text: m.a + "  →  ", options: { color: G, fontSize: 18 } }, { text: m.b, options: { color: OR, fontSize: 26, bold: true } }], { x, y: 4.1, w: 3.9, h: 0.6, valign: "middle" });
  });
  LN(s, p, 5.0, 3.75, 0, 1.05, L, 0.75);
  foot(s, 2);
  // C
  s = p.addSlide(); s.background = { color: "FFFFFF" }; head(s, "02", "내가 바꾼 것: 파이프라인의 5개 스위치");
  flowH(s, p, { y: 2.45, nodeFill: "FFFFFF", nodeLine: INK, nodeLineW: 1.25, nodeText: INK, nodeSub: G, edge: G, callLine: RED,
    callout: (s, p, w, x, y, cw, ch) => {
      R(s, p, { x, y, w: cw, h: ch, fill: { color: "FFFFFF" }, line: { color: RED, width: 1 } });
      R(s, p, { x, y, w: 0.07, h: ch, fill: { color: RED }, line: { color: RED } });
      T(s, w.n, { x: x + 0.15, y: y + 0.08, w: cw - 0.6, h: 0.3, fontSize: 10, bold: true, color: INK });
      T(s, "ON", { x: x + cw - 0.45, y: y + 0.1, w: 0.36, h: 0.2, fontSize: 7, bold: true, color: "FFFFFF", align: "center", fill: { color: RED } });
      T(s, w.d, { x: x + 0.15, y: y + 0.42, w: cw - 0.2, h: 0.28, fontSize: 9, color: G });
    } });
  foot(s, 3);
  return p;
}

// ───────────────────────── 2. Ops Console Dark
function c2() {
  const p = newPres(); const BG = "0E1621", PN = "17212F", BD = "263447", TX = "E6EDF3", DIM = "7D8DA1", GR = "3DDC97", AM = "F5B942", RD = "FF5C5C", CY = "4CC9F0";
  const bar = (s, t) => { R(s, p, { x: 0, y: 0, w: W, h: 0.42, fill: { color: "0A1018" }, line: { color: "0A1018" } });
    [RD, AM, GR].forEach((c, i) => OV(s, p, { x: 0.25 + i * 0.2, y: 0.15, w: 0.12, h: 0.12, fill: { color: c }, line: { color: c } }));
    T(s, t, { x: 0.95, y: 0.08, w: 6, h: 0.26, fontSize: 9, color: DIM });
    OV(s, p, { x: 8.55, y: 0.16, w: 0.1, h: 0.1, fill: { color: GR }, line: { color: GR } });
    T(s, "ALL SYSTEMS OK", { x: 8.7, y: 0.08, w: 1.2, h: 0.26, fontSize: 8, color: GR, bold: true }); };
  // A
  let s = p.addSlide(); s.background = { color: BG }; bar(s, "incident-agent / ablation / overview");
  T(s, "> INCIDENT RESPONSE AGENT", { x: 0.6, y: 1.1, w: 8, h: 0.3, fontSize: 11, color: CY, bold: true, charSpacing: 2 });
  T(s, TITLE, { x: 0.6, y: 1.5, w: 8.6, h: 1.3, fontSize: 30, bold: true, color: TX, valign: "top" });
  T(s, SUB, { x: 0.6, y: 2.95, w: 8.6, h: 0.35, fontSize: 13, color: DIM });
  const tiles = [["CONFIGS", String(NCFG), CY], ["SWITCHES", "5", GR], ["PRESENTER", "G062", AM]];
  tiles.forEach((t, i) => { const x = 0.6 + i * 2.15; RR(s, p, { x, y: 3.75, w: 2.0, h: 1.0, fill: { color: PN }, line: { color: BD }, rectRadius: 0.06 });
    T(s, t[0], { x: x + 0.15, y: 3.85, w: 1.7, h: 0.22, fontSize: 8, color: DIM, bold: true });
    T(s, t[1], { x: x + 0.15, y: 4.1, w: 1.7, h: 0.5, fontSize: 24, bold: true, color: t[2] }); });
  T(s, WHO, { x: 0.6, y: 5.05, w: 6, h: 0.3, fontSize: 10, color: DIM });
  // B
  s = p.addSlide(); s.background = { color: BG }; bar(s, "incident-agent / ablation / metrics  (base → final)");
  T(s, "핵심 결과", { x: 0.5, y: 0.6, w: 4, h: 0.45, fontSize: 20, bold: true, color: TX });
  T(s, MSG, { x: 4.2, y: 0.68, w: 5.3, h: 0.35, fontSize: 10, color: DIM, align: "right" });
  M3.forEach((m, i) => { const x = 0.5 + i * 3.05; RR(s, p, { x, y: 1.25, w: 2.9, h: 2.1, fill: { color: PN }, line: { color: BD }, rectRadius: 0.06 });
    OV(s, p, { x: x + 0.2, y: 1.45, w: 0.12, h: 0.12, fill: { color: GR }, line: { color: GR } });
    T(s, m.k, { x: x + 0.42, y: 1.38, w: 2.4, h: 0.26, fontSize: 10, color: DIM, bold: true });
    T(s, m.b, { x: x + 0.2, y: 1.75, w: 2.6, h: 0.95, fontSize: 46, bold: true, color: GR, valign: "middle" });
    T(s, m.a ? `prev ${m.a}` : "vs base", { x: x + 0.2, y: 2.8, w: 2.6, h: 0.3, fontSize: 10, color: RD }); });
  M2.forEach((m, i) => { const x = 0.5 + i * 4.6; RR(s, p, { x, y: 3.55, w: 4.45, h: 1.45, fill: { color: PN }, line: { color: BD }, rectRadius: 0.06 });
    OV(s, p, { x: x + 0.2, y: 3.75, w: 0.12, h: 0.12, fill: { color: CY }, line: { color: CY } });
    T(s, m.k, { x: x + 0.42, y: 3.68, w: 3.5, h: 0.26, fontSize: 10, color: DIM, bold: true });
    T(s, [{ text: m.a, options: { color: RD, fontSize: 18 } }, { text: "  ▸  ", options: { color: DIM, fontSize: 16 } }, { text: m.b, options: { color: CY, fontSize: 30, bold: true } }], { x: x + 0.2, y: 4.05, w: 4.0, h: 0.75, valign: "middle" }); });
  // C
  s = p.addSlide(); s.background = { color: BG }; bar(s, "incident-agent / pipeline / feature-flags");
  T(s, "내가 바꾼 것: 기능 플래그 5개", { x: 0.5, y: 0.6, w: 8, h: 0.45, fontSize: 20, bold: true, color: TX });
  flowH(s, p, { y: 2.55, nodeFill: PN, nodeLine: CY, nodeText: TX, nodeSub: DIM, edge: DIM, callLine: GR, dash: "sysDot",
    callout: (s, p, w, x, y, cw, ch) => {
      RR(s, p, { x, y, w: cw, h: ch, fill: { color: "0A1018" }, line: { color: BD }, rectRadius: 0.05 });
      RR(s, p, { x: x + 0.12, y: y + 0.12, w: 0.42, h: 0.22, fill: { color: GR }, line: { color: GR }, rectRadius: 0.11 });
      OV(s, p, { x: x + 0.33, y: y + 0.14, w: 0.18, h: 0.18, fill: { color: "FFFFFF" }, line: { color: "FFFFFF" } });
      T(s, w.n, { x: x + 0.62, y: y + 0.08, w: cw - 0.66, h: 0.3, fontSize: 9, bold: true, color: TX });
      T(s, w.d, { x: x + 0.12, y: y + 0.44, w: cw - 0.2, h: 0.26, fontSize: 8.5, color: DIM });
    } });
  return p;
}

// ───────────────────────── 3. Fintech Minimal
function c3() {
  const p = newPres(); const BL = "3182F6", INK = "191F28", G = "8B95A1", CARD = "F2F4F6";
  // A
  let s = p.addSlide(); s.background = { color: "FFFFFF" };
  OV(s, p, { x: 0.8, y: 1.3, w: 0.28, h: 0.28, fill: { color: BL }, line: { color: BL } });
  T(s, TITLE, { x: 0.8, y: 1.85, w: 8, h: 1.4, fontSize: 34, bold: true, color: INK, valign: "top" });
  T(s, "개선 5가지, 하나씩 켜 보며 확인했어요", { x: 0.8, y: 3.4, w: 8, h: 0.4, fontSize: 16, color: G });
  T(s, WHO, { x: 0.8, y: 4.75, w: 6, h: 0.3, fontSize: 11, color: G });
  // B
  s = p.addSlide(); s.background = { color: "FFFFFF" };
  T(s, "이렇게 좋아졌어요", { x: 0.6, y: 0.45, w: 8, h: 0.5, fontSize: 24, bold: true, color: INK });
  M3.forEach((m, i) => { const x = 0.6 + i * 2.98; RR(s, p, { x, y: 1.25, w: 2.8, h: 2.25, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.2 });
    T(s, m.k, { x: x + 0.25, y: 1.45, w: 2.4, h: 0.3, fontSize: 12, color: G });
    T(s, m.b, { x: x + 0.25, y: 1.85, w: 2.4, h: 1.0, fontSize: 52, bold: true, color: BL, valign: "middle" });
    T(s, m.a ? `${m.a}에서` : "원본보다", { x: x + 0.25, y: 2.95, w: 2.4, h: 0.3, fontSize: 12, color: G }); });
  M2.forEach((m, i) => { const x = 0.6 + i * 4.47; RR(s, p, { x, y: 3.75, w: 4.3, h: 1.1, fill: { color: "FFFFFF" }, line: { color: "E5E8EB", width: 1 }, rectRadius: 0.2 });
    T(s, m.k, { x: x + 0.3, y: 3.85, w: 3.8, h: 0.3, fontSize: 11, color: G });
    T(s, [{ text: m.a + " → ", options: { color: G, fontSize: 16 } }, { text: m.b, options: { color: INK, fontSize: 26, bold: true } }], { x: x + 0.3, y: 4.15, w: 3.8, h: 0.55, valign: "middle" }); });
  T(s, MSG, { x: 0.6, y: 5.05, w: 8.8, h: 0.3, fontSize: 10, color: G });
  // C: 세로 단계 + 오른쪽 토글
  s = p.addSlide(); s.background = { color: "FFFFFF" };
  T(s, "제가 바꾼 건 5곳이에요", { x: 0.6, y: 0.35, w: 8, h: 0.5, fontSize: 24, bold: true, color: INK });
  const rowY = (i) => 1.1 + i * 0.7;
  NODES.forEach((n, i) => { RR(s, p, { x: 0.6, y: rowY(i), w: 2.6, h: 0.55, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.27 });
    T(s, [{ text: `${i + 1}  `, options: { color: BL, bold: true } }, { text: n, options: { color: INK, bold: true } }, { text: `  ${NODE_KO[i]}`, options: { color: G, fontSize: 10 } }], { x: 0.85, y: rowY(i), w: 2.4, h: 0.55, fontSize: 13, valign: "middle" });
    if (i < 5) LN(s, p, 1.0, rowY(i) + 0.55, 0, 0.15, "D1D6DB", 1.5); });
  const C3 = [[0, "비동기 · 도구 고장 허용", "기다림 줄이고 끝까지 (1~3단계)"], [2, "RAG 매뉴얼 검색", "뜻으로 매뉴얼 찾기"], [2.0, "v2 보완", "최소 유사도 · 수치 검증 (3·6단계)"], [4, "캐스케이드", "작은 모델 먼저 써 보기"], [5, "LLM Judge 검수", "점수 미달이면 다시 쓰기"]];
  C3.forEach((c, j) => { const y = 1.05 + j * 0.84; const x = 3.75;
    RR(s, p, { x, y, w: 5.7, h: 0.7, fill: { color: "FFFFFF" }, line: { color: "E5E8EB", width: 1 }, rectRadius: 0.2 });
    RR(s, p, { x: x + 0.2, y: y + 0.21, w: 0.5, h: 0.28, fill: { color: BL }, line: { color: BL }, rectRadius: 0.14 });
    OV(s, p, { x: x + 0.44, y: y + 0.235, w: 0.23, h: 0.23, fill: { color: "FFFFFF" }, line: { color: "FFFFFF" } });
    T(s, c[1], { x: x + 0.9, y: y + 0.06, w: 4.6, h: 0.32, fontSize: 13, bold: true, color: INK });
    T(s, c[2], { x: x + 0.9, y: y + 0.37, w: 4.6, h: 0.26, fontSize: 10, color: G });
    LN(s, p, 3.2, rowY(Math.floor(c[0])) + 0.27, 0.55, (y + 0.35) - (rowY(Math.floor(c[0])) + 0.27), "C9DDFB", 1, { line: { color: "C9DDFB", width: 1 } }); });
  return p;
}

// ───────────────────────── 4. Architecture Blueprint
function c4() {
  const p = newPres(); const BG = "F4F7FB", GRD = "DCE4EE", IN = "2B3A8C", TL = "0F9D9A", INK = "1E2640", G = "6A7590";
  const grid = (s) => { for (let x = 0; x <= W; x += 0.5) LN(s, p, x, 0, 0, H, GRD, 0.5); for (let y = 0; y <= H; y += 0.5) LN(s, p, 0, y, W, 0, GRD, 0.5); };
  const tag = (s, t) => { T(s, t, { x: 0.4, y: 0.3, w: 5, h: 0.3, fontSize: 9, color: TL, bold: true, charSpacing: 2 }); };
  // A
  let s = p.addSlide(); s.background = { color: BG }; grid(s); tag(s, "WHITEPAPER  ·  MULTI-AGENT ARCHITECTURE");
  // 배경 미니 그래프
  const pts = [[6.3, 1.0], [7.6, 0.8], [8.8, 1.5], [7.4, 2.1], [8.6, 2.8], [6.5, 2.6]];
  [[0, 1], [1, 2], [1, 3], [3, 4], [3, 5], [0, 5]].forEach(([a, b]) => { const [x1, y1] = pts[a], [x2, y2] = pts[b];
    s.addShape(p.shapes.LINE, { x: Math.min(x1, x2) + 0.15, y: Math.min(y1, y2) + 0.15, w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001, flipH: (x2 - x1) * (y2 - y1) < 0, line: { color: "9FB3D1", width: 1 } }); });
  pts.forEach(([x, y], i) => OV(s, p, { x, y, w: 0.3, h: 0.3, fill: { color: i % 2 ? TL : IN }, line: { color: "FFFFFF", width: 1.5 } }));
  T(s, TITLE, { x: 0.6, y: 1.3, w: 5.6, h: 1.6, fontSize: 28, bold: true, color: INK, valign: "top" });
  T(s, SUB, { x: 0.6, y: 3.0, w: 5.6, h: 0.6, fontSize: 12, color: G, valign: "top" });
  R(s, p, { x: 5.6, y: 4.2, w: 3.9, h: 1.0, fill: { color: "FFFFFF" }, line: { color: IN, width: 1 } });
  LN(s, p, 5.6, 4.55, 3.9, 0, IN, 0.75); LN(s, p, 6.8, 4.2, 0, 0.35, IN, 0.75);
  T(s, "DOC", { x: 5.7, y: 4.25, w: 1.0, h: 0.25, fontSize: 8, color: G }); T(s, "Ablation Study  ·  v2", { x: 6.9, y: 4.25, w: 2.5, h: 0.25, fontSize: 9, color: IN, bold: true });
  T(s, WHO, { x: 5.7, y: 4.65, w: 3.7, h: 0.4, fontSize: 10, color: INK, bold: true });
  // B: 노드-엣지 형태 지표
  s = p.addSlide(); s.background = { color: BG }; grid(s); tag(s, "FIG. 1  ·  RESULTS  (base → final)");
  T(s, "핵심 결과", { x: 0.4, y: 0.6, w: 6, h: 0.5, fontSize: 22, bold: true, color: INK });
  T(s, MSG, { x: 0.4, y: 1.1, w: 8, h: 0.3, fontSize: 10, color: G });
  const all = M3.concat(M2);
  all.forEach((m, i) => { const y = 1.6 + i * 0.74; const big = i < 3;
    T(s, m.k, { x: 0.4, y, w: 2.3, h: 0.55, fontSize: big ? 13 : 11, bold: big, color: INK, valign: "middle" });
    R(s, p, { x: 2.8, y, w: 1.9, h: 0.55, fill: { color: "FFFFFF" }, line: { color: "9FB3D1", width: 1, dashType: "dash" } });
    T(s, m.a ?? "base", { x: 2.8, y, w: 1.9, h: 0.55, fontSize: m.a ? 16 : 12, color: G, align: "center", valign: "middle" });
    s.addShape(p.shapes.LINE, { x: 4.75, y: y + 0.275, w: 1.6, h: 0, line: { color: TL, width: 2, endArrowType: "triangle" } });
    T(s, big ? "개선 적용" : "실행 방식", { x: 4.75, y: y + 0.02, w: 1.6, h: 0.22, fontSize: 7, color: TL, align: "center" });
    R(s, p, { x: 6.4, y, w: 3.0, h: 0.55, fill: { color: big ? IN : TL }, line: { color: big ? IN : TL } });
    T(s, m.b, { x: 6.4, y, w: 3.0, h: 0.55, fontSize: big ? 24 : 18, bold: true, color: "FFFFFF", align: "center", valign: "middle" }); });
  // C
  s = p.addSlide(); s.background = { color: BG }; grid(s); tag(s, "FIG. 2  ·  PIPELINE  +  5 PLUG-INS (src/ext/graph_ext.py)");
  T(s, "내가 바꾼 것: 꽂아 넣은 5개 모듈", { x: 0.4, y: 0.6, w: 8, h: 0.5, fontSize: 20, bold: true, color: INK });
  flowH(s, p, { y: 2.6, nodeShape: "rr", nodeFill: "FFFFFF", nodeLine: IN, nodeLineW: 1.5, nodeText: IN, nodeSub: G, edge: IN, callLine: TL,
    callout: (s, p, w, x, y, cw, ch) => { const k = SW.indexOf(w) + 1;
      R(s, p, { x, y, w: cw, h: ch, fill: { color: "E6F6F5" }, line: { color: TL, width: 1, dashType: "dash" } });
      OV(s, p, { x: x + 0.08, y: y + 0.09, w: 0.28, h: 0.28, fill: { color: TL }, line: { color: TL } });
      T(s, String(k), { x: x + 0.08, y: y + 0.09, w: 0.28, h: 0.28, fontSize: 9, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
      T(s, w.n, { x: x + 0.42, y: y + 0.07, w: cw - 0.46, h: 0.32, fontSize: 9.5, bold: true, color: INK, valign: "middle" });
      T(s, w.d, { x: x + 0.1, y: y + 0.44, w: cw - 0.15, h: 0.28, fontSize: 8.5, color: G });
    } });
  return p;
}

// ───────────────────────── 5. Warm Story
function c5() {
  const p = newPres(); const BG = "FFF8F0", OR = "F28C28", BR = "5B3A29", YL = "FFE8C2", G = "8A6F5E", GN = "4E9F6E";
  const IMG = path.join(ROOT, "docs", "figures");
  // A
  let s = p.addSlide(); s.background = { color: BG };
  s.addImage({ path: path.join(IMG, "gpt_webtoon.png"), x: 5.5, y: 0.6, w: 4.2, h: 4.2, sizing: { type: "contain", w: 4.2, h: 4.2 } });
  RR(s, p, { x: 0.5, y: 1.0, w: 5.0, h: 2.4, fill: { color: "FFFFFF" }, line: { color: OR, width: 2 }, rectRadius: 0.3 });
  s.addShape(p.shapes.RIGHT_TRIANGLE, { x: 5.0, y: 3.2, w: 0.5, h: 0.4, fill: { color: "FFFFFF" }, line: { color: OR, width: 2 }, flipH: false });
  T(s, TITLE, { x: 0.8, y: 1.2, w: 4.5, h: 1.6, fontSize: 26, bold: true, color: BR, valign: "middle" });
  T(s, "새벽 장애 알람, AI 비서가 먼저 매뉴얼을 펼쳐 준다면?", { x: 0.8, y: 2.75, w: 4.5, h: 0.5, fontSize: 11, color: G });
  RR(s, p, { x: 0.5, y: 4.4, w: 3.6, h: 0.5, fill: { color: YL }, line: { color: YL }, rectRadius: 0.25 });
  T(s, WHO, { x: 0.5, y: 4.4, w: 3.6, h: 0.5, fontSize: 10, bold: true, color: BR, align: "center", valign: "middle" });
  // B
  s = p.addSlide(); s.background = { color: BG };
  T(s, "그래서, 얼마나 나아졌나요?", { x: 0.5, y: 0.35, w: 7, h: 0.5, fontSize: 22, bold: true, color: BR });
  M3.forEach((m, i) => { const x = 0.5 + i * 3.05; RR(s, p, { x, y: 1.1, w: 2.85, h: 2.4, fill: { color: "FFFFFF" }, line: { color: YL, width: 2 }, rectRadius: 0.25 });
    OV(s, p, { x: x + 0.2, y: 1.25, w: 0.5, h: 0.5, fill: { color: OR }, line: { color: OR } });
    T(s, String(i + 1), { x: x + 0.2, y: 1.25, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    T(s, m.k, { x: x + 0.8, y: 1.3, w: 1.95, h: 0.4, fontSize: 12, bold: true, color: BR, valign: "middle" });
    T(s, m.a ? `전에는 ${m.a}` : "같은 장애 한 건", { x: x + 0.25, y: 1.95, w: 2.4, h: 0.3, fontSize: 11, color: G });
    T(s, m.a ? `지금은 ${m.b}` : `비용 ${m.b}`, { x: x + 0.25, y: 2.3, w: 2.5, h: 0.8, fontSize: 30, bold: true, color: OR, valign: "middle" }); });
  M2.forEach((m, i) => { const x = 0.5 + i * 4.6; RR(s, p, { x, y: 3.75, w: 4.45, h: 1.0, fill: { color: YL }, line: { color: YL }, rectRadius: 0.25 });
    T(s, m.k, { x: x + 0.3, y: 3.82, w: 3.9, h: 0.3, fontSize: 11, bold: true, color: BR });
    T(s, [{ text: m.a + "  →  ", options: { color: G, fontSize: 15 } }, { text: m.b, options: { color: GN, fontSize: 24, bold: true } }], { x: x + 0.3, y: 4.12, w: 3.9, h: 0.5, valign: "middle" }); });
  T(s, `"${MSG}"`, { x: 0.5, y: 4.95, w: 9, h: 0.35, fontSize: 11, color: G });
  // C: 징검다리 경로 + 포스트잇
  s = p.addSlide(); s.background = { color: BG };
  T(s, "제가 손본 다섯 군데", { x: 0.5, y: 0.35, w: 7, h: 0.5, fontSize: 22, bold: true, color: BR });
  s.addImage({ path: path.join(IMG, "gpt_infographic.png"), x: 8.55, y: 0.2, w: 1.2, h: 1.5, sizing: { type: "contain", w: 1.2, h: 1.5 } });
  flowH(s, p, { y: 2.55, nodeShape: "oval", nw: 1.22, nh: 0.85, nodeFill: "FFFFFF", nodeLine: OR, nodeLineW: 2, nodeText: BR, nodeSub: G, edge: OR, callLine: "D9A066", dash: "sysDot",
    callout: (s, p, w, x, y, cw, ch) => { const k = SW.indexOf(w);
      s.addShape(p.shapes.RECTANGLE, { x, y, w: cw, h: ch, fill: { color: k % 2 ? "FFE1E1" : YL }, line: { color: "E8C99A", width: 0.5 }, rotate: k % 2 ? 2 : -2, shadow: { type: "outer", blur: 3, offset: 2, angle: 45, color: "000000", opacity: 0.15 } });
      T(s, w.n, { x: x + 0.1, y: y + 0.08, w: cw - 0.2, h: 0.3, fontSize: 10, bold: true, color: BR });
      T(s, w.d, { x: x + 0.1, y: y + 0.42, w: cw - 0.2, h: 0.28, fontSize: 9, color: G });
    } });
  return p;
}

const OUT = process.env.OUT_DIR || __dirname;
const list = [["concept_1_corporate_red", c1], ["concept_2_ops_console", c2], ["concept_3_fintech_minimal", c3], ["concept_4_blueprint", c4], ["concept_5_warm_story", c5]];
(async () => { for (const [n, f] of list) { await f().writeFile({ fileName: path.join(OUT, n + ".pptx") }); console.log("wrote", n); } })();
