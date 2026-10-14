# 출력 포맷

aibom-cli 는 `--spec` 으로 두 출력 포맷 중 하나를 고른다. 둘 다 CycloneDX 1.7 을 바탕으로 한 JSON 문서이고, 규제가 요구하지만
CycloneDX 1.7 에 자리가 없는 값을 어디에 적느냐가 다르다. `v0.6` 은 그 값을 위해 필드를 더하므로 CycloneDX 1.7 스키마로는 검증되지 않는다.
검증 스키마는 패키지 안 `schemas/` 폴더에 들어 있다.

| `--spec` | 포맷 | 규제 필드 자리 | 검증 스키마 | 용도 |
|---|---|---|---|---|
| `1.7` (기본) | CycloneDX 1.7 | 기존 `properties` 배열에 `aibom:` 키로 | `bom-1.7.schema.json` (공식) | CycloneDX 1.7 을 지원하는 SBOM 도구와 호환 |
| `v0.6` | AI-BOM v0.6 (CycloneDX) | AI-BOM v0.6 이 더한 정규 필드 | `aibom-v0.6-cyclonedx.schema.json` | 규제 필드의 타입·허용값까지 스키마로 검증 |

```bash
aibom-cli scan ./project -o bom.cdx.json --spec 1.7    # 기본값. properties 로
aibom-cli scan ./project -o bom.cdx.json --spec v0.6   # 정규 필드로
```

## 규제 필드 자리

하이퍼파라미터를 예로 들면, 같은 모델의 값이 두 포맷에서 이렇게 달라진다.

```jsonc
// --spec 1.7: modelCard.properties
{ "name": "aibom:model:hyperparameters:0:name",  "value": "block_count" },
{ "name": "aibom:model:hyperparameters:0:value", "value": "5" },
{ "name": "aibom:model:hyperparameters:1:name",  "value": "context_length" },
{ "name": "aibom:model:hyperparameters:1:value", "value": "2048" }
```

```jsonc
// --spec v0.6: modelCard.modelParameters.hyperparameters
[
  { "name": "block_count",    "value": "5" },
  { "name": "context_length", "value": "2048" }
]
```

각 규제 필드의 뜻과 두 포맷에서의 이름은 [규제 준수](../compliance/index.md)에 있다.

## 두 포맷의 공통 구조

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
