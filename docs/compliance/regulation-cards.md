# 규제 카드

규제 조항 하나를 표준 틀로 다시 쓴 것이 규제 카드다. 카드에는 적용대상, 의무주체·행위·대상객체, 조항이 BOM 에 남기라고 요구하는 사실(fact)과 그 원문 구절이 들어 있고, 그 사실이 BOM 의 어느 필드로 가는지는 매핑 프로파일이 안다. 카드와 프로파일을 BOM 에 대면 조항마다 반영 여부가 나온다.

세 화면이 있다. **카드**는 조항별 카드와 원문의 fact 구절, **추출**은 규칙 기반 추출기가 같은 조항에서 낸 초안과 카드의 비교, **판정**은 aibom-cli 가 낸 BOM 에 카드를 댄 결과다. ISO/IEC 42001 은 저작권 때문에 원문과 구절을 싣지 않고 조항 제목과 개념만 보인다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/" data-explorer="../field-mapping/">
<div class="cv-tabs">
  <button class="cv-tab active" data-tab="cards">카드</button>
  <button class="cv-tab" data-tab="extraction">추출</button>
  <button class="cv-tab" data-tab="judgment">판정</button>
</div>

<section class="cv-panel active" data-panel="cards">
  <div class="cv-toolbar">
    <select id="cv-reg"></select>
    <input id="cv-search" type="text" placeholder="조항 번호나 개념으로 찾기" autocomplete="off">
    <span id="cv-count" class="cv-muted"></span>
  </div>
  <div class="cv-split">
    <div class="cv-list" id="cv-card-list"></div>
    <div class="cv-detail" id="cv-card-detail"><p class="cv-muted">왼쪽에서 카드를 고르면 여기에 나온다.</p></div>
  </div>
</section>

<section class="cv-panel" data-panel="extraction">
  <div class="cv-toolbar">
    <select id="cv-ex-reg"></select>
    <span id="cv-ex-summary" class="cv-muted"></span>
  </div>
  <div class="cv-split">
    <div class="cv-list" id="cv-ex-list"></div>
    <div class="cv-detail" id="cv-ex-detail"><p class="cv-muted">카드를 고르면 추출기가 같은 조항에서 낸 초안을 정답과 나란히 보여 준다. 초록은 맞춘 개념, 노랑은 더 낸 개념, 회색은 놓친 개념이다.</p></div>
  </div>
</section>

<section class="cv-panel" data-panel="judgment">
  <div class="cv-toolbar">
    <select id="cv-bom"></select>
    <label class="cv-upload">BOM 파일 올리기 <input id="cv-bom-file" type="file" accept=".json"></label>
    <select id="cv-verdict-filter">
      <option value="">모든 판정</option>
      <option>반영</option><option>부분 반영</option><option>미반영</option><option>검토 필요</option><option>비적용</option>
    </select>
  </div>
  <div id="cv-judg-summary"></div>
  <div class="cv-split">
    <div class="cv-list" id="cv-judg-list"></div>
    <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">카드를 고르면 fact 마다 BOM 어디에 값이 있었는지, 무엇이 비었는지 나온다.</p></div>
  </div>
</section>
</div>

판정은 특허의 순서(적용 여부 → 경로 존재 → 조건 → 증빙) 중 경로 존재까지만 본다. 검사 대상은 BOM 의 시스템 자신(`metadata.component`)과 모델·데이터셋 구성요소다. "BOM 파일 올리기" 로 고른 파일은 브라우저 안에서만 판정하고 어디로도 보내지 않는다.
