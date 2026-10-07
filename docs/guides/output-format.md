# 출력 포맷

aibom-cli 의 결과는 CycloneDX 1.7 JSON 문서 하나다. `--spec` 은 규제 필드를 그 문서의 어디에 적을지만 고른다.

## 문서 구조

루트 컴포넌트(`metadata.component`)가 스캔 대상 자체다. 디렉터리면 `application`, 이미지면 `container` 다.
그 아래 `components[]` 는 `type` 으로 가른다.

| `type` | 뜻 | 누가 만드나 |
|---|---|---|
| `library` | 소프트웨어 패키지 | syft, cdxgen |
| `file` | 패키지 매니페스트, 모델·설정 파일 | syft, cdxgen |
| `machine-learning-model` | 모델 | cdxgen, OWASP aibom-generator |
| `data` | 데이터셋 | aibom-cli |

모델 카드 정보는 모델 컴포넌트의 `modelCard` 에, 데이터셋 정보는 데이터셋 컴포넌트의 `data` 에 들어 있다.
컴포넌트 사이의 관계는 `dependencies` 에 있다.

## 규제 필드의 두 자리

규제가 요구하지만 CycloneDX 1.7 에 자리가 없는 값은 `--spec` 에 따라 두 곳 중 하나에 적는다. 어느 쪽이든 문서는 CycloneDX 1.7 이고
`specVersion` 도 `1.7` 이다.

| `--spec` | 규제 필드 자리 | 검증 스키마 | 고르는 기준 |
|---|---|---|---|
| `1.7` (기본) | 기존 `properties` 배열에 `aibom:` 키로 | 공식 CycloneDX 1.7 | 기존 도구가 그대로 읽어야 할 때 |
| `v0.6` | AI-BOM v0.6 이 더한 전용 필드 | AI-BOM v0.6 (CycloneDX) | 값의 타입과 허용값을 스키마로 묶고 싶을 때 |

```bash
aibom-cli scan ./project -o bom.cdx.json               # 1.7: properties 로
aibom-cli scan ./project -o bom.cdx.json --spec v0.6   # v0.6: 전용 필드로
```

같은 모델의 하이퍼파라미터가 두 포맷에서 이렇게 달라진다.

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

규제 필드 하나하나의 뜻과 두 방식에서의 이름은 [규제 준수](../compliance/index.md)에 있다.

## jq 로 꺼내 보기

```bash
# 모델
jq '.components[] | select(.type == "machine-learning-model") | {name, version, purl}' bom.cdx.json

# 데이터셋
jq '.components[] | select(.type == "data") | {name, version, purl}' bom.cdx.json

# 종류별 개수
jq '[.components[].type] | group_by(.) | map({(.[0]): length}) | add' bom.cdx.json

# 규제 필드 (--spec 1.7 로 냈을 때)
jq '.components[] | select(.type == "machine-learning-model") | .modelCard.properties[]? | select(.name | startswith("aibom:"))' bom.cdx.json
```
