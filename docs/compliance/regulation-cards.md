# 규제 판정

BOM 을 EU AI Act, NIST AI RMF, ISO/IEC 42001 의 조항마다 대 보고, 조항마다 반영 여부와 채울 자리를 보여 준다.
판정 단위는 호다. 항에 (a) (b) 같은 호가 있으면 호마다 따로 판정하고, 항의 종합 판정을 그 위에 보여 준다 (호 판정이 전부 반영이면 반영, 전부 미반영이면 미반영, 섞이면 부분 반영).
예제 BOM 을 고르거나 sure-aibom 으로 만든 BOM 을 올린다. 올린 BOM 은 시스템 프로파일(위험등급, 역할)을 골라 판정한다. 위험등급을 보는 조항(EU AI Act)은 프로파일이 없으면 검토 필요다. 예제 BOM 은 정해 둔 프로파일로 미리 판정한 것이라 바꿀 수 없다. 조항을 누르면 그 조항의 원문과, 조항이 요구하는 사실마다 BOM 의 어느 필드에 값이 있었는지가 나온다.
ISO/IEC 42001 은 저작권 때문에 원문을 싣지 않는다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <div class="cv-toolbar">
    <select id="cv-bom"></select>
    <label class="cv-upload">BOM 파일 올리기 <input id="cv-bom-file" type="file" accept=".json"></label>
    <select id="cv-risk" title="시스템 프로파일: 위험등급">
      <option value="">위험등급 (선택)</option>
      <option value="high_risk">고위험 AI 시스템</option><option value="limited_risk">제한 위험 (투명성 의무)</option>
      <option value="minimal_risk">최소 위험 (EU AI Act 의무 없음)</option><option value="gpai">범용 AI 모델</option><option value="gpai_systemic">범용 AI 모델 (체계적 위험)</option>
    </select>
    <select id="cv-role" title="시스템 프로파일: 역할">
      <option value="">역할 (선택)</option>
      <option value="provider">제공자</option><option value="deployer">배포자</option><option value="importer">수입자</option><option value="distributor">유통자</option>
    </select>
    <select id="cv-reg"></select>
    <select id="cv-verdict-filter">
      <option value="">모든 판정</option>
      <option>반영</option><option>부분 반영</option><option>미반영</option><option>검토 필요</option><option>비적용</option>
    </select>
  </div>
  <div id="cv-judg-summary"></div>
  <div class="cv-split">
    <div class="cv-list" id="cv-judg-list"></div>
    <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나온다.</p></div>
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
