# aibom-cli

오픈소스 세 개(syft, cdxgen, OWASP aibom-generator)를 활용해 데이터셋·모델·소프트웨어 BOM(D/M/S-BOM)을 생성하고,
그 위에 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 필드를 더해 CycloneDX 1.7 한 문서로 합친다.
세 도구가 못 채우는 데이터셋 BOM 은 자체 생성기가 만든다: 스캔 대상 안의 HuggingFace 데이터셋 참조(모델 README,
파이썬 소스의 `load_dataset`)와 로컬 데이터 파일(csv, jsonl, parquet, 이미지, 오디오 등)을 `type: data` 컴포넌트로 낸다.

## 파이프라인

```
입력 (디렉터리 / 이미지)
  ├─ syft   --select-catalogers -ai            → 소프트웨어
  ├─ cdxgen -t ai                              → 모델 · 데이터셋 · 관계
  │     │  pkg:huggingface/… purl 추출
  │     └─ aibom-generator (HF ID 별)          → 모델 컴포넌트 보강
  └─ 데이터셋 생성기                            → HF 데이터셋 참조 (허브 API 로 보강) · 로컬 데이터 파일
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

`machine-learning-model` 과 `data` 컴포넌트에 AI-BOM v0.6 필드를 채운다. 값은 스캔 결과에 이미 있는 것만 쓰고,
쓴 원본 프로퍼티는 지워 한 값이 두 곳에 나오지 않게 한다. 모델의 properties 형은 `modelCard.properties`,
데이터셋의 properties 형은 `component.properties`, typed 형은 `data[0]` 에 들어간다.

| 필드 | properties (`--form properties`) | typed (`--form typed`) |
|---|---|---|
| hyperparameters | `aibom:model:hyperparameters:<i>:name` / `:value` | `modelParameters.hyperparameters[]` |
| parameterCount | `aibom:model:parameterCount` | `modelParameters.parameterCount` |
| inputs maxSize | `aibom:model:inputs:0:maxSize` | `modelParameters.inputs[0].maxSize` |
| technicalRequirements | `aibom:model:technicalRequirements:<i>` | `considerations.technicalRequirements[]` |
| dataset size | `aibom:dataset:size` | `data[0].size` |
| dataset modality | `aibom:dataset:modality:<i>` | `data[0].modality[]` |
| dataset availability | `aibom:dataset:availability` | `data[0].contents.availability` |
| dataset provenance | `aibom:dataset:provenance:<i>` | `data[0].provenance[]` |
| dataset statistics | `aibom:dataset:statistics:<i>:type` / `:value` | `data[0].statistics[]` |

데이터셋 값의 출처: HF 데이터셋은 허브 API 의 `dataset_info`(크기, split 별 행 수, feature 수, config 수), `task_categories`(모달리티),
`gated`(가용성). 로컬 데이터 파일은 파일 크기 합, 확장자(모달리티), 디렉터리 경로(출처), 파일 수·행 수·열 수.
파일마다 크기, sha256, 형식, 행 수, 열 이름을 `data[].contents.properties` 의 `aibom-cli:file:*` 로 적는다.

## Updates

### 0.1.0
- syft, cdxgen, OWASP aibom-generator 결과를 병합해 CycloneDX 1.7 로 출력
- 모델 규제 필드 4개: hyperparameters, parameterCount, inputs maxSize, technicalRequirements
- 데이터셋 BOM 생성 (HuggingFace 참조 · 로컬 데이터 파일)
- 데이터셋 규제 필드 5개: size, modality, availability, provenance, statistics
- CycloneDX 1.7 / AI-BOM v0.6 스키마 검증

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
