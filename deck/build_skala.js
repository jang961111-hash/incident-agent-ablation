// SKALA 발표용 8장 (Fintech Minimal 레이아웃 + 레드 + Warm Story 요소).
// 수치는 results/claims.json 과 반복 측정 결과 파일에서 읽는다 (손으로 적지 않음).
//   cd deck && NODE_PATH=node_modules node build_skala.js
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.join(__dirname, "..");
const RES = path.join(ROOT, "results");
const IMG = path.join(ROOT, "docs", "figures");
const CL = JSON.parse(fs.readFileSync(path.join(RES, "claims.json")));
const C = (id) => { const c = CL.find((x) => x.id === id); if (!c) throw new Error(id); return c; };
const claim = (id) => C(id)["값"];
const ab = (s) => { const m = s.match(/^([^→]+?)\s*→\s*([^\s(]+)/); return [m[1].trim(), m[2].trim()]; };
const lead = (s) => s.split(/\s/)[0]; // "-46%p [-70, -22] ★" → "-46%p"

const MISS = ab(claim("miss_base_final"));           // 56% → 9%
const WRONG = ab(claim("wrong_base_final"));         // 65% → 35%
const COSTV = claim("cost_base_final");              // $0.00343 → $0.00057 (-84%)
const COST = ab(COSTV), COSTP = COSTV.match(/\((-\d+%)\)/)[1];
const CONC = ab(claim("conc_10"));
const FAULT = ab(claim("fault"));
const RAG_MISS = lead(claim("pair_rag_miss"));
const V2_WRONG = lead(claim("pair_v2_wrong"));
const LAT_ALL = lead(claim("lat_all"));
const LAT_JUDGE = lead(claim("lat_judge"));
const RAG_PARA = claim("rag_para");
const [NCFG, NQ, NREP] = C("latctl_runs")["분모"].match(/(\d+)구성 x (\d+)문제 x (\d+)회/).slice(1);

// 5회 반복: 동시 질문 10개 동기/비동기 벽시계 비율
const concFiles = ["concurrency_bench_latest.json"].concat([2, 3, 4, 5].map((k) => `concurrency_bench_rep${k}_latest.json`));
const ratios = concFiles.map((f) => {
  const runs = JSON.parse(fs.readFileSync(path.join(RES, f))).runs.filter((r) => r.n === 10);
  const s = runs.find((r) => !r.async_io).wall_ms, a = runs.find((r) => r.async_io).wall_ms;
  return s / a;
});
const SPD = `${Math.min(...ratios).toFixed(1)}~${Math.max(...ratios).toFixed(1)}배`;
// 5회 반복: 장애 주입 seed 5개 합계
const faultFiles = ["fault_bench_latest.json"].concat([11, 23, 42, 101].map((k) => `fault_bench_seed${k}_latest.json`));
const fsum = (v, key) => faultFiles.reduce((a, f) => a + JSON.parse(fs.readFileSync(path.join(RES, f))).variants[v][key], 0);
const FB = `${fsum("base", "completed_among_faulted")}/${fsum("base", "queries_with_fault")}`;
const FF = `${fsum("final", "completed_among_faulted")}/${fsum("final", "queries_with_fault")}`;
console.log({ MISS, WRONG, COST, COSTP, CONC, FAULT, RAG_MISS, V2_WRONG, LAT_ALL, LAT_JUDGE, RAG_PARA, NCFG, NQ, NREP, ratios: ratios.map((r) => r.toFixed(2)), SPD, FB, FF });

// 발표자 노트: docs/발표/발표_대본_이전안.md D안의 ">" 줄 그대로
const SCRIPT = fs.readFileSync(path.join(ROOT, "docs", "발표", "발표_대본_이전안.md"), "utf8");
const dPart = SCRIPT.split("## D안")[1].split("### 30초")[0];
const NOTES = {};
dPart.split(/\n### /).slice(1).forEach((sec) => {
  const k = parseInt(sec, 10);
  NOTES[k] = sec.split("\n").filter((l) => l.startsWith("> ")).map((l) => l.slice(2)).join("\n");
});

const F = process.env.DECK_FONT || "Noto Sans KR";
const RED = "C8102E", ORG = "F26B21", INK = "1A1A1A", CARD = "F4F4F5", G = "6B7280", LINE = "E5E7EB";
const PINK = "FDECEE", YL = "FFF1D6";
const WHO = "SKALA 4기 · 광주 2반 · G062 장병헌";
const W = 10, H = 5.625;

const p = new pptxgen();
p.layout = "LAYOUT_16x9"; p.author = "장병헌 (G062)"; p.title = "장애 대응 AI 에이전트, 무엇이 진짜 효과였나";
p.theme = { headFontFace: F, bodyFontFace: F };
const T = (s, text, o) => s.addText(text, Object.assign({ fontFace: F, margin: 0, lang: "ko-KR" }, o));
const RR = (s, o) => s.addShape(p.shapes.ROUNDED_RECTANGLE, Object.assign({ rectRadius: 0.18 }, o));
const OV = (s, o) => s.addShape(p.shapes.OVAL, o);
const LN = (s, x, y, w, h, color, wt = 1.5) => s.addShape(p.shapes.LINE, { x, y, w, h, line: { color, width: wt } });
const img = (s, f, x, y, w, h) => s.addImage({ path: path.join(IMG, f), x, y, w, h, sizing: { type: "contain", w, h } });

let page = 0;
function slide(title, noteKey) {
  const s = p.addSlide(); page++;
  s.background = { color: "FFFFFF" };
  if (title) {
    OV(s, { x: 0.6, y: 0.47, w: 0.16, h: 0.16, fill: { color: RED }, line: { color: RED } });
    T(s, title, { x: 0.88, y: 0.3, w: 7.5, h: 0.5, fontSize: 24, bold: true, color: INK, valign: "middle" });
  }
  T(s, WHO, { x: 0.6, y: 5.28, w: 5, h: 0.22, fontSize: 8, color: G, valign: "middle" });
  T(s, String(page), { x: 8.9, y: 5.28, w: 0.5, h: 0.22, fontSize: 8, color: G, align: "right", valign: "middle" });
  if (NOTES[noteKey]) s.addNotes(NOTES[noteKey]);
  return s;
}
// 포스트잇 (Warm Story)
function sticky(s, x, y, w, h, head, body, fill = YL, rot = -1.5) {
  s.addShape(p.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: "E8D3A8", width: 0.5 }, rotate: rot,
    shadow: { type: "outer", blur: 3, offset: 2, angle: 45, color: "000000", opacity: 0.15 } });
  T(s, [{ text: head, options: { fontSize: 14, bold: true, color: INK, breakLine: true } }, { text: body, options: { fontSize: 10, color: G } }],
    { x: x + 0.15, y: y + 0.08, w: w - 0.3, h: h - 0.16, valign: "middle", rotate: rot, paraSpaceAfter: 2 });
}
// 말풍선
function bubble(s, x, y, w, h, who, text, right = false, color = RED) {
  RR(s, { x, y, w, h, fill: { color: right ? PINK : "FFFFFF" }, line: { color, width: 1.5 }, rectRadius: 0.25 });
  s.addShape(p.shapes.ISOSCELES_TRIANGLE, { x: right ? x + w - 0.6 : x + 0.35, y: y + h - 0.02, w: 0.25, h: 0.2, rotate: 180, fill: { color: right ? PINK : "FFFFFF" }, line: { color, width: 1.5 } });
  RR(s, { x: right ? x + w - 0.62 : x + 0.33, y: y + h - 0.06, w: 0.29, h: 0.08, fill: { color: right ? PINK : "FFFFFF" }, line: { color: right ? PINK : "FFFFFF", width: 0 }, rectRadius: 0 });
  T(s, [{ text: who, options: { fontSize: 10, color: G, breakLine: true } }, { text, options: { fontSize: 15, bold: true, color: INK } }],
    { x: x + 0.25, y: y + 0.08, w: w - 0.5, h: h - 0.16, valign: "middle", paraSpaceAfter: 3 });
}

// 1 표지
{
  const s = slide(null, 1);
  img(s, "gpt_webtoon.png", 5.55, 0.55, 4.1, 4.1);
  OV(s, { x: 0.6, y: 0.9, w: 0.26, h: 0.26, fill: { color: RED }, line: { color: RED } });
  T(s, "장애 대응 AI 에이전트,\n무엇이 진짜 효과였나", { x: 0.6, y: 1.35, w: 4.8, h: 1.5, fontSize: 30, bold: true, color: INK, valign: "top" });
  RR(s, { x: 0.6, y: 3.1, w: 4.6, h: 0.62, fill: { color: PINK }, line: { color: PINK }, rectRadius: 0.3 });
  T(s, [{ text: "고친 것 5가지", options: { bold: true, color: RED } }, { text: " · 스위치로 하나씩 증명", options: { color: INK } }],
    { x: 0.8, y: 3.1, w: 4.3, h: 0.62, fontSize: 14, valign: "middle" });
  T(s, "광주 2반 장병헌", { x: 0.6, y: 3.95, w: 4.5, h: 0.35, fontSize: 13, color: G });
}

// 2 문제
{
  const s = slide("새벽 장애, 에이전트가 헛짚었어요", 2);
  bubble(s, 0.6, 1.15, 4.6, 0.95, "당직자", "\"DB 프라이머리가 다운됐습니다\"");
  bubble(s, 1.2, 2.5, 4.4, 0.95, "원본 에이전트", "\"응답 지연 매뉴얼입니다\"", true, ORG);
  T(s, "✕ 엉뚱한 매뉴얼", { x: 1.2, y: 3.62, w: 4.4, h: 0.3, fontSize: 11, bold: true, color: ORG, align: "right" });
  RR(s, { x: 6.1, y: 1.15, w: 3.3, h: 2.6, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.22 });
  T(s, "맞는 매뉴얼을", { x: 6.35, y: 1.35, w: 2.9, h: 0.3, fontSize: 13, color: G });
  T(s, MISS[0], { x: 6.35, y: 1.7, w: 2.9, h: 1.3, fontSize: 72, bold: true, color: RED, valign: "middle" });
  T(s, "놓쳤어요", { x: 6.35, y: 3.1, w: 2.9, h: 0.35, fontSize: 15, bold: true, color: INK });
  sticky(s, 5.9, 4.08, 3.6, 0.95, "이유: 경고 문구로 골라요", "질문이 아니라 모니터링 경고의 단어로 매뉴얼 선택");
}

// 3 내가 바꾼 것 5가지
{
  const s = slide("제가 바꾼 건 5곳이에요", 3);
  const NODES = ["route", "plan", "research", "analysis", "write", "validate"];
  const KO = ["질문 분류", "계획", "MCP 도구 조회", "분석", "답 작성", "검수"];
  const rowY = (i) => 1.05 + i * 0.68;
  NODES.forEach((n, i) => {
    RR(s, { x: 0.6, y: rowY(i), w: 2.75, h: 0.52, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.26 });
    T(s, [{ text: `${i + 1}  `, options: { color: RED, bold: true } }, { text: n, options: { color: INK, bold: true } }, { text: `  ${KO[i]}`, options: { color: G, fontSize: 9 } }],
      { x: 0.82, y: rowY(i), w: 2.5, h: 0.52, fontSize: 12, valign: "middle" });
    if (i < 5) LN(s, 1.0, rowY(i) + 0.52, 0, 0.16, "D1D5DB");
  });
  const CARDS = [
    // 순서 = 만들고 실험한 순서(대본 3장과 같음). 단계 표시는 끼어드는 위치
    [2, "RAG 매뉴얼 검색", "맞는 매뉴얼 페이지 펴 주기", "3단계"],
    [5, "LLM Judge 검수", "답을 다시 보는 AI 채점관", "6단계"],
    [4, "캐스케이드", "신입 먼저, 막히면 선배", "5단계"],
    [2, "v2 보완", "억지로 고르지 않기", "3·6단계"],
    [0, "비동기 · 도구 고장 허용", "줄 안 세우고 동시에", "1~3단계"],
  ];
  CARDS.forEach((c, j) => {
    const y = 1.0 + j * 0.82, x = 3.85;
    RR(s, { x, y, w: 5.55, h: 0.68, fill: { color: "FFFFFF" }, line: { color: LINE, width: 1 }, rectRadius: 0.2 });
    RR(s, { x: x + 0.2, y: y + 0.2, w: 0.5, h: 0.28, fill: { color: RED }, line: { color: RED }, rectRadius: 0.14 });
    OV(s, { x: x + 0.44, y: y + 0.225, w: 0.23, h: 0.23, fill: { color: "FFFFFF" }, line: { color: "FFFFFF" } });
    T(s, c[1], { x: x + 0.9, y: y + 0.06, w: 3.4, h: 0.32, fontSize: 13, bold: true, color: INK, valign: "middle" });
    T(s, c[2], { x: x + 0.9, y: y + 0.37, w: 3.4, h: 0.25, fontSize: 10, color: G, valign: "middle" });
    RR(s, { x: x + 4.35, y: y + 0.2, w: 1.0, h: 0.28, fill: { color: PINK }, line: { color: PINK }, rectRadius: 0.14 });
    T(s, c[3], { x: x + 4.35, y: y + 0.2, w: 1.0, h: 0.28, fontSize: 9, bold: true, color: RED, align: "center", valign: "middle" });
  });
  T(s, "원본은 그대로, 스위치로 켜고 끄기", { x: 3.85, y: 5.0, w: 5.55, h: 0.25, fontSize: 9, color: G, align: "right" });
}

// 4 어떻게 증명했나
{
  const s = slide("어떻게 증명했나요", 4);
  const BIG = [[NCFG, "가지 버전"], [NQ, "안 본 문제"], [NREP, "번씩 반복"]];
  BIG.forEach((b, i) => {
    const x = 0.6 + i * 2.25;
    RR(s, { x, y: 1.1, w: 1.95, h: 1.9, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.22 });
    T(s, b[0], { x, y: 1.25, w: 1.95, h: 1.05, fontSize: 54, bold: true, color: RED, align: "center", valign: "middle" });
    T(s, b[1], { x, y: 2.35, w: 1.95, h: 0.4, fontSize: 13, bold: true, color: INK, align: "center", valign: "middle" });
    if (i < 2) T(s, "×", { x: x + 1.95, y: 1.75, w: 0.3, h: 0.5, fontSize: 22, color: G, align: "center", valign: "middle" });
  });
  T(s, "holdout: 개발 중 한 번도 안 본 시험 문제", { x: 0.6, y: 3.08, w: 6.4, h: 0.28, fontSize: 10, color: G });
  [["⇄", "같은 문제끼리 짝지어 비교"], ["▤", "숫자는 결과 파일에서 자동"]].forEach((r, i) => {
    const x = 0.6 + i * 3.25;
    RR(s, { x, y: 3.55, w: 3.05, h: 0.62, fill: { color: "FFFFFF" }, line: { color: LINE, width: 1 }, rectRadius: 0.2 });
    OV(s, { x: x + 0.15, y: 3.68, w: 0.36, h: 0.36, fill: { color: RED }, line: { color: RED } });
    T(s, r[0], { x: x + 0.15, y: 3.68, w: 0.36, h: 0.36, fontSize: 12, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
    T(s, r[1], { x: x + 0.62, y: 3.55, w: 2.35, h: 0.62, fontSize: 11.5, bold: true, color: INK, valign: "middle" });
  });
  sticky(s, 0.75, 4.42, 4.3, 0.7, "Ablation = 스위치 하나씩 켜고 끄기", "무엇이 효과였는지 가려내는 방법", YL, -1);
  img(s, "gpt_infographic.png", 7.25, 0.95, 2.35, 4.15);
}

// 5 무엇이 진짜 효과였나 (핵심)
{
  const s = slide("무엇이 진짜 효과였나", 5);
  RR(s, { x: 0.45, y: 0.95, w: 6.75, h: 3.3, fill: { color: "FFFFFF" }, line: { color: LINE, width: 1 }, rectRadius: 0.12 });
  img(s, "fig6_contrib.png", 0.55, 1.03, 6.55, 3.14);
  sticky(s, 7.45, 0.95, 2.1, 0.95, `RAG: ${RAG_MISS}`, "맞는 매뉴얼 누락\n효과 확인 ✓", YL, -2);
  sticky(s, 7.45, 2.05, 2.1, 0.95, `v2 보완: ${V2_WRONG}`, "엉뚱한 매뉴얼 혼입\n효과 확인 ✓", YL, 1.5);
  sticky(s, 7.45, 3.15, 2.1, 0.95, "Judge 단독", `효과 확인 안 됨\n지연만 ${LAT_JUDGE}`, PINK, -1.5);
  RR(s, { x: 0.45, y: 4.48, w: 9.1, h: 0.6, fill: { color: RED }, line: { color: RED }, rectRadius: 0.3 });
  T(s, "AI 검수를 넣는다고 좋아지진 않았다: 측정이 먼저", { x: 0.65, y: 4.48, w: 8.7, h: 0.6, fontSize: 16, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
}

// 6 운영에서
{
  const s = slide("운영에서는요", 6);
  const M = [
    ["장애 1건 비용", COSTP, `${COST[0]} → ${COST[1]}`],
    ["동시 질문 10개", CONC[1], `${CONC[0]}에서`],
    ["고장 나도 완주", FAULT[1], `${FAULT[0]}에서`],
  ];
  M.forEach((m, i) => {
    const x = 0.6 + i * 2.98;
    RR(s, { x, y: 1.05, w: 2.8, h: 2.25, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.22 });
    T(s, m[0], { x: x + 0.25, y: 1.22, w: 2.35, h: 0.3, fontSize: 12, color: G });
    T(s, m[1], { x: x + 0.25, y: 1.6, w: 2.35, h: 1.0, fontSize: 46, bold: true, color: RED, valign: "middle" });
    T(s, m[2], { x: x + 0.25, y: 2.75, w: 2.35, h: 0.3, fontSize: 11.5, color: INK });
  });
  RR(s, { x: 0.6, y: 3.55, w: 8.75, h: 0.62, fill: { color: "FFFFFF" }, line: { color: RED, width: 1.5 }, rectRadius: 0.3 });
  RR(s, { x: 0.75, y: 3.67, w: 1.5, h: 0.38, fill: { color: RED }, line: { color: RED }, rectRadius: 0.19 });
  T(s, "5회 반복 확인", { x: 0.75, y: 3.67, w: 1.5, h: 0.38, fontSize: 10.5, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  T(s, [{ text: "속도 배수 ", options: { color: G } }, { text: SPD, options: { bold: true, color: INK } },
    { text: "   ·   고장 위치 5가지 ", options: { color: G } }, { text: `${FB} → ${FF}`, options: { bold: true, color: INK } }],
    { x: 2.45, y: 3.55, w: 6.8, h: 0.62, fontSize: 13, valign: "middle" });
  sticky(s, 0.75, 4.42, 3.9, 0.66, `대신 질의당 ${LAT_ALL}`, "같은 부하 재측정", PINK, -1);
}

// 7 시연
{
  const s = slide("같은 질문, 다른 답", 7);
  T(s, "실제 실행 기록", { x: 0.88, y: 0.8, w: 3, h: 0.25, fontSize: 10, color: G });
  sticky(s, 0.6, 1.5, 2.75, 0.95, "비용 약 6분의 1", `장애 1건 ${COSTP}`, YL, -2);
  sticky(s, 0.6, 2.8, 2.75, 0.95, "혼입은 남았어요", "디스크 부족 매뉴얼이 섞임", PINK, 1.5);
  RR(s, { x: 3.75, y: 0.95, w: 5.85, h: 4.25, fill: { color: "FFFFFF" }, line: { color: LINE, width: 1 }, rectRadius: 0.1 });
  img(s, "fig10_demo.png", 3.83, 1.0, 5.69, 4.15);
}

// 8 한계와 배운 점
{
  const s = slide("한계와 배운 점", 8);
  const L = [[RAG_PARA, "자기 말로 묻는 질문", "Recall@1"], [WRONG[1], "엉뚱한 매뉴얼 혼입", "아직 남음"], ["합성", "평가셋", "사람 채점 없음"]];
  L.forEach((l, i) => {
    const x = 0.6 + i * 2.98;
    RR(s, { x, y: 1.0, w: 2.8, h: 1.6, fill: { color: CARD }, line: { color: CARD }, rectRadius: 0.22 });
    T(s, l[0], { x: x + 0.25, y: 1.12, w: 2.35, h: 0.75, fontSize: 36, bold: true, color: ORG, valign: "middle" });
    T(s, [{ text: l[1], options: { bold: true, color: INK, breakLine: true } }, { text: l[2], options: { color: G } }],
      { x: x + 0.25, y: 1.9, w: 2.35, h: 0.6, fontSize: 11.5, valign: "middle" });
  });
  bubble(s, 0.6, 2.9, 5.6, 0.95, "배운 점", "기능을 더하기 전에, 재는 법부터");
  T(s, "감사합니다", { x: 6.5, y: 2.85, w: 3.0, h: 0.8, fontSize: 32, bold: true, color: RED, align: "right", valign: "middle" });
  T(s, "github.com/jang961111-hash/incident-agent-ablation", { x: 0.6, y: 4.55, w: 8.8, h: 0.3, fontSize: 10, color: G, align: "right",
    hyperlink: { url: "https://github.com/jang961111-hash/incident-agent-ablation" } });
}

const OUT = process.env.OUT_FILE || path.join(__dirname, "incident-agent-ablation_skala.pptx");
p.writeFile({ fileName: OUT }).then(() => console.log("wrote", OUT));
