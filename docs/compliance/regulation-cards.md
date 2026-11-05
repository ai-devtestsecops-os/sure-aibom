# 규제 판정

BOM 을 EU AI Act, NIST AI RMF, ISO/IEC 42001 의 조항마다 대 보고, 조항마다 반영 여부와 채울 자리를 보여 준다.
판정 단위는 호다. 항에 (a) (b) 같은 호가 있으면 호마다 따로 판정하고, 항의 종합 판정을 그 위에 보여 준다 (호 판정이 전부 반영이면 반영, 전부 미반영이면 미반영, 섞이면 부분 반영).
sure-aibom 으로 만든 BOM 을 올리거나 예제 BOM 을 고른다. 올린 BOM 은 "BOM 보기" 로 내용을 확인할 수 있고, 시스템 프로파일(위험등급, 역할)을 골라 판정한다. 역할은 여럿을 고를 수 있다 (직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자). 위험등급을 보는 조항(EU AI Act)은 프로파일이 없으면 검토 필요다. 예제 BOM 은 프로파일이 미리 골라져 있고 바꿀 수 있다. 조항을 누르면 그 조항의 원문과, 조항이 요구하는 사실마다 BOM 의 어느 필드에 값이 있었는지가 나온다.
ISO/IEC 42001 은 저작권 때문에 원문을 싣지 않는다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <div class="cv-dropzone" id="cv-drop" tabindex="0" role="button" aria-label="BOM 파일 올리기">
    <input id="cv-bom-file" type="file" accept=".json,application/json">
    <div class="cv-drop-icon" aria-hidden="true">⬆</div>
    <div class="cv-drop-main">BOM 파일을 여기에 끌어다 놓거나 <span class="cv-link">클릭해서 고르세요</span></div>
    <div class="cv-drop-sub">sure-aibom 이 만든 CycloneDX JSON (<code>.cdx.json</code>). 브라우저 안에서만 판정하고 어디로도 보내지 않습니다.</div>
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

| 판정 | 뜻 |
|---|---|
| 반영 | 조항이 요구하는 사실이 BOM 에 모두 있다 |
| 부분 반영 | 일부만 있거나, 값은 있는데 필드의 대상 범위·표현 형태가 요구와 다르다(부분 대응). 비어 있는 사실의 필드가 채울 자리다 |
| 미반영 | 요구하는 사실이 하나도 없다. 필드가 비었거나 BOM 형식(CycloneDX·SPDX)에 담을 자리가 없는 것 모두 누락이다 |
| 검토 필요 | 시스템 프로파일에 위험등급이나 역할이 없어 적용 여부를 알 수 없거나, 조건(예: 개인데이터인지)을 판단할 정보가 BOM 에 없거나, 매핑이 승인되지 않아 판정할 수 없다 |
| 비적용 | 시스템 프로파일의 위험등급이나 역할이 조항의 적용 대상(고위험 AI 시스템의 제공자 등)과 다르다 |

판정 기준은 조항(호)마다 요구 사실을 정리한 규제 카드와, 그 사실을 BOM 필드로 잇는 매핑 프로파일이다. 어느 조항이 어느 필드를 요구하는지는 [필드 탐색기](field-mapping.md)에서 본다.
판정은 적용 여부, 필드에 값이 있는지, 조건(예: 개인데이터인 데이터셋에만 요구) 순서로 보고, 증빙 문서의 내용까지는 보지 않는다. 조건 변수의 필드가 비어 있으면 거짓이고(개인데이터 없음), 필드 자체가 없으면 판단할 수 없어 검토 필요다.
검사 대상은 BOM 의 시스템 자신(`metadata.component`)과 모델·데이터셋 구성요소이고, 관련 소프트웨어를 묻는 사실은 라이브러리 같은 소프트웨어 구성요소에서 본다.
"BOM 파일 올리기" 로 고른 파일은 브라우저 안에서만 판정하고 어디로도 보내지 않는다.
