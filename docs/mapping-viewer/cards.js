// 규제 판정 화면 (compliance/regulation-cards.md). BOM 을 규제 조항마다 대 본 결과와, 조항을 누르면 원문과 요구 사실.
// 데이터는 export_data.py 가 data/cards/ 에 둔 JSON. 카드 보기·추출기 비교·승인은 내부 화면의 몫이라 여기 두지 않는다.
if (document.querySelector(".card-viewer")) (() => {
const root = document.querySelector(".card-viewer");
const BASE = root.dataset.base || "data/cards/";
const REG_NAME = {EUAIA: "EU AI Act", NISTRMF: "NIST AI RMF", ISO42001: "ISO/IEC 42001"};
const VERDICTS = ["반영", "부분 반영", "미반영", "검토 필요", "비적용"];
const STATUS_KO = {present: "있음", partial: "부분 대응", missing: "비어 있음", gap: "자리 없음", not_required: "요구 안 됨", unknown: "판단 못 함"};
const MARK_CLS = {present: "", partial: "partial", missing: "missing", gap: "missing", not_required: "muted", unknown: "muted"};      // 원문 구절의 색
const $ = (sel) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const regOf = (id) => REG_NAME[id.split("-")[1]] || id.split("-")[1];
const vclass = (v) => "v-" + v.replace(/\s/g, "");
let cards = [], cardById = {}, vocab = {}, profile = {}, targets = {}, examples = [];
let pending = new Set(), partial = {}, profileApproved = true;      // 승인 안 된 줄, 부분 대응 줄(개념 → 이유), 프로파일 승인 여부
const KIND_KO = {system: "시스템", model: "모델", dataset: "데이터셋", software: "소프트웨어"};
const RISK_KO = {high_risk: "고위험 AI 시스템", minimal_risk: "고위험 아님", limited_risk: "투명성 의무 (50조)", gpai: "범용 AI 모델", gpai_systemic: "범용 AI 모델 (체계적 위험)", any: "모든 AI 시스템"};
const RISK_ORDER = ["high_risk", "minimal_risk", "limited_risk", "gpai", "gpai_systemic"];
const ROLE_KO = {provider: "제공자", deployer: "배포자", importer: "수입자", distributor: "유통자", authorised_representative: "수권대리인", operator: "운영자", organisation: "조직"};
let currentBom = null, currentName = "", currentSize = 0;      // 지금 판정하는 BOM. 올린 것이든 예제든 브라우저 안에서 판정한다 (프로파일을 바꾸면 다시)

async function load(name) { const r = await fetch(BASE + name); if (!r.ok) throw new Error(name); return r.json(); }

async function init() {
  const [c, v, p, ex, src] = await Promise.all([load("cards.json"), load("vocabulary.json"), load("profile.json"), load("boms/index.json").catch(() => []), load("source.json").catch(() => ({}))]);
  cards = c; cardById = Object.fromEntries(c.map((x) => [x.card_id, x])); vocab = Object.fromEntries(v.concepts.map((x) => [x.id, x])); examples = ex;
  if (src.cards === "gold") { const n = document.createElement("p"); n.className = "cv-note"; n.textContent = "지금 판정에 쓰는 카드는 요구사항 표에서 변환한 정답 카드(cards/gold)다. 승인한 카드가 생기면 그것으로 바뀐다."; root.prepend(n); }
  targets = p.targets || {};                          // fact 의 target(대상 구성요소 종류)을 BOM 에서 찾는 법
  profileApproved = p.status === "approved";
  for (const line of p.lines) {                       // 개념별 줄: concept → {cdx: [...], spdx: [...]}
    const e = (profile[line.concept] ||= {cdx: [], spdx: []});
    for (const x of [line.cdx_path, ...(line.cdx_paths_more || [])]) if (x && !e.cdx.includes(x)) e.cdx.push(x);
    for (const x of [line.spdx_path, ...(line.spdx_paths_more || [])]) if (x && !e.spdx.includes(x)) e.spdx.push(x);
    if (line.status === "pending_review") pending.add(line.concept);
    if (line.fit === "partial") partial[line.concept] = line.fit_note || "부분 대응 (경로의 대상 범위 또는 표현 형태가 요구와 다름)";
  }
  initJudgment();
}

// ---------- 공통 ----------
function regSelect(el, onChange) {
  el.innerHTML = `<option value="">모든 규제</option>` + Object.entries(REG_NAME).map(([k, n]) => `<option value="${k}">${n}</option>`).join("");
  el.addEventListener("change", onChange);
}
function groupedList(container, items, render, onPick) {
  container.innerHTML = "";
  let lastReg = null;
  for (const it of items) {
    const reg = regOf(it.card_id);
    if (reg !== lastReg) { const g = document.createElement("div"); g.className = "cv-group"; g.textContent = reg; container.appendChild(g); lastReg = reg; }
    const row = document.createElement("div"); row.className = "cv-item"; row.dataset.id = it.card_id; row.innerHTML = render(it);
    row.addEventListener("click", () => { container.querySelectorAll(".cv-item").forEach((r) => r.classList.toggle("active", r === row)); onPick(it); });
    container.appendChild(row);
  }
}
function label(concept) { return vocab[concept]?.label_ko || concept; }

// 원문에 구절을 칠한다. spans: [{text, cls, idx}] . 겹치면 긴 것부터 칠하고 나머지는 건너뛴다.
function highlightText(text, spans) {
  if (!text) return "";
  const marks = [];
  const taken = [];
  const sorted = [...spans].filter((s) => s.text).sort((a, b) => b.text.length - a.text.length);
  for (const s of sorted) {
    for (const piece of s.text.split(" | ")) {
      const pos = text.indexOf(piece);
      if (pos < 0) continue;
      const end = pos + piece.length;
      if (taken.some(([a, b]) => pos < b && end > a)) continue;
      taken.push([pos, end]); marks.push({pos, end, cls: s.cls, idx: s.idx, title: s.title});
    }
  }
  marks.sort((a, b) => a.pos - b.pos);
  let out = "", cur = 0;
  for (const m of marks) {
    out += esc(text.slice(cur, m.pos));
    out += `<mark class="${m.cls || ""}" data-idx="${m.idx}" title="${esc(m.title || "")}">${esc(text.slice(m.pos, m.end))}</mark>`;
    cur = m.end;
  }
  return out + esc(text.slice(cur));
}
function wireMarks(detail) {
  detail.querySelectorAll("mark[data-idx]").forEach((m) => m.addEventListener("click", () => focusFact(detail, m.dataset.idx)));
  detail.querySelectorAll("tr[data-idx]").forEach((tr) => tr.addEventListener("click", () => focusFact(detail, tr.dataset.idx)));
}
function focusFact(detail, idx) {
  detail.querySelectorAll("mark, tr[data-idx]").forEach((el) => el.classList.toggle("focus", el.dataset.idx === idx));
  const m = detail.querySelector(`mark[data-idx="${idx}"]`); if (m) m.scrollIntoView({block: "nearest"});
}

// ---------- 판정 ----------
// 처음엔 BOM 을 올리는 자리(드롭존)만 보인다. 파일을 끌어다 놓거나 골라 올리거나 예제를 누르면 브라우저 안에서 판정해 화면을 연다.
let currentRecord = null;
function initJudgment() {
  const drop = $("#cv-drop"), input = $("#cv-bom-file");
  $("#cv-examples").innerHTML = examples.map((e, i) => `<button type="button" data-i="${i}" title="${esc(e.note || "")} (${esc(e.file)}, ${fmtSize(e.size || 0)})">${esc(e.label || e.subject)}</button>`).join("") || `<span class="cv-muted">없음</span>`;
  $("#cv-examples").querySelectorAll("button").forEach((b) => b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    const e = examples[+b.dataset.i];
    try { const r = await fetch(BASE + "boms/" + e.file); if (!r.ok) throw new Error(e.file); useBom(await r.json(), e.file, e.size, e.system_profile); }
    catch (err) { dropError(`예제를 읽지 못했다: ${esc(err.message)}`); }
  }));
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); input.click(); } });
  for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.add("over"); });
  for (const t of ["dragleave", "drop"]) drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", (ev) => { const f = ev.dataTransfer?.files?.[0]; if (f) readFile(f); else dropError("파일이 아니다"); });
  input.addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) readFile(f); input.value = ""; });
  $("#cv-another").addEventListener("click", () => { $("#cv-main").hidden = true; showBomView(false); $("#cv-drop-error").hidden = true; drop.hidden = false; drop.focus(); });
  $("#cv-show-bom").addEventListener("click", () => showBomView($("#cv-bom-view").hidden));
  $("#cv-hide-bom").addEventListener("click", () => showBomView(false));
  regSelect($("#cv-reg"), () => { renderSummary(); renderJudgList(); });
  $("#cv-verdict-filter").addEventListener("change", renderJudgList);
  for (const b of extraBoxes()) b.addEventListener("change", () => {          // 체계적 위험은 범용 AI 모델 위에 얹힌다
    const gpai = extraBoxes().find((x) => x.value === "gpai"), systemic = extraBoxes().find((x) => x.value === "gpai_systemic");
    if (b === systemic && b.checked) gpai.checked = true;
    if (b === gpai && !b.checked) systemic.checked = false;
  });
  for (const el of [$("#cv-system"), ...extraBoxes(), ...roleBoxes()]) el.addEventListener("change", () => { if (currentBom) showRecord(judgeBom(currentBom, currentName, systemProfile())); });
}
async function readFile(file) {
  try {
    const bom = JSON.parse(await file.text());
    if (!bom || typeof bom !== "object" || Array.isArray(bom)) throw new Error("JSON 객체가 아니다");
    if (bom.bomFormat !== "CycloneDX") throw new Error("CycloneDX 문서가 아니다 (bomFormat 이 " + (bom.bomFormat ? `'${bom.bomFormat}'` : "없음") + ")");
    useBom(bom, file.name, file.size, null);
  } catch (err) { dropError(`읽을 수 없는 파일 (${esc(file.name)}): ${esc(err.message)}`); }
}
function dropError(html) { const e = $("#cv-drop-error"); e.innerHTML = html; e.hidden = false; }
// BOM 하나를 화면에 올린다. system 이 있으면(예제) 프로파일 칸을 그 값으로 채우고, 없으면(올린 파일) 비운다. 어느 쪽이든 바꿀 수 있다
function useBom(bom, name, size, system) {
  currentBom = bom; currentName = name; currentSize = size || 0;
  $("#cv-drop-error").hidden = true;
  applyProfileInputs(system || {});
  $("#cv-file").innerHTML = `<span title="${esc(name)}">${esc(name)}</span><span class="cv-size">${fmtSize(currentSize)}</span>`;
  showBomView(false);
  $("#cv-drop").hidden = true; $("#cv-main").hidden = false;
  $("#cv-judg-detail").innerHTML = `<p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나온다.</p>`;
  showRecord(judgeBom(bom, name, systemProfile()));
}
const BOM_VIEW_MAX = 400000;                          // 글자 수. 큰 BOM(1.5 MB)은 앞부분만 보인다
function showBomView(on) {
  const view = $("#cv-bom-view"); view.hidden = !on; $("#cv-show-bom").textContent = on ? "BOM 닫기" : "BOM 보기";
  if (!on || !currentBom) return;
  const text = JSON.stringify(currentBom, null, 2), cut = text.length > BOM_VIEW_MAX;
  $("#cv-bom-pre").textContent = cut ? text.slice(0, BOM_VIEW_MAX) + `\n… (앞 ${fmtSize(BOM_VIEW_MAX)} 만 보인다. 전체 ${fmtSize(text.length)})` : text;
  let n = 0; (function walk(items) { for (const c of items || []) { n += 1; walk(c.components); } })(currentBom.components);
  $("#cv-bom-info").textContent = `${currentName} · ${currentBom.bomFormat} ${currentBom.specVersion || ""} · 구성요소 ${n}개 · ${fmtSize(currentSize || text.length)}`;
}
const fmtSize = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;
// 시스템 프로파일 (2층): 위험등급과 역할. 위험등급은 시스템 칸 하나(고위험 / 고위험 아님)에 얹히는 것(투명성 의무, 범용 AI 모델, 체계적 위험)을
// 더한 목록이다. 시스템 칸을 고르지 않으면 위험등급을 비워 두어, 위험등급을 보는 카드는 검토 필요가 된다
const roleBoxes = () => [...root.querySelectorAll("input[name=cv-role]")];
const extraBoxes = () => [...root.querySelectorAll("input[name=cv-extra]")];
const asList = (v) => Array.isArray(v) ? v : v ? [v] : [];
function systemProfile() {
  const sys = $("#cv-system").value, extras = extraBoxes().filter((b) => b.checked).map((b) => b.value);
  const roles = roleBoxes().filter((b) => b.checked).map((b) => b.value);
  return {...(sys ? {risk_class: [sys, ...extras]} : {}), ...(roles.length ? {role: roles} : {})};
}
function applyProfileInputs(system) {
  const rc = asList(system.risk_class), roles = asList(system.role);
  $("#cv-system").value = !rc.length ? "" : rc.includes("high_risk") ? "high_risk" : "minimal_risk";
  for (const b of extraBoxes()) b.checked = rc.includes(b.value) || (b.value === "gpai" && rc.includes("gpai_systemic"));
  for (const b of roleBoxes()) b.checked = roles.includes(b.value);
}
const profileText = (system) => {
  const rc = asList(system?.risk_class);
  const r = [...RISK_ORDER.filter((x) => rc.includes(x)), ...rc.filter((x) => !RISK_ORDER.includes(x))]
    .filter((x) => !(x === "gpai" && rc.includes("gpai_systemic"))).map((x) => RISK_KO[x] || x).join("+");
  const roles = asList(system?.role);
  const o = roles.map((x) => ROLE_KO[x] || x).join("+");
  return r || o ? [r, o].filter(Boolean).join(" · ") : "없음";
};
function regCards() {                                 // 고른 규제의 카드 판정
  const reg = $("#cv-reg").value;
  return currentRecord.cards.filter((r) => !reg || r.card_id.startsWith("RC-" + reg + "-"));
}
// 카드 단위는 호라서 항(parent_clause_id) 하나에 카드가 여럿일 수 있다. 항의 종합 판정 (cards/judge/judge.py 의 aggregate 와 같은 규칙):
// 판정한 카드(반영·부분 반영·미반영)가 전부 반영이면 반영, 전부 미반영이면 미반영, 섞이면 부분 반영. 판정한 카드가 없으면 검토 필요가 있을 때 검토 필요, 아니면 비적용.
const clauseOf = (id) => cardById[id]?.source?.parent_clause_id || cardById[id]?.source?.clause_id || id.replace(/^RC-[A-Z0-9]+-/, "");
function aggregate(verdicts) {
  const judged = verdicts.filter((v) => v === "반영" || v === "부분 반영" || v === "미반영");
  if (!judged.length) return verdicts.includes("검토 필요") ? "검토 필요" : "비적용";
  if (judged.every((v) => v === "반영")) return "반영";
  if (judged.every((v) => v === "미반영")) return "미반영";
  return "부분 반영";
}
function clauseGroups(rs) {                           // 판정 목록 → [{clause, reg, verdict, cards}] (원문 차례)
  const groups = new Map();
  for (const r of rs) { const key = regOf(r.card_id) + "|" + clauseOf(r.card_id); if (!groups.has(key)) groups.set(key, {clause: clauseOf(r.card_id), reg: regOf(r.card_id), cards: []}); groups.get(key).cards.push(r); }
  return [...groups.values()].map((g) => ({...g, verdict: aggregate(g.cards.map((r) => r.verdict))}));
}
function showRecord(rec) { currentRecord = rec; renderSummary(); renderJudgList(); }
function renderSummary() {
  if (!currentRecord) return;
  const rec = currentRecord, rs = regCards(), total = rs.length, groups = clauseGroups(rs);
  const s = Object.fromEntries(VERDICTS.map((v) => [v, rs.filter((r) => r.verdict === v).length]));
  const cs = Object.fromEntries(VERDICTS.map((v) => [v, groups.filter((g) => g.verdict === v).length]));
  const lack = [!rec.system_profile?.risk_class && "시스템", !rec.system_profile?.role && "역할"].filter(Boolean);
  $("#cv-judg-summary").innerHTML = `<div class="cv-stat"><b>${esc(rec.bom.subject || rec.bom.serialNumber || "")}</b>카드 ${total}장 (조항 ${groups.length}개) · ${esc(rec.bom.bomFormat)} ${esc(rec.bom.specVersion)} · 시스템 프로파일 ${esc(profileText(rec.system_profile))}${lack.length ? ` <span class="cv-muted">(${lack.join("·")}을 고르지 않아 그것을 보는 조항은 검토 필요)</span>` : ""}</div>`
    + VERDICTS.map((v) => `<div class="cv-stat"><span class="cv-verdict ${vclass(v)}">${v}</span> <b>${s[v]}</b><span class="cv-muted"> · 조항 ${cs[v]}</span></div>`).join("")
    + `<div class="cv-bar" style="flex-basis:100%">${VERDICTS.map((v) => `<span class="${vclass(v)}" style="width:${100 * s[v] / Math.max(total, 1)}%"></span>`).join("")}</div>`;
}
function renderJudgList() {
  if (!currentRecord) return;
  const want = $("#cv-verdict-filter").value;
  const groups = clauseGroups(regCards()).map((g) => ({...g, cards: g.cards.filter((r) => !want || r.verdict === want)})).filter((g) => g.cards.length);
  const container = $("#cv-judg-list");
  container.innerHTML = "";
  let lastReg = null;
  for (const g of groups) {
    if (g.reg !== lastReg) { const h = document.createElement("div"); h.className = "cv-group"; h.textContent = g.reg; container.appendChild(h); lastReg = g.reg; }
    if (g.cards.length > 1) {                          // 호가 여럿인 항: 항의 종합 판정을 머리로
      const h = document.createElement("div"); h.className = "cv-clause"; h.innerHTML = `<span class="cv-id">${esc(g.clause)}</span><span class="cv-sub"><span class="cv-verdict ${vclass(g.verdict)}">${g.verdict}</span> 종합</span>`; container.appendChild(h);
    }
    for (const r of g.cards) {
      const f = r.facts || []; const p = f.filter((x) => x.status === "present").length, n = f.filter((x) => x.status === "not_required").length;
      const row = document.createElement("div"); row.className = "cv-item" + (g.cards.length > 1 ? " cv-point" : ""); row.dataset.id = r.card_id;
      row.innerHTML = `<span class="cv-id">${esc(cardById[r.card_id]?.source?.clause_id || r.card_id.replace(/^RC-[A-Z0-9]+-/, ""))}</span><span class="cv-sub"><span class="cv-verdict ${vclass(r.verdict)}">${r.verdict}</span> ${p}/${f.length - n}</span>`;
      row.addEventListener("click", () => { container.querySelectorAll(".cv-item").forEach((x) => x.classList.toggle("active", x === row)); renderJudg(r); });
      container.appendChild(row);
    }
  }
}
function renderJudg(r) {
  const d = $("#cv-judg-detail"), card = cardById[r.card_id], facts = r.facts || [];
  const text = card?.source?.excerpt_en, ko = card?.source?.excerpt;
  // 판정 기록의 fact 는 카드 fact 와 같은 차례라, 원문 구절을 그 fact 의 상태 색으로 칠한다
  const spans = (card?.facts || []).map((f, i) => ({text: f.highlight_en || f.gap_highlight_en, cls: MARK_CLS[facts[i]?.status] ?? "", idx: i,
    title: `${label(f.concept)} · ${STATUS_KO[facts[i]?.status] || ""}`}));
  d.innerHTML = `
    <h3>${esc(card?.title || r.title || r.card_id)} <span class="cv-verdict ${vclass(r.verdict)}">${r.verdict}</span></h3>
    <div class="cv-meta">
      <span class="cv-chip">${esc(card?.regulation?.title || regOf(r.card_id))}</span>
      ${card?.applicability?.text ? `<span class="cv-chip">적용 대상: ${esc(card.applicability.text)}</span>` : ""}
    </div>
    ${r.reason ? `<p class="cv-note">${esc(r.reason)}</p>` : ""}
    ${text ? `<div class="cv-text">${highlightText(text, spans)}${ko ? `<span class="cv-trans">${esc(ko)}</span>` : ""}</div>
      <p class="cv-note">칠한 구절이 조항이 요구하는 사실이다. 초록은 BOM 에 있음, 노랑은 부분 대응, 빨강은 비어 있거나 BOM 형식에 자리가 없음, 회색은 이 BOM 에는 요구되지 않거나 판단할 정보가 없음.</p>`
      : `<p class="cv-note">이 규제의 원문은 저작권 때문에 싣지 않는다. 요구 사실과 필드만 보인다.</p>`}
    ${r.conditions ? `<h4>조건</h4><ul>${Object.entries(r.conditions).map(([k, c]) => `<li><code>${esc(k)}</code> ${esc(c.text)} → <b>${!c.evaluated ? "평가 못 함 (조건식 없음)" : c.result === null || c.result === undefined ? "모름 (판단할 정보 없음)" : c.result ? "참" : "거짓"}</b></li>`).join("")}</ul>` : ""}
    <h4>조항이 요구하는 사실 (${facts.length})</h4>
    <table class="cv-facts"><thead><tr><th>상태</th><th>사실</th><th>BOM 필드</th><th>값이 있는 구성요소</th></tr></thead><tbody>
    ${facts.map((f, i) => `<tr data-idx="${i}"><td><span class="cv-chip ${f.status}">${STATUS_KO[f.status] || f.status}</span>
      ${f.condition_evaluated === false ? `<br><span class="cv-muted">조건 미평가</span>` : f.condition ? `<br><span class="cv-muted">조건 ${esc(f.condition)}</span>` : ""}</td>
      <td>${esc(f.label || label(f.concept))}<br><code>${esc(f.concept)}</code>${f.target ? `<br><span class="cv-muted">대상 ${esc(KIND_KO[f.target] || f.target)}</span>` : ""}</td>
      <td>${(f.paths || []).map((p) => `<span class="cv-path">${esc(p)}</span>`).join(" ") || `<span class="cv-muted">${esc(f.reason || "")}</span>`}</td>
      <td>${[...new Set(Object.values(f.found_at || {}).flat())].map((x) => `<code>${esc(x)}</code>`).join(" ")}${targetDetail(f)}</td></tr>`).join("")}
    </tbody></table>
    <p class="cv-note">"비어 있음" 과 "자리 없음" 이 누락이고, 비어 있음의 필드가 채울 자리다. "부분 대응" 은 값은 있지만 필드의 대상 범위나 표현 형태가 요구와 달라 부분 반영까지만 간다. 조건식(JSON Logic)이 있는 조항은 조건이 거짓이면 그 사실을 "요구 안 됨" 으로 빼고, 조건을 판단할 정보가 BOM 에 없으면(자리 자체가 없음) "판단 못 함" 이라 검토 필요다. 대상 구성요소가 정해진 사실은 그 종류의 구성요소마다 보고(조건도 구성요소마다), 값이 빠진 구성요소를 적는다. 증빙 검사는 아직 없다.</p>`;
  wireMarks(d);
}
// 대상 구성요소가 정해진 fact: 구성요소별 조건과 빠진 구성요소
function targetDetail(f) {
  if (!f.target) return "";
  const out = [];
  if (f.condition_on) out.push(`조건 ${esc(f.condition)}: ` + Object.entries(f.condition_on).map(([k, v]) => `<code>${esc(k)}</code> ${v === true ? "참" : v === false ? "거짓" : "평가 못 함"}`).join(", "));
  if (f.missing_on?.length) out.push(`빠진 구성요소${f.missing_count > f.missing_on.length ? ` (${f.missing_count}개 중 ${f.missing_on.length}개)` : ""}: ` + f.missing_on.map((x) => `<code>${esc(x)}</code>`).join(" "));
  else if (f.status === "missing" && f.reason) out.push(esc(f.reason));
  return out.map((x) => `<br><span class="cv-muted">${x}</span>`).join("");
}

// 브라우저 안 판정 (cards/judge/judge.py 와 같은 규칙). 검사 대상은 metadata.component 와 모델·데이터셋 구성요소.
// fact 에 target 이 있으면 프로파일의 targets 로 그 종류의 구성요소를 찾아 하나씩 본다 (조건도 구성요소마다).
// 조건 변수는 값이 있으면 참, 자리는 있는데 비면 거짓, 자리 자체가 없으면 모름(null)이고, 모름이면 그 사실은 unknown 이라 카드가 검토 필요다.
// 카드가 이 시스템에 적용되나 (judge.py 의 applicability): "applies" / "not_applies" / "unknown". 카드의 risk_class 가 any 면 위험등급을 안 보고,
// 주체가 organisation(NIST·ISO)이나 operator(제공자·배포자·수입자·유통자를 묶는 말)면 역할을 안 본다. 보는 칸이 프로파일에 없으면 unknown (검토 필요).
function applicability(card, system) {
  const wanted = new Set(card.applicability?.risk_class || ["any"]), actor = card.obligation?.actor || "organisation";
  const missing = [], mismatch = [];
  if (!wanted.has("any")) {
    const have = new Set(Array.isArray(system.risk_class) ? system.risk_class : system.risk_class ? [system.risk_class] : []);
    if (have.has("gpai_systemic")) have.add("gpai");
    if (!have.size) missing.push("위험등급(risk_class)");
    else if (![...wanted].some((x) => have.has(x))) mismatch.push(`카드의 위험등급 ${[...wanted].sort().join(", ")} 과 시스템의 ${[...have].sort().join(", ")} 이 안 맞음`);
  }
  if (actor !== "organisation" && actor !== "operator") {      // 역할은 목록 (제공자이면서 배포자일 수 있다)
    const roles = Array.isArray(system.role) ? system.role : system.role ? [system.role] : [];
    if (!roles.length) missing.push("역할(role)");
    else if (!roles.includes(actor)) mismatch.push(`카드의 주체 ${actor} 가 시스템의 역할 ${[...roles].sort().join(", ")} 에 없음`);
  }
  if (mismatch.length) return ["not_applies", mismatch.join("; ")];
  if (missing.length) return ["unknown", `시스템 프로파일에 ${missing.join("·")} 이 없어 적용 여부를 알 수 없음`];
  return ["applies", null];
}
function judgeBom(bom, name, system = {}) {
  const comps = [];
  if (bom.metadata?.component) comps.push(bom.metadata.component);
  (function walk(items) { for (const c of items || []) { if (c.type === "machine-learning-model" || c.type === "data") comps.push(c); walk(c.components); } })(bom.components);
  const isEmpty = (v) => v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
  const get = (obj, keys) => {
    if (!keys.length) return isEmpty(obj) ? [] : [obj];
    if (Array.isArray(obj)) return obj.flatMap((x) => get(x, keys));
    if (obj && typeof obj === "object" && keys[0] in obj) return get(obj[keys[0]], keys.slice(1));
    return [];
  };
  // 값 상태 (judge.py 의 _probe): value 값 있음, empty 자리는 있는데 비어 있음, absent 자리 자체가 없음. 배열은 value > empty > absent 로 합친다
  const probe = (obj, keys) => {
    if (!keys.length) return isEmpty(obj) ? "empty" : "value";
    if (Array.isArray(obj)) { const st = obj.map((x) => probe(x, keys)); return st.includes("value") ? "value" : st.includes("empty") ? "empty" : "absent"; }
    if (obj && typeof obj === "object") return keys[0] in obj ? probe(obj[keys[0]], keys.slice(1)) : "absent";
    return "absent";
  };
  const tri = (states) => states.includes("value") ? true : states.includes("empty") ? false : null;
  const lab = (c) => c["bom-ref"] || c.name || "?";
  const allComps = [];
  (function walk(items) { for (const c of items || []) { allComps.push(c); walk(c.components); } })(bom.components);
  const compsOfKind = (kind) => {
    const spec = targets[kind]; if (!spec) throw new Error(`프로파일 targets 에 '${kind}' 가 없다`);
    if (spec.root) return get(bom, spec.root.split(".")).filter((v) => v && typeof v === "object");
    return allComps.filter((c) => (spec.component_types || []).includes(c.type));
  };
  const resolve = (path) => {
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); return comps.filter((c) => (c.externalReferences || []).some((e) => e.type === t && e.url)).map(lab); }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return comps.filter((c) => get(c, rest).length).map(lab);
    if (rootKey === "componentData") return comps.filter((c) => c.type === "data" && get(c.data, rest).length).map(lab);
    if (rootKey === "releaseNotes") return comps.filter((c) => get(c, ["releaseNotes", ...rest]).length).map(lab);
    if (["components", "services", "dependencies", "formulation", "declarations", "definitions", "metadata", "compositions"].includes(rootKey)) return get(bom, [rootKey, ...rest]).length ? ["$"] : [];
    return [];
  };
  // 구성요소 하나에 그 경로의 값이 있나 (value / empty / absent). 구성요소에 달리지 않는 경로(declarations 등)는 문서에서 본다
  const probeComp = (c, path) => {
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); const refs = c.externalReferences; if (refs === undefined || refs === null) return "absent"; return refs.some((e) => e.type === t && e.url) ? "value" : "empty"; }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return probe(c, rest);
    if (rootKey === "componentData") return c.type === "data" && "data" in c ? probe(c.data, rest) : "absent";
    if (rootKey === "releaseNotes") return probe(c, ["releaseNotes", ...rest]);
    if (rootKey === "components" && !rest.length) return allComps.includes(c) ? "value" : "empty";      // 구성요소 목록 자체: 실려 있으면 참
    return resolve(path).length ? "value" : "absent";
  };
  const onComp = (c, path) => probeComp(c, path) === "value";
  // 조건식 변수(개념 id): 문서 단위 참·거짓·모름. target 이 있는 fact 는 구성요소 하나에서 본다
  const stateInBom = (k) => tri(comps.flatMap((c) => (profile[k]?.cdx || []).map((p) => probeComp(c, p))));
  const logic = (expr, varOf = stateInBom) => {
    if (expr === null || typeof expr !== "object" || Array.isArray(expr)) return expr;
    const [op, raw] = Object.entries(expr)[0]; const args = Array.isArray(raw) ? raw : [raw];
    if (op === "var") return varOf(args[0]);
    const v = args.map((a) => logic(a, varOf)), unk = v.some((x) => x === null || x === undefined);
    switch (op) {
      case "==": return unk ? null : v[0] === v[1]; case "!=": return unk ? null : v[0] !== v[1]; case "!": return unk ? null : !v[0];
      case "and": return v.some((x) => x === false) ? false : unk ? null : true;
      case "or": return v.some((x) => x === true) ? true : unk ? null : false;
      case "if": return v[0] === null || v[0] === undefined ? null : v[0] ? v[1] : v[2];
      case "in": return unk ? null : (v[1] || []).includes(v[0]);
      case ">": return unk ? null : v[0] > v[1]; case "<": return unk ? null : v[0] < v[1]; case ">=": return unk ? null : v[0] >= v[1]; case "<=": return unk ? null : v[0] <= v[1];
      default: throw new Error("조건식 연산자를 모른다: " + op);
    }
  };
  const results = cards.map((c) => {
    const [applies, whyApplies] = applicability(c, system);
    if (applies === "not_applies") return {card_id: c.card_id, verdict: "비적용", reason: whyApplies, facts: []};
    const conditions = {};
    for (const cond of c.conditions || []) {
      if (cond.expr) { try { conditions[cond.id] = {text: cond.text, evaluated: true, result: logic(cond.expr)}; } catch (e) { conditions[cond.id] = {text: cond.text, evaluated: true, result: null, error: e.message}; } }
      else conditions[cond.id] = {text: cond.text, evaluated: false, result: null};
    }
    const byId = Object.fromEntries((c.conditions || []).map((x) => [x.id, x]));
    const onTargets = (f, paths, entry) => {            // judge.py 의 judge_on_targets
      const kind = f.target, kcomps = compsOfKind(kind);
      entry.target = kind; let required = kcomps;
      if (f.required === "conditional") {
        const expr = byId[f.condition]?.expr;
        entry.condition = f.condition; entry.condition_evaluated = expr !== undefined && expr !== null;
        if (entry.condition_evaluated) {
          const vals = kcomps.map((x) => { try { return [x, logic(expr, (k) => tri((profile[k]?.cdx || []).map((p) => probeComp(x, p))))]; } catch (e) { return [x, null]; } });
          entry.condition_on = Object.fromEntries(vals.map(([x, v]) => [lab(x), v]));
          const unknown = vals.filter(([, v]) => v === null || v === undefined).map(([x]) => x);
          if (unknown.length) return {...entry, status: "unknown", paths, reason: `조건 ${f.condition} 을 판단할 정보가 없는 ${KIND_KO[kind]} 구성요소: ${unknown.slice(0, 10).map(lab).join(", ")} (${byId[f.condition]?.text})`};
          required = vals.filter(([, v]) => v === true).map(([x]) => x);
          if (!required.length) return {...entry, status: "not_required", paths, reason: `조건 ${f.condition} 이 참인 ${KIND_KO[kind]} 구성요소가 없음: ${byId[f.condition]?.text}`};
        }
      }
      if (pending.has(f.concept)) return {...entry, status: "unknown", paths, reason: "매핑이 승인되지 않음 (프로파일 줄이 pending_review)"};
      if (!paths.length) return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      entry.checked = required.length;
      if (!required.length) return {...entry, status: "missing", paths, found_at: {}, reason: `BOM 에 ${KIND_KO[kind]} 구성요소가 없음`};
      const have = required.filter((x) => paths.some((p) => onComp(x, p))), missing = required.filter((x) => !have.includes(x));
      const found = {}; for (const p of paths) { const refs = have.filter((x) => onComp(x, p)).map(lab).slice(0, 10); if (refs.length) found[p] = refs; }
      const status = missing.length ? "missing" : partial[f.concept] ? "partial" : "present";
      const out = {...entry, status, paths, found_at: found};
      if (missing.length) Object.assign(out, {missing_on: missing.map(lab).slice(0, 10), missing_count: missing.length, reason: `요구되는 ${KIND_KO[kind]} 구성요소 ${required.length}개 중 ${missing.length}개에 값이 없음`});
      else if (status === "partial") out.reason = partial[f.concept];
      return out;
    };
    const facts = c.facts.map((f) => {
      const paths = profile[f.concept]?.cdx || [];
      const entry = {concept: f.concept, label: label(f.concept), required: f.required};
      if (f.target) return onTargets(f, paths, entry);
      if (f.required === "conditional") {
        const cond = conditions[f.condition] || {};
        entry.condition = f.condition; entry.condition_evaluated = !!cond.evaluated;
        if (cond.evaluated && (cond.result === null || cond.result === undefined)) return {...entry, status: "unknown", paths, reason: `조건 ${f.condition} 을 판단할 정보가 BOM 에 없음: ${cond.text}` + (cond.error ? ` (${cond.error})` : "")};
        if (cond.result === false) return {...entry, status: "not_required", paths, reason: `조건 ${f.condition} 이 거짓이라 요구되지 않음: ${cond.text}`};
      }
      if (pending.has(f.concept)) return {...entry, status: "unknown", paths, reason: "매핑이 승인되지 않음 (프로파일 줄이 pending_review)"};
      if (!paths.length) return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      const found = {}; for (const p of paths) { const refs = resolve(p); if (refs.length) found[p] = refs.slice(0, 5); }
      const status = !Object.keys(found).length ? "missing" : partial[f.concept] ? "partial" : "present";
      return {...entry, status, paths, found_at: found, ...(status === "partial" ? {reason: partial[f.concept]} : {})};
    });
    const required = facts.filter((f) => f.status !== "not_required"), unknown = required.filter((f) => f.status === "unknown");
    let verdict, reason;
    if (applies === "unknown") { verdict = "검토 필요"; reason = whyApplies; }
    else if (!profileApproved) { verdict = "검토 필요"; reason = "매핑 프로파일이 승인되지 않음"; }
    else if (unknown.length) { verdict = "검토 필요"; reason = unknown.map((f) => `${f.concept}: ${f.reason}`).join("; "); }
    else if (!required.length) { verdict = "반영"; reason = "요구되는 사실이 없음 (조건이 모두 거짓)"; }
    else if (required.every((f) => f.status === "present")) verdict = "반영";
    else if (required.every((f) => f.status === "missing" || f.status === "gap")) verdict = "미반영";
    else verdict = "부분 반영";
    return {card_id: c.card_id, verdict, ...(reason ? {reason} : {}), facts, ...(Object.keys(conditions).length ? {conditions} : {})};
  });
  const summary = Object.fromEntries(VERDICTS.map((v) => [v, results.filter((r) => r.verdict === v).length]));
  return {bom: {bomFormat: bom.bomFormat, specVersion: bom.specVersion, serialNumber: bom.serialNumber, subject: bom.metadata?.component?.name || name}, system_profile: system, summary, cards: results};
}

init().catch((err) => { root.innerHTML = `<p class="cv-muted">데이터를 읽지 못했다: ${esc(err.message)}</p>`; });
})();
