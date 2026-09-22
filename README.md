# aibom-cli

syft, cdxgen, OWASP aibom-generator 를 묶어 데이터셋·모델·소프트웨어를 한 AI-BOM 에 담는다.

## 파이프라인

```
입력 (디렉터리 / 이미지)
  ├─ syft   --select-catalogers -ai            → 소프트웨어
  └─ cdxgen -t ai --include-formulation        → 모델 · 데이터셋 · 관계
        │  pkg:huggingface/… purl 추출
        └─ aibom-generator (HF ID 별)          → 모델 컴포넌트 보강
병합 → aibom-v0.6 스키마 검증 → CycloneDX 1.7 → (자체 변환) SPDX 3.0.1
```

## 설치

```bash
# conda 환경
conda env create -f environment.yml && conda activate aibom-cli

# syft
curl -sSfL https://get.anchore.io/syft | sh -s -- -b /usr/local/bin

# cdxgen
npm install -g @cyclonedx/cdxgen

# owasp
git clone https://github.com/GenAI-Security-Project/aibom-generator
pip install -r aibom-generator/requirements.txt
conda env config vars set AIBOM_GENERATOR_DIR=$PWD/aibom-generator && conda activate aibom-cli
```

## 사용

```bash
aibom-cli scan ./project --cdx out/bom.cdx.json --spdx out/bom.spdx.json
aibom-cli scan alpine:latest --cdx out/alpine.cdx.json --no-enrich
aibom-cli scan ./project --keep-intermediate out/raw      # 도구별 원본 출력 보존
```

| 옵션 | 뜻 |
|---|---|
| `--cdx PATH` | CycloneDX 1.7 JSON 출력 경로 |
| `--spdx PATH` | SPDX 3.0.1 JSON-LD 출력 경로 (CycloneDX 결과를 변환) |
| `--spdx-strict` | SPDX 출력에서 v0.6 전용 `aibom_*` 속성을 확장 항목으로 내려 공식 3.0.1 스키마에 맞춘다 |
| `--keep-intermediate DIR` | syft·cdxgen·owasp 원본 출력을 이 디렉터리에 남긴다 |
| `--no-syft` / `--no-cdxgen` | 해당 생산자 생략 |
| `--no-enrich` | aibom-generator 보강 생략 |
| `--no-validate` | 스키마 검증 생략 (CycloneDX·SPDX 모두) |
| `--install-deps` | cdxgen 이 락파일 없는 하위 프로젝트에서 설치 명령을 돌리도록 허용 (기본 금지) |
| `--strict` | 도구 실패·검증 실패를 종료 코드로 반영 |

`--cdx` 와 `--spdx` 를 둘 다 생략하면 CycloneDX 를 표준출력으로 낸다.

## 구조

```
src/aibom_cli/
  cli.py              진입점
  runners/            syft.py · cdxgen.py · aibom_generator.py (서브프로세스)
  merge.py            CycloneDX 병합 — 키는 purl → hashes → (type,name,version)
  enrich.py           owasp 결과를 HF 모델 컴포넌트에 덧붙임
  spdx/convert.py     CycloneDX 1.7 → SPDX 3.0.1 (_tables 어휘표 · _ids 식별자 · _props 라우터 · _modelcard · _datasets)
  validate.py         aibom-v0.6 스키마 검증 (CycloneDX draft-07 · SPDX 2020-12 + 참조 무결성)
schemas/              ai-bom/aibom-v0.6 에서 가져온 스키마 (CDX 네 파일은 같은 폴더에)
data/cdx_spdx_mapping.json   ai-bom 의 CDX↔SPDX 매핑표 — SPDX 변환기가 참조
```

`schemas/` 와 `data/` 는 `ai-bom` 저장소가 정의를 만들고 이 저장소가 소비한다. 갱신은 복사로 한다.

## 단계

| 단계                                   | 상태                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| 1. syft + cdxgen 병합 → CycloneDX 1.7 | 골격 완료                                                                  |
| 2. aibom-generator 보강                | 골격 완료                                                                  |
| 3. CycloneDX → SPDX 3.0.1 변환기      | 핵심 완료 — 골격·컴포넌트·modelCard→ai_*/aibom_*·데이터셋·관계·확장·strict 모드. formulation·annotations·services·evidence(hasEvidence) 는 보류 |
| 4. 규제 모듈                           | 미착수                                                                     |
