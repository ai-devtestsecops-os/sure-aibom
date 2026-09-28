# aibom-cli

오픈소스 세 개(syft, cdxgen, OWASP aibom-generator)를 활용해 데이터셋·모델·소프트웨어 BOM(D/M/S-BOM)을 생성하고,
그 위에 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 필드를 더해 CycloneDX 1.7 한 문서로 합친다.
세 도구가 못 채우는 D-BOM 은 자체 생성기가 만든다: 스캔 대상 안의 HuggingFace 데이터셋과 로컬 데이터 파일
(csv, jsonl, parquet, 이미지, 오디오 등)을 D-BOM 컴포넌트로 낸다.

## 파이프라인

| 단계    | 작업                      | 도구                | 커맨드                                                      |
| ------- | ------------------------- | ------------------- | ----------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                | syft                | `syft <target> --select-catalogers -ai -o cyclonedx-json` |
|         | M-BOM · D-BOM 생성       | cdxgen              | `cdxgen <target> -t ai --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합   | **aibom-cli** |                                                             |
| 3. 보강 | D-BOM 보강                | **aibom-cli** |                                                             |
|         | M-BOM 보강                | OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | 규제 필드 추가            | **aibom-cli** | `aibom-cli scan --form properties \| typed`                |
| 4. 검증 | CycloneDX 1.7/AI-BOM v0.6 | **aibom-cli** | `aibom-cli validate --spec 1.7 \| v0.6`                    |

## 설치

Python 3.12 에서 테스트했다. OWASP aibom-generator 의 의존성이 3.12 이상을 요구하므로 그 아래 버전은 지원하지 않는다.

```bash
# 파이썬 환경과 aibom-cli (wheel 파일은 배포 시 함께 전달)
conda create -n aibom-cli python=3.12 && conda activate aibom-cli
pip install aibom_cli-0.1.0-py3-none-any.whl

# syft
curl -sSfL https://get.anchore.io/syft | sh -s -- -b /usr/local/bin

# cdxgen
npm install -g @cyclonedx/cdxgen

# OWASP aibom-generator
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
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 properties로 내보냄
  aibom-cli scan ./project -o bom.cdx.json --form typed       디렉터리를 스캔하여 규제 필드를 v0.6 필드로 내보냄
  
  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  컨테이너 이미지를 스캔 (Docker/Podman 데몬이 없는 경우)
  
  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 스키마로 검증

Flags (scan):
  -o, --output PATH               출력 경로. 없으면 표준출력
  --form {properties,typed}       규제 필드를 내보내는 형태 (default: properties)
                                    properties  CycloneDX의 properties로 내보냄
                                    typed       AI-BOM v0.6 의 필드로 내보냄

Flags (validate):
  --spec {1.7,v0.6}               검증할 스키마 (필수). 1.7 = CycloneDX 1.7, v0.6 = AI-BOM v0.6

Exit codes:
  0  성공        2  도구·입력 문제        3  검증 실패
```

## 규제 필드

`machine-learning-model` 과 `data` 컴포넌트에 AI-BOM v0.6 필드를 채운다. 값은 스캔 결과에 이미 있는 것만 쓰고,
쓴 원본 프로퍼티는 지워 한 값이 두 곳에 나오지 않게 한다. 모델의 properties 형은 `modelCard.properties`,
데이터셋의 properties 형은 `component.properties`, typed 형은 `data[0]` 에 들어간다.

| 필드                  | properties (`--form properties`)                    | typed (`--form typed`)                   |
| --------------------- | ----------------------------------------------------- | ------------------------------------------ |
| hyperparameters       | `aibom:model:hyperparameters:<i>:name` / `:value` | `modelParameters.hyperparameters[]`      |
| parameterCount        | `aibom:model:parameterCount`                        | `modelParameters.parameterCount`         |
| inputs maxSize        | `aibom:model:inputs:0:maxSize`                      | `modelParameters.inputs[0].maxSize`      |
| technicalRequirements | `aibom:model:technicalRequirements:<i>`             | `considerations.technicalRequirements[]` |
| dataset size          | `aibom:dataset:size`                                | `data[0].size`                           |
| dataset modality      | `aibom:dataset:modality:<i>`                        | `data[0].modality[]`                     |
| dataset availability  | `aibom:dataset:availability`                        | `data[0].contents.availability`          |
| dataset provenance    | `aibom:dataset:provenance:<i>`                      | `data[0].provenance[]`                   |
| dataset statistics    | `aibom:dataset:statistics:<i>:type` / `:value`    | `data[0].statistics[]`                   |

데이터셋 값의 출처: HF 데이터셋은 허브 API 의 `dataset_info`(크기, split 별 행 수, feature 수, config 수), `modality:*` 태그(모달리티,
없으면 `task_categories` 로 추론), `gated`(가용성). 로컬 데이터 파일은 파일 크기 합, 확장자(모달리티), 디렉터리 경로(출처), 파일 수·행 수·열 수.
HF 데이터셋의 이름은 허브가 돌려준 정식 id 로 맞추고(`imdb` → `stanfordnlp/imdb`), 같은 데이터셋을 다른 이름으로 부른 참조는 컴포넌트 하나로 모은다.
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
