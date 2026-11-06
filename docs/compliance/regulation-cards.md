# 규제 판정

만들어진 AI-BOM 이 규제(EU AI Act, NIST AI RMF, ISO/IEC 42001)를 얼마나 만족하는지 조항마다 판정한다. 규제 항목이 어느 필드에 해당하는지는 [필드 탐색기](field-mapping.md)에 있고, 여기서는 BOM 에 그 필드가 채워졌는지를 본다.
EU AI Act 조항은 시스템의 위험 분류와 조직의 역할에 따라 적용이 갈리므로, 판정 화면의 시스템 프로파일에 그것을 적는다 (항목의 뜻은 아래 표). 예제 BOM 세 개를 제공하며, 지금은 CycloneDX 형식(`.cdx.json`)만 판정한다.

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
    <div class="cv-filebar">
      <div class="cv-fileinfo">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3v5h5"/></svg>
        <span class="cv-filename" id="cv-file"></span>
        <span class="cv-filemeta" id="cv-file-meta"></span>
      </div>
      <div class="cv-fileactions">
        <button type="button" class="cv-btn" id="cv-show-bom">원본 JSON</button>
        <button type="button" class="cv-btn" id="cv-another">파일 바꾸기</button>
      </div>
    </div>
    <div class="cv-bom-view" id="cv-bom-view" hidden>
      <div class="cv-bom-head"><span id="cv-bom-info"></span><button type="button" class="cv-btn" id="cv-hide-bom">닫기</button></div>
      <pre id="cv-bom-pre"></pre>
    </div>
    <div class="cv-profile">
      <div class="cv-profile-head"><span class="cv-profile-title">시스템 프로파일</span><span class="cv-muted">EU AI Act 조항의 적용 여부를 가른다. 바꾸면 바로 다시 판정한다</span></div>
      <div class="cv-fields">
        <div class="cv-field">
          <label class="cv-label" for="cv-system">위험 분류 <span class="cv-ref">6조</span></label>
          <select id="cv-system" title="고위험 AI 시스템: 부속서 I 제품의 안전 구성요소이거나 부속서 III 의 분야(생체인식, 핵심 인프라, 교육, 고용, 필수 서비스, 법 집행, 이민, 사법)에 쓰는 시스템">
            <option value="">선택하세요</option>
            <option value="high_risk">고위험 AI 시스템</option>
            <option value="minimal_risk">고위험 아님</option>
          </select>
        </div>
        <div class="cv-field">
          <span class="cv-label">해당 사항 <span class="cv-ref">50조 · 51조</span></span>
          <div class="cv-checks">
            <label title="사람과 직접 상호작용하거나 합성 콘텐츠를 만드는 시스템, 감정 인식·생체 분류·딥페이크 (50조). 고위험 여부와 별개로 더해진다"><input type="checkbox" name="cv-extra" value="limited_risk"> 투명성 의무</label>
            <label title="넓은 범위의 과업을 할 수 있어 여러 시스템에 통합되는 모델 (3조(63), 53조)"><input type="checkbox" name="cv-extra" value="gpai"> 범용 AI 모델</label>
            <label title="범용 AI 모델 중 학습 연산량이 10²⁵ FLOPs 를 넘거나 위원회가 지정한 것 (51조, 55조)"><input type="checkbox" name="cv-extra" value="gpai_systemic"> 체계적 위험</label>
          </div>
        </div>
        <div class="cv-field">
          <span class="cv-label">역할 <span class="cv-ref">3조</span></span>
          <div class="cv-checks">
            <label title="AI 시스템을 개발해 시장에 내놓거나 자기 이름으로 서비스를 개시하는 조직 (3조(3))"><input type="checkbox" name="cv-role" value="provider"> 제공자</label>
            <label title="자기 권한으로 AI 시스템을 사용하는 조직 (3조(4)). 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자"><input type="checkbox" name="cv-role" value="deployer"> 배포자</label>
            <label title="제3국 제공자의 AI 시스템을 EU 시장에 들여오는 조직 (3조(6))"><input type="checkbox" name="cv-role" value="importer"> 수입자</label>
            <label title="제공자·수입자가 아니면서 공급망에서 AI 시스템을 시장에 공급하는 조직 (3조(7))"><input type="checkbox" name="cv-role" value="distributor"> 유통자</label>
          </div>
        </div>
      </div>
      <div class="cv-alert" id="cv-profile-alert" hidden></div>
    </div>
    <div class="cv-results-head">
      <div class="cv-seg" id="cv-reg" role="group" aria-label="규제"></div>
      <span class="cv-muted" id="cv-results-count"></span>
    </div>
    <div class="cv-tiles" id="cv-judg-summary"></div>
    <div class="cv-split">
      <div class="cv-list" id="cv-judg-list"></div>
      <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나온다.</p></div>
    </div>
  </section>
</div>

## 시스템 프로파일

| 항목 | 뜻 | 조항 |
|---|---|---|
| 고위험 AI 시스템 | 부속서 I 의 제품(기계, 의료기기 등)의 안전 구성요소이거나, 부속서 III 의 분야(생체인식, 핵심 인프라, 교육, 고용, 필수 서비스, 법 집행, 이민·국경, 사법·선거)에 쓰는 시스템. 아니면 "고위험 아님" | 6조, 부속서 I·III |
| 투명성 의무 | 사람과 직접 상호작용하거나, 합성 콘텐츠를 만들거나, 감정 인식·생체 분류·딥페이크에 쓰는 시스템에 더해지는 의무. 고위험 여부와 별개다 | 50조 |
| 범용 AI 모델 | 넓은 범위의 과업을 할 수 있어 여러 시스템에 통합되는 모델(기반 모델). 시스템의 위험 분류와 별개로 모델에 걸린다 | 3조(63), 53조, 부속서 XI·XII |
| 체계적 위험 | 범용 AI 모델 중 학습 연산량이 10²⁵ FLOPs 를 넘거나 위원회가 지정한 것. 범용 AI 모델의 의무에 더해진다 | 3조(65), 51조, 55조 |
| 역할 | 제공자: 개발해 시장에 내놓거나 자기 이름으로 서비스를 개시. 배포자: 자기 권한으로 업무에 사용. 수입자: 제3국 제공자의 시스템을 EU 시장에 들여옴. 유통자: 공급망에서 시장에 공급. 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자 | 3조(3)~(7) |
