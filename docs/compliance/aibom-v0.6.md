# AI-BOM v0.6

AI-BOM v0.6 은 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하지만 기존 표준에 담을 자리가 없는 값을 위해
CycloneDX 1.7 과 SPDX 3.0.1 에 각각 필드를 더한 스키마 2종이다. 기존 필드의 이름, 타입, 필수 여부는 바꾸지 않고
새 필드를 기존 객체 안에 더하며, 더한 필드는 전부 선택 필드다.

| | CycloneDX 1.7 기반 | SPDX 3.0.1 기반 |
|---|---|---|
| 더한 필드 | 36개 | 29개 |
| 모델 | `component.modelCard` | `ai_AIPackage` |
| 데이터셋 | `component.data` | `dataset_DatasetPackage` |

근거 수(중복 포함)는 EU AI Act 61, NIST AI RMF 9, ISO/IEC 42001 6 이다.

## 두 가지 표현

같은 값을 두 방식으로 쓸 수 있다. aibom-cli 의 `--spec` 이 이것을 고른다.

| `--spec` | 표현 | 검증 |
|---|---|---|
| `1.7` (기본) | 기존 `properties` 배열에 `aibom:` 키로 넣는다 | 공식 CycloneDX 1.7 스키마를 그대로 통과한다 |
| `v0.6` | v0.6 이 정의한 새 필드에 넣는다 | AI-BOM v0.6 (CycloneDX) 스키마로 검증한다 |

properties 형은 기존 도구 생태계가 그대로 읽을 수 있고, 새 필드 형은 값의 타입과 허용값이 스키마로 묶인다.

## 구조

CycloneDX 1.7 기반 (보라: 기존 필드, 빨강: v0.6 이 더한 필드)

![AI-BOM v0.6 구조 (CycloneDX 1.7 기반)](../images/aibom_v0.6_cyclonedx_anatomy.png)

SPDX 3.0.1 기반

![AI-BOM v0.6 구조 (SPDX 3.0.1 기반)](../images/aibom_v0.6_spdx_anatomy.png)

## aibom-cli 가 지금 채우는 필드

v0.6 이 정의한 필드 가운데 aibom-cli 0.1.0 이 실제로 값을 채우는 것은 아홉 개다.

| 대상 | 필드 | 값의 출처 |
|---|---|---|
| 모델 | hyperparameters, parameterCount | 받아 둔 모델의 `config.json`, gguf 헤더, safetensors 헤더 |
| 모델 | inputs maxSize, technicalRequirements | cdxgen 이 읽은 모델 카드와 코드 |
| 데이터셋 | size, modality, availability, provenance, statistics | HuggingFace Hub API (허브 데이터셋), 파일 분석 (로컬 데이터) |

필드가 어디에 붙고 기존 표준의 어느 필드와 대응하는지는 [필드 매핑](field-mapping.md)에서 볼 수 있다.
