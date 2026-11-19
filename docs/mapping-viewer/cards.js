// 규제 판정 화면 (compliance/regulation-cards.md). BOM 을 규제 조항마다 대 본 결과와, 조항을 누르면 원문과 요구 사실.
// 데이터는 export_data.py 가 data/cards/ 에 둔 JSON. 카드 보기·추출기 비교·승인은 내부 화면의 몫이라 여기 두지 않는다.
if (document.querySelector(".card-viewer")) (() => {
const root = document.querySelector(".card-viewer");
const BASE = root.dataset.base || "data/cards/";
const REG_NAME = {EUAIA: "EU AI Act", NISTRMF: "NIST AI RMF", ISO42001: "ISO/IEC 42001"};
const VERDICTS = ["반영", "부분 반영", "미반영", "검토 필요", "비적용"];
const STATUS_KO = {present: "있음", partial: "부분 대응", missing: "비어 있음", gap: "자리 없음", not_required: "요구 안 됨", unknown: "판단 못 함", optional: "해당 시 필요"};
const OPTIONAL_REASON = "해당 시 필요한 사실(where applicable)인데 값이 없어 해당 여부를 BOM 으로 판단할 수 없음";
const EV_STATUS_KO = {present: "있음", invalid: "무효", missing: "없음", unknown: "조회식 없음"};      // 증빙 종류 하나의 상태
const EV_CLS = {present: "present", invalid: "missing", missing: "missing", unknown: "unknown"};
const MARK_CLS = {present: "", partial: "partial", missing: "missing", gap: "missing", not_required: "muted", unknown: "muted", optional: "muted"};      // 원문 구절의 색
const $ = (sel) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const regOf = (id) => REG_NAME[id.split("-")[1]] || id.split("-")[1];
const vclass = (v) => "v-" + v.replace(/\s/g, "");
let cards = [], cardById = {}, vocab = {}, profile = {}, targets = {}, examples = [];
let pending = new Set(), partial = {}, profileApproved = true, unitOverride = {};   // unitOverride: 프로파일 줄이 정한 확인 단위 (개념 → 단위)      // 승인 안 된 줄, 부분 대응 줄(개념 → 이유), 프로파일 승인 여부
let evidenceSpec = {}, evidenceKinds = {};        // 프로파일의 증빙 조회식(evidence.kinds), 어휘의 증빙 종류(evidence_kinds)
let truth = {}, classParents = {};                // 조건 변환식(줄의 truth), SPDX 클래스 → 조상 (SPDX 프로파일의 class_parents)
const PROFILES = {};                              // 형식 → 읽어 둔 프로파일 (CycloneDX: profile.json, SPDX: profile-spdx.json). judgeBom 이 문서 형식에 맞는 것을 켠다
const isSpdx = (bom) => Boolean(bom) && typeof bom === "object" && Array.isArray(bom["@graph"]);
const KIND_KO = {system: "시스템", model: "모델", dataset: "데이터셋", software: "소프트웨어"};
const UNIT_KO = {document: "문서", component: "구성요소", ...KIND_KO};      // 확인 단위 (judge.py 의 UNIT_KO)
let currentBom = null, currentName = "", currentSize = 0;      // 지금 판정하는 BOM. 올린 것이든 예제든 브라우저 안에서 판정한다 (프로파일을 바꾸면 다시)
let regSel = new Set(Object.keys(REG_NAME)), verdictSel = new Set(VERDICTS);   // 목록 거르기: 고른 규제들과 고른 판정들 (처음엔 모두 켜져 있고, 집계 칩을 누르면 끄고 켠다)

async function load(name) { const r = await fetch(BASE + name); if (!r.ok) throw new Error(name); return r.json(); }

async function init() {
  const [c, v, p, ps, ex, src] = await Promise.all([load("cards.json"), load("vocabulary.json"), load("profile.json"), load("profile-spdx.json").catch(() => null), load("boms/index.json").catch(() => []), load("source.json").catch(() => ({}))]);
  cards = c; cardById = Object.fromEntries(c.map((x) => [x.card_id, x])); vocab = Object.fromEntries(v.concepts.map((x) => [x.id, x])); examples = ex;
  evidenceKinds = Object.fromEntries((v.evidence_kinds || []).map((x) => [x.id, x]));
  if (src.cards === "gold") { const n = document.createElement("p"); n.className = "cv-note"; n.textContent = "지금 판정에 쓰는 카드는 요구사항 표에서 변환한 정답 카드(cards/gold)입니다. 승인한 카드가 생기면 그것으로 바뀝니다."; root.prepend(n); }
  PROFILES.CycloneDX = buildProfile(p, "cdx_path", "cdx_paths_more");
  if (ps) PROFILES.SPDX = buildProfile(ps, "spdx_path", "spdx_paths_more");
  activateProfile("CycloneDX");
  systemKeys = (p.system_profile || {}).keys || {};
  buildProfileInputs();
  initJudgment();
}
// 프로파일 파일 하나 → 판정이 쓰는 모양. 줄의 경로 열은 형식마다 다르다 (CycloneDX 는 cdx_path, SPDX 는 spdx_path)
function buildProfile(p, key, more) {
  const out = {paths: {}, pending: new Set(), partial: {}, truth: {}, unitOverride: {}, targets: p.targets || {}, evidence: p.evidence || {}, approved: p.status === "approved", classParents: p.class_parents || {}, meta: {profile_id: p.profile_id, profile_version: p.profile_version, format: p.schema?.format || "CycloneDX"}};
  for (const line of p.lines) {
    const list = (out.paths[line.concept] ||= []);
    for (const x of [line[key], ...(line[more] || [])]) if (x && !list.includes(x)) list.push(x);
    if (line.status === "pending_review") out.pending.add(line.concept);
    if (line.fit === "partial") out.partial[line.concept] = line.fit_note || "부분 대응 (경로의 대상 범위 또는 표현 형태가 요구와 다름)";
    if (line.truth) out.truth[line.concept] = line.truth;
    if (line.target) out.unitOverride[line.concept] = line.target;
  }
  return out;
}
function activateProfile(fmt) {                       // judgeBom 이 문서 형식에 맞는 프로파일을 켠다 (judge.py 의 load_profile 자리)
  const p = PROFILES[fmt]; if (!p) throw new Error(`${fmt} 프로파일이 없습니다`);
  profile = Object.fromEntries(Object.entries(p.paths).map(([k, v]) => [k, {cdx: v}]));     // 아래 코드는 profile[k].cdx 를 "이 형식의 경로" 로 쓴다
  pending = p.pending; partial = p.partial; truth = p.truth; targets = p.targets; unitOverride = p.unitOverride; evidenceSpec = p.evidence; profileApproved = p.approved; classParents = p.classParents;
  return p;
}

// ---------- 공통 ----------
function regChecks(el, onChange) {                    // 규제 고르기: 체크박스라 여럿을 함께 본다. 처음엔 모두 켜져 있다
  el.innerHTML = Object.entries(REG_NAME).map(([k, n]) => `<label><input type="checkbox" value="${k}"${regSel.has(k) ? " checked" : ""}> ${n}</label>`).join("");
  el.querySelectorAll("input").forEach((b) => b.addEventListener("change", () => { if (b.checked) regSel.add(b.value); else regSel.delete(b.value); onChange(); }));
}
function label(concept) { return vocab[concept]?.label_ko || concept; }
function evLabel(kind) { return evidenceKinds[kind]?.label_ko || kind; }

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
// 처음엔 올리는 자리(드롭존과 예제 카드)만 보인다. 파일을 끌어다 놓거나 골라 올리거나 예제를 누르면 브라우저 안에서 판정해 결과 화면을 연다.
let currentRecord = null;
function initJudgment() {
  const drop = $("#cv-drop"), input = $("#cv-bom-file");
  $("#cv-examples").innerHTML = examples.map((e, i) => `<button type="button" class="cv-example" data-i="${i}"><span class="cv-ex-title">${esc(e.label || e.subject)}</span><span class="cv-ex-note">${esc(e.note || "")}</span><span class="cv-ex-file">${esc(e.file)} · ${fmtSize(e.size || 0)}</span></button>`).join("") || `<span class="cv-muted">없음</span>`;
  $("#cv-examples").querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
    const e = examples[+b.dataset.i];
    try { const r = await fetch(BASE + "boms/" + e.file); if (!r.ok) throw new Error(e.file); useBom(await r.json(), e.file, e.size, e.system_profile); }
    catch (err) { dropError(`예제를 읽지 못했습니다: ${esc(err.message)}`); }
  }));
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); input.click(); } });
  for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.add("over"); });
  for (const t of ["dragleave", "drop"]) drop.addEventListener(t, (ev) => { ev.preventDefault(); drop.classList.remove("over"); });
  drop.addEventListener("drop", (ev) => { const f = ev.dataTransfer?.files?.[0]; if (f) readFile(f); else dropError("파일이 아닙니다"); });
  input.addEventListener("change", (ev) => { const f = ev.target.files[0]; if (f) readFile(f); input.value = ""; });
  $("#cv-another").addEventListener("click", () => { $("#cv-main").hidden = true; showBomView(false); $("#cv-drop-error").hidden = true; $("#cv-upload").hidden = false; drop.focus(); });
  $("#cv-show-bom").addEventListener("click", () => showBomView($("#cv-bom-view").hidden));
  const bar = $("#cv-filebar");                       // 결과 화면의 파일 줄에 다른 파일을 끌어다 놓으면 그 파일로 바꾼다
  for (const t of ["dragenter", "dragover"]) bar.addEventListener(t, (ev) => { ev.preventDefault(); bar.classList.add("over"); });
  for (const t of ["dragleave", "drop"]) bar.addEventListener(t, (ev) => { ev.preventDefault(); bar.classList.remove("over"); });
  bar.addEventListener("drop", (ev) => { const f = ev.dataTransfer?.files?.[0]; if (f) readFile(f); });
  regChecks($("#cv-reg"), () => { syncProfilePanel(); renderSummary(); renderJudgList(); });
  for (const b of extraBoxes()) b.addEventListener("change", () => {          // 체계적 위험은 범용 AI 모델 위에 얹힌다
    const gpai = extraBoxes().find((x) => x.value === "gpai"), systemic = extraBoxes().find((x) => x.value === "gpai_systemic");
    if (b === systemic && b.checked) gpai.checked = true;
    if (b === gpai && !b.checked) systemic.checked = false;
  });
  for (const b of systemBoxes()) b.addEventListener("change", () => {         // 고위험 여부는 둘 중 하나: 하나를 켜면 다른 것은 꺼진다 (둘 다 끄면 모름)
    if (b.checked) for (const x of systemBoxes()) if (x !== b) x.checked = false;
  });
  for (const el of [...systemBoxes(), ...extraBoxes(), ...roleBoxes()]) el.addEventListener("change", () => { if (currentBom) rejudge(); });
  for (const el of root.querySelectorAll("#cv-area, #cv-flags, #cv-exemptions")) el.addEventListener("change", () => { if (currentBom) rejudge(); });   // 분야 · 상황 · 예외 주장 (칸은 buildProfileInputs 가 만든다)
}
function rejudge() { const system = systemProfile(); updateProfileAlert(system); showRecord(judgeBom(currentBom, currentName, system)); }
function syncProfilePanel() { $("#cv-eu").hidden = !regSel.has("EUAIA"); }   // 적용 조건은 EU AI Act 에만 있다
async function readFile(file) {
  try {
    const bom = JSON.parse(await file.text());
    if (!bom || typeof bom !== "object" || Array.isArray(bom)) throw new Error("JSON 객체가 아닙니다");
    if (bom.bomFormat !== "CycloneDX" && !isSpdx(bom)) throw new Error("CycloneDX 문서(bomFormat)도 SPDX 3.0.1 JSON-LD(@graph)도 아닙니다" + (bom.bomFormat ? ` (bomFormat 이 '${bom.bomFormat}')` : ""));
    if (isSpdx(bom) && !PROFILES.SPDX) throw new Error("SPDX 프로파일이 없어 SPDX 문서는 판정할 수 없습니다");
    useBom(bom, file.name, file.size, null);
  } catch (err) {                                     // 결과 화면에서 떨어뜨린 파일이 잘못됐으면 올리기 화면으로 돌아가 알린다
    $("#cv-main").hidden = true; showBomView(false); $("#cv-upload").hidden = false;
    dropError(`읽을 수 없는 파일 (${esc(file.name)}): ${esc(err.message)}`);
  }
}
function dropError(html) { const e = $("#cv-drop-error"); e.innerHTML = html; e.hidden = false; }
// BOM 하나를 화면에 올린다. system 이 있으면(예제) 프로파일 칸을 그 값으로 채우고, 없으면(올린 파일) 비운다. 어느 쪽이든 바꿀 수 있다
function useBom(bom, name, size, system) {
  currentBom = bom; currentName = name; currentSize = size || JSON.stringify(bom).length;
  $("#cv-drop-error").hidden = true;
  applyProfileInputs(system || {});
  $("#cv-file").textContent = name; $("#cv-file").title = name;
  $("#cv-file-meta").textContent = fmtSize(currentSize);
  showBomView(false);
  $("#cv-upload").hidden = true; $("#cv-main").hidden = false;
  $("#cv-judg-detail").innerHTML = `<p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나옵니다.</p>`;
  verdictSel = new Set(VERDICTS); collapsed = new Set();
  syncProfilePanel();
  rejudge();
}
const BOM_VIEW_MAX = 400000;                          // 글자 수. 큰 BOM(1.5 MB)은 앞부분만 보인다
function showBomView(on) {                            // 파일 줄 자체가 펼침 버튼. 열리면 꺾쇠가 아래를 본다
  const view = $("#cv-bom-view"), btn = $("#cv-show-bom");
  view.hidden = !on; btn.classList.toggle("active", on); btn.setAttribute("aria-expanded", String(on));
  if (!on || !currentBom) return;
  const text = JSON.stringify(currentBom, null, 2), cut = text.length > BOM_VIEW_MAX;
  $("#cv-bom-pre").textContent = cut ? text.slice(0, BOM_VIEW_MAX) + `\n… (앞 ${fmtSize(BOM_VIEW_MAX)} 만 보입니다. 전체 ${fmtSize(text.length)})` : text;
}
const fmtSize = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;
// 시스템 프로파일 (2층): 위험등급과 역할. 위험등급은 고위험 여부(high_risk / minimal_risk)에 얹히는 것(시스템의 투명성 의무 limited_risk, 모델의
// 범용 AI 모델 gpai 와 체계적 위험 gpai_systemic)을 더한 목록이다. 고위험 여부를 고르지 않으면 위험등급을 비워 두어, 위험등급을 보는 카드는 검토 필요가 된다
// (특허: 적용대상을 판단할 정보가 없으면 검토 필요. 체크 하나로 줄이면 빈칸이 "고위험 아님"이 되어 버려서 둘을 둔다)
const systemBoxes = () => [...root.querySelectorAll("input[name=cv-system]")];   // 고위험 여부 (체크 둘, 서로 배타. 둘 다 끄면 모름)
const roleBoxes = () => [...root.querySelectorAll("input[name=cv-role]")];
const extraBoxes = () => [...root.querySelectorAll("input[name=cv-extra]")];
const asList = (v) => Array.isArray(v) ? v : v ? [v] : [];
// 시스템 프로파일의 나머지 칸 (조건식 · 예외가 profile.<칸> 으로 보는 것): 부속서 III 분야(annex_iii_area), 참·거짓 칸들(상황), 주장하는 예외 목록(exemptions).
// 칸의 정의는 프로파일의 system_profile.keys 에서 오고, 예외 주장의 후보는 카드의 예외식("<조항 id>" in profile.exemptions)에서 모은다.
// 상황 칸은 예 · 아니오 · 모름이다. 모름은 칸을 비우는 것이라 그 칸을 보는 조건은 판단 못 함(검토 필요), 예외는 해당 없음이 된다
let systemKeys = {};
const AREA_KO = {biometrics: "생체인식", critical_infrastructure: "핵심 기반시설", education: "교육 · 직업훈련", employment: "고용 · 근로자 관리",
                 essential_services: "필수 서비스", law_enforcement: "법 집행", migration_asylum_border: "이민 · 망명 · 국경", justice_democracy: "사법 · 민주적 절차"};
const FLAG_KO = {annex_i_product: "부속서 I 제품 관련 고위험 시스템", common_specifications_applied: "공통 규격(41조)을 따름", deployer_controls_input_data: "배포자가 입력 데이터를 통제",
                 provider_outside_eu: "EU 밖에 설립된 제공자", assistive_editing_only: "편집 보조 기능만 하는 시스템"};
const flagKeys = () => Object.entries(systemKeys).filter(([, d]) => d.type === "boolean" && d.status === "active").map(([k]) => k);
function exemptionIds() {
  const ids = new Map();
  const walk = (x, card, text) => {
    if (!x || typeof x !== "object") return;
    if (Array.isArray(x)) { x.forEach((v) => walk(v, card, text)); return; }
    const [op, raw] = Object.entries(x)[0] || [], args = Array.isArray(raw) ? raw : [raw];
    if (op === "in" && typeof args[0] === "string" && JSON.stringify(args[1]) === '{"var":"profile.exemptions"}') ids.set(args[0], {card, text});
    else args.forEach((v) => walk(v, card, text));
  };
  for (const c of cards) for (const e of c.exceptions || []) if (e.expr) walk(e.expr, c, e.text);
  return [...ids.entries()].sort((a, b) => a[0].localeCompare(b[0], undefined, {numeric: true}));
}
function buildProfileInputs() {
  const area = systemKeys.annex_iii_area, areas = area && area.status === "active" ? area.values || [] : [];
  $("#cv-area").innerHTML = `<option value="">고르지 않음</option>` + areas.map((v) => `<option value="${esc(v)}">${esc(AREA_KO[v] || v)}</option>`).join("");
  $("#cv-flags").innerHTML = flagKeys().map((k) => `<div class="cv-tri-row" title="${esc(systemKeys[k].description || "")}"><span>${esc(FLAG_KO[k] || k)}</span>${[["true", "예"], ["false", "아니오"], ["", "모름"]].map(([v, l]) => `<label><input type="radio" name="cv-flag-${k}" value="${v}"${v === "" ? " checked" : ""}> ${l}</label>`).join("")}</div>`).join("")
    || `<span class="cv-muted">없음</span>`;
  $("#cv-exemptions").innerHTML = exemptionIds().map(([id, {card, text}]) => `<label title="${esc(text || "")}"><input type="checkbox" name="cv-exempt" value="${esc(id)}"> ${esc(id)} ${esc(topicOf(card))}</label>`).join("")
    || `<span class="cv-muted">없음 (예외식이 있는 카드가 없다)</span>`;
}
function systemProfile() {
  const sys = systemBoxes().find((b) => b.checked)?.value || "", extras = extraBoxes().filter((b) => b.checked).map((b) => b.value);
  const roles = roleBoxes().filter((b) => b.checked).map((b) => b.value);
  const out = {...(sys ? {risk_class: [sys, ...extras]} : {}), ...(roles.length ? {role: roles} : {})};
  const area = $("#cv-area")?.value; if (area) out.annex_iii_area = area;
  for (const k of flagKeys()) { const v = root.querySelector(`input[name=cv-flag-${k}]:checked`)?.value; if (v === "true") out[k] = true; else if (v === "false") out[k] = false; }
  const ex = [...root.querySelectorAll("input[name=cv-exempt]:checked")].map((b) => b.value); if (ex.length) out.exemptions = ex;
  return out;
}
function applyProfileInputs(system) {
  const rc = asList(system.risk_class), roles = asList(system.role);
  const sys = !rc.length ? "" : rc.includes("high_risk") ? "high_risk" : "minimal_risk";
  for (const b of systemBoxes()) b.checked = b.value === sys;
  for (const b of extraBoxes()) b.checked = rc.includes(b.value) || (b.value === "gpai" && rc.includes("gpai_systemic"));
  for (const b of roleBoxes()) b.checked = roles.includes(b.value);
  const area = $("#cv-area"); if (area) area.value = system.annex_iii_area || "";
  for (const k of flagKeys()) { const v = system[k]; for (const b of root.querySelectorAll(`input[name=cv-flag-${k}]`)) b.checked = b.value === (v === true ? "true" : v === false ? "false" : ""); }
  const ex = asList(system.exemptions); for (const b of root.querySelectorAll("input[name=cv-exempt]")) b.checked = ex.includes(b.value);
}
function updateProfileAlert(system) {                // 비운 칸의 라벨 옆에 빨간 글씨로, 그 칸을 보는 조항이 검토 필요가 된다고 알린다
  $("#cv-hint-system").hidden = Boolean(system.risk_class);
  $("#cv-hint-role").hidden = Boolean(system.role);
}
function regCards() {                                 // 고른 규제들의 카드 판정
  return currentRecord.cards.filter((r) => regSel.has(r.card_id.split("-")[1]));
}
// 카드 단위는 호라서 항(parent_clause_id) 하나에 카드가 여럿일 수 있다. 항의 종합 판정 (ai-bom/src/judge/judge.py 의 aggregate 와 같은 규칙):
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
// 판정 집계 칩. 호 단위 항목 수만 센다 (항의 종합 판정은 목록의 항 머리줄에만, 말 없이 칩으로). 처음엔 모두 켜져 있고, 체크를 풀면 그 판정이 목록에서 빠진다 (여럿 조합 가능)
function renderSummary() {
  if (!currentRecord) return;
  const rs = regCards();
  const s = Object.fromEntries(VERDICTS.map((v) => [v, rs.filter((r) => r.verdict === v).length]));
  const box = $("#cv-judg-summary");
  box.innerHTML = VERDICTS.map((v) => `<label class="cv-tile ${vclass(v)}${verdictSel.has(v) ? " active" : ""}"><input type="checkbox" value="${v}"${verdictSel.has(v) ? " checked" : ""}>
    <span class="cv-tile-l"><span class="cv-dot"></span>${v}</span><span class="cv-tile-n">${s[v]}</span></label>`).join("");
  box.querySelectorAll("input").forEach((b) => b.addEventListener("change", () => { if (b.checked) verdictSel.add(b.value); else verdictSel.delete(b.value); renderSummary(); renderJudgList(); }));
}
const topicOf = (card) => card?.topic || (card?.title || "").split(": ").slice(1).join(": ");
const CHEV = '<svg class="cv-chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6"/></svg>';   // 파일 줄·용어 설명과 같은 꺾쇠
let collapsed = new Set();                             // 접어 둔 항 (규제|항). 새 BOM 을 올리면 비운다
function renderJudgList() {
  if (!currentRecord) return;
  const groups = clauseGroups(regCards()).map((g) => ({...g, cards: g.cards.filter((r) => verdictSel.has(r.verdict))})).filter((g) => g.cards.length);
  const container = $("#cv-judg-list");
  container.innerHTML = "";
  if (!groups.length) { container.innerHTML = `<p class="cv-muted" style="padding:.8rem">${!regSel.size ? "규제를 하나 이상 고르세요." : !verdictSel.size ? "판정을 하나 이상 고르세요." : "해당하는 조항이 없습니다."}</p>`; return; }
  let lastReg = null;
  for (const g of groups) {
    if (g.reg !== lastReg) { const h = document.createElement("div"); h.className = "cv-group"; h.textContent = g.reg; container.appendChild(h); lastReg = g.reg; }
    const key = g.reg + "|" + g.clause, grouped = g.cards.length > 1, folded = grouped && collapsed.has(key), rows = [];
    if (grouped) {                                     // 호가 여럿인 항: 항의 판정을 머리줄로. 카드가 없어 상세는 없고, 누르면 호 줄을 접고 편다
      const h = document.createElement("div"); h.className = "cv-clause" + (folded ? "" : " open"); h.setAttribute("role", "button"); h.tabIndex = 0; h.setAttribute("aria-expanded", String(!folded));
      h.innerHTML = `<span class="cv-head">${CHEV}<span class="cv-id">${esc(g.clause)}</span></span><span class="cv-sub"><span class="cv-verdict ${vclass(g.verdict)}">${g.verdict}</span><span class="cv-count"></span></span>`;
      const toggle = () => { const open = collapsed.has(key); if (open) collapsed.delete(key); else collapsed.add(key); h.classList.toggle("open", open); h.setAttribute("aria-expanded", String(open)); rows.forEach((x) => { x.hidden = !open; }); };
      h.addEventListener("click", toggle);
      h.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
      container.appendChild(h);
    }
    for (const r of g.cards) {
      const card = cardById[r.card_id], f = r.facts || []; const p = f.filter((x) => x.status === "present" || x.status === "partial").length, n = f.filter((x) => x.status === "not_required").length;   // 분자: 값이 있는 사실 (부분 대응 포함)
      const row = document.createElement("div"); row.className = "cv-item" + (grouped ? " cv-point" : ""); row.dataset.id = r.card_id; row.hidden = folded;
      row.innerHTML = `<span class="cv-row-main"><span class="cv-id">${esc(card?.source?.clause_id || r.card_id.replace(/^RC-[A-Z0-9]+-/, ""))}</span><span class="cv-topic" title="${esc(topicOf(card))}">${esc(topicOf(card))}</span></span>`
        + `<span class="cv-sub"><span class="cv-verdict ${vclass(r.verdict)}">${r.verdict}</span><span class="cv-count" title="요구 사실 중 BOM 에 값이 있는 것 (부분 대응 포함)">${f.length ? `${p}/${f.length - n}` : ""}</span></span>`;
      row.addEventListener("click", () => { container.querySelectorAll(".cv-item").forEach((x) => x.classList.toggle("active", x === row)); renderJudg(r); });
      container.appendChild(row); rows.push(row);
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
      <div class="cv-legend"><span class="cv-muted">칠한 구절 = 조항이 요구하는 사실</span><span><i></i>BOM 에 있음</span><span><i class="partial"></i>부분 대응</span><span><i class="missing"></i>비어 있거나 자리 없음</span><span><i class="muted"></i>요구 안 됨 · 판단 못 함</span></div>`
      : `<p class="cv-note">이 규제의 원문은 저작권 때문에 싣지 않습니다. 요구 사실과 필드만 보입니다.</p>`}
    ${r.conditions ? `<h4>조건</h4><ul>${Object.entries(r.conditions).map(([k, c]) => `<li><code>${esc(k)}</code>${c.scope === "card" ? ` <span class="cv-muted">카드 전체</span>` : ""} ${esc(c.text)} → <b>${!c.evaluated ? (c.note ? "설명만 (사실에 걸지 않음)" : "평가 못 함 (조건식 없음)") : c.result === null || c.result === undefined ? "모름 (판단할 정보 없음)" : c.result ? "참" : "거짓"}</b>${c.note ? `<br><span class="cv-muted">${esc(c.note)}</span>` : ""}</li>`).join("")}</ul>` : ""}
    ${r.exceptions ? `<h4>예외</h4><ul>${Object.entries(r.exceptions).map(([k, e]) => `<li><code>${esc(k)}</code> ${esc(e.text)} → <b>${!e.evaluated ? "평가 못 함 (조건식 없음)" : e.result === null || e.result === undefined ? "모름 (판단할 정보 없음)" : e.result ? "해당 (비적용)" : "해당 없음"}</b>${e.note ? `<br><span class="cv-muted">${esc(e.note)}</span>` : ""}</li>`).join("")}</ul>` : ""}
    <h4>조항이 요구하는 사실 (${facts.length})</h4>
    <table class="cv-facts"><thead><tr><th>상태</th><th>요구 사실</th><th>BOM 필드 · 값이 있는 구성요소</th></tr></thead><tbody>
    ${facts.map((f, i) => { const found = [...new Set(Object.values(f.found_at || {}).flat())]; return `<tr data-idx="${i}"><td><span class="cv-chip ${f.status}">${STATUS_KO[f.status] || f.status}</span>
      ${f.required === "optional" ? `<br><span class="cv-muted">해당 시</span>` : f.condition_evaluated === false ? `<br><span class="cv-muted">조건 미평가</span>` : f.condition ? `<br><span class="cv-muted">조건 ${esc(f.condition)}</span>` : ""}</td>
      <td>${esc(f.label || label(f.concept))}<br><code>${esc(f.concept)}</code>${f.unit && f.unit !== "document" ? `<br><span class="cv-muted">단위 ${esc(f.unit.split(" · ").map((u) => UNIT_KO[u] || u).join(" · "))}</span>` : ""}</td>
      <td>${(f.paths || []).map((p) => `<span class="cv-path">${esc(p)}</span>`).join(" ") || `<span class="cv-muted">${esc(f.reason || "")}</span>`}
      ${found.length ? `<br><span class="cv-muted">값 있음:</span> ${found.map((x) => `<code>${esc(x)}</code>`).join(" ")}` : ""}${targetDetail(f)}</td></tr>`; }).join("")}
    </tbody></table>
    ${(r.evidence || []).length ? `<h4>조항이 요구하는 증빙 (${r.evidence.length})</h4>
    <table class="cv-facts"><thead><tr><th>상태</th><th>증빙 종류</th><th>BOM 에서 찾은 증빙</th></tr></thead><tbody>
    ${r.evidence.map((e) => `<tr><td><span class="cv-chip ${EV_CLS[e.status] || ""}">${EV_STATUS_KO[e.status] || e.status}</span></td>
      <td>${esc(evLabel(e.kind))}<br><code>${esc(e.kind)}</code></td>
      <td>${e.found?.length ? e.found.map(evidenceFound).join("<br>") : `<span class="cv-muted">${esc(e.reason || "")}</span>`}</td></tr>`).join("")}
    </tbody></table>` : ""}
    <p class="cv-note">"비어 있음" 과 "자리 없음" 이 누락이고, 비어 있음의 필드가 채울 자리입니다. "부분 대응" 은 값은 있지만 필드의 대상 범위나 표현 형태가 요구와 달라 부분 반영까지만 갑니다. 조건식(JSON Logic)이 있는 조항은 조건이 거짓이면 그 사실을 "요구 안 됨" 으로 빼고, 조건을 판단할 정보가 BOM 에 없으면(자리 자체가 없음) "판단 못 함" 이라 검토 필요입니다. 사실은 프로파일 경로가 속한 단위(데이터셋 · 모델 · 구성요소 · 문서)마다 전부 확인하고(조건도 단위마다), 값이 빠진 구성요소를 적습니다. "해당 시 필요" 는 where applicable 처럼 해당 여부를 BOM 으로 판단할 수 없는 사실이라, 값이 있으면 세고 없어도 누락으로 세지 않으며 그런 사실만 있는 조항은 검토 필요입니다. 카드 전체에 걸린 조건이 거짓이거나 예외에 해당하면 비적용입니다. 시스템 프로파일 칸(profile.…)을 보는 조건은 칸이 없으면 모름이라 검토 필요이고, 예외는 칸이 없으면 해당 없음입니다. 증빙은 사실 다음에 봅니다. 요구 사실이 다 있어도 증빙이 없거나 무효(만료)이면 부분 반영입니다. 증빙은 구성요소의 externalReferences(종류별 type), declarations 의 주장(claims)이 가리키는 evidence(propertyName aibom:evidence:…), 요구사항(definitions.standards)에 댄 attestations 에서 찾습니다.</p>`;
  wireMarks(d);
}
// 찾은 증빙 하나를 한 줄로
function evidenceFound(f) {
  const flag = (v) => v ? "있음" : "없음";
  const bad = f.problems?.length ? ` <span class="cv-chip missing">${esc(f.problems.join(", "))}</span>` : "";
  if (f.via === "externalReferences") return `<code>${esc(f.on)}</code> externalReferences <b>${esc(f.type)}</b> <span class="cv-path">${esc(f.url || "")}</span> <span class="cv-muted">해시 ${flag(f.hashes)}</span>${bad}`;
  if (f.via === "externalRef") return `<code>${esc(f.on)}</code> externalRef <b>${esc(f.type)}</b> <span class="cv-path">${esc(f.url || "")}</span>${bad}`;
  if (f.via === "relationship") return `<code>${esc(f.on)}</code> <b>${esc(f.type)}</b> → <code>${esc(f.ref || "")}</code> <span class="cv-muted">작성 ${f.created || "없음"} · 만료 ${f.expires || "없음"} · 작성자 ${flag(f.author)} · 해시 ${flag(f.hashes)}</span>${bad}`;
  if (f.via === "affirmation") return `<code>$</code> declarations.affirmation <span class="cv-muted">서명자 ${(f.signatories || []).map(esc).join(", ") || "없음"} · 서명 ${flag(f.signature)}</span>${bad}`;
  const parts = [`작성 ${f.created || "없음"}`, `만료 ${f.expires || "없음"}`, `작성자 ${flag(f.author)}`, `서명 ${flag(f.signature)}`];
  if (f.requirement) parts.push(`요구사항 ${f.requirement} 에 댄 입증` + (f.conformance !== null && f.conformance !== undefined ? ` (준수도 ${f.conformance})` : ""));
  return `<code>${esc(f.on)}</code> declarations <code>${esc(f.ref || "")}</code> <span class="cv-muted">${esc(f.property || "")} · ${parts.map(esc).join(" · ")}</span>${bad}`;
}
// 단위가 구성요소인 fact: 구성요소별 조건과 빠진 구성요소
function targetDetail(f) {
  if (!f.unit || f.unit === "document") return "";
  const out = [];
  if (f.condition_on) out.push(`조건 ${esc(f.condition)}: ` + Object.entries(f.condition_on).map(([k, v]) => `<code>${esc(k)}</code> ${v === true ? "참" : v === false ? "거짓" : "평가 못 함"}`).join(", "));
  if (f.missing_on?.length) out.push(`빠진 구성요소${f.missing_count > f.missing_on.length ? ` (${f.missing_count}개 중 ${f.missing_on.length}개)` : ""}: ` + f.missing_on.map((x) => `<code>${esc(x)}</code>`).join(" "));
  else if (f.status === "missing" && f.reason) out.push(esc(f.reason));
  return out.map((x) => `<br><span class="cv-muted">${x}</span>`).join("");
}

// 브라우저 안 판정 (ai-bom/src/judge/judge.py 와 같은 규칙). 검사 대상은 metadata.component 와 모델·데이터셋 구성요소.
// fact 에 target 이 있으면 프로파일의 targets 로 그 종류의 구성요소를 찾아 하나씩 본다 (조건도 구성요소마다).
// 조건 변수는 값이 있으면 참, 자리는 있는데 비면 거짓, 자리 자체가 없으면 모름(null)이고, 모름이면 그 사실은 unknown 이라 카드가 검토 필요다.
// 카드가 이 시스템에 적용되나 (judge.py 의 applicability): "applies" / "not_applies" / "unknown". 카드의 risk_class 가 any 면 위험등급을 안 보고,
// 주체(obligation.actor)는 역할 목록이라 시스템의 역할과 하나라도 겹치면 맞다 (4조 "Providers and deployers" 는 제공자든 배포자든).
// 주체가 organisation(NIST·ISO)이면 역할을 안 본다. 예전 카드의 문자열 하나와 operator(모든 운영자 = 다섯 역할 전부)도 목록으로 읽는다.
// 보는 칸이 프로파일에 없으면 unknown (검토 필요).
const EU_ROLES = ["provider", "deployer", "importer", "distributor", "authorised_representative"];
const actorsOf = (card) => [...new Set(asList(card.obligation?.actor).flatMap((a) => a === "operator" ? EU_ROLES : a === "any" ? ["organisation"] : [a]))];
function applicability(card, system) {
  const wanted = new Set(card.applicability?.risk_class || ["any"]), actors = actorsOf(card).length ? actorsOf(card) : ["organisation"];
  const missing = [], mismatch = [];
  if (!wanted.has("any")) {
    const have = new Set(Array.isArray(system.risk_class) ? system.risk_class : system.risk_class ? [system.risk_class] : []);
    if (have.has("gpai_systemic")) have.add("gpai");
    if (!have.size) missing.push("위험등급(risk_class)");
    else if (![...wanted].some((x) => have.has(x))) mismatch.push(`카드의 위험등급 ${[...wanted].sort().join(", ")} 과 시스템의 ${[...have].sort().join(", ")} 이 안 맞음`);
  }
  if (!actors.includes("organisation")) {      // 시스템의 역할도 목록 (제공자이면서 배포자일 수 있다)
    const roles = Array.isArray(system.role) ? system.role : system.role ? [system.role] : [];
    if (!roles.length) missing.push("역할(role)");
    else if (!actors.some((a) => roles.includes(a))) mismatch.push(`카드의 주체 ${actors.join(", ")} 가운데 시스템의 역할 ${[...roles].sort().join(", ")} 에 있는 것이 없음`);
  }
  if (mismatch.length) return ["not_applies", mismatch.join("; ")];
  if (missing.length) return ["unknown", `시스템 프로파일에 ${missing.join("·")} 이 없어 적용 여부를 알 수 없음`];
  return ["applies", null];
}
function judgeBom(bom, name, system = {}) {
  const spdx = isSpdx(bom);
  activateProfile(spdx ? "SPDX" : "CycloneDX");
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
  // ---- SPDX 3.0.1 JSON-LD (judge.py 의 spdx_* 함수). 요소의 클래스는 type 에서 접두사를 뗀 것이고 조상은 프로파일의 class_parents
  const graph = spdx ? bom["@graph"].filter((e) => e && typeof e === "object") : [];
  const byId = Object.fromEntries(graph.filter((e) => e.spdxId || e["@id"]).map((e) => [e.spdxId || e["@id"], e]));
  const spdxClass = (e) => { const t = e.type || ""; return t.includes("_") ? t.slice(t.indexOf("_") + 1) : t; };
  const spdxIs = (e, cls) => { const c = spdxClass(e); return c === cls || (classParents[c] || []).includes(cls); };
  const artifactClass = (cls) => cls === "Artifact" || (classParents[cls] || []).includes("Artifact");
  const roots = graph.filter((d) => spdxClass(d) === "SpdxDocument").flatMap((d) => (d.rootElement || []).map((r) => byId[r]).filter(Boolean));
  const spdxLabel = (e) => { const sid = e.spdxId || e["@id"] || ""; return sid.includes("#") ? sid.slice(sid.indexOf("#") + 1) : (sid || e.name || "?"); };
  const parseSpdx = (path) => { let want = null; if (path.endsWith(")") && path.includes(" (type:")) { const i = path.lastIndexOf(" (type:"); want = path.slice(i + 7, -1); path = path.slice(0, i); } const [cls, ...props] = path.split("."); return [cls, props, want]; };
  const spdxValues = (start, props, want) => {               // [값들, 상태]. id 문자열은 요소로, '@관계[:클래스]' 는 나가는 Relationship 의 to 요소로
    let objs = [start];
    for (const k of props) {
      const nxt = []; let seen = false;
      if (k.startsWith("@")) {
        const [rel, wantCls] = k.slice(1).split(":"); const ids = new Set(objs.filter((o) => o && typeof o === "object" && o.spdxId).map((o) => o.spdxId));
        for (const r of graph) if (spdxClass(r) === "Relationship" && ids.has(r.from)) { seen = true; if (r.relationshipType === rel) for (const t of r.to || []) { const e = byId[t] ?? t; if (!wantCls || (e && typeof e === "object" && spdxIs(e, wantCls))) nxt.push(e); } }
        if (!seen) return [[], "absent"]; objs = nxt; continue;
      }
      for (let o of objs) {
        if (typeof o === "string" && o in byId) o = byId[o];
        if (o && typeof o === "object" && k in o) { seen = true; const v = o[k]; let items = Array.isArray(v) ? v : [v]; if (want && k === "externalRef") items = items.filter((x) => x && typeof x === "object" && x.externalRefType === want); nxt.push(...items); }
      }
      if (!seen) return [[], "absent"]; objs = nxt;
    }
    const vals = objs.filter((o) => !isEmpty(o)); return [vals, vals.length ? "value" : "empty"];
  };
  // ---- 검사 대상 구성요소: CycloneDX 는 metadata.component 와 모델·데이터셋, SPDX 는 루트 요소와 AIPackage·DatasetPackage
  const comps = [];
  if (spdx) { comps.push(...roots); for (const e of graph) if (!comps.includes(e) && (spdxIs(e, "AIPackage") || spdxIs(e, "DatasetPackage"))) comps.push(e); }
  else { if (bom.metadata?.component) comps.push(bom.metadata.component); (function walk(items) { for (const c of items || []) { if (c.type === "machine-learning-model" || c.type === "data") comps.push(c); walk(c.components); } })(bom.components); }
  const lab = (c) => spdx ? spdxLabel(c) : (c["bom-ref"] || c.name || "?");
  const allComps = spdx ? graph.filter((e) => spdxIs(e, "Artifact") && !roots.includes(e)) : [];
  if (!spdx) (function walk(items) { for (const c of items || []) { allComps.push(c); walk(c.components); } })(bom.components);
  const compsOfKind = (kind) => {
    const spec = targets[kind]; if (!spec) throw new Error(`프로파일 targets 에 '${kind}' 가 없다`);
    if (spdx) { if (spec.root) return roots.slice(); const purposes = spec.purposes || []; return [...roots, ...allComps].filter((e) => (spec.classes || []).some((c) => spdxIs(e, c)) && !(spec.exclude_classes || []).some((x) => spdxIs(e, x)) && (!purposes.length || purposes.includes(e.software_primaryPurpose))); }
    if (spec.root) return get(bom, spec.root.split(".")).filter((v) => v && typeof v === "object");
    const meta = bom.metadata?.component;                 // 시스템 자신이 그 종류면 같이 센다 (모델이 주체인 BOM)
    return [...(meta && typeof meta === "object" ? [meta] : []), ...allComps].filter((c) => (spec.component_types || []).includes(c.type));
  };
  const DOC_ROOTS = ["components", "services", "dependencies", "formulation", "declarations", "definitions", "metadata", "compositions"];
  const resolve = (path) => {
    if (spdx) { const [cls, props, want] = parseSpdx(path); if (artifactClass(cls)) return comps.filter((c) => spdxIs(c, cls) && spdxValues(c, props, want)[0].length).map(lab); return graph.some((e) => spdxIs(e, cls) && spdxValues(e, props, want)[0].length) ? ["$"] : []; }
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); return comps.filter((c) => (c.externalReferences || []).some((e) => e.type === t && e.url)).map(lab); }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return comps.filter((c) => get(c, rest).length).map(lab);
    if (rootKey === "componentData") return comps.filter((c) => c.type === "data" && get(c.data, rest).length).map(lab);
    if (rootKey === "releaseNotes") return comps.filter((c) => get(c, ["releaseNotes", ...rest]).length).map(lab);
    if (DOC_ROOTS.includes(rootKey)) return get(bom, [rootKey, ...rest]).length ? ["$"] : [];
    return [];
  };
  // 구성요소 하나에 그 경로의 값이 있나 (value / empty / absent). 구성요소에 달리지 않는 경로(declarations 등)는 문서에서 본다
  const probeComp = (c, path) => {
    if (spdx) { const [cls, props, want] = parseSpdx(path); if (!artifactClass(cls)) return resolve(path).length ? "value" : "absent"; if (!spdxIs(c, cls)) return "absent"; return spdxValues(c, props, want)[1]; }
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); const refs = c.externalReferences; if (refs === undefined || refs === null) return "absent"; return refs.some((e) => e.type === t && e.url) ? "value" : "empty"; }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return probe(c, rest);
    if (rootKey === "componentData") return c.type === "data" && "data" in c ? probe(c.data, rest) : "absent";
    if (rootKey === "releaseNotes") return probe(c, ["releaseNotes", ...rest]);
    if (rootKey === "components" && !rest.length) return allComps.includes(c) ? "value" : "empty";      // 구성요소 목록 자체: 실려 있으면 참
    return resolve(path).length ? "value" : "absent";
  };
  const onComp = (c, path) => probeComp(c, path) === "value";
  // 구성요소 하나에 있는 경로의 값들 (조건 변환식·val 용. judge.py 의 component_values)
  const componentValues = (c, path) => {
    if (spdx) { const [cls, props, want] = parseSpdx(path); if (!artifactClass(cls)) return graph.filter((e) => spdxIs(e, cls)).flatMap((e) => spdxValues(e, props, want)[0]); return spdxIs(c, cls) ? spdxValues(c, props, want)[0] : []; }
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); return (c.externalReferences || []).filter((e) => e.type === t && e.url).map((e) => e.url); }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return get(c, rest);
    if (rootKey === "componentData") return c.type === "data" ? get(c.data, rest) : [];
    if (rootKey === "releaseNotes") return get(c, ["releaseNotes", ...rest]);
    return DOC_ROOTS.includes(rootKey) ? get(bom, [rootKey, ...rest]) : [];
  };
  // 조건식 변수(개념 id): 참·거짓·모름. 프로파일 줄에 truth(조건 변환식)가 있으면 값으로(yes/no), 없으면 값의 유무로. 단위가 구성요소인 fact 는 구성요소 하나에서 본다
  // profile. 변수는 시스템 프로파일의 칸 (조건에서는 없으면 모름, 예외에서는 없으면 거짓). val 은 경로의 첫 값 (judge.py 의 first_value)
  const PROFILE = "profile.";
  const profileVar = (k, dflt = null) => { const key = k.slice(PROFILE.length); return system && typeof system === "object" && key in system ? system[key] : dflt; };
  const truthState = (values, rule) => { const vals = values.map(String); if (vals.some((v) => (rule.true || []).includes(v))) return true; if (vals.some((v) => (rule.false || []).includes(v))) return false; return null; };
  const varState = (k, cs) => { const paths = (profile[k]?.cdx || []).slice().sort(); const rule = truth[k]; if (rule) return truthState(cs.flatMap((c) => paths.flatMap((p) => componentValues(c, p))), rule); return tri(cs.flatMap((c) => paths.map((p) => probeComp(c, p)))); };
  const stateInBom = (k, dflt = null) => k.startsWith(PROFILE) ? profileVar(k, dflt) : varState(k, comps);
  const valueOf = (cs) => (k) => { if (k.startsWith(PROFILE)) return profileVar(k); for (const p of (profile[k]?.cdx || []).slice().sort()) for (const c of cs) { const vals = componentValues(c, p); if (vals.length) return vals[0]; } return null; };
  const valueInBom = valueOf(comps);
  const logic = (expr, varOf = stateInBom, valOf = valueInBom) => {
    if (expr === null || typeof expr !== "object" || Array.isArray(expr)) return expr;
    const [op, raw] = Object.entries(expr)[0]; const args = Array.isArray(raw) ? raw : [raw];
    if (op === "var") return varOf(args[0]);
    if (op === "val") return valOf ? valOf(args[0]) : null;
    if (op === "missing") return args.every((a) => varOf(a) !== true);      // 변수가 전부 참이 아니면 참 (모름도 없음으로)
    const v = args.map((a) => logic(a, varOf, valOf)), unk = v.some((x) => x === null || x === undefined);
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
  // 증빙 (judge.py 의 find_evidence / judge_evidence). 카드의 evidence[] 종류마다 프로파일 evidence.kinds 의 조회식으로 찾는다
  const now = Date.now();
  const past = (ts) => { if (!ts || typeof ts !== "string") return null; const t = Date.parse(ts); return Number.isNaN(t) ? null : t < now; };
  const idsOf = (c) => new Set([c.card_id, c.source?.clause_id, c.source?.parent_clause_id].filter(Boolean));
  const declared = (e, via, on, extra = {}) => { const expired = past(e.expires) === true, a = e.author;
    return {via, on, ref: e["bom-ref"], property: e.propertyName, created: e.created ?? null, expires: e.expires ?? null, author: a && typeof a === "object" ? Boolean(a.name || a.email) : Boolean(a),
            signature: Boolean(e.signature), data: (e.data || []).length, valid: !expired, problems: expired ? [`만료 (${e.expires})`] : [], ...extra}; };
  const findEvidence = (c, spec) => {
    let cs = comps;
    if (spec.target) { const kc = compsOfKind(spec.target); cs = kc.filter((x) => comps.includes(x)); if (!cs.length) cs = kc; }     // 특정 종류의 구성요소에만 (DATASHEET 는 데이터셋)
    const found = [];
    if (spdx) {                                                // SPDX: 요소의 externalRef 와 요소에서 나가는 Relationship 의 to 요소
      const ids = new Set(cs.map((x) => x.spdxId).filter(Boolean)), rtypes = new Set(spec.external_ref_types || []), reltypes = new Set(spec.relationship_types || []);
      for (const x of cs) for (const e of x.externalRef || []) if (e && typeof e === "object" && rtypes.has(e.externalRefType)) { const loc = e.locator || []; found.push({via: "externalRef", on: spdxLabel(x), type: e.externalRefType, url: loc[0] ?? null, hashes: false, valid: loc.length > 0, problems: loc.length ? [] : ["locator 없음"]}); }
      for (const r of graph) {
        if (spdxClass(r) !== "Relationship" || !reltypes.has(r.relationshipType) || !ids.has(r.from)) continue;
        for (const to of r.to || []) {
          const e = byId[to]; if (!e) continue;
          const ci = typeof e.creationInfo === "string" ? (byId[e.creationInfo] || {}) : (e.creationInfo || {});
          const expired = past(e.validUntilTime) === true;
          found.push({via: "relationship", on: spdxLabel(byId[r.from] || {}), type: r.relationshipType, ref: spdxLabel(e), created: ci.created ?? null, expires: e.validUntilTime ?? null, author: Boolean(ci.createdBy && ci.createdBy.length), signature: false, hashes: Boolean(e.verifiedUsing && e.verifiedUsing.length), valid: !expired, problems: expired ? [`만료 (${e.validUntilTime})`] : []});
        }
      }
      return found;
    }
    const refs = new Set(cs.map((x) => x["bom-ref"]).filter(Boolean)), types = new Set(spec.external_reference_types || []);
    for (const x of cs) for (const e of x.externalReferences || []) if (types.has(e.type)) found.push({via: "externalReferences", on: lab(x), type: e.type, url: e.url, hashes: Boolean(e.hashes), valid: Boolean(e.url), problems: e.url ? [] : ["url 없음"]});
    const decl = bom.declarations || {}, evByRef = Object.fromEntries((decl.evidence || []).filter((e) => e && typeof e === "object" && e["bom-ref"]).map((e) => [e["bom-ref"], e]));
    const claims = (decl.claims || []).filter((x) => x && typeof x === "object");
    for (const cl of claims) { if (!refs.has(cl.target)) continue; for (const ref of cl.evidence || []) { const e = evByRef[ref]; if (e && spec.property && e.propertyName === spec.property) found.push(declared(e, "declarations", cl.target, {claim: cl["bom-ref"]})); } }
    const wanted = idsOf(c), reqs = {};
    for (const s of bom.definitions?.standards || []) for (const rq of s.requirements || []) if (rq && typeof rq === "object" && rq["bom-ref"]) reqs[rq["bom-ref"]] = rq;
    const claimsByRef = Object.fromEntries(claims.filter((x) => x["bom-ref"]).map((x) => [x["bom-ref"], x])), seen = new Set(found.map((f) => f.ref).filter(Boolean));
    for (const att of decl.attestations || []) for (const m of att.map || []) {
      const rq = reqs[m.requirement]; if (!rq || !wanted.has(rq.identifier)) continue;
      for (const cref of m.claims || []) { const cl = claimsByRef[cref] || {}; for (const ref of cl.evidence || []) { const e = evByRef[ref]; if (e && !seen.has(ref)) { seen.add(ref); found.push(declared(e, "attestations", cl.target || "$", {requirement: rq.identifier, conformance: m.conformance?.score ?? null})); } } }
    }
    const aff = decl.affirmation || {};
    if (spec.affirmation && aff.statement) { const sg = (aff.signatories || []).filter((s) => s && typeof s === "object"); found.push({via: "affirmation", on: "$", signatories: sg.map((s) => s.name).slice(0, 10), signature: sg.some((s) => s.signature), valid: true, problems: []}); }
    return found;
  };
  const judgeEvidence = (c) => (c.evidence || []).map((ev) => {
    const spec = (evidenceSpec.kinds || {})[ev.concept], entry = {kind: ev.concept, label: ev.label};
    if (!spec) return {...entry, status: "unknown", found: [], reason: "프로파일에 이 증빙 종류의 조회식이 없음"};
    const found = findEvidence(c, spec), valid = found.filter((f) => f.valid), status = valid.length ? "present" : found.length ? "invalid" : "missing";
    const out = {...entry, status, found: found.slice(0, 10)};
    if (status === "invalid") out.reason = "찾은 증빙이 전부 무효: " + found.slice(0, 10).map((f) => `${f.ref || f.url || f.via} ${f.problems.join(", ")}`).join("; ");
    else if (status === "missing") { const where = []; if (spec.external_reference_types?.length) where.push(`externalReferences type ${spec.external_reference_types.join("/")}`); if (spec.property) where.push(`declarations.claims → evidence (propertyName ${spec.property})`); if (spec.external_ref_types?.length) where.push(`externalRef externalRefType ${spec.external_ref_types.join("/")}`); if (spec.relationship_types?.length) where.push(`Relationship ${spec.relationship_types.join("/")} 의 to 요소`); out.reason = "증빙 없음. 둘 자리: " + where.join(" 또는 "); }
    return out;
  });
  // 카드 단위 조건(scope card)과 예외 (judge.py 의 evaluate_gates): 조건이 거짓이면 비적용, 모름이면 검토 필요. 예외가 참이면 비적용, 모름이면 검토 필요
  const evaluateGates = (c) => {
    const conditions = {}, exceptions = {}, notApplies = [], unknown = [];
    for (const cond of c.conditions || []) {
      const rec = {text: cond.text, scope: cond.scope || "fact", evaluated: Boolean(cond.expr), result: null};
      if (cond.note) rec.note = cond.note;
      if (cond.expr) {
        try { rec.result = logic(cond.expr); } catch (e) { rec.error = e.message; }
        if (cond.scope === "card") {
          if (rec.result === false) notApplies.push(`조건 ${cond.id} 에 해당하지 않음: ${cond.text}`);
          else if (rec.result === null || rec.result === undefined) unknown.push(`조건 ${cond.id} 을 판단할 정보가 없음: ${cond.text}` + (rec.error ? ` (${rec.error})` : ""));
        }
      }
      conditions[cond.id] = rec;
    }
    (c.exceptions || []).forEach((ex, i) => {
      const eid = ex.id || `E${i + 1}`, rec = {text: ex.text, evaluated: Boolean(ex.expr), result: null};
      if (ex.note) rec.note = ex.note;
      if (ex.expr) {
        try { rec.result = logic(ex.expr, (k) => stateInBom(k, false)); } catch (e) { rec.error = e.message; }
        if (rec.result === true) notApplies.push(`예외 ${eid} 에 해당: ${ex.text}`);
        else if (rec.result === null || rec.result === undefined) unknown.push(`예외 ${eid} 을 판단할 정보가 없음: ${ex.text}` + (rec.error ? ` (${rec.error})` : ""));
      }
      exceptions[eid] = rec;
    });
    return {conditions, exceptions, notApplies: notApplies.join("; ") || null, gateUnknown: unknown.join("; ") || null};
  };
  const results = cards.map((c) => {
    const [applies, whyApplies] = applicability(c, system);
    if (applies === "not_applies") return {card_id: c.card_id, verdict: "비적용", reason: whyApplies, facts: []};
    const {conditions, exceptions, notApplies, gateUnknown} = evaluateGates(c);
    const extra = {...(Object.keys(conditions).length ? {conditions} : {}), ...(Object.keys(exceptions).length ? {exceptions} : {})};
    if (notApplies) return {card_id: c.card_id, verdict: "비적용", reason: notApplies, facts: [], ...extra};
    const byId = Object.fromEntries((c.conditions || []).map((x) => [x.id, x]));
    // 확인 단위 (judge.py 의 unit_of_path · judge_fact): 경로가 속한 단위마다 전부 확인한다. CycloneDX 는 componentData → 데이터셋, component.modelCard → 모델,
    // 그 밖의 경로 → 문서(검사 대상 구성요소 어디에든 하나라도). SPDX 는 DatasetPackage · AIPackage · 나머지. 프로파일 줄의 target 이 있으면 그것. 조건 변수가 다른 단위에 있으면 문서 단위로 본다
    const unitOf = (path) => {
      const base = path.split(" (type:")[0];
      if (spdx) { const cls = base.split(".")[0]; if (cls === "DatasetPackage") return "dataset"; if (cls === "AIPackage") return "model"; return "document"; }
      const [rootKey, ...rest] = base.split(".");
      if (rootKey === "componentData") return "dataset";
      if (rootKey === "component") return rest[0] === "modelCard" ? "model" : "document";
      return "document";
    };
    const unitComps = (unit) => unit === "document" ? [null] : unit === "component" ? comps : compsOfKind(unit);
    const onUnit = (unit, x, p) => unit === "document" ? resolve(p).length > 0 : onComp(x, p);
    const ulab = (unit, x) => unit === "document" ? "$" : lab(x);
    const judgeFact = (f, paths, entry) => {
      const override = unitOverride[f.concept], unitPaths = {};
      for (const p of paths) (unitPaths[override || unitOf(p)] ||= []).push(p);
      entry.unit = Object.keys(unitPaths).join(" · ") || override || "document";
      const cid = f.required === "conditional" ? f.condition : null, cond = cid ? (byId[cid] || {}) : {}, expr = cid ? cond.expr : undefined, hasExpr = expr !== undefined && expr !== null;
      if (cid) { entry.condition = cid; entry.condition_evaluated = hasExpr; }
      if (pending.has(f.concept)) return {...entry, status: "unknown", paths, reason: "매핑이 승인되지 않음 (프로파일 줄이 pending_review)"};
      if (!paths.length) {
        if (hasExpr && conditions[cid]?.result === false) return {...entry, status: "not_required", paths: [], reason: `조건 ${cid} 이 거짓이라 요구되지 않음: ${cond.text}`};
        return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      }
      const groups = Object.entries(unitPaths).map(([u, ps]) => { const cs = unitComps(u); return u === "system" && !cs.length ? ["document", ps, [null]] : [u, ps, cs]; }).filter(([, , cs]) => cs.length);   // 루트 구성요소가 없는 BOM: 시스템 단위는 문서 단위로
      if (!groups.length) return {...entry, status: "missing", paths, found_at: {}, checked: 0, reason: "BOM 에 " + Object.keys(unitPaths).map((u) => UNIT_KO[u] || u).join(" · ") + " 구성요소가 없음"};
      const required = [], condOn = {}, unknown = [];
      for (const [u, ps, cs] of groups) for (const x of cs) {
        if (hasExpr) {
          let v;
          if (u === "document") v = conditions[cid]?.result;                     // 문서 단위: 카드 단위로 평가한 조건 결과
          else { const same = (k) => !(profile[k]?.cdx || []).length || (profile[k].cdx || []).every((p) => unitOf(p) === u), scope = (k) => same(k) ? [x] : comps;
                 try { v = logic(expr, (k) => k.startsWith(PROFILE) ? profileVar(k) : varState(k, scope(k)), (k) => k.startsWith(PROFILE) ? profileVar(k) : valueOf(scope(k))(k)); } catch (e) { v = null; } }
          condOn[ulab(u, x)] = v;
          if (v === null || v === undefined) { unknown.push(ulab(u, x)); continue; }
          if (!v) continue;
        }
        required.push([u, x, ps]);
      }
      if (hasExpr) entry.condition_on = condOn;
      if (unknown.length) return {...entry, status: "unknown", paths, reason: `조건 ${cid} 을 판단할 정보가 BOM 에 없음: ${cond.text}` + (unknown.length === 1 && unknown[0] === "$" ? "" : ` (구성요소 ${unknown.slice(0, 10).join(", ")})`)};
      if (hasExpr && !required.length) return {...entry, status: "not_required", paths, reason: `조건 ${cid} 이 거짓이라 요구되지 않음: ${cond.text}`};
      const have = [], missing = [], found = {};
      for (const [u, x, ps] of required) { const hits = ps.filter((p) => onUnit(u, x, p)); (hits.length ? have : missing).push([u, x]); for (const p of hits) (found[p] ||= []).push(ulab(u, x)); }
      for (const p of Object.keys(found)) found[p] = found[p].slice(0, 10);
      entry.checked = required.length;
      const status = missing.length ? "missing" : partial[f.concept] ? "partial" : "present";
      if (missing.length && f.required === "optional") return {...entry, status: "optional", paths, found_at: found, missing_on: missing.map(([u, x]) => ulab(u, x)).slice(0, 10), missing_count: missing.length, reason: OPTIONAL_REASON};   // 해당 시 필요: 누락이 아니라 판단 보류
      const out = {...entry, status, paths, found_at: found};
      if (missing.length) { const units = [...new Set(required.map(([u]) => UNIT_KO[u] || u))].join(" · "); Object.assign(out, {missing_on: missing.map(([u, x]) => ulab(u, x)).slice(0, 10), missing_count: missing.length, reason: required.length > 1 || missing[0][0] !== "document" ? `요구되는 ${units} ${required.length}개 중 ${missing.length}개에 값이 없음` : "값이 없음"}); }
      else if (status === "partial") out.reason = partial[f.concept];
      return out;
    };
    const facts = c.facts.map((f) => judgeFact(f, profile[f.concept]?.cdx || [], {concept: f.concept, label: label(f.concept), required: f.required}));
    const evidence = judgeEvidence(c), evUnknown = evidence.filter((e) => e.status === "unknown"), evLacking = evidence.filter((e) => e.status === "missing" || e.status === "invalid");   // 증빙은 사실 다음
    const required = facts.filter((f) => f.status !== "not_required" && f.status !== "optional"), unknown = required.filter((f) => f.status === "unknown");
    const optionalAbsent = facts.filter((f) => f.status === "optional");
    let verdict, reason;
    if (applies === "unknown") { verdict = "검토 필요"; reason = whyApplies; }
    else if (gateUnknown) { verdict = "검토 필요"; reason = gateUnknown; }
    else if (!profileApproved) { verdict = "검토 필요"; reason = "매핑 프로파일이 승인되지 않음"; }
    else if (unknown.length) { verdict = "검토 필요"; reason = unknown.map((f) => `${f.concept}: ${f.reason}`).join("; "); }
    else if (evUnknown.length) { verdict = "검토 필요"; reason = evUnknown.map((e) => `증빙 ${e.kind}: ${e.reason}`).join("; "); }
    else if (!required.length && optionalAbsent.length) { verdict = "검토 필요"; reason = "해당 시 필요한 사실만 있는데 값이 없어 해당 여부를 판단할 수 없음: " + optionalAbsent.map((f) => f.concept).join(", "); }
    else if (!required.length) { verdict = "반영"; reason = "요구되는 사실이 없음 (조건이 모두 거짓)"; }
    else if (required.every((f) => f.status === "present")) {
      if (evLacking.length) { verdict = "부분 반영"; reason = "사실은 다 있으나 증빙이 " + evLacking.map((e) => `${e.kind} ${e.status === "invalid" ? "무효" : "없음"}`).join(", "); }   // 특허: 항목은 있으나 증빙 검증에 실패
      else verdict = "반영";
    }
    else if (required.every((f) => f.status === "missing" || f.status === "gap")) verdict = "미반영";
    else verdict = "부분 반영";
    return {card_id: c.card_id, verdict, ...(reason ? {reason} : {}), facts, ...extra, ...(evidence.length ? {evidence} : {})};
  });
  const summary = Object.fromEntries(VERDICTS.map((v) => [v, results.filter((r) => r.verdict === v).length]));
  const sdoc = spdx ? (graph.find((e) => spdxClass(e) === "SpdxDocument") || {}) : null;
  const info = spdx ? {bomFormat: "SPDX", specVersion: (typeof sdoc.creationInfo === "string" ? byId[sdoc.creationInfo] : sdoc.creationInfo)?.specVersion ?? null, serialNumber: (sdoc.spdxId || "").split("#")[0] || null, subject: roots[0]?.name || sdoc.name || name}
    : {bomFormat: bom.bomFormat, specVersion: bom.specVersion, serialNumber: bom.serialNumber, subject: bom.metadata?.component?.name || name};
  return {bom: info, system_profile: system, summary, cards: results};
}

init().catch((err) => { root.innerHTML = `<p class="cv-muted">데이터를 읽지 못했습니다: ${esc(err.message)}</p>`; });
})();
