# aibom-cli

오픈소스 세 개(syft, cdxgen, OWASP aibom-generator)를 활용해 데이터셋·모델·소프트웨어 BOM(D/M/S-BOM)을 생성하고,
그 위에 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 필드를 더해 CycloneDX 1.7 한 문서로 합친다.
세 도구가 못 채우는 데이터셋 BOM 생성기는 별도로 만들어 붙일 예정이다.

## 파이프라인

```
입력 (디렉터리 / 이미지)
  ├─ syft   --select-catalogers -ai            → 소프트웨어
  └─ cdxgen -t ai                              → 모델 · 데이터셋 · 관계
        │  pkg:huggingface/… purl 추출
        └─ aibom-generator (HF ID 별)          → 모델 컴포넌트 보강
병합 → 규제 필드 정규화 → CycloneDX 1.7      (검증은 validate 서브커맨드)
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

```
Usage:
  aibom-cli scan     <TARGET> [flags]
  aibom-cli validate <BOM> --spec {1.7,v0.6}

Examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 properties로 넣음
  aibom-cli scan ./project -o bom.cdx.json --form typed       디렉터리를 스캔하여 규제 필드를 v0.6 필드로 넣음
  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  컨테이너 이미지를 스캔 (Docker/Podman 데몬이 없는 경우)
  aibom-cli scan ./project                                    표준출력으로 출력
  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 스키마로 검증

Flags (scan):
  -o, --output PATH               출력 경로. 없으면 표준출력
      --form {properties,typed}   규제 필드를 내보내는 형태 (default: properties)
                                    properties  CycloneDX의 properties로 내보냄
                                    typed       AI-BOM v0.6 스키마의 필드로 내보냄

Flags (validate):
      --spec {1.7,v0.6}           검증할 스키마 (필수). 1.7 = CycloneDX 1.7, v0.6 = AI-BOM v0.6

Exit codes:
  0  성공        2  도구·입력 문제        3  검증 실패
```

## 규제 필드

`regulation.py` 는 `machine-learning-model` 컴포넌트마다 v0.6 필드 네 개를, 병합 문서에 **이미 있는 프로퍼티 값**으로만 채운다 (조회·추론·본문 해석 없음).

| v0.6 필드 | typed 형 | properties 형 | 원본 (우선순위 순) |
|---|---|---|---|
| hyperparameters | `modelParameters.hyperparameters[]{name,value}` | `aibom:model:hyperparameters:<i>:name` / `:value` | `genai:aibom:modelcard:hyperparameter` (JSON 객체 → 키마다 한 항목) → 키가 없을 때만 `genai:aibom:modelcard:{vocabSize, embeddingLength, blockCount, attentionHeadCount, attentionHeadCountKV, feedForwardLength, ropeDimensionCount}` |
| parameterCount | `modelParameters.parameterCount` (integer) | `aibom:model:parameterCount` | `safetensors_total_parameters` (owasp) → `cdx:ai:parameterCount`. 음이 아닌 정수로 읽히지 않으면 승격하지 않고 원본을 남긴다 |
| inputs maxSize | `modelParameters.inputs[0].maxSize` | `aibom:model:inputs:0:maxSize` | `genai:aibom:modelcard:contextLength` → `cdx:ai:contextWindow` |
| technicalRequirements | `considerations.technicalRequirements[]` | `aibom:model:technicalRequirements:<i>` | `owasp:aibom:distribution:runtimeRequirement` + `cdx:ai:runtime` (둘 다, 중복 제거) |

**승격하면 소비한다.** 값이 목표에 쓰인 원본 프로퍼티는 `component.properties` 와 `modelCard.properties` 양쪽에서 지운다 — 한 값이 출력에 두 번 나오지 않는다. 쓰지 않은 프로퍼티(`syft:*`, 그 밖의 `cdx:*`, `genai:aibom:trainingData*`, `owasp:aibom:distribution:modelFileSize` …)는 그대로 둔다. 원본끼리 값이 다르면 우선순위 앞의 것을 쓰고, 진 쪽 프로퍼티는 남기고 로그에 적는다. 두 번 돌려도 결과가 같다.

**승격한 값 밖은 건드리지 않는다.** 목표에 이미 값이 있으면(정수로 읽히지 않는 `aibom:model:parameterCount` 라도) 그 값이 이기고 원본은 남는다. 목록 필드(hyperparameters, technicalRequirements)는 기존 항목 뒤에 이어 붙이며 — 인덱스를 다시 매기지 않고, 이름·값이 없는 항목(스키마상 둘 다 선택)도 지우지 않는다. 소비해서 비어 버린 `properties` 목록·`modelCard` 만 없애고, 원래 비어 있던 것은 그대로 둔다. 원본이 하나도 없는 컴포넌트는 바이트 단위로 같다.

나머지 v0.6 필드 — 모델 카드 본문(designChoices, trainingTechniques, limitationIdentificationMethods …), 사람이 선언하는 값(sensitivePersonalInformation, safetyRiskAssessment …), 데이터셋 필드(`componentData.*`, `aibom:dataset:*`) — 는 아직 채우지 않는다.

## 구조

```
src/aibom_cli/
  cli.py              진입점 — scan (--form) · validate (--spec)
  runners/            syft.py · cdxgen.py · aibom_generator.py (서브프로세스)
  merge.py            CycloneDX 병합 — 키는 purl → hashes → (type,name,version)
  enrich.py           owasp 결과를 HF 모델 컴포넌트에 덧붙임 (genai:aibom:* · owasp:aibom:* · safetensors_total_parameters)
  regulation.py       v0.6 규제 필드 4개 정규화 — properties 형 / typed 형, 승격한 원본은 소비
  spdx/convert.py     CycloneDX 1.7 → SPDX 3.0.1 — 재검증 전이라 CLI 미노출 (_tables · _ids · _props · _modelcard · _datasets)
  validate.py         CycloneDX 검증 — --spec 이 고른 스키마 하나로 (SPDX 검증 함수는 남아 있으나 CLI 미노출)
schemas/              공식 CycloneDX 1.7 + ai-bom/aibom-v0.6 스키마 (참조 파일은 같은 폴더에)
data/cdx_spdx_mapping.json   ai-bom 의 CDX↔SPDX 매핑표 — SPDX 변환기가 참조
```

`schemas/` 와 `data/` 는 `ai-bom` 저장소가 정의를 만들고 이 저장소가 소비한다. 갱신은 복사로 한다.

## 단계

| 단계                                   | 상태                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| 1. syft + cdxgen 병합 → CycloneDX 1.7 | 골격 완료                                                                  |
| 2. aibom-generator 보강                | 골격 완료                                                                  |
| 3. CycloneDX → SPDX 3.0.1 변환기 | 미착수 (초안 코드만 `spdx/` 에 있음, 미검증·CLI 미노출) |
| 4. 규제 모듈 (`regulation`) | 일부 — 4개 필드 정규화 |

## 출처

- syft — https://github.com/anchore/syft
- cdxgen — https://github.com/CycloneDX/cdxgen
- OWASP aibom-generator — https://github.com/GenAI-Security-Project/aibom-generator
