# 출력 포맷

aibom-cli 는 `--format` 으로 문서 형식을, `--spec` 으로 규제 필드를 넣는 스키마를 고른다. 형식은 CycloneDX(기본)와 SPDX 둘이고,
형식마다 바탕 표준에 그대로 맞추는 스펙과 AI-BOM v0.6 스펙이 있다. AI-BOM v0.6 은 규제가 요구하지만 바탕 표준에 자리가 없는 값을 위해
필드를 더한 스키마라, 바탕 표준의 스키마로는 검증되지 않는다. 검증 스키마는 패키지 안 `schemas/` 폴더에 들어 있다.

| `--format` | `--spec` | 포맷 | 규제 필드 자리 | 검증 스키마 |
|---|---|---|---|---|
| `cyclonedx` (기본) | `1.7` (기본) | CycloneDX 1.7 | 기존 `properties` 배열에 `aibom:` 키로 | `bom-1.7.schema.json` (공식) |
| `cyclonedx` | `v0.6` | AI-BOM v0.6 (CycloneDX) | AI-BOM v0.6 이 더한 정규 필드 | `aibom-v0.6-cyclonedx.schema.json` |
| `spdx` | `3.0.1` (기본) | SPDX 3.0.1 | SPDX 에 자리가 있으면 그 속성에, 없으면 확장(`CdxPropertiesExtension`)에 `aibom:` 키로 | `spdx-3.0.1.schema.json` (공식) |
| `spdx` | `v0.6` | AI-BOM v0.6 (SPDX) | SPDX 에 자리가 있으면 그 속성에, 없으면 AI-BOM v0.6 이 더한 `aibom_` 속성에 | `aibom-v0.6-spdx.schema.json` |

```bash
aibom-cli scan ./project -o bom.cdx.json                              # CycloneDX 1.7. properties 로
aibom-cli scan ./project -o bom.cdx.json --spec v0.6                  # AI-BOM v0.6 (CycloneDX). 정규 필드로
aibom-cli scan ./project -o bom.spdx.json --format spdx               # SPDX 3.0.1. 속성과 확장으로
aibom-cli scan ./project -o bom.spdx.json --format spdx --spec v0.6   # AI-BOM v0.6 (SPDX). 속성으로
```

바탕 표준 스펙(`1.7`, `3.0.1`)은 그 표준을 지원하는 SBOM 도구와 호환되고, `v0.6` 은 규제 필드의 타입과 허용값까지 스키마로 검증한다.

## 규제 필드 자리

하이퍼파라미터를 예로 들면, 같은 모델의 값이 포맷마다 이렇게 달라진다.

```jsonc
// --format cyclonedx --spec 1.7: modelCard.properties
{ "name": "aibom:model:hyperparameters:0:name",  "value": "block_count" },
{ "name": "aibom:model:hyperparameters:0:value", "value": "5" },
{ "name": "aibom:model:hyperparameters:1:name",  "value": "context_length" },
{ "name": "aibom:model:hyperparameters:1:value", "value": "2048" }
```

```jsonc
// --format cyclonedx --spec v0.6: modelCard.modelParameters.hyperparameters
[
  { "name": "block_count",    "value": "5" },
  { "name": "context_length", "value": "2048" }
]
```

```jsonc
// --format spdx: ai_hyperparameter. SPDX 3.0.1 에 자리가 있어 두 스펙이 같다
[
  { "type": "DictionaryEntry", "key": "block_count",    "value": "5" },
  { "type": "DictionaryEntry", "key": "context_length", "value": "2048" }
]
```

파라미터 수처럼 SPDX 3.0.1 에 자리가 없는 값은 `3.0.1` 이면 확장에 `aibom:` 키로, `v0.6` 이면 더한 속성에 들어간다.

```jsonc
// --format spdx --spec 3.0.1: extension
{ "type": "extension_CdxPropertyEntry", "extension_cdxPropName": "aibom:model:parameterCount", "extension_cdxPropValue": "292800" }
```

```jsonc
// --format spdx --spec v0.6
"aibom_parameterCount": 292800
```

각 규제 필드의 뜻과 포맷마다의 이름은 [규제 준수](../compliance/index.md)에 있다.

## CycloneDX 문서의 구조

루트 컴포넌트(`metadata.component`)는 스캔 대상 자체로, 디렉터리면 `application`, 이미지면 `container` 다.
그 아래 `components[]` 는 `component.type` 으로 가른다.

| `component.type` | 뜻 | 도구 |
|---|---|---|
| `library` | 소프트웨어 패키지 | syft |
| `application` | 실행 파일(python, node 같은 바이너리), Hugging Face Space | syft, cdxgen |
| `operating-system` | 이미지의 운영체제 | syft |
| `file` | 패키지 매니페스트, 모델·설정 파일 | syft, cdxgen |
| `machine-learning-model` | 모델 | cdxgen |
| `data` | 데이터셋 | cdxgen, aibom-cli |

코드가 SDK 로 부르는 외부 AI 서비스(OpenAI API 등)는 컴포넌트가 아니라 `services[]` 에 따로 들어간다.
컴포넌트 사이의 관계는 `dependencies` 에 있다. 필드마다 어느 도구가 값을 채우는지는 [필드 탐색기](../compliance/field-mapping.md)에서 본다.

## SPDX 문서의 구조

SPDX 문서는 다 만든 CycloneDX 문서를 마지막에 바꾼 것이라 담긴 값이 같고 모양만 다르다. SPDX 3.0.1 JSON-LD 라 모든 것이 `@graph` 안의 요소다.

| CycloneDX | SPDX |
|---|---|
| 루트 컴포넌트 | `software_Package`. `SpdxDocument.rootElement` 가 가리킨다 |
| `library`, `application`, `operating-system` 컴포넌트 | `software_Package` (`software_primaryPurpose` 로 가른다) |
| `file` | `software_File` |
| `machine-learning-model` | `ai_AIPackage` |
| `data` (데이터셋) | `dataset_DatasetPackage` |
| `services[]` | `software_Package` (SPDX 에 서비스 클래스가 없어 comment 에 service 라고 적는다) |
| `dependencies` | `Relationship` (`dependsOn`) |
| 모델 카드의 학습·평가 데이터셋 (CycloneDX 에는 구분이 없다) | `Relationship` (`trainedOn`, `testedOn`). `dependsOn` 도 그대로 둔다 |
| `pedigree` 의 베이스 모델, 베이스 이미지 | 그 모델·이미지의 요소와 `Relationship` (`descendantOf`) |
| `licenses` | `simplelicensing_LicenseExpression` 요소와 `Relationship` (`hasDeclaredLicense`) |
| `metadata.tools` | `Tool` 요소. `CreationInfo.createdUsing` 이 가리키고, 작성 주체(`createdBy`)는 aibom-cli 다 |
| (CycloneDX 에 없음) 이미지의 `created` 라벨, 허브의 `lastModified` | 루트의 `builtTime`, 허브 모델·데이터셋의 `releaseTime` |
| `bom-ref`, `group`, `tags`, `evidence` 처럼 SPDX 에 자리가 없는 값 | 요소의 `extension` 에 CycloneDX 경로를 이름으로 |

요소의 id 는 문서 일련번호(`urn:uuid:…`) 뒤에 `bom-ref` 를 붙인 것이라, 같은 CycloneDX 문서를 바꾸면 늘 같은 SPDX 가 나온다.
학습·평가 관계와 생성·공개 시각은 CycloneDX 에 자리가 없어, 수집 단계가 메모리로만 들고 가다가 SPDX 로 바꿀 때 더한다.
모델 카드의 `datasets` 와 GGUF 헤더의 `general.datasets` 는 학습, `model-index` 의 데이터셋은 평가다. CycloneDX 출력에는 이 값이 없다.
