# 규제 판정

BOM 을 EU AI Act, NIST AI RMF, ISO/IEC 42001 의 조항마다 대 보고, 조항마다 반영 여부와 채울 자리를 보여 준다.
예제 BOM 을 고르거나 sure-aibom 으로 만든 BOM 을 올린다. 조항을 누르면 그 조항의 원문과, 조항이 요구하는 사실마다 BOM 의 어느 필드에 값이 있었는지가 나온다.
ISO/IEC 42001 은 저작권 때문에 원문을 싣지 않는다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <div class="cv-toolbar">
    <select id="cv-bom"></select>
    <label class="cv-upload">BOM 파일 올리기 <input id="cv-bom-file" type="file" accept=".json"></label>
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
| 부분 반영 | 일부만 있다. 비어 있는 사실의 필드가 채울 자리다 |
| 미반영 | 하나도 없다 |
| 검토 필요 | 요구하는 사실이 전부 BOM 형식(CycloneDX·SPDX)에 담을 자리가 없어 BOM 으로는 확인할 수 없다 |
| 비적용 | 시스템의 위험 등급이 조항의 적용 대상과 다르다 |

판정 기준은 조항마다 요구 사실을 정리한 규제 카드와, 그 사실을 BOM 필드로 잇는 매핑 프로파일이다. 어느 조항이 어느 필드를 요구하는지는 [필드 탐색기](field-mapping.md)에서 본다.
판정은 적용 여부, 필드에 값이 있는지, 조건(예: 개인데이터인 데이터셋에만 요구) 순서로 보고, 증빙 문서의 내용까지는 보지 않는다.
검사 대상은 BOM 의 시스템 자신(`metadata.component`)과 모델·데이터셋 구성요소이고, 관련 소프트웨어를 묻는 사실은 라이브러리 같은 소프트웨어 구성요소에서 본다.
"BOM 파일 올리기" 로 고른 파일은 브라우저 안에서만 판정하고 어디로도 보내지 않는다.
