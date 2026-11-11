---
hide:
  - toc
---

# 규제 판정

만들어진 AI-BOM 이 규제(EU AI Act, NIST AI RMF, ISO/IEC 42001)를 얼마나 만족하는지 조항마다 판정한다. 규제 항목이 어느 필드에 해당하는지는 [필드 탐색기](field-mapping.md)에 있고, 여기서는 BOM 에 그 필드가 채워졌는지와 조항이 요구하는 증빙(사용 설명서, 로그, 선언서 등)이 BOM 에 달려 있는지를 본다.
EU AI Act 조항은 시스템이 고위험인지, 투명성 의무나 범용 AI 모델에 해당하는지, 조직의 역할이 무엇인지에 따라 적용이 갈리므로, 판정 화면에서 그것을 고른다. 조건식과 예외가 보는 부속서 III 분야 · 상황 · 예외 주장도 같은 자리에서 고른다. 예제 BOM 을 CycloneDX 와 SPDX 판으로 세 개씩 제공한다. CycloneDX 1.7 JSON 과 SPDX 3.0.1 JSON-LD 를 받고, 같은 규제 카드를 형식마다 다른 매핑 프로파일로 판정한다.

<div class="card-viewer" data-base="../../mapping-viewer/data/cards/">
  <section class="cv-upload" id="cv-upload">
    <div class="cv-dropzone" id="cv-drop" tabindex="0" role="button" aria-label="AI-BOM 파일 올리기">
      <input id="cv-bom-file" type="file" accept=".json,application/json">
      <svg class="cv-drop-icon" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>
      <div class="cv-drop-main">AI-BOM 파일을 끌어다 놓거나 <span class="cv-link">파일을 선택</span>하세요</div>
      <div class="cv-drop-sub">CycloneDX 1.7 JSON 또는 SPDX 3.0.1 JSON-LD</div>
      <div class="cv-drop-error" id="cv-drop-error" hidden></div>
    </div>
    <div class="cv-examples-head">예제 BOM</div>
    <div class="cv-examples" id="cv-examples"></div>
  </section>
  <section class="cv-main" id="cv-main" hidden>
    <div class="cv-filebar" id="cv-filebar">
      <button type="button" class="cv-filerow" id="cv-show-bom" aria-expanded="false" aria-controls="cv-bom-view">
        <svg class="cv-chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6"/></svg>
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" d="M14 3v5h5"/></svg>
        <span class="cv-filename" id="cv-file"></span>
        <span class="cv-filemeta" id="cv-file-meta"></span>
      </button>
      <button type="button" class="cv-btn" id="cv-another"><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>새 BOM 올리기</button>
    </div>
    <div class="cv-bom-view" id="cv-bom-view" hidden><pre id="cv-bom-pre"></pre></div>
    <div class="cv-profile" id="cv-profile">
      <div class="cv-field cv-field-row">
        <span class="cv-label">규제</span>
        <div class="cv-checks" id="cv-reg" role="group" aria-label="규제"></div>
      </div>
      <div class="cv-eu" id="cv-eu">
        <div class="cv-eu-head"><span class="cv-label">EU AI Act 적용 조건</span><span class="cv-muted">BOM 의 AI 시스템에 해당하는 것을 고르세요</span></div>
        <div class="cv-fields">
          <div class="cv-field">
            <span class="cv-label">시스템 <span class="cv-hint" id="cv-hint-system" hidden><svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M12 3 2.5 20h19L12 3z"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 10v4"/><circle cx="12" cy="17" r="1.1" fill="currentColor"/></svg>고르지 않으면 관련 조항은 검토 필요</span></span>
            <div class="cv-checks">
              <label><input type="checkbox" name="cv-system" value="high_risk"> 고위험 AI 시스템</label>
              <label><input type="checkbox" name="cv-system" value="minimal_risk"> 고위험 아님</label>
              <label><input type="checkbox" name="cv-extra" value="limited_risk"> 투명성 의무</label>
            </div>
          </div>
          <div class="cv-field">
            <span class="cv-label">모델</span>
            <div class="cv-checks">
              <label><input type="checkbox" name="cv-extra" value="gpai"> 범용 AI 모델</label>
              <label><input type="checkbox" name="cv-extra" value="gpai_systemic"> 체계적 위험</label>
            </div>
          </div>
          <div class="cv-field">
            <span class="cv-label">역할 <span class="cv-hint" id="cv-hint-role" hidden><svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M12 3 2.5 20h19L12 3z"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 10v4"/><circle cx="12" cy="17" r="1.1" fill="currentColor"/></svg>고르지 않으면 관련 조항은 검토 필요</span></span>
            <div class="cv-checks">
              <label><input type="checkbox" name="cv-role" value="provider"> 제공자</label>
              <label><input type="checkbox" name="cv-role" value="deployer"> 배포자</label>
              <label><input type="checkbox" name="cv-role" value="importer"> 수입자</label>
              <label><input type="checkbox" name="cv-role" value="distributor"> 유통자</label>
              <label><input type="checkbox" name="cv-role" value="authorised_representative"> 수권대리인</label>
            </div>
          </div>
          <div class="cv-field">
            <span class="cv-label">부속서 III 분야</span>
            <div class="cv-checks"><select id="cv-area" aria-label="부속서 III 분야"></select></div>
          </div>
          <div class="cv-field">
            <span class="cv-label">상황 <span class="cv-muted">모름으로 두면 그 칸을 보는 조항은 검토 필요</span></span>
            <div class="cv-tri" id="cv-flags"></div>
          </div>
          <div class="cv-field">
            <span class="cv-label">예외 주장 <span class="cv-muted">법적 판단이 드는 예외는 주장할 때만 적용</span></span>
            <div class="cv-checks" id="cv-exemptions"></div>
          </div>
        </div>
        <details class="cv-help">
          <summary><span>용어 설명</span><svg class="cv-chev" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6"/></svg></summary>
          <dl>
            <dt>고위험 AI 시스템</dt><dd>부속서 I 제품의 안전 구성요소이거나 부속서 III 의 분야(생체인식, 핵심 인프라, 교육, 고용, 필수 서비스, 법 집행, 이민, 사법)에 쓰는 시스템. 둘 다 아니면 고위험 아님. <span class="cv-ref">6조, 부속서 I·III</span></dd>
            <dt>투명성 의무</dt><dd>사람과 직접 상호작용하거나, 합성 콘텐츠를 만들거나, 감정 인식·생체 분류·딥페이크에 쓰는 시스템에 고위험 여부와 상관없이 더해지는 의무. <span class="cv-ref">50조</span></dd>
            <dt>범용 AI 모델</dt><dd>큰 데이터로 학습해 넓은 범위의 과업을 할 수 있고 여러 시스템에 통합될 수 있는 모델. <span class="cv-ref">3조(63)</span></dd>
            <dt>체계적 위험</dt><dd>범용 AI 모델 가운데 학습 연산량이 10²⁵ FLOPs 를 넘거나 위원회가 지정한 모델에 있다고 보는 위험. <span class="cv-ref">3조(65), 51조</span></dd>
            <dt>역할</dt><dd>제공자는 개발해 시장에 내놓거나 자기 이름으로 서비스를 개시하는 조직, 배포자는 자기 권한으로 사용하는 조직, 수입자는 제3국 제공자의 시스템을 EU 시장에 들여오는 조직, 유통자는 공급망에서 시장에 공급하는 조직, 수권대리인은 EU 밖의 제공자에게서 서면 위임을 받아 EU 안에서 그 의무를 대신하는 조직. 직접 만들어 자기 조직에서 쓰면 제공자이면서 배포자. 조항이 여러 역할에 걸리면(4조 "Providers and deployers") 고른 역할 가운데 하나라도 겹칠 때 적용. <span class="cv-ref">3조(3)~(7)</span></dd>
            <dt>부속서 III 분야</dt><dd>고위험 시스템이 쓰이는 부속서 III 의 분야. 법 집행·이민 분야의 14조(5) 예외와 핵심 기반시설의 27조(1) 예외가 이것으로 갈린다. <span class="cv-ref">부속서 III</span></dd>
            <dt>상황</dt><dd>조건식이 보는 시스템의 사정. 부속서 I 제품 관련(11조(2) 단일 기술문서), 공통 규격 적용(41조(5)), 배포자의 입력 데이터 통제(26조(4)), EU 밖 제공자(수권대리인. 13조(3)(a), 부속서 V·VIII), 편집 보조 기능만(50조(2) 예외). 모름으로 두면 그 칸을 보는 조항은 검토 필요이고, 예외는 해당 없음이다.</dd>
            <dt>예외 주장</dt><dd>법적 판단이 드는 예외(법이 허가한 범죄 수사 시스템, 오픈소스 구성요소를 공개하는 제3자 등)는 BOM 으로 가릴 수 없어, 조직이 주장하는 조항만 비적용으로 본다. <span class="cv-ref">14조(5), 25조(4), 50조(1)·(2)</span></dd>
          </dl>
        </details>
      </div>
    </div>
    <div class="cv-tiles" id="cv-judg-summary"></div>
    <div class="cv-split">
      <div class="cv-list" id="cv-judg-list"></div>
      <div class="cv-detail" id="cv-judg-detail"><p class="cv-muted">조항을 고르면 원문과 요구 사실, 사실마다 BOM 에 값이 있었는지가 나옵니다.</p></div>
    </div>
  </section>
</div>
