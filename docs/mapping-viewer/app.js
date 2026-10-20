// 필드 매핑 뷰어. docs/field-mapping.md 에 직접 넣은 HTML 을 채운다. 다른 페이지에서는 (뷰어 요소가 없으니) 아무것도 하지 않는다.
if (document.querySelector(".mapping-viewer")) (() => {
// CycloneDX <-> SPDX 필드 레퍼런스 뷰어.
// 데이터는 build 스텝 없이 data/*.json 을 그대로 fetch 해서 쓴다 (ai-bom/data 의 복사본).
//
// 데이터 소스 역할 분담:
//   aibom_v0.6_cyclonedx.json : CycloneDX 1.7 전체(공용 타입 포함) + v0.6 추가 필드(added, origin·reference 는 근거 조항)
//   aibom_v0.6_spdx.json      : SPDX 3.0.1 전체 + v0.6 추가 필드(added, path 는 대응하는 CycloneDX 경로)
//   aibom_v0.6_spdx_mapping.json : 두 형식의 대응 (조인 테이블). 1.7 매핑에 v0.6 추가 필드를 넣은 표로, ai-bom 이 만든다
//   aibom_v0.6_requirement_field_mapping.json : 규제 요구사항이 어느 v0.6 필드로 충족되는지 (엑셀 「요구사항 매핑」 시트와 같은 표).
//                                cdx_ref(CDX 경로)·spdx_ref("Class.property") 가 조인 키, version 은 그 필드가 1.7 의 것인지 v0.6 의 것인지
//   aibom_v0.6_properties.json : 추가 필드를 --spec 1.7 로 낼 때의 properties 키 (ai-bom 의 정의서와 같은 출처)

const BASE = document.querySelector(".mapping-viewer").dataset.base || "data/";   // 페이지 기준 상대 경로
const CDX_URL = BASE + "aibom_v0.6_cyclonedx.json";
const SPDX_URL = BASE + "aibom_v0.6_spdx.json";
const MAPPING_URL = BASE + "aibom_v0.6_spdx_mapping.json";
const REQ_URL = BASE + "aibom_v0.6_requirement_field_mapping.json";
const PROPS_URL = BASE + "aibom_v0.6_properties.json";
// aibom-cli 출력에서 자리마다 값을 채우는 도구. 허구의 픽스처를 실제로 스캔해 값 하나하나의 출처를 따라간 결과다
// (tests/test_fields.py 가 만들고 검사한다). 자리 경로는 아래 renderCdxNode 의 sitePath 와 같은 모양이다.
const SOURCES_URL = BASE + "aibom_cli_sources.json";
const TOOL_ORDER = ["syft", "cdxgen", "OWASP aibom-generator", "aibom-cli"];
const TOOL_LABEL = { "syft": "syft", "cdxgen": "cdxgen", "OWASP aibom-generator": "OWASP", "aibom-cli": "aibom-cli" };

const PROFILE_ORDER = ["Core", "Software", "AI", "Dataset", "Security",
  "Expanded Licensing", "Simple Licensing", "Build", "Extension"];

const cdxTreeEl = document.getElementById("cdx-tree");
const spdxTreeEl = document.getElementById("spdx-tree");
const searchEl = document.getElementById("search");
const detailPanel = document.getElementById("detail-panel");
const detailBody = document.getElementById("detail-body");
const detailToggle = document.getElementById("detail-toggle");

// 토글 버튼 자체가 패널이 열려있는지를 항상 반영한다(눌린 상태처럼) — 버튼과 패널이
// 하나의 스위치라는 걸 시각적으로 묶어준다. 닫기(X)/토글 버튼/필드 클릭으로 자동 열림,
// 이 세 경로 전부 이 함수 하나로만 상태를 바꾼다.
function setDetailPanelOpen(open) {
  detailPanel.classList.toggle("hidden", !open);
  detailToggle.classList.toggle("active", open);
  if (open && !detailBody.childElementCount) {                 // 아직 아무 필드도 안 눌렀을 때
    detailBody.innerHTML = `<div class="detail-placeholder">왼쪽 트리에서 필드를 누르면 여기에 설명과 다른 형식의 대응 필드,
      properties 키, 규제 요구사항이 나온다.</div>`;
  }
}
document.getElementById("detail-close").addEventListener("click", () => setDetailPanelOpen(false));
detailToggle.addEventListener("click", () => setDetailPanelOpen(detailPanel.classList.contains("hidden")));

let mappingByPath = new Map();          // cdx path -> aibom_v0.6_spdx_mapping.json row
let spdxToCdx = new Map();              // "class::property" -> [{cdxPath, hopIndex, mismatch}]
let cdxRowByPath = new Map();           // cdx path -> cyclonedx(_refs).json row (title/type/description/...)
let spdxRowByKey = new Map();           // "class::property" -> spdx.json row (summary/type/...)
let cdxEnumIndex = new Map();           // "cdxPath::value" -> [{cls, value}]        (enum 값 단위 대응)
let spdxEnumIndex = new Map();          // "cls::value" -> [{cdxPath, value}]
let reqByCdxPath = new Map();           // cdx path -> [requirement row, ...]
let reqBySpdxKey = new Map();           // "class::property" -> [requirement row, ...]
const spdxNodeIndex = new Map();        // "class::property" -> <li>  (SPDX 트리는 클래스당 1곳)
const cdxNodeIndex = new Map();         // cdx path -> [<li>, ...]     (그래프트로 여러 곳에 나타날 수 있음)
const cdxChipIndex = new Map();         // "cdxPath::value" -> [<span class=enum-chip>, ...]
const spdxChipIndex = new Map();        // "cls::value" -> [<span class=enum-chip>, ...]
let currentHighlighted = [];
let propsByPath = new Map();            // CycloneDX 경로 -> [properties 키 행, ...] (v0.6 추가 필드만)
let siteAlias = new Map();              // 접붙인 자리의 경로(…inputs.maxSize) -> 공용 타입 행(inputOutputMLParameters.maxSize)
let representativeLis = new Set();      // 경로마다 가장 얕은 자리의 <li> 하나 ("추가 필드만" 필터가 남기는 자리)
let sourcesBySite = new Map();          // 자리 경로 -> [{tool, kinds}] (aibom-cli 출력에서 그 자리의 값을 채우는 도구)
const addedOnlyEl = document.getElementById("added-only");
const generatedOnlyEl = document.getElementById("generated-only");

init();

async function init() {
  const [cdxRows, spdxRows, mappingRowsRaw, reqRows, propRows, sourceRows] = await Promise.all([
    fetch(CDX_URL).then(r => r.json()),
    fetch(SPDX_URL).then(r => r.json()),
    fetch(MAPPING_URL).then(r => r.json()),
    fetch(REQ_URL).then(r => r.json()),
    fetch(PROPS_URL).then(r => r.json()),
    fetch(SOURCES_URL).then(r => (r.ok ? r.json() : [])).catch(() => []),
  ]);

  for (const r of sourceRows) sourcesBySite.set(r.site, r.sources);

  // 그릇(hyperparameters)에는 그 안의 키 전부가, 칸(hyperparameters.name)에는 제 키 하나가 붙는다
  const addProp = (path, p) => { if (!propsByPath.has(path)) propsByPath.set(path, []); propsByPath.get(path).push(p); };
  for (const p of propRows) {
    addProp(p.path, p);
    if (p.child) addProp(`${p.path}.${p.child}`, p);
  }
  spdxRowByKey = new Map(spdxRows.map(r => [keyFor(r.class, r.property), r]));
  ({ reqByCdxPath, reqBySpdxKey } = buildRequirementIndex(reqRows));

  // 형식 간 대응. 자리마다 대상이 다른 공용 타입 필드는 자리별 행으로 나눈다.
  const mapping = new Map(siteMappingRows(mappingRowsRaw).map(r => [r.path, r]));
  const mappingRows = [...mapping.values()];
  mappingByPath = mapping;
  spdxToCdx = buildReverseIndex(mappingRows);
  cdxRowByPath = new Map(cdxRows.map(r => [r.path, r]));
  // 공용 타입의 필드가 접붙인 자리마다 다른 SPDX 속성에 대응하면 (inputs 와 outputs 의 maxSize), 그 자리의 경로로 찾는다
  for (const r of mappingRows) if (r.defPath && cdxRowByPath.has(r.defPath)) siteAlias.set(r.path, cdxRowByPath.get(r.defPath));
  ({ cdxEnumIndex, spdxEnumIndex } = buildEnumIndex(mappingRows));

  spdxTreeEl.appendChild(renderChildren(buildSpdxTree(spdxRows).children, renderSpdxProfileNode, 0));
  cdxTreeEl.appendChild(renderChildren(buildCdxTree(cdxRows).children, renderCdxNode, 0, new Set()));
  countNewFields(cdxRows);
  for (const path of cdxNodeIndex.keys()) representativeLis.add(shallowestLi(path));

  buildFilterIndex();
  buildSuggestIndex();
  searchEl.addEventListener("input", debounce(() => { applyFilter(); showSuggestions(); }, 150));
  searchEl.addEventListener("keydown", onSearchKey);
  searchEl.addEventListener("blur", () => setTimeout(hideSuggestions, 150));
  if (addedOnlyEl) addedOnlyEl.addEventListener("change", applyFilter);
  if (generatedOnlyEl) generatedOnlyEl.addEventListener("change", applyFilter);
  initResizers();
  syncToolbarHeight();
  fitTrees();
  window.addEventListener("resize", () => { syncToolbarHeight(); scheduleFit(); });
  window.addEventListener("scroll", scheduleFit, { passive: true });
  for (const tree of document.querySelectorAll(".mapping-viewer .tree")) tree.addEventListener("wheel", wheelBeforeDock, { passive: false });
  if (document.fonts) document.fonts.ready.then(fitTrees);
}

/** 트리 머리줄과 상세 패널이 붙는 자리는 검색 줄 바로 아래다. 검색 줄의 실제 높이를 CSS 변수로 넘긴다 (글자 크기·줄바꿈에 따라 달라진다). */
function syncToolbarHeight() {
  const viewer = document.querySelector(".mapping-viewer");
  const topbar = document.getElementById("topbar");
  if (viewer && topbar) viewer.style.setProperty("--toolbar-h", `${topbar.offsetHeight}px`);
}

/** 뷰어 윗선이 상단 바 밑선보다 얼마나 아래 있는지 (px). 0 이하면 뷰어가 상단 바에 붙은 것 */
function dockDistance() {
  const viewer = document.querySelector(".mapping-viewer");
  const header = document.querySelector(".md-header");
  return viewer.getBoundingClientRect().top - (header ? header.getBoundingClientRect().bottom : 0);
}

/** 트리 높이를 화면에 맞춘다: 뷰어가 상단 바에 붙었을 때 트리 윗선부터, 바닥글이 다 보이는 화면 바닥까지.
 *  스크롤과 무관한 고정 높이라 페이지는 꼭 소개 글 높이만큼만 움직이고, 붙는 순간 페이지 끝(바닥글 밑선)이
 *  화면 바닥에 온다. 그 뒤로는 두 트리와 상세 패널이 각자 스크롤한다.
 *  (스크롤마다 트리를 다시 재면 한 프레임 늦게 자라서 바닥글이 올라왔다 내려가는 떨림이 생긴다) */
function fitTrees() {
  const viewer = document.querySelector(".mapping-viewer");
  const tree = document.getElementById("cdx-tree");
  if (!viewer || !tree) return;
  const dist = dockDistance();
  const rect = tree.getBoundingClientRect();
  const top = rect.top - dist;   // 붙었을 때의 트리 윗선 (지금 스크롤 위치와 무관)
  // 트리 밑에 남은 페이지(여백과 바닥글). 트리 높이와 무관하므로 이만큼 빼면 붙었을 때 페이지 끝이 꼭 화면 바닥에 온다
  const below = document.documentElement.scrollHeight - (rect.bottom + window.scrollY);
  const h = Math.max(320, Math.round(window.innerHeight - top - below));
  viewer.style.setProperty("--tree-h", `${h}px`);
  // 붙기 전엔 트리 위에서 휠을 굴려도 페이지가 내려가고, 붙은 뒤에야 트리가 스크롤된다.
  // 그래야 한 번의 스크롤로 소개 글을 지나 트리 속으로 이어진다.
  viewer.classList.toggle("docked", dist <= 1);
}

/** 붙기 전에 트리 위에서 아래로 굴린 휠: 붙을 만큼만 페이지를 내리고 나머지로 트리를 굴린다.
 *  브라우저에 맡기면 한 칸(100px 남짓)씩 움직여서 검색 줄이 상단 바 밑으로 들어가 버린다. */
function wheelBeforeDock(e) {
  const dist = dockDistance();
  if (dist <= 1 || e.deltaY <= 0 || e.ctrlKey) return;
  const tree = e.currentTarget;
  const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * tree.clientHeight : e.deltaY;
  e.preventDefault();
  const pageStep = Math.min(dy, dist);
  window.scrollBy(0, pageStep);
  if (dy > pageStep) tree.scrollTop += dy - pageStep;
}

let fitPending = false;
function scheduleFit() {
  if (fitPending) return;
  fitPending = true;
  requestAnimationFrame(() => { fitPending = false; fitTrees(); });
}

/** 공용 타입의 필드가 놓인 자리마다 다른 SPDX 속성에 대응하면 (inputOutputMLParameters.maxSize 는 inputs 자리에서
 *  aibom_inputMaxSize, outputs 자리에서 aibom_outputMaxSize. format 도 aibom_inputs · aibom_outputs 로 갈린다) 매핑표는
 *  대안(alt)마다 자리(site)를 단다. 그 행을 자리별 행으로 바꾼다 — 경로는 접붙인 자리의 것, defPath 는 공용 타입 안의 경로.
 *  대안 뒤에 딸린 체인 홉은 그 자리의 체인이 된다. 나머지 행은 그대로 둔다. */
function siteMappingRows(rows) {
  const out = [];
  for (const row of rows) {
    const multi = row.spdx_multi || [];
    if (!multi.some(t => t.site)) { out.push(row); continue; }
    // 자리마다 대안 하나와, 그 뒤에 딸린 체인 홉(depth 가 있는 것 — maxSize 의 DictionaryEntry.value)이 온다
    const groups = [];
    for (const t of multi) {
      if (t.site) groups.push([t]);
      else if (groups.length && t.depth) groups[groups.length - 1].push(t);
    }
    for (const [t, ...hops] of groups) {
      const site = { ...row, path: t.site + row.path.slice(row.path.indexOf(".")), defPath: row.path,
        spdx: `${t.profile}::${t.class}.${t.property}${hops.map(h => "." + h.property).join("")}` };
      if (hops.length) Object.assign(site, { spdx_multi: [t, ...hops], spdx_multi_kind: "chain",
        spdx_profile: "", spdx_kind: "", spdx_class: "", spdx_property: "", spdx_type: "" });
      else Object.assign(site, { spdx_multi: undefined, spdx_multi_kind: undefined, spdx_profile: t.profile,
        spdx_kind: t.kind, spdx_class: t.class, spdx_property: t.property, spdx_type: t.type });
      out.push(site);
    }
  }
  return out;
}

/** 접붙인 자리의 경로(metadata.component.modelCard…, components.modelCard…)가 공용 타입 안의 경로(component.modelCard…)와
 *  같은 자리인가. 공용 타입은 트리에 제 이름으로 서지 않고 쓰이는 자리마다 다른 이름(components, metadata.component) 밑에
 *  붙으므로, 타입 이름(첫 마디)을 뗀 나머지가 자리 경로의 끝과 같으면 같은 자리로 본다. */
function atSite(sitePath, path) {
  if (sitePath === path) return true;
  const head = path.slice(0, path.indexOf("."));
  const def = cdxRowByPath.get(head);
  const tail = def && def.parent === "(공용 타입)" ? path.slice(head.length + 1) : path;
  return sitePath === tail || sitePath.endsWith("." + tail);
}

/** properties 키는 접붙인 자리의 경로(component.modelCard.modelParameters.inputs.format)에 걸려 있다. 공용 타입 행의 경로
 *  (inputOutputMLParameters.format)로는 안 잡히므로 자리 경로로 찾는다. */
function propsFor(sitePath, defPath) {
  if (propsByPath.has(defPath)) return propsByPath.get(defPath);
  for (const [k, v] of propsByPath) if (atSite(sitePath, k)) return v;
  return [];
}

/** 접붙인 자리가 자리별 대응을 가진 경로(…modelParameters.inputs.maxSize)의 자리면 그 경로 */
function siteKeyFor(sitePath) {
  for (const a of siteAlias.keys()) if (atSite(sitePath, a)) return a;
  return null;
}

/** 공용 타입은 트리 여러 자리에 접붙여진다. 그중 가장 얕은 한 곳이 그 필드의 대표 자리다. */
function shallowestLi(path) {
  let best = null, bestDepth = Infinity;
  for (const li of cdxNodeIndex.get(path) || []) {
    let d = 0;
    for (let a = li.parentElement; a && a !== cdxTreeEl; a = a.parentElement) if (a.tagName === "LI") d++;
    if (d < bestDepth) { bestDepth = d; best = li; }
  }
  return best;
}

/* 접힌 가지에 "이 아래 새 필드가 몇 개"를 새겨 둔다. 트리는 전부 접힌 채로 열리므로, 이게
   없으면 새 필드가 어느 가지에 꽂혔는지 다 펼쳐 보기 전에는 안 보인다.

   숨기지 않는 것이 요점이다 — 예전의 「새 필드만」은 나머지를 display:none 으로 지워서,
   SPDX 쪽 속성을 눌렀을 때 그 대응 CDX 필드가 1.7 필드면 강조가 안 보이는 노드에 걸려
   아무 일도 안 일어난 것처럼 보였다. 역방향 조회가 필터에 막히면 안 된다.

   **자리를 센다.** 공용 타입은 여러 곳에 접붙여지는데, 접붙여진 자리를 다 세면 거의 모든 가지가
   42 가 되어(component 는 metadata·vulnerabilities·annotations·formulation·declarations 밑에서
   전부 닿는다) 길잡이 구실을 못 한다. 그래서 세는 자리는 **그 필드의 가장 얕은 깊이의 자리들**
   로 한정한다 — 하나만 고르면 같은 깊이에 나란히 붙는 자리 중 하나가 빈손이 되기 때문이다
   (inputOutputMLParameters 는 modelParameters 아래 inputs 와 outputs 두 곳에 같은 깊이로 붙는다).

   그리고 **잎만 센다.** 새 필드 마흔둘 중 다섯(hyperparameters·knownBias·knownGaps·sensors·
   statistics)은 컨테이너라 그 자신은 값을 담지 않는다. 컨테이너까지 세면 hyperparameters 처럼
   NEW 와 +2 가 같이 붙은 자리가 셋처럼 읽히고, 「값을 담을 자리」와 「자리를 묶는 자리」가 한
   숫자에 섞인다. 컨테이너가 새것이라는 사실은 그 행의 NEW 배지가 따로 든다.

   그래서 배지가 말하는 것은 **이 아래 값을 담을 수 있는 새 자리 수**이고, 가지의 수는 자식들의
   수를 더한 것과 같다. 루트는 39 다 — 잎 서른일곱에 inputOutputMLParameters 의 둘이 inputs·
   outputs 두 자리에서 각각 세어져 둘이 더 붙는다. */
function countNewFields(rows) {
  const counts = new Map();   // 조상 <li> -> 그 아래 새 필드가 나타나는 자리 수
  for (const r of rows) {
    if (!r.added) continue;
    const lis = cdxNodeIndex.get(r.path) || [];
    // 컨테이너는 값을 담지 않으므로 세지 않는다 — 트리에 자식이 달렸으면 컨테이너다.
    if (lis.length && lis[0].querySelector(":scope > ul.tree-list")) continue;
    const depths = lis.map(li => {
      let d = 0;
      for (let a = li.parentElement; a && a !== cdxTreeEl; a = a.parentElement) if (a.tagName === "LI") d++;
      return d;
    });
    const min = Math.min(...depths);
    lis.forEach((li, i) => {
      if (depths[i] !== min) return;
      // 자기 자신은 세지 않는다 — 그 행엔 이미 NEW 배지가 있다. 조상만 올라가며 센다.
      for (let n = li.parentElement; n && n !== cdxTreeEl; n = n.parentElement) {
        if (n.tagName === "LI") counts.set(n, (counts.get(n) || 0) + 1);
      }
    });
  }
  for (const [li, n] of counts) {
    const div = li.querySelector(":scope > .node-row");
    const badge = document.createElement("span");
    badge.className = "new-count";
    badge.textContent = `+${n}`;
    badge.title = `이 가지 아래 v0.6 추가 필드가 나타나는 자리 ${n}곳`;
    appendToRow(div, badge);
  }
}

/* enum-chips 는 flex-basis:100% 라 자기 앞에서 무조건 줄바꿈한다 — 배지를 그냥 맨 뒤에
   붙이면 칩들 아래 줄에 뚝 떨어져 보인다. 있으면 칩 앞(라벨과 같은 첫 줄)에 끼워 넣는다. */
function appendToRow(div, el) {
  const chips = div.querySelector(":scope > .enum-chips");
  if (chips) chips.before(el); else div.appendChild(el);
}

// ── 좌우 폭 드래그로 조절 ────────────────────────────────────────────────
// data-resize="cdx-pane" 손잡이는 왼쪽(cdx-pane) 폭을 직접 조절한다.
// data-resize="detail-panel" 손잡이(data-invert)는 오른쪽(detail-panel) 폭을
// 반대 방향으로 조절한다 — 핸들 기준 오른쪽에 있는 패널이라 마우스가 오른쪽으로
// 갈수록 그 패널은 좁아져야 하기 때문. 가운데 spdx-pane은 flex:1이라 남는 공간을
// 알아서 채우므로 따로 안 건드려도 된다.
function initResizers() {
  for (const handle of document.querySelectorAll(".resizer")) {
    const target = document.getElementById(handle.dataset.resize);
    const invert = handle.dataset.invert === "1";
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = target.getBoundingClientRect().width;
      handle.classList.add("dragging");
      target.classList.add("no-transition"); // 드래그 중엔 열림/닫힘용 트랜지션이 끼면 안 밀린다
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      function onMove(ev) {
        const delta = ev.clientX - startX;
        const newWidth = startWidth + (invert ? -delta : delta);
        target.style.flex = `0 0 ${Math.max(newWidth, 0)}px`;
      }
      function onUp() {
        handle.classList.remove("dragging");
        target.classList.remove("no-transition");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }
}

// ── 매핑 조인 헬퍼 ──────────────────────────────────────────────────────
function getTargets(row) {
  if (!row) return [];
  if (row.spdx_multi && row.spdx_multi.length > 1) {
    // chain(순차 경로)은 전체가 하나의 후보라 1,2,3...으로 쭉 이어서 센다.
    // alt(서로 독립된 대안)는 후보가 바뀔 때마다 번호를 1부터 다시 세고, 후보마다
    // 다른 색을 쓴다 — "depth"가 없는 hop이 새 후보의 시작(그 후보의 대표 매핑),
    // "depth"가 있는 hop은 그 후보의 뒤이은 체인 구간(예: alt 뒤에 공통으로 이어지는
    // Vocabulary hop)이라 같은 후보로 취급한다.
    const isChain = row.spdx_multi_kind === "chain";
    let candidateIndex = -1;
    let hopIndex = 0;
    // 타입 어긋남은 행 단위(CDX 필드 대 그 대응)로 적히는 경우가 대부분이고(서른 행 중
    // 스물아홉), hop 에 적히는 건 한 행뿐이다. hop 만 읽으면 스무 행이 조용히 사라지므로,
    // 행 단위 표시는 각 후보의 **첫 단계**(그 후보의 대표 대응)에 붙인다.
    const rowMismatch = row.type_mismatch === "Y"
      && !row.spdx_multi.some(h => h.type_mismatch === "Y");
    return row.spdx_multi.map((hop, i) => {
      if (isChain) {
        hopIndex = i + 1;
        candidateIndex = 0;
      } else if (!("depth" in hop)) {
        candidateIndex++;
        hopIndex = 1;
      } else {
        hopIndex++;
      }
      return {
        profile: hop.profile, cls: hop.class, property: hop.property, kind: hop.kind,
        type: hop.type, hopIndex, candidateIndex,
        mismatch: hop.type_mismatch === "Y" || (rowMismatch && hopIndex === 1),
      };
    });
  }
  if (row.spdx_class && row.spdx_class !== "-" && row.spdx_class !== "") {
    return [{
      profile: row.spdx_profile, cls: row.spdx_class, property: row.spdx_property,
      type: row.spdx_type, hopIndex: 1, candidateIndex: 0, mismatch: row.type_mismatch === "Y",
    }];
  }
  return [];
}

function keyFor(cls, property) {
  return `${cls}::${property || ""}`;
}

function buildReverseIndex(mappingRows) {
  const idx = new Map();
  for (const row of mappingRows) {
    // parent === "" 인 행은 진짜 CDX 필드가 아니라 "SPDX엔 있지만 CDX엔 대응 없음"을
    // 기록해두는 gap 행이다(path가 CDX 경로가 아니라 그 SPDX class.property 자기 자신
    // 문자열 — 예: "Package.software_contentIdentifier"). 이걸 걸러내지 않으면
    // 매핑 안 된 SPDX 속성을 클릭해도 "자기 자신"이 CDX 매칭인 것처럼 잘못 뜬다.
    if (row.parent === "") continue;
    for (const t of getTargets(row)) {
      const key = keyFor(t.cls, t.property);
      if (!idx.has(key)) idx.set(key, []);
      idx.get(key).push({ cdxPath: row.path, hopIndex: t.hopIndex, candidateIndex: t.candidateIndex, mismatch: t.mismatch });
    }
  }
  return idx;
}

// 요구사항 역인덱스 — 요구사항 매핑의 한 행 = (요구사항, 그 요구사항을 충족하는 필드) 한 쌍이다. 필드는 v0.6 판이라
// 1.7 에 자리가 없던 요구사항도 v0.6 이 더한 필드로 걸려 있다. cdx_ref/spdx_ref가 비어 있는 행은 그 축에 대응 필드가
// 없다는 뜻(격차)이라 인덱스에 넣지 않는다.
//
// spdx_ref는 "AIPackage.ai_metric.key"처럼 체인 끝까지 적힌 경우가 있는데, SPDX 트리 노드는
// "클래스::프로퍼티" 두 단계뿐이라 앞 두 마디로 잘라 맞춘다. 마디가 하나뿐이면(예:
// "DatasetPackage") 클래스 노드 자신을 가리킨다.
function buildRequirementIndex(reqRows) {
  const byCdx = new Map();
  const bySpdx = new Map();
  const push = (map, key, row) => {
    if (!map.has(key)) map.set(key, []);
    const list = map.get(key);
    if (!list.some(r => r.row_key === row.row_key)) list.push(row);  // 같은 요구사항이 같은 필드에 두 번 걸리지 않게
  };
  for (const row of reqRows) {
    if (row.cdx_ref) push(byCdx, row.cdx_ref, row);
    if (row.spdx_ref) {
      const parts = row.spdx_ref.split(".");
      push(bySpdx, keyFor(parts[0], parts[1] || ""), row);
    }
  }
  return { reqByCdxPath: byCdx, reqBySpdxKey: bySpdx };
}

// enum 값 단위 대응 — cdx_spdx_mapping.json의 row-level "type_match"(CDX 쪽 매칭 토큰)와
// spdx_multi 안 Vocabulary hop의 "match"(SPDX 쪽 매칭 토큰)는 같은 순서로 나란히 대응한다
// (예: type_match[3] ↔ match[3]) — 문자열이 다를 수도 있어서(operating-system ↔
// operatingSystem) 이름이 아니라 인덱스로 짝짓는다. 엑셀 시트의 파란색 강조와 같은 데이터.
//
// **한쪽만 있는 대응이 더 많다(31행 대 19행).** CDX 쪽이 그냥 문자열이라 고를 값이 없고, 그
// 필드를 쓰면 SPDX 어휘의 **한 값으로 고정**되는 자리다 — organizationalEntity.url 은
// ExternalRefType.altWebPage 로, dependency.dependsOn 은 RelationshipType.dependsOn 으로 간다.
// 예전에는 type_match 가 없으면 행을 통째로 건너뛰어서 이 서른한 행이 전부 안 보였다.
function buildEnumIndex(mappingRows) {
  const cdxIdx = new Map();
  const spdxIdx = new Map();
  for (const row of mappingRows) {
    if (!row.spdx_multi) continue;
    for (const hop of row.spdx_multi) {
      if (hop.kind !== "Vocabulary" || !hop.match) continue;
      hop.match.forEach((spdxVal, i) => {
        const cdxVal = row.type_match ? row.type_match[i] : undefined;
        const sk = `${hop.class}::${spdxVal}`;
        if (!spdxIdx.has(sk)) spdxIdx.set(sk, []);
        // value 가 없으면 짝지을 CDX 값이 없는 고정 대응이다.
        spdxIdx.get(sk).push({ cdxPath: row.path, value: cdxVal });
        if (cdxVal === undefined) return;
        const ck = `${row.path}::${cdxVal}`;
        if (!cdxIdx.has(ck)) cdxIdx.set(ck, []);
        cdxIdx.get(ck).push({ cls: hop.class, value: spdxVal });
      });
    }
  }
  return { cdxEnumIndex: cdxIdx, spdxEnumIndex: spdxIdx };
}

/** 그 필드가 SPDX 어휘의 어떤 값으로 고정되는가 — 짝지을 CDX 값이 없는 대응만 모은다. */
function fixedVocabChips(mapping) {
  const out = [];
  for (const hop of (mapping && mapping.spdx_multi) || []) {
    if (hop.kind !== "Vocabulary" || !hop.match) continue;
    hop.match.forEach((v, i) => {
      if (mapping.type_match && mapping.type_match[i] !== undefined) return;  // 양쪽 다 있으면 칩끼리 짝지어진다
      out.push(...(spdxChipIndex.get(`${hop.class}::${v}`) || []));
    });
  }
  return out;
}

/* SPDX 트리는 판보다 먼저 한 번만 그려지는데, 값 대응 색인은 판마다 새로 만들어진다. 그래서
   SPDX 칩의 matched 표시는 렌더 시점에 정할 수 없고 — 실제로 지금까지 한 칩도 켜지지 않아
   SPDX 쪽에서는 값을 눌러 볼 수가 없었다 — 판을 갈아 끼울 때마다 여기서 다시 매긴다. */
function refreshSpdxChipMatches() {
  for (const [key, chips] of spdxChipIndex) {
    const on = spdxEnumIndex.has(key);
    for (const chip of chips) chip.classList.toggle("matched", on);
  }
}

// "enum of string: a, b, c" / "array of enum of string: a, b" / "enum: a, b" 형태에서
// 라벨과 값 목록을 분리한다. CDX·SPDX 양쪽 다 이 함수 하나로 통일해서 처리한다.
function parseEnum(typeStr) {
  const m = /^((?:array of )?enum(?: of string)?):\s*(.+)$/.exec(typeStr || "");
  if (!m) return null;
  return { label: m[1], values: m[2].split(",").map(s => s.trim()).filter(Boolean) };
}

function enumChipsHtml(values, side, contextKey) {
  const index = side === "cdx" ? cdxEnumIndex : spdxEnumIndex;
  const chips = values.map(v => {
    const matched = index.has(`${contextKey}::${v}`);
    return `<span class="enum-chip${matched ? " matched" : ""}" data-side="${side}" data-key="${escapeHtml(contextKey)}" data-value="${escapeHtml(v)}">${escapeHtml(v)}</span>`;
  }).join("");
  return `<span class="enum-chips">${chips}</span>`;
}

// 렌더링 직후 각 칩을 DOM에서 찾아 side별 chip 인덱스에 등록하고, 호버·클릭 핸들러를
// 단다(매칭된 칩만 — 엑셀에서 파란색으로만 칠하는 것과 같은 기준). onSelectRow는 클릭
// 시 "이 칩이 속한 행을 평소처럼 선택한 것"도 같이 실행해주는 콜백 — 먼저 그 행 선택으로
// clearHighlight()가 한 번 지나가게 한 다음에 칩을 고정해야, 고정한 칩이 곧바로 지워지지
// 않는다(순서가 반대면 방금 고정한 칩까지 같이 지워져버린다).
function wireEnumChips(container, side, contextKey, onSelectRow) {
  for (const chip of container.querySelectorAll(":scope > .enum-chips > .enum-chip")) {
    const key = `${contextKey}::${chip.dataset.value}`;
    const idx = side === "cdx" ? cdxChipIndex : spdxChipIndex;
    if (!idx.has(key)) idx.set(key, []);
    idx.get(key).push(chip);
    {
      // 호버: 아무것도 접거나 지우지 않고 반대쪽을 얹었다 뗀다.
      // SPDX 칩은 값 대응 색인이 만들어지기 전에 그려져서 지금은 matched 가 아니어도 나중에
      // 될 수 있다(refreshSpdxChipMatches). 그래서 핸들러는 늘 달고 그 안에서 확인한다.
      const off = () => !chip.classList.contains("matched");
      chip.addEventListener("mouseenter", () => { if (!off()) hoverEnumChip(chip, true); });
      chip.addEventListener("mouseleave", () => { if (!off()) hoverEnumChip(chip, false); });
      // 클릭: 이 칩이 속한 행도 평소처럼 선택되고(전체 체인 강조), 그 다음에 이 칩과
      // 반대쪽 대응 칩을 계속 파랗게 "고정"한다(마우스를 떼도 유지, 다른 칩/행을
      // 클릭하면 해제).
      chip.addEventListener("click", (e) => {
        if (off()) return;
        e.stopPropagation();
        // onSelectRow() 안의 clearHighlight()가 고정된 칩까지 다 풀어버리므로, "같은 칩을
        // 다시 눌러서 고정 해제" 여부는 그 전에 먼저 확인해둬야 한다.
        const wasPinned = chip.classList.contains("chip-pinned");
        onSelectRow();
        if (!wasPinned) pinChip(chip);
      });
    }
  }
}

// ── CDX 트리 (cyclonedx.json 루트 트리 + cyclonedx_refs.json 공용 타입, ref로 접붙임) ──
function buildCdxTree(rows) {
  const real = rows.filter(r => r.parent !== "");
  // path가 겹치는 자리가 하나 있다 — 루트 BOM의 signature 필드와 공용 타입 signature
  // 정의가 같은 "signature"다. 한 Map에 담으면 한쪽이 지워지므로, 부모 조회용과
  // 정의(ref) 조회용을 나눈다. 정의 쪽이 ref 대상이고, 루트 필드는 자기 행을 유지한다.
  const nodes = real.map(r => ({ row: r, children: [] }));
  const byPath = new Map();
  const byDef = new Map();
  for (const n of nodes) {
    if (!byPath.has(n.row.path)) byPath.set(n.row.path, n);
    if (n.row.parent === "(공용 타입)") byDef.set(n.row.path, n);
  }
  // 추출기가 "화면 표시용 부모(display_path 계열)"를 parent 필드에 넣는 자리가 있어서
  // (분기(oneOf) 밑에 중첩된 필드의 손자뻘 필드들 — 예: licenseChoice.License.license의
  // 하위 필드 bom-ref/id/... 는 parent가 실제 존재하는 "licenseChoice.License.license"가
  // 아니라 표시용인 "licenseChoice.license"로 돼있다), path로 못 찾으면 display_path로도
  // 한 번 더 찾아본다. 못 찾으면 진짜 orphan이라 root로 떨어뜨린다.
  const byDisplayPath = new Map(real.filter(r => r.display_path).map(r => [r.display_path, byPath.get(r.path)]));
  // 정의 시트 안의 자식(예: signature.option1)은 그 정의에 붙어야 한다.
  const parentOf = r => (r.path.startsWith(r.parent + ".") && byDef.has(r.parent))
    ? byDef.get(r.parent) : (byPath.get(r.parent) || byDisplayPath.get(r.parent));
  const root = { children: [] };
  // 공용 타입 정의 자신은 트리에 별도 최상위 가지로 두지 않는다 — "그것도 어차피
  // 어떤 필드니까 그 필드 자리에서 자연스럽게 펼쳐져야 한다"는 요청에 따라, 아래
  // ref 접붙이기를 통해 실제 쓰이는 자리(예: component.supplier)에만 나타난다.
  // (34개 공용 타입 전부 최소 한 곳 이상에서 ref로 참조되는 걸 확인했다 — 안 쓰이고
  // 붕 뜨는 정의는 없다.)
  const orphan = { children: [] };

  for (const n of nodes) {
    const r = n.row;
    if (r.parent === "(root BOM)") root.children.push(n);
    else if (r.parent === "(공용 타입)") orphan.children.push(n); // 렌더링 안 함, ref 조회용으로만 존재
    else (parentOf(r) || root).children.push(n);
  }

  // ref 접붙이기: component.hashes(ref: hash) 아래에 hash 정의의 자식들을 그대로 이어붙인다.
  // component/service처럼 자기 자신을 다시 참조하는 타입이 있어서(component.components가
  // 다시 component를 가리키는 식), refChain에 이미 있는 타입은 더 안 붙인다 — 안 그러면
  // "컴포넌트의 하위 컴포넌트의 하위 컴포넌트의…" 식으로 같은 필드(예: name)가 재귀 깊이마다
  // 반복 등장해서, 그 필드 하나 클릭했을 때 엉뚱하게 수십 곳이 한꺼번에 강조되는 문제가 있었다.
  // 자기참조는 딱 한 단계까지만 펼치고 그다음은 그대로 둔다(더 안쪽은 재귀 표시만).
  function resolveChildren(node, refChain) {
    const ref = node.row.ref;
    if (ref && (byDef.has(ref) || byPath.has(ref)) && !refChain.has(ref)) {
      const refNode = byDef.get(ref) || byPath.get(ref);
      const grafted = resolveChildren(refNode, new Set(refChain).add(ref));
      return node.children.concat(grafted);
    }
    return node.children;
  }
  for (const node of nodes) {
    node.children = resolveChildren(node, new Set());
  }
  return root;
}

function renderCdxNode(node, depth, ancestors, parentPath) {
  const row = node.row;
  const isBranch = row.name === "";
  // 접붙인 자리의 실제 경로. 공용 타입의 필드는 자리마다 대응이 다를 수 있어서 (inputs.maxSize 와 outputs.maxSize), 그런 자리는 이 경로로 찾는다
  const sitePath = parentPath && row.name ? `${parentPath}.${row.name}` : (parentPath || row.path);
  const key = siteKeyFor(sitePath) || row.path;
  // CDX 스키마엔 진짜 재귀 구조가 있다(component.components/pedigree.* 가 다시 component를
  // 참조하는 식) — ref 접붙이기와 만나면 같은 노드가 자기 자손으로 다시 나타나 무한
  // 렌더링에 빠질 수 있다. 지금 조상 경로에 이미 나온 path면 더 안 펼치고 leaf로 멈춘다.
  const isRecursive = ancestors.has(row.path);
  const mapping = mappingByPath.get(key);
  const hasMapping = !!(mapping && mapping.spdx && mapping.spdx !== "-" && mapping.spdx !== "");
  const li = document.createElement("li");
  li.className = "collapsed";
  li.dataset.path = row.path;

  // aibom-cli 출력에서 이 자리의 값을 채우는 도구. 갈래 행은 부모와 자리가 같으므로 배지를 달지 않는다
  const sources = !isBranch ? sourcesBySite.get(sitePath) : null;
  const div = document.createElement("div");
  div.className = "node-row" + (isBranch ? " branch" : "") +
    (!isBranch && !hasMapping ? " no-map" : "") +
    (row.added ? " is-new" : "") +    // v0.6 이 더한 필드. 필터를 켜지 않아도 늘 눈에 띄게
    (sources ? " is-gen" : "") +      // aibom-cli 가 값을 채우는 자리 ("생성하는 필드만" 필터가 남긴다)
    (!isBranch ? " clickable" : "");
  div.dataset.searchText = [row.name, row.title, row.path, row.type, row.description, row.description_ko,
    ...(sources || []).map(s => s.tool)]
    .filter(Boolean).join(" ").toLowerCase();

  const label = row.name || row.title || row.path;
  const enumInfo = parseEnum(row.type);
  // 갈래(oneOf·anyOf)를 가진 행: 갈래 사이에 or 구분선을 긋는다
  const choice = hasChoiceBranches(node.children);
  // added 면 v0.6 이 더한 필드다. origin 은 그 근거(규제)이고 여럿이면 배열로 온다.
  const origins = row.added ? (Array.isArray(row.origin) ? row.origin : (row.origin ? [row.origin] : [])) : [];
  const newBadge = row.added
    ? `<span class="new-badge" title="${escapeHtml(origins.join(" · ") || "AI-BOM v0.6 추가 필드")}">v0.6</span>` : "";
  div.innerHTML = `<span class="toggle"></span><span class="label">${escapeHtml(label)}</span>${newBadge}` +
    (sources ? toolBadgesHtml(sources) : "") +
    (row.type ? `<span class="sub">${escapeHtml(enumInfo ? enumInfo.label : row.type)}</span>` : "") +
    (row.required === "Y" ? `<span class="badge badge-required">required</span>` : "") +
    (isRecursive ? `<span class="sub">↻ recursive</span>` : "") +
    (enumInfo ? enumChipsHtml(enumInfo.values, "cdx", row.path) : "");

  if (!isBranch) {
    div.addEventListener("click", () => {
      selectCdxRow(row, mapping, div, true, key, sitePath);
    });
  }
  if (enumInfo) wireEnumChips(div, "cdx", row.path, () => selectCdxRow(row, mapping, div, false, key, sitePath));
  li.appendChild(div);

  if (!cdxNodeIndex.has(row.path)) cdxNodeIndex.set(row.path, []);
  cdxNodeIndex.get(row.path).push(li);
  if (key !== row.path) {                                 // 자리 경로로도 찾는다 (SPDX 쪽에서 되짚어 올 때)
    if (!cdxNodeIndex.has(key)) cdxNodeIndex.set(key, []);
    cdxNodeIndex.get(key).push(li);
  }

  if (node.children.length && !isRecursive) {
    div.classList.add("expandable");          // 두 트리 공통: 펼칠 수 있는 행은 조금 굵게 (SPDX 의 클래스 행과 같은 규칙)
    const toggle = div.querySelector(".toggle");
    toggle.textContent = "▶";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      li.classList.toggle("collapsed");
      toggle.textContent = li.classList.contains("collapsed") ? "▶" : "▼";
    });
    const childAncestors = new Set(ancestors);
    childAncestors.add(row.path);
    const ul = renderChildren(node.children, renderCdxNode, depth + 1, childAncestors, sitePath);
    if (choice) markChoiceBranches(ul);
    li.appendChild(ul);
  }
  return li;
}

/** 갈래(oneOf·anyOf 의 각 모양) 행이 둘 이상인가 */
function hasChoiceBranches(children) {
  return children.filter(c => c.row && c.row.name === "").length >= 2;
}
/** 갈래 행에 묶음 표시를 붙인다 (CSS 가 갈래 사이에 or 구분선을 긋는다). 행을 더 만들지 않는다 (필터가 li 마다 .node-row 를 찾는다) */
function markChoiceBranches(ul) {
  ul.classList.add("choice-group");
  for (const li of ul.children) {
    const div = li.querySelector(":scope > .node-row");
    if (div && div.classList.contains("branch")) li.classList.add("choice-branch");
  }
}

// ── SPDX 트리 (profile -> class -> property) ───────────────────────────
function buildSpdxTree(rows) {
  const profiles = new Map();
  for (const r of rows) {
    if (!profiles.has(r.profile)) profiles.set(r.profile, new Map());
    const classes = profiles.get(r.profile);
    if (!classes.has(r.class)) classes.set(r.class, []);
    classes.get(r.class).push(r);
  }
  const orderedProfiles = [...profiles.keys()].sort((a, b) => {
    const ia = PROFILE_ORDER.indexOf(a), ib = PROFILE_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
  const root = { children: [] };
  orderedProfiles.forEach((profile, profileIdx) => {
    const classes = profiles.get(profile);
    const classNames = [...classes.keys()].sort();
    root.children.push({
      isProfile: true, label: profile, profileIdx,
      children: classNames.map(cls => {
        const propRows = classes.get(cls);
        const defRow = propRows.find(r => !r.property);
        return {
          isClass: true, label: cls, cls, profileIdx,
          kind: propRows[0].kind,
          summary: defRow ? (defRow.summary || defRow.summary_ko) : propRows[0].summary,
          summaryKo: defRow ? defRow.summary_ko : propRows[0].summary_ko,
          enumType: defRow ? defRow.type : "",
          children: propRows.filter(r => r.property).map(r => ({ isProperty: true, row: r, profileIdx, children: [] })),
        };
      }),
    });
  });
  return root;
}

function renderSpdxProfileNode(node, depth) {
  if (node.isProperty) return renderSpdxPropertyNode(node);

  const li = document.createElement("li");
  li.className = "collapsed";
  const div = document.createElement("div");
  div.className = "node-row" + (node.isProfile ? " branch profile-header" : "") + (node.isClass ? " clickable class-row" : "");
  const searchBits = node.isProfile ? [node.label] : [node.label, node.kind, node.summary, node.enumType];
  div.dataset.searchText = searchBits.filter(Boolean).join(" ").toLowerCase();

  const enumInfo = parseEnum(node.enumType);
  div.innerHTML = `<span class="toggle"></span><span class="label">${escapeHtml(node.label)}</span>` +
    (node.isClass && node.kind ? kindBadge(node.kind) : "") +
    (enumInfo ? enumChipsHtml(enumInfo.values, "spdx", node.cls) : "");

  if (node.isClass) {
    spdxNodeIndex.set(keyFor(node.cls, ""), li);
    div.addEventListener("click", () => selectSpdxNode(node, div));
    if (enumInfo) wireEnumChips(div, "spdx", node.cls, () => selectSpdxNode(node, div, false));
  }

  li.appendChild(div);
  if (node.children.length) {
    div.classList.add("expandable");
    const toggle = div.querySelector(".toggle");
    toggle.textContent = "▶";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      li.classList.toggle("collapsed");
      toggle.textContent = li.classList.contains("collapsed") ? "▶" : "▼";
    });
    li.appendChild(renderChildren(node.children, renderSpdxProfileNode, depth + 1));
  }
  return li;
}

function renderSpdxPropertyNode(node) {
  const row = node.row;
  const li = document.createElement("li");
  const div = document.createElement("div");
  div.className = "node-row clickable" + (row.added ? " is-new" : "");
  div.dataset.searchText = [row.class, row.property, row.summary, row.summary_ko, row.type]
    .filter(Boolean).join(" ").toLowerCase();
  const enumInfo = parseEnum(row.type);
  div.innerHTML = `<span class="toggle"></span><span class="label">${escapeHtml(row.property)}</span>` +
    (row.added ? `<span class="new-badge" title="AI-BOM v0.6 추가 필드">v0.6</span>` : "") +
    (row.type ? `<span class="sub">${escapeHtml(enumInfo ? enumInfo.label : row.type)}</span>` : "") +
    (enumInfo ? enumChipsHtml(enumInfo.values, "spdx", row.class) : "");
  div.addEventListener("click", () => selectSpdxNode(node, div));
  if (enumInfo) wireEnumChips(div, "spdx", row.class, () => selectSpdxNode(node, div, false));
  li.appendChild(div);
  spdxNodeIndex.set(keyFor(row.class, row.property), li);
  return li;
}

// ── 공통 렌더 헬퍼 ──────────────────────────────────────────────────────
function renderChildren(children, renderFn, depth, ancestors, parentPath) {
  const ul = document.createElement("ul");
  ul.className = "tree-list";
  for (const child of children) ul.appendChild(renderFn(child, depth, ancestors, parentPath));
  return ul;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const KIND_BADGE_CLASS = { Class: "badge-class", Vocabulary: "badge-vocab", Individual: "badge-individual", Datatype: "badge-datatype" };
function kindBadge(kind) {
  const cls = KIND_BADGE_CLASS[kind];
  return cls ? `<span class="badge ${cls}">${escapeHtml(kind)}</span>` : "";
}

// candidateIndex별로 다른 색을 순환시킨다(체인은 항상 0이라 색이 하나로 유지되고,
// alt는 후보가 바뀔 때마다 다음 색으로 넘어간다). 배지는 absolute 포지션이라 라벨
// 위치를 밀어내지 않는다.
const CANDIDATE_COLORS = 4;
function applyHighlight(targetDiv) {
  currentHighlighted.push(targetDiv);
  // SPDX 트리(정방향의 대상)는 paintTree 가 매핑 단위로 칠한다 — 대응하는 자리가 여럿일 때
  // 전부 칠하면 어디부터 읽을지가 안 보이기 때문이다.
  if (spdxTreeEl.contains(targetDiv)) return;
  // 역방향(CDX 트리)은 켜진 줄들이 한 매핑의 단계가 아니라 **서로 다른 필드**다. 그래서 단계
  // 번호도 후보 색도 붙이지 않는다 — 붙이면 없는 순서와 갈래를 있는 것처럼 보이게 한다.
  targetDiv.classList.add("highlight");
}

// ── CDX 행 선택 → SPDX 대상 강조 ───────────────────────────────────────
//
// v0.5 가 더한 필드는 "왜 더했는지"(origin·reference)를 달고 있다. 그 근거를 따로 뗀 절에
// 모아 두었더니 같은 사실이 두 군데로 갈렸다 — SPDX 에서 옮겨 온 필드는 SPDX 절에도 뜨는데,
// 조항 때문에 만든 필드는 Requirement Coverage 가 "No requirement" 인 채로 근거 절에만 떴다.
// 그래서 근거를 **그것이 원래 속한 절로 흘려보낸다**: SPDX 출처는 SPDX 절, G7 출처는 G7 절,
// 조항 출처는 Requirement Coverage. 어느 절에 놓이든 초록 v0.5 표시가 "이것 때문에 더했다"를
// 뜻하고, 필드 자체가 새것이라는 사실은 CycloneDX 절의 NEW 배지가 든다.
function selectCdxRow(row, mapping, sourceDiv, scroll = true, key = row.path, sitePath = key) {
  clearHighlight();
  markSelected(sourceDiv);
  const targets = mapping ? getTargets(mapping) : [];
  if (targets.length) collapseAutoExpanded(sourceDiv); // 새로 보여줄 SPDX 대상이 있을 때만 이전 것을 접는다

  const origins = originsOf(row);

  // 스크롤은 **펼치기가 다 끝난 뒤**에 한 번만 한다. 1단계로 먼저 스크롤을 걸고 나서 뒷 단계
  // 가지를 펼치면, 그 가지가 1단계보다 위쪽 프로파일일 때(metadata.timestamp 의 2단계
  // CreationInfo 는 Core 라 Sbom 보다 위다) 목표 줄이 아래로 밀려 엉뚱한 자리에 멈춘다.
  let scrollTo = null;
  const spdxFields = targets.map((t, i) => {
    const key = keyFor(t.cls, t.property || "");
    const li = spdxNodeIndex.get(key) || spdxNodeIndex.get(keyFor(t.cls, ""));
    if (li) {
      expandAncestors(li);
      const targetDiv = li.querySelector(":scope > .node-row");
      applyHighlight(targetDiv);
      if (i === 0) scrollTo = targetDiv;
    }
    const spdxRow = spdxRowByKey.get(key);
    return {
      badge: targets.length > 1 ? { hopIndex: t.hopIndex, candidateIndex: t.candidateIndex } : null,
      name: `${t.cls}${t.property ? "." + t.property : ""}`,
      type: t.type || "",
      desc: spdxRow ? (spdxRow.summary || "") : "",
      descKo: spdxRow ? (spdxRow.summary_ko || "") : "",
      mismatch: t.mismatch,
      cand: t.candidateIndex,
      hop: t.hopIndex,
      kind: t.kind || "",
      spdxKey: key,
      isNew: !!(spdxRow && spdxRow.added),   // v0.6 이 SPDX 에 더한 속성 (CycloneDX 쪽과 같은 v0.6 표)
    };
  });
  renderDetailPanel({
    cdxFields: [{
      name: key,
      type: row.type || "",
      desc: row.description || "",
      descKo: row.description_ko || "",
      isNew: origins.length > 0,
    }],
    spdxFields,
    properties: propsFor(sitePath, row.path),
    // 그릇에는 자기 키가 없다 — 실제 이름은 하위 칸의 것(aibom:dataset:knownGaps:<i>:name)이다
    propsViaChildren: propsFor(sitePath, row.path).some(p => p.child && p.path === row.path),
    ...requirementsFor(row.path, origins),
    // 매핑표에서 빈칸인 그릇은 대응이 그릇이 아니라 하위 칸에 있다(knownBias 의 name·detectionMethod …)
    viaChildren: !!(mapping && mapping.spdx === ""),
    from: "cdx",
  });

  // 이 필드가 어휘의 한 값으로 고정되는 자리면 그 값을 켜 둔다 — CDX 쪽엔 누를 칩이 없어서
  // 가만 두면 대응이 있다는 것 자체가 안 보인다.
  pinChips(fixedVocabChips(mapping));

  // renderDetailPanel 안의 paintTree 도 가지를 펼치므로 그것까지 끝난 지금 스크롤한다.
  if (scroll && scrollTo) revealInTree(scrollTo);
}

/** 그 필드를 더한 근거 (출처, 지시자) 쌍. 1.7 필드는 빈 배열이다. */
function originsOf(row) {
  if (!row || !row.origin) return [];
  const os = Array.isArray(row.origin) ? row.origin : [row.origin];
  const rs = Array.isArray(row.reference) ? row.reference : [row.reference];
  return os.map((source, i) => ({ source, reference: rs[i] || "" }));
}
const isSpdxSource = source => source.startsWith("SPDX");
const isG7Source = source => source === "G7";

/* Requirement Coverage 에 들어갈 행. 두 갈래를 모은다.
     1. cdx_ref 로 걸린 것 — 요구사항 매핑이 이 필드(1.7 의 것이든 v0.6 이 더한 것이든)에 건 요구사항
     2. 이 필드의 근거 조항인데 1 에 없는 것 — 조항은 그릇에 걸렸는데 근거는 하위 칸이 물려받거나
        (statistics → statistics.type), 하위 name 의 조항이 그릇으로 올라간 자리(knownBias.name → knownBias)다.
        같은 계열(그릇과 그 하위)에서 그 조항의 행을 끌어온다. */
function requirementsFor(path, origins) {
  const rows = [];
  const push = r => { if (!rows.some(x => x.row_key === r.row_key)) rows.push(r); };
  const clauses = new Set(origins.filter(o => !isSpdxSource(o.source) && !isG7Source(o.source))
                                 .map(o => o.reference));
  for (const r of reqByCdxPath.get(path) || []) push(r);
  for (const ref of clauses) {
    if (rows.some(r => r.id === ref)) continue;
    for (const [field, list] of reqByCdxPath) {
      if (!sameFamily(field, path)) continue;
      for (const r of list) if (r.id === ref) push(r);
    }
  }
  return { requirements: rows };
}

/** 컨테이너와 그 하위 필드는 한 계열로 본다 — 조항이 어느 쪽에 걸렸든 같은 사실이다. */
function sameFamily(a, b) {
  return a === b || a.startsWith(b + ".") || b.startsWith(a + ".");
}

// G7 요소 설명 — 출처가 G7 인 필드는 그 요소 이름만으로는 무엇을 요구하는지 안 보인다.
let g7DescByName = new Map();
function buildG7Index(g7Rows) {
  g7DescByName = new Map(g7Rows.filter(r => r.name).map(r => [r.name, r.description_ko || r.description || ""]));
}

/** "Model properties, Dataset content" → ["Model properties", "Dataset content"]. */
function g7Names(g7String) {
  return g7String ? g7String.split(",").map(s => s.trim()).filter(Boolean) : [];
}

/** 이름 목록을 G7 절이 그리는 꼴로 — 요소 이름만으론 무엇을 요구하는지 안 보여 설명을 붙인다. */
function g7Blocks(names) {
  return names.map(name => ({ name, desc: g7DescByName.get(name) || "" }));
}

/* G7 요소는 매핑표의 g7_element 가 든다. v0.5 새 필드의 G7 출처는 **언제나 그 목록 안에** 있어서
   (데이터에서 어긋나는 자리가 하나도 없다) 「이것 때문에 더했다」를 따로 표시할 것이 없다. */
function g7Tags(g7String, origins) {
  const names = g7Names(g7String);
  for (const o of (origins || [])) {
    if (isG7Source(o.source) && !names.includes(o.reference)) names.push(o.reference);
  }
  return g7Blocks(names);
}

// ── Reverse: selecting an SPDX node highlights its CDX field(s) ────────
function selectSpdxNode(node, sourceDiv, scroll = true) {
  clearHighlight();
  markSelected(sourceDiv);
  const key = node.isClass ? keyFor(node.cls, "") : keyFor(node.row.class, node.row.property);
  // 같은 CDX 필드가 한 체인에서 이 자리를 두 번 지나면 항목이 둘로 잡힌다(component.cpe 가
  // 그랬다). 필드 단위로 한 번만 센다.
  const seen = new Set();
  const matches = (spdxToCdx.get(key) || []).filter(m => !seen.has(m.cdxPath) && seen.add(m.cdxPath));
  if (matches.length) collapseAutoExpanded(sourceDiv); // 새로 보여줄 CDX 대상이 있을 때만 이전 것을 접는다

  const cdxFields = [];
  let scrollTo = null;
  let first = true;
  const properties = [];
  for (const m of matches) {
    // 공용 타입은 수십 자리에 접붙여져 있어서 사본을 전부 켜면 필드 넷이 이천 줄로 보인다
    // (ExternalRefType 이 2055 줄이었다). 대표 자리 한 곳만 켠다 — 숨기는 게 아니라, 같은
    // 필드를 같은 수만큼 세는 것이다.
    const li = shallowestLi(m.cdxPath);
    if (li) {
      expandAncestors(li);
      const targetDiv = li.querySelector(":scope > .node-row");
      applyHighlight(targetDiv);
      if (first) { scrollTo = targetDiv; first = false; }
    }
    const cdxRow = cdxRowByPath.get(m.cdxPath) || siteAlias.get(m.cdxPath);
    properties.push(...(propsByPath.get(m.cdxPath) || []));
    cdxFields.push({
      // 여기 늘어서는 것은 한 매핑의 단계가 아니라 **서로 다른 필드들**이라 번호를 붙이지 않는다.
      name: m.cdxPath,
      type: cdxRow ? (cdxRow.type || "") : "",
      desc: cdxRow ? (cdxRow.description || "") : "",
      descKo: cdxRow ? (cdxRow.description_ko || "") : "",
      isNew: !!(cdxRow && cdxRow.added),
      cdxPath: m.cdxPath,
    });
  }

  let spdxFields;
  if (node.isClass) {
    spdxFields = [{ name: node.cls, type: node.kind || "", desc: node.summary || "", descKo: node.summaryKo || "" }];
  } else {
    const row = node.row;
    spdxFields = [{ name: `${row.class}.${row.property}`, type: row.type || "", desc: row.summary || "",
                    descKo: row.summary_ko || "", isNew: !!row.added }];
  }

  // CDX 쪽에서 걸린 요구사항도 함께 모은다 — 요구사항 행이 CDX 축으로만 필드를 지정한
  // 경우(spdx_ref 없음)에도 그 CDX 필드와 이어진 SPDX 속성을 누르면 보이게 하기 위함.
  const reqs = [...(reqBySpdxKey.get(key) || [])];
  for (const m of matches) {
    const cdxRow = cdxRowByPath.get(m.cdxPath) || siteAlias.get(m.cdxPath);
    const { requirements } = requirementsFor(cdxRow ? cdxRow.path : m.cdxPath, originsOf(cdxRow));
    for (const r of requirements) if (!reqs.some(x => x.row_key === r.row_key)) reqs.push(r);
  }

  renderDetailPanel({
    cdxFields,
    spdxFields,
    properties,
    requirements: reqs,
    from: "spdx",
  });

  if (scroll && scrollTo) revealInTree(scrollTo);
}

// ── 오른쪽 패널 공통 렌더러: 어느 쪽에서 클릭했든 CycloneDX/SPDX/G7 Element 세
// 칸으로 항상 같은 구조를 보여준다 ───────────────────────────────────────
/** 트리 행의 도구 배지. 도구 순서는 TOOL_ORDER, 마우스를 올리면 그 도구가 채우는 대상 종류가 나온다. */
function toolBadgesHtml(sources) {
  return sortedSources(sources).map(s =>
    `<span class="tool-badge" title="${escapeHtml(`${s.tool}: ${s.kinds.join(", ")}`)}">${escapeHtml(TOOL_LABEL[s.tool] || s.tool)}</span>`).join("");
}

function sortedSources(sources) {
  const rank = t => (TOOL_ORDER.indexOf(t) === -1 ? 99 : TOOL_ORDER.indexOf(t));
  return [...sources].sort((a, b) => rank(a.tool) - rank(b.tool));
}

function renderDetailPanel({ cdxFields, spdxFields, properties, propsViaChildren, requirements, viaChildren, from }) {
  // 비어 있는 절은 문장 대신 제목 옆의 작은 "없음" 표로. 절 자체는 남긴다 (없다는 것도 정보다)
  const none = `<span class="section-none">없음</span>`;
  const cdxHtml = cdxFields.length ? cdxFields.map(fieldBlockHtml).join("") : "";
  // 매핑이 없으면 fieldBlocksHtml 이 안 불린다. 그러면 지난 필드의 단계 목록이 남아서 그 자리에 색과 페이저가
  // 그대로 서 있게 된다. 여기서 비워 준다.
  const via = !spdxFields.length && viaChildren;
  const spdxHtml = spdxFields.length ? fieldBlocksHtml(spdxFields) : (panelChains = new Map(), "");
  const reqs = requirements || [];
  // 요구사항 본문은 비공식 자체 번역이다. 출처와 함께 절 끝에 작게 밝힌다 (ISO 는 본문 없이 조항 제목만 싣는다)
  const reqNote = `<div class="req-source">한국어는 비공식 자체 번역. 출처: EU AI Act (Regulation (EU) 2024/1689), ` +
    `NIST AI RMF 1.0 (NIST AI 100-1), ISO/IEC 42001:2023. ISO/IEC 42001 은 조항 번호와 제목만 싣는다.</div>`;
  const reqHtml = reqs.length ? reqs.map(requirementBlockHtml).join("") + reqNote : "";
  const reqCount = reqs.length ? sectionCount(reqs.length) : none;
  // SPDX 는 **매핑 수**를 센다. 체인 단계는 한 매핑 안에서의 이동이지 매핑이 늘어난 게 아니다.
  const spdxCount = spdxFields.length ? sectionCount(mappingCount(spdxFields))
    : via ? `<span class="section-via">하위 필드에 대응</span>` : none;
  const cdxCount = cdxFields.length ? sectionCount(cdxFields.length) : none;

  const props = properties || [];
  const propsHtml = propsViaChildren
    ? `<div class="detail-section section-props"><h4>properties 키<span class="section-via">하위 필드에 대응</span></h4></div>`
    : props.length
    ? `<div class="detail-section section-props"><h4>properties 키${sectionCount(props.length)}</h4>` +
      props.map(propertyBlockHtml).join("") + `</div>`
    : "";

  const html = `
    <div class="detail-section section-cdx"><h4>CycloneDX${cdxCount}</h4>${cdxHtml}</div>
    <div class="detail-section section-spdx"><h4>SPDX${spdxCount}</h4>${spdxHtml}</div>
    ${propsHtml}
    <div class="detail-section section-req"><h4>규제 요구사항${reqCount}</h4>${reqHtml}</div>
  `;
  detailBody.innerHTML = html;
  detailBody.scrollTop = 0;   // 다른 필드로 바꾸면 새 설명의 머리부터 보인다 (이전 필드에서 내려 둔 스크롤을 잇지 않는다)
  wirePanelJumps();
  setDetailPanelOpen(true);
}

/** --spec 1.7 로 낼 때의 properties 키. 같은 값을 v0.6 필드 대신 이 이름으로 적는다. */
function propertyBlockHtml(p) {
  return `<div class="field-block">` +
    `<div class="field-name"><code class="prop-key">${escapeHtml(p.key)}</code></div>` +
    (p.allowed ? `<div class="field-desc">허용값: ${escapeHtml(p.allowed)}</div>` : "") +
    `</div>`;
}

const sectionCount = n => n > 1 ? `<span class="section-count">${n}</span>` : "";
const mappingCount = fields =>
  new Set(fields.map((f, i) => f.cand != null ? `c${f.cand}` : `x${i}`)).size;

/** 상세 패널의 hop 배지 → 트리의 그 자리. 어느 쪽 트리인지는 배지에 심어 둔 열쇠가 정한다. */
function wirePanelJumps() {
  for (const pager of detailBody.querySelectorAll(".pager")) {
    for (const btn of pager.querySelectorAll(".pager-btn")) {
      btn.addEventListener("click", () => showStep(pager.dataset.cand, currentStep(pager.dataset.cand) + +btn.dataset.delta, true));
    }
  }
  // 페이저가 없는 홑 배지(역방향의 CDX 블록 등)는 그냥 그 자리로 데려다준다.
  for (const badge of detailBody.querySelectorAll(".hop-badge[data-cdx-path]")) {
    badge.addEventListener("click", () => {
      const li = (cdxNodeIndex.get(badge.dataset.cdxPath) || [])[0];
      if (li) { expandAncestors(li); flashRow(li.querySelector(":scope > .node-row")); }
    });
  }
  // 처음 열릴 때는 매핑마다 1단계가 현재다. 테두리만 두르고 스크롤은 하지 않는다 — 선택할 때
  // 이미 그리로 스크롤했다.
  stepByCand = new Map();
  lastMoved = null;
  paintTree();
}

/* 지금 몇 단계를 보고 있나. 트리 배지와 페이저가 같은 상태를 고쳐 쓴다 — 어느 쪽에서 넘기든
   패널의 내용, 페이저의 「1 / 2」, 트리의 테두리가 한꺼번에 따라온다. */
let stepByCand = new Map();
const currentStep = cand => stepByCand.get(String(cand)) || 0;

function showStep(cand, index, scroll) {
  cand = String(cand);
  const steps = panelChains.get(cand);
  if (!steps) return;
  const i = (index + steps.length) % steps.length;
  stepByCand.set(cand, i);
  // **앞으로 나가 있는 매핑은 하나뿐이다.** 매핑 1 을 2단계까지 보다가 매핑 2 로 넘어가면
  // 매핑 1 은 1단계로 되돌린다 — 안 그러면 둘이 같은 자리로 모이는 체인에서(component.type 의
  // 두 매핑이 둘 다 SoftwarePurpose 로 간다) 같은 「2/2」가 두 개 서 있게 된다.
  for (const other of panelChains.keys()) if (other !== cand) stepByCand.set(other, 0);

  lastMoved = cand;           // 겹치는 줄에서 색을 가져갈 쪽
  syncPanel();
  paintTree();
  if (scroll) {
    const li = spdxNodeIndex.get(steps[i].spdxKey);
    if (li) flashRow(li.querySelector(":scope > .node-row"));
  }
}

/** 패널의 페이저·본문을 지금 상태에 맞춘다 — 되돌려진 매핑까지 한꺼번에 본다. */
function syncPanel() {
  for (const [cand, steps] of panelChains) {
    const chain = detailBody.querySelector(`.chain[data-cand="${cand}"]`);
    if (!chain) continue;
    const i = currentStep(cand);
    for (const body of chain.querySelectorAll(".step-body")) body.hidden = +body.dataset.step !== i;
    const pager = chain.querySelector(".pager");
    if (!pager) continue;
    pager.querySelector(".pager-now").firstChild.textContent = `${i + 1} `;
    for (const btn of pager.querySelectorAll(".pager-btn")) {
      btn.disabled = (+btn.dataset.delta < 0 && i === 0) || (+btn.dataset.delta > 0 && i === steps.length - 1);
    }
  }
}

/* **한 번에 한 매핑.** 대응하는 SPDX 자리가 여럿일 때(매핑이 여럿일 때) 전부를 동시에 칠하려니
   겹치는 자리에서 색이 두 벌 붙고, 어느 매핑의 색인지도 어긋났다 — component.type 의 두 매핑이
   둘 다 SoftwarePurpose 로 가는 자리가 그랬다. 그래서 표시를 매핑 단위로 정한다.

     활성 매핑    그 매핑의 지금 단계 한 줄만 **진한 색 + 페이저**. 처음엔 매핑 1 이 활성이다.
     다른 매핑    그 매핑의 지금 단계 한 줄에 **옅은 색만**. 여기도 대응된다는 것은 보이되,
                  조작은 활성 매핑에서만 한다.
     같은 매핑의 다른 단계    아무 표시도 하지 않는다 — 페이저로 넘기면 색이 그리로 옮겨간다.

   한 줄이 두 매핑의 현재 단계일 수도 있다(수렴). 그때는 활성 매핑이 이긴다 — 그래야 색이 하나다. */
let lastMoved = null;
let paintedRows = [];

function paintTree() {
  for (const row of paintedRows) clearStepRow(row);
  paintedRows = [];

  // 마지막으로 움직인 매핑을 나중에 칠한다 — 두 매핑이 같은 줄로 모였을 때 그쪽 색이 남는다.
  const cands = [...panelChains.keys()].sort((a, b) => (a === lastMoved) - (b === lastMoved));
  for (const cand of cands) {
    const steps = panelChains.get(cand);
    const li = spdxNodeIndex.get(steps[currentStep(cand)].spdxKey);
    if (!li) continue;
    expandAncestors(li);
    const row = li.querySelector(":scope > .node-row");
    for (let c = 0; c < CANDIDATE_COLORS; c++) row.classList.remove(`cand-${c}`);
    row.classList.add("step-row", `cand-${+cand % CANDIDATE_COLORS}`);
    // 페이저는 매핑마다 하나다. 두 매핑이 같은 줄로 모이면 그 줄에 둘이 나란히 선다 —
    // 어느 쪽이든 거기서 바로 움직일 수 있어야 하기 때문이다.
    if (steps.length > 1) appendToRow(row, treePager(cand, steps.length));
    if (!paintedRows.includes(row)) paintedRows.push(row);
  }
}

function clearStepRow(row) {
  row.classList.remove("step-row");
  for (let c = 0; c < CANDIDATE_COLORS; c++) row.classList.remove(`cand-${c}`);
  for (const el of row.querySelectorAll(":scope > .tree-pager")) el.remove();
}

/** 매핑의 현재 줄에 붙는 페이저 — 상세 패널의 것과 같은 모양·같은 규칙이다. */
function treePager(cand, total) {
  const i = currentStep(cand);
  const box = document.createElement("span");
  box.className = `tree-pager cand-${+cand % CANDIDATE_COLORS}`;
  box.innerHTML =
    `<button class="pager-btn" data-delta="-1" title="이전 단계"${i === 0 ? " disabled" : ""}>‹</button>` +
    `<span class="pager-now">${i + 1} <span class="pager-of">/ ${total}</span></span>` +
    `<button class="pager-btn" data-delta="1" title="다음 단계"${i === total - 1 ? " disabled" : ""}>›</button>`;
  for (const btn of box.querySelectorAll(".pager-btn")) {
    btn.addEventListener("click", e => {
      e.stopPropagation();   // 그 행을 선택하는 클릭으로 번지지 않게
      showStep(cand, currentStep(cand) + +btn.dataset.delta, true);
    });
  }
  return box;
}

/** 행을 그 트리 안에서만 가운데로 스크롤한다. scrollIntoView 는 페이지까지 움직여서
 *  누른 행이 화면 밖으로 밀려난다. 가로는 보이지 않을 때만 끌어온다. */
function revealInTree(el) {
  const label = el.querySelector(".label") || el;
  const tree = el.closest(".tree");
  if (!tree) { label.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" }); return; }
  const t = tree.getBoundingClientRect(), r = label.getBoundingClientRect();
  const top = tree.scrollTop + (r.top - t.top) - (tree.clientHeight - r.height) / 2;
  let left = tree.scrollLeft;
  if (r.left < t.left) left += r.left - t.left - 8;
  else if (r.right > t.left + tree.clientWidth) left += r.right - (t.left + tree.clientWidth) + 8;
  tree.scrollTo({ top: Math.max(0, top), left: Math.max(0, left), behavior: "smooth" });
}

/** 그 행으로 스크롤하고 잠깐 밝힌다 — 건너뛴 자리를 눈이 따라가게. */
function flashRow(row) {
  if (!row) return;
  revealInTree(row);
  row.classList.add("hop-flash");
  setTimeout(() => row.classList.remove("hop-flash"), 700);
}

/* 체인을 어떻게 보일 것인가.

   번호 동그라미를 1·2·3·4 로 늘어놓아 봤더니 단계가 늘수록 안 늘어난다. **페이지 넘기듯** 바꾼다:
   양쪽 홑화살표 사이에 `1 / 2` 만 두고, 한 번에 한 단계의 내용을 편다. 단계가 넷이든 열이든
   같은 크기다.

   한 필드가 SPDX 여러 자리에 매핑될 때는 매핑마다 이 페이저를 따로 둔다 — 그 여럿은 후보가
   아니라 **전부 실제로 매핑되는 자리**라, 세어서 「매핑 N」이라고만 적는다. */
function fieldBlocksHtml(fields) {
  const groups = [];
  for (const f of fields) {
    const last = groups[groups.length - 1];
    if (f.cand != null && last && last.cand === f.cand) last.steps.push(f);
    else groups.push({ cand: f.cand, steps: [f] });
  }
  const chains = groups.filter(g => g.cand != null);

  const html = groups.map(g => {
    if (g.cand == null) return fieldBlockHtml(g.steps[0]);
    const cls = `cand-${g.cand % CANDIDATE_COLORS}`;
    const pager = g.steps.length > 1 ? pagerHtml(g, cls) : "";
    const bodies = g.steps.map((f, i) =>
      `<div class="step-body" data-cand="${g.cand}" data-step="${i}"${i ? " hidden" : ""}>` +
      fieldBlockHtml({ ...f, badge: null }) + `</div>`).join("");
    return `<div class="chain" data-cand="${g.cand}">${pager}${bodies}</div>`;
  }).join("");

  // 배선에서 쓰도록 단계 목록을 남겨 둔다 — 트리 배지와 페이저가 같은 목록을 본다.
  panelChains = new Map(chains.map(g => [String(g.cand), g.steps]));
  return html;
}

let panelChains = new Map();   // "후보 번호" -> [{spdxKey, hop, kind}, ...]

function pagerHtml(g, cls) {
  const n = g.steps.length;
  return `<div class="pager ${cls}" data-cand="${g.cand}">` +
    `<button class="pager-btn" data-delta="-1" title="이전 단계" disabled>‹</button>` +
    `<span class="pager-now">1 <span class="pager-of">/ ${n}</span></span>` +
    `<button class="pager-btn" data-delta="1" title="다음 단계">›</button>` +
    `</div>`;
}

function g7BlockHtml(t) {
  return `<div class="g7-block">` +
    `<div class="g7-head"><span class="badge badge-g7">${escapeHtml(t.name)}</span>` +
    `</div>` +
    (t.desc ? `<div class="field-desc-ko">${escapeHtml(t.desc)}</div>` : "") +
    `</div>`;
}

// 요구사항 원문에서 매핑 근거가 된 문구를 엑셀 "요구사항 매핑" 시트와 같은 방식으로 파랗게
// 칠한다. 문구는 원문에 그대로 들어 있는 부분 문자열이므로, escape 한 쪽끼리 치환한다.
//
// **시트의 빨강(대응 필드 없음)은 여기 오지 않는다.** 격차 문구를 가진 행은 cdx_ref·spdx_ref 가 비어 있고,
// 이 패널은 필드를 통해서만 행에 닿는다. v0.6 이 메운 격차의 문구는 데이터에서 이미 파랑으로 옮겨져 있다.
function highlightPhrases(text, phrases) {
  let html = escapeHtml(text);
  for (const p of phrases || []) {
    if (!p) continue;
    const esc = escapeHtml(p);
    html = html.split(esc).join(`<span class="req-hl">${esc}</span>`);
  }
  return html;
}

function requirementBlockHtml(r) {
  const text = highlightPhrases(r.requirement_ko || "", r.requirement_highlight);
  const cell = (label, value, cls) =>
    `<div class="req-cell"><span class="req-label">${label}</span><span class="${cls}">${escapeHtml(value)}</span></div>`;
  return `
    <div class="req-block">
      <div class="req-meta">
        ${cell("규제", r.source || "", "req-doc")}
        ${cell("조항", r.id || "", "req-id")}
      </div>
      <div class="req-text">${text}</div>
    </div>
  `;
}

function fieldBlockHtml(f) {
  // 배지에 그 대상의 열쇠를 심어 두면 눌렀을 때 트리의 그 자리로 갈 수 있다.
  const jump = f.spdxKey ? ` data-spdx-key="${escapeHtml(f.spdxKey)}"`
             : f.cdxPath ? ` data-cdx-path="${escapeHtml(f.cdxPath)}"` : "";
  const badge = f.badge
    ? `<span class="hop-badge jumpable cand-${(f.badge.candidateIndex || 0) % CANDIDATE_COLORS}"${jump}` +
      ` title="트리에서 이 자리로">${f.badge.hopIndex}</span>`
    : "";
  const mark = f.isNew ? `<span class="new-badge">v0.6</span>` : "";
  return `
    <div class="field-block">
      <div class="field-name">${badge}${escapeHtml(f.name)}${mark}</div>
      ${f.descKo || f.desc ? `<div class="field-desc">${escapeHtml(f.descKo || f.desc)}</div>` : ""}
    </div>
  `;
}

function clearHighlight() {
  for (const el of currentHighlighted) {
    for (let c = 0; c < CANDIDATE_COLORS; c++) el.classList.remove(`cand-${c}`);
    el.classList.remove("highlight");
    // 한 행에 배지가 여럿 붙을 수 있다 — 한 후보가 같은 자리를 다른 단계로 두 번 지나는 경우다.
    // 하나만 지우면 지난 선택의 배지가 남는다.
    for (const el2 of el.querySelectorAll(":scope > .hop-badge, :scope > .tree-pager")) el2.remove();

  }
  currentHighlighted = [];
  for (const row of paintedRows) clearStepRow(row);
  paintedRows = [];
  lastMoved = null;
  if (currentSelected) currentSelected.classList.remove("selected");
  currentSelected = null;
  clearPinnedChips();
  // 자동으로 펼쳐졌던 가지는 여기서 접지 않는다 — 새로 보여줄 매핑이 있을 때만
  // (selectCdxRow/selectSpdxNode 쪽에서) 접는다. 안 그러면 매핑이 없는 걸 눌렀을
  // 때도(예: SPDX 클래스 이름 자체 클릭) 이전에 봐뒀던 트리가 이유 없이 다 접혀버린다.
}

// 클릭해서 지금 보고 있는 게 "이 필드/속성이다"를 표시한다 — 반대쪽(SPDX/CDX)에
// 뜨는 파란 강조(.highlight)와는 다른 색으로, "내가 클릭한 원본"과 "그게 매핑되는
// 대상"을 구분한다.
let currentSelected = null;
function markSelected(div) {
  if (!div) return;
  div.classList.add("selected");
  currentSelected = div;
}

// enum 값 칩 클릭으로 "고정"한 것들 — 마우스를 떼도 유지되고, 다른 걸 클릭하면 풀린다.
let pinnedChips = [];
function clearPinnedChips() {
  for (const c of pinnedChips) c.classList.remove("chip-pinned");
  pinnedChips = [];
}
/** 칩 여러 개를 한꺼번에 켠다 — 짝이 없는 고정 값 대응에 쓴다. */
function pinChips(chips) {
  if (!chips.length) return;
  clearPinnedChips();
  for (const c of chips) { c.classList.add("chip-pinned"); pinnedChips.push(c); }
}

function pinChip(chip) {
  clearPinnedChips();
  const side = chip.dataset.side;
  const key = `${chip.dataset.key}::${chip.dataset.value}`;
  const targets = (side === "cdx" ? cdxEnumIndex : spdxEnumIndex).get(key) || [];
  const otherChipIndex = side === "cdx" ? spdxChipIndex : cdxChipIndex;

  chip.classList.add("chip-pinned");
  pinnedChips.push(chip);
  for (const t of targets) {
    const otherKey = side === "cdx" ? `${t.cls}::${t.value}` : `${t.cdxPath}::${t.value}`;
    for (const otherChip of otherChipIndex.get(otherKey) || []) {
      otherChip.classList.add("chip-pinned");
      pinnedChips.push(otherChip);
    }
  }
}

// enum 값 칩에 마우스를 올리면 반대쪽 대응 값(들)을 밝힌다 — 클릭과 달리 기존
// 강조·펼침 상태를 전혀 건드리지 않는다(지우지도, 새로 펼치지도 않는다). 이미
// 펼쳐져서 보이는 칩만 밝혀지고, 접혀 있어 안 보이는 건 그냥 안 보인다.
function hoverEnumChip(chip, on) {
  chip.classList.toggle("chip-hover", on);
  const side = chip.dataset.side;
  const key = `${chip.dataset.key}::${chip.dataset.value}`;
  const targets = (side === "cdx" ? cdxEnumIndex : spdxEnumIndex).get(key) || [];
  const otherChipIndex = side === "cdx" ? spdxChipIndex : cdxChipIndex;

  for (const t of targets) {
    const otherKey = side === "cdx" ? `${t.cls}::${t.value}` : `${t.cdxPath}::${t.value}`;
    for (const otherChip of otherChipIndex.get(otherKey) || []) {
      otherChip.classList.toggle("chip-hover", on);
    }
  }
}

// 이전 클릭 때 자동으로 펼쳐졌던 가지들을 기억해뒀다가, 다음 클릭 전에 도로 접는다 —
// 사용자가 직접 펼친 가지는 이 목록에 없으니 그대로 남는다.
let autoExpanded = [];
// protectDiv(지금 클릭한 그 행)의 조상은 접지 않는다 — 안 그러면 "SPDX 쪽에서 뭔가
// 눌렀는데 그 순간 자기 자신을 담고 있던 가지가 접혀서 방금 누른 게 사라져 보이는"
// 문제가 생긴다(이전 선택 때 자동으로 펼쳐진 가지 안에서 새로 클릭한 경우).
function collapseAutoExpanded(protectDiv) {
  const protectedLis = new Set();
  if (protectDiv) {
    let el = protectDiv.closest("li");
    while (el) {
      protectedLis.add(el);
      el = el.parentElement && el.parentElement.closest("li");
    }
  }
  const remaining = [];
  for (const li of autoExpanded) {
    if (protectedLis.has(li)) { remaining.push(li); continue; }
    li.classList.add("collapsed");
    const toggle = li.querySelector(":scope > .node-row > .toggle");
    if (toggle) toggle.textContent = "▶";
  }
  autoExpanded = remaining;
}

function expandAncestors(li) {
  let el = li.parentElement; // ul.tree-list
  while (el) {
    const parentLi = el.closest("li");
    if (!parentLi) break;
    if (parentLi.classList.contains("collapsed")) {
      parentLi.classList.remove("collapsed");
      autoExpanded.push(parentLi);
    }
    const toggle = parentLi.querySelector(":scope > .node-row > .toggle");
    if (toggle) toggle.textContent = "▼";
    el = parentLi.parentElement;
  }
}

// ── 검색 필터 ───────────────────────────────────────────────────────────
function debounce(fn, ms) {
  let timer = null;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

/* 필터 색인. 트리가 9만 줄이라 글자마다 DOM 을 훑으면 멈춘다. li 마다 글자·표시 상태를 한 번 모아 두고, 검색은 이 배열만 돌며
   DOM 은 보이기가 바뀌는 자리만 쓴다. */
let filterIndex = [];
function buildFilterIndex() {
  const walk = ul => [...ul.children].map(li => {
    const div = li.querySelector(":scope > .node-row");
    const childUl = li.querySelector(":scope > ul.tree-list");
    return { li, div, toggle: div.querySelector(":scope > .toggle"), text: div.dataset.searchText || "",
             isNew: div.classList.contains("is-new"), isGen: div.classList.contains("is-gen"),
             rep: !li.dataset.path || representativeLis.has(li),
             children: childUl ? walk(childUl) : [], shown: true };
  });
  filterIndex = [cdxTreeEl, spdxTreeEl].map(t => t.querySelector(":scope > ul.tree-list")).filter(Boolean).map(walk);
}

function applyFilter() {
  const query = searchEl.value.trim().toLowerCase();
  const addedOnly = !!(addedOnlyEl && addedOnlyEl.checked);
  const generatedOnly = !!(generatedOnlyEl && generatedOnlyEl.checked);
  // "생성하는 필드만" 은 CycloneDX 트리에만 건다 (출처는 aibom-cli 가 내는 CycloneDX 자리에만 있다)
  filterIndex.forEach((nodes, i) => {
    const genOnly = generatedOnly && i === 0;
    filterNodes(nodes, query, addedOnly, genOnly, !!(query || addedOnly || genOnly));
  });
}

/** 검색어에 맞는 행과 그 조상만 남긴다. "추가 필드만" 이면 v0.6 추가 필드(대표 자리)와 그 조상만, "생성하는 필드만" 이면
    aibom-cli 가 값을 채우는 자리와 그 조상만. 필터가 없으면 전부 접어 둔다. */
function filterNodes(nodes, query, addedOnly, generatedOnly, active) {
  let any = false;
  for (const n of nodes) {
    const self = (!query || n.text.includes(query)) && (!addedOnly || (n.isNew && n.rep)) && (!generatedOnly || n.isGen);
    const child = n.children.length ? filterNodes(n.children, query, addedOnly, generatedOnly, active) : false;
    const visible = self || child;
    if (visible !== n.shown) { n.li.style.display = visible ? "" : "none"; n.shown = visible; }
    if (n.children.length) {
      const collapse = !(visible && active);
      if (n.li.classList.contains("collapsed") !== collapse) {
        n.li.classList.toggle("collapsed", collapse);
        if (n.toggle && n.toggle.textContent) n.toggle.textContent = collapse ? "▶" : "▼";
      }
    }
    any = any || visible;
  }
  return any;
}

/* 검색 제안: 입력하는 동안 이름이 맞는 필드를 몇 개 보여 주고, 각 항목에 다른 형식의 대응 필드를 함께 적는다.
   고르면 필터를 비우고 그 자리로 가서 누른 것과 같이 동작한다. */
let suggestItems = [];
const suggestEl = document.getElementById("suggest");
function buildSuggestIndex() {
  const items = [];
  const sited = new Set([...siteAlias.values()].map(r => r.path));   // 자리마다 따로 싣는 공용 타입 필드
  for (const [path, row] of [...cdxRowByPath].filter(([p]) => !sited.has(p)).concat([...siteAlias])) {
    if (row.parent === "" || row.parent === "(공용 타입)" || !row.name) continue;
    const m = mappingByPath.get(path);
    const targets = m ? getTargets(m) : [];
    items.push({ side: "cdx", key: path, name: row.name, path, isNew: !!row.added,
                 to: targets.map(t => `${t.cls}${t.property ? "." + t.property : ""}`).slice(0, 2) });
  }
  for (const [key, row] of spdxRowByKey) {
    if (!row.property) continue;
    const back = (spdxToCdx.get(key) || []).map(m => m.cdxPath);
    items.push({ side: "spdx", key, name: row.property, path: `${row.class}.${row.property}`, isNew: !!row.added,
                 to: [...new Set(back)].slice(0, 2) });
  }
  suggestItems = items;
}

function showSuggestions() {
  if (!suggestEl) return;
  const q = searchEl.value.trim().toLowerCase();
  if (q.length < 2) return hideSuggestions();
  const rank = it => { const n = it.name.toLowerCase(); return n === q ? 0 : n.startsWith(q) ? 1 : n.includes(q) ? 2 : it.path.toLowerCase().includes(q) ? 3 : 9; };
  const hits = suggestItems.map(it => [rank(it), it]).filter(([r]) => r < 9).sort((a, b) => a[0] - b[0] || a[1].name.length - b[1].name.length).slice(0, 8);
  if (!hits.length) return hideSuggestions();
  suggestEl.innerHTML = hits.map(([, it], i) =>
    `<div class="suggest-item${i === 0 ? " active" : ""}" data-side="${it.side}" data-key="${escapeHtml(it.key)}">` +
    `<span class="suggest-side">${it.side === "cdx" ? "CycloneDX" : "SPDX"}</span>` +
    `<span class="suggest-name">${escapeHtml(it.name)}</span>${it.isNew ? `<span class="new-badge">v0.6</span>` : ""}` +
    `<span class="suggest-path">${escapeHtml(it.path)}</span>` +
    `<span class="suggest-to">${it.to.length ? "→ " + escapeHtml(it.to.join(", ")) : "대응 없음"}</span></div>`).join("");
  suggestEl.classList.remove("hidden");
  for (const el of suggestEl.querySelectorAll(".suggest-item")) {
    el.addEventListener("mousedown", e => { e.preventDefault(); jumpTo(el.dataset.side, el.dataset.key); });
  }
}
function hideSuggestions() { if (suggestEl) { suggestEl.classList.add("hidden"); suggestEl.innerHTML = ""; } }
function onSearchKey(e) {
  if (!suggestEl || suggestEl.classList.contains("hidden")) return;
  const items = [...suggestEl.querySelectorAll(".suggest-item")];
  const cur = items.findIndex(el => el.classList.contains("active"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const next = (cur + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((el, i) => el.classList.toggle("active", i === next));
  } else if (e.key === "Enter" && cur >= 0) {
    e.preventDefault(); jumpTo(items[cur].dataset.side, items[cur].dataset.key);
  } else if (e.key === "Escape") {
    hideSuggestions();
  }
}
/** 제안 항목으로 이동: 필터를 비우고 그 행을 펼쳐 누른다 (대응 필드가 필터에 가려지지 않게). */
function jumpTo(side, key) {
  hideSuggestions();
  searchEl.value = "";
  applyFilter();
  const li = side === "cdx" ? shallowestLi(key) : spdxNodeIndex.get(key);
  if (!li) return;
  expandAncestors(li);
  const div = li.querySelector(":scope > .node-row");
  div.click();
  revealInTree(div);
}

})();
