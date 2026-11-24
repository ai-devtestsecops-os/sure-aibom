# 출력 포맷

sure-aibom 은 `--format` 으로 문서 형식(CycloneDX, SPDX)을, `--spec` 으로 스펙(공식 스키마 1.7·3.0.1 또는 AI-BOM v0.6)을 고른다.

## 문서 형식 (`--format`)

CycloneDX 가 기본이고, `--format spdx` 면 CycloneDX 문서를 SPDX 3.0.1 JSON-LD 로 변환해 낸다.

## 스펙 (`--spec`)

형식마다 공식 스키마(CycloneDX 1.7, SPDX 3.0.1)에 그대로 맞추는 스펙과 AI-BOM v0.6 스펙이 있다. AI-BOM v0.6 은 규제가 요구하지만
CycloneDX 1.7 과 SPDX 3.0.1 에 자리가 없는 값을 위해 필드를 더한 스키마라, 공식 스키마로는 검증되지 않는다. 스펙을 고르는 것은 곧 규제 필드를
어디에 넣을지 고르는 것이다.

| `--format` | `--spec` | 포맷 | 규제 필드 자리 | 검증 스키마 |
|---|---|---|---|---|
| `cyclonedx` (기본) | `1.7` (기본) | CycloneDX 1.7 | `properties` 에 `aibom:` 키로 | `bom-1.7.schema.json` (공식) |
| `cyclonedx` | `v0.6` | AI-BOM v0.6 (CycloneDX) | AI-BOM v0.6 이 더한 필드 | `aibom-v0.6-cyclonedx.schema.json` |
| `spdx` | `3.0.1` (기본) | SPDX 3.0.1 | `CdxPropertiesExtension` 에 `aibom:` 키로 | `spdx-3.0.1.schema.json` (공식) |
| `spdx` | `v0.6` | AI-BOM v0.6 (SPDX) | AI-BOM v0.6 이 더한 `aibom_*` 속성 | `aibom-v0.6-spdx.schema.json` |

SPDX 3.0.1 에 자리가 있는 값(하이퍼파라미터, 데이터셋 크기·모달리티 등)은 SPDX 두 스펙 모두 그 속성에 적고, 표의 자리는 나머지 값에 쓴다.

```bash
sure-aibom scan ./project -o bom.cdx.json                              # CycloneDX 1.7
sure-aibom scan ./project -o bom.cdx.json --spec v0.6                  # AI-BOM v0.6 (CycloneDX)
sure-aibom scan ./project -o bom.spdx.json --format spdx               # SPDX 3.0.1
sure-aibom scan ./project -o bom.spdx.json --format spdx --spec v0.6   # AI-BOM v0.6 (SPDX)
```

`1.7` 과 `3.0.1` 은 그 표준을 지원하는 SBOM 도구와 호환되고, `v0.6` 은 규제 필드의 타입과 허용값까지 스키마로 검증한다.
검증 스키마는 패키지 안 `engine/common/schemas/` 폴더에 들어 있다.

파라미터 수를 예로 들면, 같은 모델의 값이 스펙마다 이렇게 달라진다.

```jsonc
// --format cyclonedx --spec 1.7: modelCard.properties
{ "name": "aibom:model:parameterCount", "value": "292800" }
```

```jsonc
// --format cyclonedx --spec v0.6: modelCard.modelParameters
"parameterCount": 292800
```

```jsonc
// --format spdx --spec 3.0.1: extension
{ "type": "extension_CdxPropertyEntry", "extension_cdxPropName": "aibom:model:parameterCount", "extension_cdxPropValue": "292800" }
```

```jsonc
// --format spdx --spec v0.6
"aibom_parameterCount": 292800
```

각 규제 필드의 뜻과 포맷마다의 이름은 [규제 준수](../compliance/index.md)에 있다.
