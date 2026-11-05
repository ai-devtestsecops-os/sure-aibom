// 규제 판정 화면 (compliance/regulation-cards.md). BOM 을 규제 조항마다 대 본 결과와, 조항을 누르면 원문과 요구 사실.
// 데이터는 export_data.py 가 data/cards/ 에 둔 JSON. 카드 보기·추출기 비교·승인은 내부 화면의 몫이라 여기 두지 않는다.
if (document.querySelector(".card-viewer")) (() => {
const root = document.querySelector(".card-viewer");
const BASE = root.dataset.base || "data/cards/";
const REG_NAME = {EUAIA: "EU AI Act", NISTRMF: "NIST AI RMF", ISO42001: "ISO/IEC 42001"};
const VERDICTS = ["반영", "부분 반영", "미반영", "검토 필요", "비적용"];
const STATUS_KO = {present: "있음", missing: "비어 있음", gap: "자리 없음", not_required: "요구 안 됨"};
const MARK_CLS = {present: "", missing: "missing", gap: "muted", not_required: "muted"};      // 원문 구절의 색
const $ = (sel) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const regOf = (id) => REG_NAME[id.split("-")[1]] || id.split("-")[1];
const vclass = (v) => "v-" + v.replace(/\s/g, "");
let cards = [], cardById = {}, vocab = {}, profile = {}, targets = {}, judgIndex = [];
const KIND_KO = {system: "시스템", model: "모델", dataset: "데이터셋", software: "소프트웨어"};

async function load(name) { const r = await fetch(BASE + name); if (!r.ok) throw new Error(name); return r.json(); }

async function init() {
  const [c, v, p, j, src] = await Promise.all([load("cards.json"), load("vocabulary.json"), load("profile.json"), load("judgments/index.json"), load("source.json").catch(() => ({}))]);
  cards = c; cardById = Object.fromEntries(c.map((x) => [x.card_id, x])); vocab = Object.fromEntries(v.concepts.map((x) => [x.id, x])); judgIndex = j;
  if (src.cards === "gold") { const n = document.createElement("p"); n.className = "cv-note"; n.textContent = "지금 판정에 쓰는 카드는 요구사항 표에서 변환한 정답 카드(cards/gold)다. 승인한 카드가 생기면 그것으로 바뀐다."; root.prepend(n); }
  targets = p.targets || {};                          // fact 의 target(대상 구성요소 종류)을 BOM 에서 찾는 법
  for (const line of p.lines) {                       // 개념별 줄: concept → {cdx: [...], spdx: [...]}
    const e = (profile[line.concept] ||= {cdx: [], spdx: []});
    for (const x of [line.cdx_path, ...(line.cdx_paths_more || [])]) if (x && !e.cdx.includes(x)) e.cdx.push(x);
    for (const x of [line.spdx_path, ...(line.spdx_paths_more || [])]) if (x && !e.spdx.includes(x)) e.spdx.push(x);
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
let currentRecord = null;
function initJudgment() {
  const sel = $("#cv-bom");
  sel.innerHTML = judgIndex.map((j, i) => `<option value="${i}">${esc(j.subject)} (${esc(j.file)})</option>`).join("") || `<option value="">예제 BOM 없음</option>`;
  sel.addEventListener("change", async () => { const j = judgIndex[+sel.value]; if (j) showRecord(await load("judgments/" + j.file)); });
  regSelect($("#cv-reg"), () => { renderSummary(); renderJudgList(); });
  $("#cv-verdict-filter").addEventListener("change", renderJudgList);
  $("#cv-bom-file").addEventListener("change", async (ev) => {
    const file = ev.target.files[0]; if (!file) return;
    try { const bom = JSON.parse(await file.text()); showRecord(judgeBom(bom, file.name)); sel.value = ""; }
    catch (err) { $("#cv-judg-summary").innerHTML = `<span class="cv-chip gap">읽을 수 없는 파일: ${esc(err.message)}</span>`; }
  });
  if (judgIndex.length) sel.dispatchEvent(new Event("change"));
}
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
  $("#cv-judg-summary").innerHTML = `<div class="cv-stat"><b>${esc(rec.bom.subject || rec.bom.serialNumber || "")}</b>카드 ${total}장 (조항 ${groups.length}개) · ${esc(rec.bom.bomFormat)} ${esc(rec.bom.specVersion)}</div>`
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
      const f = r.facts || []; const p = f.filter((x) => x.status === "present").length, n = f.filter((x) => x.status === "gap" || x.status === "not_required").length;
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
      <p class="cv-note">칠한 구절이 조항이 요구하는 사실이다. 초록은 BOM 에 있음, 빨강은 비어 있음, 회색은 BOM 형식에 자리가 없거나 이 BOM 에는 요구되지 않음.</p>`
      : `<p class="cv-note">이 규제의 원문은 저작권 때문에 싣지 않는다. 요구 사실과 필드만 보인다.</p>`}
    ${r.conditions ? `<h4>조건</h4><ul>${Object.entries(r.conditions).map(([k, c]) => `<li><code>${esc(k)}</code> ${esc(c.text)} → <b>${c.result === null || c.result === undefined ? "평가 못 함 (조건식 없음)" : c.result ? "참" : "거짓"}</b></li>`).join("")}</ul>` : ""}
    <h4>조항이 요구하는 사실 (${facts.length})</h4>
    <table class="cv-facts"><thead><tr><th>상태</th><th>사실</th><th>BOM 필드</th><th>값이 있는 구성요소</th></tr></thead><tbody>
    ${facts.map((f, i) => `<tr data-idx="${i}"><td><span class="cv-chip ${f.status}">${STATUS_KO[f.status] || f.status}</span>
      ${f.condition_evaluated === false ? `<br><span class="cv-muted">조건 미평가</span>` : f.condition ? `<br><span class="cv-muted">조건 ${esc(f.condition)}</span>` : ""}</td>
      <td>${esc(f.label || label(f.concept))}<br><code>${esc(f.concept)}</code>${f.target ? `<br><span class="cv-muted">대상 ${esc(KIND_KO[f.target] || f.target)}</span>` : ""}</td>
      <td>${(f.paths || []).map((p) => `<span class="cv-path">${esc(p)}</span>`).join(" ") || `<span class="cv-muted">${esc(f.reason || "")}</span>`}</td>
      <td>${[...new Set(Object.values(f.found_at || {}).flat())].map((x) => `<code>${esc(x)}</code>`).join(" ")}${targetDetail(f)}</td></tr>`).join("")}
    </tbody></table>
    <p class="cv-note">"비어 있음" 의 필드가 채울 자리다. 조건식(JSON Logic)이 있는 조항은 조건이 거짓이면 그 사실을 "요구 안 됨" 으로 뺀다. 대상 구성요소가 정해진 사실은 그 종류의 구성요소마다 보고(조건도 구성요소마다), 값이 빠진 구성요소를 적는다. 증빙 검사는 아직 없다.</p>`;
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
function judgeBom(bom, name) {
  const comps = [];
  if (bom.metadata?.component) comps.push(bom.metadata.component);
  (function walk(items) { for (const c of items || []) { if (c.type === "machine-learning-model" || c.type === "data") comps.push(c); walk(c.components); } })(bom.components);
  const get = (obj, keys) => {
    if (!keys.length) return obj === null || obj === undefined || obj === "" || (Array.isArray(obj) && !obj.length) || (typeof obj === "object" && !Array.isArray(obj) && !Object.keys(obj).length) ? [] : [obj];
    if (Array.isArray(obj)) return obj.flatMap((x) => get(x, keys));
    if (obj && typeof obj === "object" && keys[0] in obj) return get(obj[keys[0]], keys.slice(1));
    return [];
  };
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
  // 구성요소 하나에 그 경로의 값이 있나. 구성요소에 달리지 않는 경로(declarations 등)는 문서에서 본다
  const onComp = (c, path) => {
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); return (c.externalReferences || []).some((e) => e.type === t && e.url); }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return get(c, rest).length > 0;
    if (rootKey === "componentData") return c.type === "data" && get(c.data, rest).length > 0;
    if (rootKey === "releaseNotes") return get(c, ["releaseNotes", ...rest]).length > 0;
    if (rootKey === "components" && !rest.length) return allComps.includes(c);      // 구성요소 목록 자체: 실려 있으면 참
    return resolve(path).length > 0;
  };
  // 조건식 변수(개념 id): 그 개념의 프로파일 경로(어느 카드든)에 BOM 값이 있으면 참. target 이 있는 fact 는 구성요소 하나에서 본다
  const presentInBom = (k) => (profile[k]?.cdx || []).some((p) => resolve(p).length);
  const logic = (expr, varOf = presentInBom) => {
    if (expr === null || typeof expr !== "object" || Array.isArray(expr)) return expr;
    const [op, raw] = Object.entries(expr)[0]; const args = Array.isArray(raw) ? raw : [raw];
    if (op === "var") return varOf(args[0]);
    const v = args.map((a) => logic(a, varOf));
    switch (op) {
      case "==": return v[0] === v[1]; case "!=": return v[0] !== v[1]; case "!": return !v[0];
      case "and": return v.every(Boolean); case "or": return v.some(Boolean);
      case "if": return v[0] ? v[1] : v[2]; case "in": return (v[1] || []).includes(v[0]);
      case ">": return v[0] > v[1]; case "<": return v[0] < v[1]; case ">=": return v[0] >= v[1]; case "<=": return v[0] <= v[1];
      default: throw new Error("조건식 연산자를 모른다: " + op);
    }
  };
  const results = cards.map((c) => {
    const conditions = {};
    for (const cond of c.conditions || []) {
      if (cond.expr) { try { conditions[cond.id] = {text: cond.text, result: !!logic(cond.expr)}; } catch (e) { conditions[cond.id] = {text: cond.text, result: null, error: e.message}; } }
      else conditions[cond.id] = {text: cond.text, result: null};
    }
    const byId = Object.fromEntries((c.conditions || []).map((x) => [x.id, x]));
    const onTargets = (f, paths, entry) => {            // judge.py 의 judge_on_targets
      const kind = f.target, comps = compsOfKind(kind);
      entry.target = kind; let required = comps;
      if (f.required === "conditional") {
        const expr = byId[f.condition]?.expr;
        entry.condition = f.condition; entry.condition_evaluated = expr !== undefined && expr !== null;
        if (entry.condition_evaluated) {
          const vals = comps.map((x) => { try { return [x, !!logic(expr, (k) => (profile[k]?.cdx || []).some((p) => onComp(x, p)))]; } catch (e) { return [x, null]; } });
          entry.condition_on = Object.fromEntries(vals.map(([x, v]) => [lab(x), v]));
          required = vals.filter(([, v]) => v !== false).map(([x]) => x);
          if (!required.length) return {...entry, status: "not_required", paths, reason: `조건 ${f.condition} 이 참인 ${KIND_KO[kind]} 구성요소가 없음: ${byId[f.condition]?.text}`};
        }
      }
      if (!paths.length) return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      entry.checked = required.length;
      if (!required.length) return {...entry, status: "missing", paths, found_at: {}, reason: `BOM 에 ${KIND_KO[kind]} 구성요소가 없음`};
      const have = required.filter((x) => paths.some((p) => onComp(x, p))), missing = required.filter((x) => !have.includes(x));
      const found = {}; for (const p of paths) { const refs = have.filter((x) => onComp(x, p)).map(lab).slice(0, 10); if (refs.length) found[p] = refs; }
      const out = {...entry, status: missing.length ? "missing" : "present", paths, found_at: found};
      if (missing.length) Object.assign(out, {missing_on: missing.map(lab).slice(0, 10), missing_count: missing.length, reason: `요구되는 ${KIND_KO[kind]} 구성요소 ${required.length}개 중 ${missing.length}개에 값이 없음`});
      return out;
    };
    const facts = c.facts.map((f) => {
      const paths = profile[f.concept]?.cdx || [];
      const entry = {concept: f.concept, label: label(f.concept), required: f.required};
      if (f.target) return onTargets(f, paths, entry);
      if (f.required === "conditional") {
        const cond = conditions[f.condition] || {};
        entry.condition = f.condition; entry.condition_evaluated = cond.result !== null && cond.result !== undefined;
        if (cond.result === false) return {...entry, status: "not_required", paths, reason: `조건 ${f.condition} 이 거짓이라 요구되지 않음: ${cond.text}`};
      }
      if (!paths.length) return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      const found = {}; for (const p of paths) { const refs = resolve(p); if (refs.length) found[p] = refs.slice(0, 5); }
      return {...entry, status: Object.keys(found).length ? "present" : "missing", paths, found_at: found};
    });
    const checkable = facts.filter((f) => f.status !== "gap" && f.status !== "not_required"), present = checkable.filter((f) => f.status === "present");
    const verdict = !checkable.length ? "검토 필요" : present.length === checkable.length ? "반영" : present.length ? "부분 반영" : "미반영";
    return {card_id: c.card_id, verdict, facts, ...(Object.keys(conditions).length ? {conditions} : {})};
  });
  const summary = Object.fromEntries(VERDICTS.map((v) => [v, results.filter((r) => r.verdict === v).length]));
  return {bom: {bomFormat: bom.bomFormat, specVersion: bom.specVersion, serialNumber: bom.serialNumber, subject: bom.metadata?.component?.name || name}, summary, cards: results};
}

init().catch((err) => { root.innerHTML = `<p class="cv-muted">데이터를 읽지 못했다: ${esc(err.message)}</p>`; });
})();
