# 규제 판정

만들어진 AI-BOM 이 규제(EU AI Act, NIST AI RMF, ISO/IEC 42001)를 얼마나 만족하는지 보여 준다. 규제 항목이 어느 필드에 해당하는지는 [필드 탐색기](field-mapping.md)에 있고, 여기서는 BOM 을 올리면 그 필드들이 채워졌는지를 조항마다 판정한다.
판정은 시스템의 위험등급과 역할(제공자·배포자 등)에 따라 달라지므로, 올린 뒤 고른다. 예제는 위험등급마다 하나씩 손으로 만든 작은 BOM 이다.
지금은 CycloneDX 형식(`.cdx.json`)만 판정한다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <div class="cv-dropzone" id="cv-drop" tabindex="0" role="button" aria-label="BOM 파일 올리기">
    <input id="cv-bom-file" type="file" accept=".json,application/json">
    <div class="cv-drop-icon" aria-hidden="true">⬆</div>
    <div class="cv-drop-main">BOM 파일을 여기에 끌어다 놓거나 <span class="cv-link">클릭해서 고르세요</span></div>
    <div class="cv-drop-examples">예제로 보기: <span id="cv-examples"></span></div>
    <div class="cv-drop-error" id="cv-drop-error" hidden></div>
  </div>
  <div class="cv-main" id="cv-main" hidden>
    <div class="cv-toolbar">
      <span class="cv-file" id="cv-file"></span>
      <button type="button" class="cv-btn" id="cv-show-bom">BOM 보기</button>
      <button type="button" class="cv-btn" id="cv-another">다른 BOM 올리기</button>
      <select id="cv-risk" title="시스템 프로파일: 위험등급">
        <option value="">위험등급 (선택)</option>
        <option value="high_risk">고위험 AI 시스템</option><option value="limited_risk">제한 위험 (투명성 의무)</option>
        <option value="minimal_risk">최소 위험 (EU AI Act 의무 없음)</option><option value="gpai">범용 AI 모델</option><option value="gpai_systemic">범용 AI 모델 (체계적 위험)</option>
      </select>
      <span class="cv-roles" title="시스템 프로파일: 역할 (여럿 가능. 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자)">역할:
        <label><input type="checkbox" name="cv-role" value="provider"> 제공자</label>
        <label><input type="checkbox" name="cv-role" value="deployer"> 배포자</label>
        <label><input type="checkbox" name="cv-role" value="importer"> 수입자</label>
        <label><input type="checkbox" name="cv-role" value="distributor"> 유통자</label>
      </span>
      <select id="cv-reg"></select>
      <select id="cv-verdict-filter">
        <option value="">모든 판정</option>
        <option>반영</option><option>부분 반영</option><option>미반영</option><option>검토 필요</option><option>비적용</option>
      </select>
    </div>
    <div class="cv-bom-view" id="cv-bom-view" hidden>
      <div class="cv-bom-head"><span id="cv-bom-info"></span><button type="button" class="cv-btn" id="cv-hide-bom">닫기</button></div>
      <pre id="cv-bom-pre"></pre>
    </div>
    <div id="cv-judg-summary"></div>
    <div class="cv-split">
      <div class="cv-list" id="cv-judg-list"></div>
      <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나온다.</p></div>
    </div>
  </div>
</div>
