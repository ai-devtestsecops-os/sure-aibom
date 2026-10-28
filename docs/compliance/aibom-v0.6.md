# AI-BOM v0.6 필드

AI-BOM v0.6 은 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하지만 기존 표준에 담을 자리가 없는 값을 위해 CycloneDX 1.7 과 SPDX 3.0.1 에
각각 필드를 더한 스키마 2종이다. 기존 필드의 이름, 타입, 필수 여부는 바꾸지 않고 새 필드를 기존 객체 안에 더하며, 더한 필드는 전부 선택 필드다.
sure-aibom 에서는 `--spec v0.6` 으로 고르고, `--format` 에 따라 CycloneDX 또는 SPDX 로 낸다.

| | CycloneDX 1.7 기반 | SPDX 3.0.1 기반 |
|---|---|---|
| 더한 필드 | 36개 | 29개 |
| 모델 | `component.modelCard` | `ai_AIPackage` |
| 데이터셋 | `component.data` | `dataset_DatasetPackage` |

## 구조

CycloneDX 1.7 기반

![AI-BOM v0.6 구조 (CycloneDX 1.7 기반)](../images/aibom_v0.6_cyclonedx_anatomy.png)

SPDX 3.0.1 기반

![AI-BOM v0.6 구조 (SPDX 3.0.1 기반)](../images/aibom_v0.6_spdx_anatomy.png)

## 지원 현황

v0.6 이 정의한 필드 가운데 sure-aibom 이 스캔 결과로 값을 채우는 것은 열한 개다 (이름은 CycloneDX 기준). 나머지 필드는 순차적으로 지원할 예정이다.

| 대상 | 허브 | 로컬 |
|---|---|---|
| 모델 | hyperparameters, parameterCount, inputs maxSize, technicalRequirements | hyperparameters, parameterCount, inputs maxSize, technicalRequirements |
| 데이터셋 | size, modality, statistics, availability, provenance, intendedUse, collectionProcess | size, modality, statistics |

각 필드가 어느 규제 조항에 근거하는지는 [필드 탐색기](field-mapping.md)에서 볼 수 있다.
