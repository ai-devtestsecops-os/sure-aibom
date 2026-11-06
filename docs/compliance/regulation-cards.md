# 규제 판정

만들어진 AI-BOM 이 규제(EU AI Act, NIST AI RMF, ISO/IEC 42001)를 얼마나 만족하는지 조항마다 판정한다. 규제 항목이 어느 필드에 해당하는지는 [필드 탐색기](field-mapping.md)에 있고, 여기서는 BOM 에 그 필드가 채워졌는지를 본다.
EU AI Act 조항은 시스템의 위험 분류와 조직의 역할에 따라 적용이 갈리므로, 판정 화면에서 그것을 고른다. 예제 BOM 세 개를 제공하며, 지금은 CycloneDX 형식(`.cdx.json`)만 판정한다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <section class="cv-upload" id="cv-upload">
    <div class="cv-dropzone" id="cv-drop" tabindex="0" role="button" aria-label="AI-BOM 파일 올리기">
      <input id="cv-bom-file" type="file" accept=".json,application/json">
      <svg class="cv-drop-icon" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
      <div class="cv-drop-main">AI-BOM 파일을 끌어다 놓거나 <span class="cv-link">파일을 선택</span>하세요</div>
      <div class="cv-drop-sub">CycloneDX JSON (.cdx.json)</div>
      <div class="cv-drop-error" id="cv-drop-error" hidden></div>
    </div>
    <div class="cv-examples-head">예제 BOM</div>
    <div class="cv-examples" id="cv-examples"></div>
  </section>
  <section class="cv-main" id="cv-main" hidden>
    <div class="cv-filebar" id="cv-filebar" title="다른 파일을 여기에 끌어다 놓아도 된다">
      <div class="cv-fileinfo">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3v5h5"/></svg>
        <span class="cv-filename" id="cv-file"></span>
        <span class="cv-filemeta" id="cv-file-meta"></span>
      </div>
      <div class="cv-fileactions">
        <button type="button" class="cv-btn cv-toggle" id="cv-show-bom" aria-expanded="false" aria-controls="cv-bom-view">원본 JSON<svg class="cv-chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6"/></svg></button>
        <button type="button" class="cv-linkbtn" id="cv-another">다른 파일 올리기</button>
      </div>
    </div>
    <div class="cv-bom-view" id="cv-bom-view" hidden><pre id="cv-bom-pre"></pre></div>
    <div class="cv-results-head">
      <div class="cv-seg" id="cv-reg" role="group" aria-label="규제"></div>
      <span class="cv-muted" id="cv-results-count"></span>
    </div>
    <div class="cv-profile" id="cv-profile">
      <div class="cv-profile-head"><span class="cv-profile-title">EU AI Act 적용 조건</span><span class="cv-muted">위험 분류와 역할에 따라 적용되는 조항이 갈린다</span></div>
      <div class="cv-fields">
        <div class="cv-field">
          <label class="cv-label" for="cv-system">위험 분류</label>
          <select id="cv-system" title="고위험 AI 시스템: 부속서 I 제품의 안전 구성요소이거나 부속서 III 의 분야(생체인식, 핵심 인프라, 교육, 고용, 필수 서비스, 법 집행, 이민, 사법)에 쓰는 시스템 (6조)">
            <option value="">선택하세요</option>
            <option value="high_risk">고위험 AI 시스템</option>
            <option value="minimal_risk">고위험 아님</option>
          </select>
        </div>
        <div class="cv-field">
          <span class="cv-label">해당 사항</span>
          <div class="cv-checks">
            <label title="사람과 직접 상호작용하거나 합성 콘텐츠를 만드는 시스템, 감정 인식·생체 분류·딥페이크 (50조). 고위험 여부와 별개로 더해진다"><input type="checkbox" name="cv-extra" value="limited_risk"> 투명성 의무</label>
            <label title="넓은 범위의 과업을 할 수 있어 여러 시스템에 통합되는 모델 (3조(63))"><input type="checkbox" name="cv-extra" value="gpai"> 범용 AI 모델</label>
            <label title="범용 AI 모델 중 학습 연산량이 10²⁵ FLOPs 를 넘거나 위원회가 지정한 것 (3조(65), 51조)"><input type="checkbox" name="cv-extra" value="gpai_systemic"> 체계적 위험</label>
          </div>
        </div>
        <div class="cv-field">
          <span class="cv-label">역할</span>
          <div class="cv-checks">
            <label title="AI 시스템을 개발해 시장에 내놓거나 자기 이름으로 서비스를 개시하는 조직 (3조(3))"><input type="checkbox" name="cv-role" value="provider"> 제공자</label>
            <label title="자기 권한으로 AI 시스템을 사용하는 조직 (3조(4)). 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자"><input type="checkbox" name="cv-role" value="deployer"> 배포자</label>
            <label title="제3국 제공자의 AI 시스템을 EU 시장에 들여오는 조직 (3조(6))"><input type="checkbox" name="cv-role" value="importer"> 수입자</label>
            <label title="제공자·수입자가 아니면서 공급망에서 AI 시스템을 시장에 공급하는 조직 (3조(7))"><input type="checkbox" name="cv-role" value="distributor"> 유통자</label>
          </div>
        </div>
      </div>
      <details class="cv-help">
        <summary><span>항목 설명</span><svg class="cv-chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6"/></svg></summary>
        <dl>
          <dt>고위험 AI 시스템</dt><dd>부속서 I 제품(기계, 의료기기 등)의 안전 구성요소이거나 부속서 III 의 분야(생체인식, 핵심 인프라, 교육, 고용, 필수 서비스, 법 집행, 이민·국경, 사법·선거)에 쓰는 시스템. 둘 다 아니면 "고위험 아님". 6조(1)·(2), 부속서 I·III</dd>
          <dt>투명성 의무</dt><dd>사람과 직접 상호작용하거나(1항), 합성 콘텐츠를 만들거나(2항), 감정 인식·생체 분류(3항)나 딥페이크(4항)에 쓰는 시스템에 더해지는 의무. 고위험 여부와 별개다. 50조(1)~(4)</dd>
          <dt>범용 AI 모델</dt><dd>큰 데이터로 학습해 넓은 범위의 과업을 할 수 있고 여러 시스템에 통합될 수 있는 모델. 3조(63)</dd>
          <dt>체계적 위험</dt><dd>범용 AI 모델의 고영향 역량에서 오는 위험. 학습 연산량이 10²⁵ FLOPs 를 넘으면 그렇다고 추정하고, 위원회가 지정할 수도 있다. 3조(64)·(65), 51조</dd>
          <dt>역할</dt><dd>제공자: 개발해 시장에 내놓거나 자기 이름으로 서비스를 개시 3조(3). 배포자: 자기 권한으로 사용 3조(4). 수입자: 제3국 제공자의 시스템을 EU 시장에 들여옴 3조(6). 유통자: 공급망에서 시장에 공급 3조(7). 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자</dd>
        </dl>
      </details>
      <div class="cv-alert" id="cv-profile-alert" hidden></div>
    </div>
    <div class="cv-tiles" id="cv-judg-summary"></div>
    <div class="cv-split">
      <div class="cv-list" id="cv-judg-list"></div>
      <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나온다.</p></div>
    </div>
  </section>
</div>
