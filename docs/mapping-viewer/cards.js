// 규제 카드 화면 (compliance/regulation-cards.md). 카드·추출 비교·판정 세 탭. 데이터는 export_data.py 가 data/cards/ 에 둔 JSON.
if (document.querySelector(".card-viewer")) (() => {
const root = document.querySelector(".card-viewer");
const BASE = root.dataset.base || "data/cards/";
const EXPLORER = root.dataset.explorer || "../field-mapping/";
const REG_NAME = {EUAIA: "EU AI Act", NISTRMF: "NIST AI RMF", ISO42001: "ISO/IEC 42001"};
const VERDICTS = ["반영", "부분 반영", "미반영", "검토 필요", "비적용"];
const $ = (sel) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const regOf = (id) => REG_NAME[id.split("-")[1]] || id.split("-")[1];
const vclass = (v) => "v-" + v.replace(/\s/g, "");
let cards = [], vocab = {}, profile = {}, extraction = {}, judgIndex = [];

async function load(name) { const r = await fetch(BASE + name); if (!r.ok) throw new Error(name); return r.json(); }

async function init() {
  const [c, v, p, e, j] = await Promise.all([load("cards.json"), load("vocabulary.json"), load("profile.json"), load("extraction.json"), load("judgments/index.json")]);
  cards = c; vocab = Object.fromEntries(v.concepts.map((x) => [x.id, x])); judgIndex = j;
  for (const line of p.lines) ((profile[line.card_id] ||= {})[line.concept] ||= []).push(line);
  extraction = Object.fromEntries(e.map((x) => [x.card_id, x]));
  root.querySelectorAll(".cv-tab").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll(".cv-tab").forEach((t) => t.classList.toggle("active", t === b));
    root.querySelectorAll(".cv-panel").forEach((s) => s.classList.toggle("active", s.dataset.panel === b.dataset.tab));
  }));
  initCards(); initExtraction(); initJudgment();
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
function clauseOf(card) { return card.source.clause_id; }
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
function pathCell(cardId, concept) {
  const lines = (profile[cardId] || {})[concept] || [];
  const cdx = [...new Set(lines.map((l) => l.cdx_path).filter(Boolean))];
  const spdx = [...new Set(lines.map((l) => l.spdx_path).filter(Boolean))];
  if (!cdx.length && !spdx.length) return `<span class="cv-chip gap">자리 없음</span>`;
  return [...cdx.map((p) => `<span class="cv-path">${esc(p)}</span>`), ...spdx.map((p) => `<span class="cv-path cv-muted">${esc(p)}</span>`)].join(" ");
}

// ---------- 카드 ----------
function initCards() {
  regSelect($("#cv-reg"), renderCardList);
  $("#cv-search").addEventListener("input", renderCardList);
  renderCardList();
}
function renderCardList() {
  const reg = $("#cv-reg").value, q = $("#cv-search").value.trim().toLowerCase();
  const items = cards.filter((c) => (!reg || c.card_id.startsWith("RC-" + reg + "-")) &&
    (!q || clauseOf(c).toLowerCase().includes(q) || (c.topic || "").toLowerCase().includes(q) || c.facts.some((f) => f.concept.toLowerCase().includes(q) || label(f.concept).includes(q))));
  $("#cv-count").textContent = `${items.length}장`;
  groupedList($("#cv-card-list"), items, (c) => `<span class="cv-id">${esc(clauseOf(c))}</span><span class="cv-sub">${esc(c.topic || "")} · fact ${c.facts.length}</span>`, renderCard);
}
function renderCard(c) {
  const d = $("#cv-card-detail");
  const text = c.source.excerpt_en, ko = c.source.excerpt;
  const spans = c.facts.map((f, i) => ({text: f.highlight_en || f.gap_highlight_en, cls: f.gap_highlight_en ? "gap" : "", idx: i, title: `${f.concept} · ${label(f.concept)}`}));
  const cond = (c.conditions || []).map((x) => `<li><code>${esc(x.id)}</code> ${esc(x.text)}</li>`).join("");
  const exc = (c.exceptions || []).map((x) => `<li>${esc(x.text)}</li>`).join("");
  const evd = (c.evidence || []).map((x) => `<span class="cv-chip">${esc(x.label || x.concept)}</span>`).join(" ");
  d.innerHTML = `
    <h3>${esc(c.title)}</h3>
    <div class="cv-meta">
      <span class="cv-chip">${esc(c.regulation.title)}</span>
      <span class="cv-chip">${esc(c.applicability?.text || "")}</span>
      <span class="cv-chip">${esc(c.obligation.actor)} · ${esc(c.obligation.action)} · ${esc(c.obligation.object)}</span>
      <span class="cv-chip">${esc(c.status)} · 신뢰도 ${c.confidence}</span>
    </div>
    ${text ? `<div class="cv-text">${highlightText(text, spans)}${ko ? `<span class="cv-trans">${esc(ko)}</span>` : ""}</div>`
           : `<p class="cv-note">이 규제의 원문과 구절은 저작권 때문에 싣지 않는다. 개념과 호만 보인다.</p>`}
    <h4>Facts (${c.facts.length})</h4>
    <table class="cv-facts"><thead><tr><th>개념</th><th>호</th><th>요구</th><th>BOM 자리 (CycloneDX · SPDX)</th></tr></thead><tbody>
    ${c.facts.map((f, i) => `<tr data-idx="${i}"><td><code>${esc(f.concept)}</code><br>${esc(label(f.concept))}</td><td>${esc(f.clause || "")}</td>
      <td>${esc(f.required)}${f.condition ? ` <code>${esc(f.condition)}</code>` : ""}</td><td>${pathCell(c.card_id, f.concept)}</td></tr>`).join("")}
    </tbody></table>
    ${cond ? `<h4>조건</h4><ul>${cond}</ul>` : ""}${exc ? `<h4>예외</h4><ul>${exc}</ul>` : ""}${evd ? `<h4>증빙</h4><div class="cv-meta">${evd}</div>` : ""}
    ${c.notes ? `<p class="cv-note">${esc(c.notes)}</p>` : ""}
    <p class="cv-note">BOM 자리의 필드 정의와 두 형식의 대응은 <a href="${EXPLORER}">필드 탐색기</a>에서 본다.</p>`;
  wireMarks(d);
}

// ---------- 추출 비교 ----------
function initExtraction() { regSelect($("#cv-ex-reg"), renderExList); renderExList(); }
function renderExList() {
  const reg = $("#cv-ex-reg").value;
  const items = cards.filter((c) => !reg || c.card_id.startsWith("RC-" + reg + "-"));
  let hit = 0, gold = 0, pred = 0;
  for (const c of items) { const e = extraction[c.card_id]; if (!e) continue; gold += new Set(c.facts.map((f) => f.concept)).size; pred += e.facts.length; hit += e.facts.filter((f) => f.result === "hit").length; }
  $("#cv-ex-summary").textContent = `${items.length}장 · 재현율 ${(hit / Math.max(gold, 1)).toFixed(2)} · 정밀도 ${(hit / Math.max(pred, 1)).toFixed(2)} (자기 카드의 구절은 용어집에서 뺀 조건)`;
  groupedList($("#cv-ex-list"), items, (c) => { const e = extraction[c.card_id] || {facts: [], missed: []}; const h = e.facts.filter((f) => f.result === "hit").length;
    return `<span class="cv-id">${esc(clauseOf(c))}</span><span class="cv-sub">맞춤 ${h}/${c.facts.length} · 더 냄 ${e.facts.length - h}</span>`; }, renderEx);
}
function renderEx(c) {
  const d = $("#cv-ex-detail"), e = extraction[c.card_id];
  if (!e) { d.innerHTML = `<p class="cv-muted">비교 데이터가 없다.</p>`; return; }
  const text = c.source.excerpt_en;
  const spans = e.facts.map((f, i) => ({text: f.span, cls: f.result === "hit" ? "" : "extra", idx: i, title: `${f.concept} (${f.result})`}));
  const goldOf = Object.fromEntries(c.facts.map((f) => [f.concept, f]));
  d.innerHTML = `
    <h3>${esc(c.title)}</h3>
    <div class="cv-meta">
      <span class="cv-chip">추출 신뢰도 ${e.confidence} · ${esc(e.status)}</span>
      <span class="cv-chip">주체 ${esc(e.actor)}${e.actor === e.gold_actor ? "" : ` (카드 ${esc(e.gold_actor)})`}</span>
      <span class="cv-chip">행위 ${esc(e.action)} · 객체 ${esc(e.object)} · 범위 ${esc(e.object_scope)}</span>
    </div>
    ${text ? `<div class="cv-text">${highlightText(text, spans)}</div>` : `<p class="cv-note">원문은 싣지 않는다 (저작권).</p>`}
    <h4>추출기가 낸 개념 (${e.facts.length}) · 놓친 개념 (${e.missed.length})</h4>
    <table class="cv-facts"><thead><tr><th>결과</th><th>개념</th><th>호 (추출 / 카드)</th><th>구절</th></tr></thead><tbody>
    ${e.facts.map((f, i) => `<tr data-idx="${i}"><td><span class="cv-chip ${f.result}">${f.result === "hit" ? "맞춤" : "더 냄"}</span></td>
      <td><code>${esc(f.concept)}</code><br>${esc(label(f.concept))}</td><td>${esc(f.clause || "")} / ${esc(f.gold_clause || "")}</td><td>${esc(f.span || "")}</td></tr>`).join("")}
    ${e.missed.map((k) => `<tr><td><span class="cv-chip miss">놓침</span></td><td><code>${esc(k)}</code><br>${esc(label(k))}</td><td> / ${esc(goldOf[k]?.clause || "")}</td><td>${esc(goldOf[k]?.highlight_en || goldOf[k]?.gap_highlight_en || "")}</td></tr>`).join("")}
    </tbody></table>
    ${e.conditions.length ? `<h4>추출한 조건</h4><ul>${e.conditions.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${e.exceptions.length ? `<h4>추출한 예외</h4><ul>${e.exceptions.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    <p class="cv-note">"더 냄" 은 카드(정답 표)에 없는 개념이다. 원문에 그 말이 있으면 표 쪽을 봐야 할 수도 있다.</p>`;
  wireMarks(d);
}

// ---------- 판정 ----------
let currentRecord = null;
function initJudgment() {
  const sel = $("#cv-bom");
  sel.innerHTML = judgIndex.map((j, i) => `<option value="${i}">${esc(j.subject)} (${esc(j.file)})</option>`).join("") || `<option value="">예제 BOM 없음</option>`;
  sel.addEventListener("change", async () => { const j = judgIndex[+sel.value]; if (j) showRecord(await load("judgments/" + j.file)); });
  $("#cv-verdict-filter").addEventListener("change", renderJudgList);
  $("#cv-bom-file").addEventListener("change", async (ev) => {
    const file = ev.target.files[0]; if (!file) return;
    try { const bom = JSON.parse(await file.text()); showRecord(judgeBom(bom, file.name)); sel.value = ""; }
    catch (err) { $("#cv-judg-summary").innerHTML = `<span class="cv-chip gap">읽을 수 없는 파일: ${esc(err.message)}</span>`; }
  });
  if (judgIndex.length) sel.dispatchEvent(new Event("change"));
}
function showRecord(rec) {
  currentRecord = rec;
  const s = rec.summary, total = rec.cards.length;
  $("#cv-judg-summary").innerHTML = `<div class="cv-stat"><b>${esc(rec.bom.subject || rec.bom.serialNumber || "")}</b>카드 ${total}장 · ${esc(rec.bom.bomFormat)} ${esc(rec.bom.specVersion)}</div>`
    + VERDICTS.map((v) => `<div class="cv-stat"><span class="cv-verdict ${vclass(v)}">${v}</span> <b>${s[v] || 0}</b></div>`).join("")
    + `<div class="cv-bar" style="flex-basis:100%">${VERDICTS.map((v) => `<span class="${vclass(v)}" style="width:${100 * (s[v] || 0) / Math.max(total, 1)}%"></span>`).join("")}</div>`;
  renderJudgList();
}
function renderJudgList() {
  if (!currentRecord) return;
  const want = $("#cv-verdict-filter").value;
  const items = currentRecord.cards.filter((r) => !want || r.verdict === want);
  groupedList($("#cv-judg-list"), items, (r) => { const f = r.facts || []; const p = f.filter((x) => x.status === "present").length, g = f.filter((x) => x.status === "gap").length;
    return `<span class="cv-id">${esc(r.card_id.replace(/^RC-[A-Z0-9]+-/, ""))}</span><span class="cv-sub"><span class="cv-verdict ${vclass(r.verdict)}">${r.verdict}</span> ${p}/${f.length - g}${g ? ` · 자리 없음 ${g}` : ""}</span>`; }, renderJudg);
}
function renderJudg(r) {
  const d = $("#cv-judg-detail"), card = cards.find((c) => c.card_id === r.card_id);
  d.innerHTML = `
    <h3>${esc(card?.title || r.card_id)} <span class="cv-verdict ${vclass(r.verdict)}">${r.verdict}</span></h3>
    ${r.reason ? `<p class="cv-note">${esc(r.reason)}</p>` : ""}
    <table class="cv-facts"><thead><tr><th>상태</th><th>개념</th><th>BOM 경로</th><th>값이 있는 구성요소</th></tr></thead><tbody>
    ${(r.facts || []).map((f) => `<tr><td><span class="cv-chip ${f.status}">${{present: "있음", missing: "비어 있음", gap: "자리 없음"}[f.status] || f.status}</span>
      ${f.condition_evaluated === false ? `<br><span class="cv-muted">조건 미평가</span>` : ""}</td>
      <td><code>${esc(f.concept)}</code><br>${esc(f.label || label(f.concept))}</td>
      <td>${(f.paths || []).map((p) => `<span class="cv-path">${esc(p)}</span>`).join(" ") || `<span class="cv-muted">${esc(f.reason || "")}</span>`}</td>
      <td>${Object.values(f.found_at || {}).flat().map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>`).join("")}
    </tbody></table>
    <p class="cv-note">"비어 있음" 의 경로가 보완 위치다. 판정은 경로 존재만 본다. 조건식과 증빙 검사는 아직 없다.</p>`;
}

// 브라우저 안 판정 (cards/judge/judge.py 와 같은 규칙). 검사 대상은 metadata.component 와 모델·데이터셋 구성요소.
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
  const resolve = (path) => {
    if (path.startsWith("component.externalReferences.url (type:")) { const t = path.split("type:")[1].replace(/\)$/, ""); return comps.filter((c) => (c.externalReferences || []).some((e) => e.type === t && e.url)).map(lab); }
    const [rootKey, ...rest] = path.split(".");
    if (rootKey === "component") return comps.filter((c) => get(c, rest).length).map(lab);
    if (rootKey === "componentData") return comps.filter((c) => c.type === "data" && get(c.data, rest).length).map(lab);
    if (rootKey === "releaseNotes") return comps.filter((c) => get(c, ["releaseNotes", ...rest]).length).map(lab);
    if (["components", "services", "dependencies", "formulation", "declarations", "definitions", "metadata", "compositions"].includes(rootKey)) return get(bom, [rootKey, ...rest]).length ? ["$"] : [];
    return [];
  };
  const results = cards.map((c) => {
    const facts = c.facts.map((f) => {
      const lines = ((profile[c.card_id] || {})[f.concept] || []).filter((l) => l.cdx_path);
      const entry = {concept: f.concept, label: label(f.concept), required: f.required};
      if (f.required === "conditional") { entry.condition = f.condition; entry.condition_evaluated = false; }
      if (!lines.length) return {...entry, status: "gap", paths: [], reason: "프로파일에 경로 없음 (스키마에 자리 없음)"};
      const found = {}; for (const l of lines) { const refs = resolve(l.cdx_path); if (refs.length) found[l.cdx_path] = refs.slice(0, 5); }
      return {...entry, status: Object.keys(found).length ? "present" : "missing", paths: lines.map((l) => l.cdx_path), found_at: found};
    });
    const checkable = facts.filter((f) => f.status !== "gap"), present = checkable.filter((f) => f.status === "present");
    const verdict = !checkable.length ? "검토 필요" : present.length === checkable.length ? "반영" : present.length ? "부분 반영" : "미반영";
    return {card_id: c.card_id, verdict, facts};
  });
  const summary = Object.fromEntries(VERDICTS.map((v) => [v, results.filter((r) => r.verdict === v).length]));
  return {bom: {bomFormat: bom.bomFormat, specVersion: bom.specVersion, serialNumber: bom.serialNumber, subject: bom.metadata?.component?.name || name}, summary, cards: results};
}

init().catch((err) => { root.innerHTML = `<p class="cv-muted">데이터를 읽지 못했다: ${esc(err.message)}</p>`; });
})();
