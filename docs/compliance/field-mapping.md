# 필드 레퍼런스

AI-BOM 의 필드를 세 가지로 본다. 이 값이 BOM 의 어디에 들어가는지(구조), CycloneDX 와 SPDX 중 어느 쪽을 써도 같은 정보가 어디로 가는지(형식 대응),
그리고 규제 조항이 어느 필드로 채워지는지(규제와 필드). 각 트리는 표준 그대로에 AI-BOM v0.6 이 더한 필드를 <span class="new-badge">v0.6</span> 로 표시한다.
필드를 누르면 다른 형식의 대응 필드가 켜지고 오른쪽 상세에 설명, 대응, properties 키, 근거 조항이 나온다.

<div class="mapping-viewer" data-base="../../mapping-viewer/data/">
<div id="topbar">
    <div id="search-box" class="mapping-only">
    <svg id="search-icon" viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M11.03 9.62a4.7 4.7 0 1 0-1.41 1.41l3.02 3.02 1.41-1.41-3.02-3.02ZM4 6.7a2.7 2.7 0 1 1 5.4 0 2.7 2.7 0 0 1-5.4 0Z"/></svg>
    <input id="search" type="text" placeholder="필드 이름이나 설명으로 찾기">
  </div>
  <label id="added-only-box" title="AI-BOM v0.6 이 더한 필드와 그 조상만 남긴다"><input id="added-only" type="checkbox"> v0.6 추가 필드만</label>
  <button id="detail-toggle" class="mapping-only" title="상세 패널 열기/닫기">
    <svg viewBox="0 0 16 16" width="15" height="15">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/>
      <rect id="detail-toggle-fill" x="9.7" y="2.5" width="4.8" height="11" fill="currentColor"/>
    </svg>
    <span>상세</span>
  </button>
</div>
<div id="panes" class="tab-view">
  <section class="pane" id="cdx-pane">
    <h2>
      <span class="pane-title">AI-BOM v0.6 (CycloneDX 1.7)</span>
    </h2>
    <div class="tree" id="cdx-tree"></div>
  </section>
  <div class="resizer" data-resize="cdx-pane"></div>
  <section class="pane" id="spdx-pane">
    <h2><span class="pane-title">AI-BOM v0.6 (SPDX 3.0.1)</span></h2>
    <div class="tree" id="spdx-tree"></div>
  </section>
  <div class="resizer" data-resize="detail-panel" data-invert="1"></div>
  <aside id="detail-panel" class="hidden">
    <div id="detail-panel-header">
      <h3>상세</h3>
      <button id="detail-close" title="닫기">✕</button>
    </div>
    <div id="detail-body"></div>
  </aside>
</div>
</div>
