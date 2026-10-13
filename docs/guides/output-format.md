# 출력 포맷

aibom-cli 는 `--spec` 으로 두 출력 포맷 중 하나를 고른다. 둘 다 CycloneDX 1.7 JSON 문서이고 구조도 같다. 다른 것은 규제가 요구하지만
CycloneDX 1.7 에 자리가 없는 값을 어디에 적느냐다.

| `--spec` | 포맷 | 규제 필드 자리 | 검증 스키마 | 고르는 기준 |
|---|---|---|---|---|
| `1.7` (기본) | CycloneDX 1.7 | 기존 `properties` 배열에 `aibom:` 키로 | 공식 CycloneDX 1.7 | 기존 도구가 그대로 읽어야 할 때 |
| `v0.6` | AI-BOM v0.6 (CycloneDX) | AI-BOM v0.6 이 더한 전용 필드 | AI-BOM v0.6 (CycloneDX) | 값의 타입과 허용값을 스키마로 묶고 싶을 때 |

```bash
aibom-cli scan ./project -o bom.cdx.json --spec 1.7    # 기본값. properties 로
aibom-cli scan ./project -o bom.cdx.json --spec v0.6   # 전용 필드로
```

## 공통 구조

루트 컴포넌트(`metadata.component`)가 스캔 대상 자체다. 디렉터리면 `application`, 이미지면 `container` 다.
그 아래 `components[]` 는 `type` 으로 가른다.

| `type` | 뜻 | 도구 |
|---|---|---|
| `library` | 소프트웨어 패키지 | syft |
| `application` | 실행 파일(busybox 등), Hugging Face Space | syft, cdxgen |
| `operating-system` | 이미지의 운영체제 | syft |
| `file` | 패키지 매니페스트, 모델·설정 파일 | syft, cdxgen |
| `machine-learning-model` | 모델 | cdxgen |
| `data` | 데이터셋 | cdxgen, aibom-cli |

`services[]` 에는 코드가 SDK 로 부르는 외부 AI 서비스(OpenAI API 등)가 들어간다 (cdxgen).
필드마다 어느 도구가 값을 채우는지는 [필드 탐색기](../compliance/field-mapping.md)에서 본다.

모델 카드 정보는 모델 컴포넌트의 `modelCard` 에, 데이터셋 정보는 데이터셋 컴포넌트의 `data[]` 에 들어 있다. `data[]` 의 원소 하나는
데이터의 한 묶음이다. 허브 데이터셋은 데이터셋 전체가 원소 하나이고, 로컬 데이터는 표 파일 하나, 또는 폴더 단위로 묶은 이미지·오디오가
원소 하나다. 어떤 단위로 묶는지는 [수집 항목](collected-items.md#d-bom)에 있다. 컴포넌트 사이의 관계는 `dependencies` 에 있다.

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

## properties

출력의 `properties` 에는 aibom-cli 가 정한 `aibom:` 키만 있다. syft·cdxgen·OWASP aibom-generator 가 properties 로 낸 값은 믿을 만한 것을
정규 필드나 규제 필드로 옮기고, 나머지는 aibom-cli 가 뜻과 값을 관리하지 않으므로 내보내지 않는다.

| 도구 properties | 옮긴 자리 |
|---|---|
| syft `syft:location:<i>:path` (패키지를 찾은 파일) | `evidence.occurrences[].location` |
| syft `syft:image:labels:org.opencontainers.image.*` (이미지 OCI 라벨) | 루트 컴포넌트의 `version`, `description`, `licenses`, `supplier`, `authors`, `externalReferences`(source·url·documentation), `pedigree.ancestors`(base.name·base.digest) |
| cdxgen `cdx:ai:runtime`, `cdx:ai:contextWindow`, `cdx:ai:parameterCount` | 규제 필드 technicalRequirements, inputs maxSize, parameterCount |
| OWASP aibom-generator 하이퍼파라미터(`genai:aibom:modelcard:hyperparameter` 등), contextLength, runtimeRequirement, `safetensors_total_parameters` | 규제 필드 hyperparameters, inputs maxSize, technicalRequirements, parameterCount |

내보내지 않는 것은 syft 의 CPE 후보·카탈로거 이름·패키지 메타데이터, cdxgen 의 탐지 정보·GGUF 토크나이저 정보·라이선스 분류·co2 배출량,
OWASP aibom-generator 의 학습 데이터 확인·파일 크기 등이다. co2 배출량은 CycloneDX `energyConsumptions` 가 에너지 공급자와 사용량을
필수로 요구해 옮길 수 없다.

## 도구 값 정리

aibom-cli 는 도구 출력에서 틀리거나 자리표시자인 값을 고친다. 고친 값의 출처는 그 도구로 본다.

| 도구 | 고치는 것 |
|---|---|
| syft | 버전을 못 찾은 패키지에 `UNKNOWN` 을 적지 않고 비워 둔다. 알아보지 못한 라이선스 본문의 해시(`sha256:…`)를 이름으로 적은 라이선스는 뺀다. npm 의 `repository.url` 은 `vcs`, apk 의 프로젝트 주소는 `website` 로 종류를 바꾸고, pip 로컬 설치의 `file://` 주소는 뺀다. jar 해시는 `hashes` 로 옮긴다 |
| cdxgen | 이름의 공백이 두 번 인코딩된 purl(`%2520`)을 고친다. Modelfile 의 `FROM ./x.gguf` 를 허브 id 로 읽어 만든 가짜 허브 모델은 그 GGUF 모델에 합치고, `LICENSE """` 다음 줄에서 시작하는 라이선스는 본문 첫 줄을 이름으로 쓴다. SDK import 없이 지어낸 서비스(`google-bert-service`, `ollama-service` 등)와 서비스의 고정 버전 `observed` 는 뺀다. 계보(`pedigree`) 안의 `bom-ref` 는 최상위 컴포넌트와 겹쳐 뺀다 |
| cdxgen (데이터셋) | 코드의 링크로 만든 데이터셋을 알아봐 허브 조회한다. 이름만 있는 id 의 `datasets/datasets/<이름>` 주소는 정식 주소로 고친다. 모델 카드의 데이터셋을 모델의 `modelCard.modelParameters.datasets` 에 모두 적는다 (cdxgen 은 하나만 남긴다) |
| OWASP aibom-generator | 규제 필드 원본만 가져온다. 값이 없을 때 채우는 고정값(설명 `No description available`, task `text-generation`, 구조 `transformer`)과 README 를 잘라 만든 값, 허브에 없는 저장소의 결과는 쓰지 않는다 |
