# aibom-cli

오픈소스 세 개(syft, cdxgen, OWASP aibom-generator)를 활용해 데이터셋·모델·소프트웨어 BOM(D/M/S-BOM)을 생성하고,
그 위에 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 필드를 더해 CycloneDX 1.7 한 문서로 합친다.
세 도구가 못 채우는 D-BOM 은 자체 생성기가 만든다: 스캔 대상 안의 HuggingFace 데이터셋과 로컬 데이터 파일
(csv, jsonl, parquet, 이미지, 오디오 등)을 D-BOM 컴포넌트로 낸다.

## 파이프라인

| 단계    | 작업                        | 도구                  | 커맨드                                                      |
| ------- | --------------------------- | --------------------- | ----------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                  | syft                  | `syft <target> --select-catalogers -ai -o cyclonedx-json` |
|         | M-BOM · D-BOM 생성         | cdxgen                | `cdxgen <target> -t ai --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합     | **aibom-cli**   |                                                             |
| 3. 보강 | D-BOM 보강                  | **aibom-cli**   |                                                             |
|         | M-BOM 보강                  | OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | 규제 필드 추가              | **aibom-cli**   | `aibom-cli scan --form properties \| typed`                |
| 4. 검증 | CycloneDX 1.7 / AI-BOM v0.6 | **aibom-cli**   | `aibom-cli validate --spec 1.7 \| v0.6`                    |

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

## Updates

### 0.1.0

- syft, cdxgen, OWASP aibom-generator 결과를 병합해 CycloneDX 1.7 로 출력
- D-BOM 생성기 추가 (HuggingFace 데이터셋 · 로컬 데이터 폴더)
- 규제 필드 9개 추가 (properties 또는 v0.6 필드)
  - M-BOM: hyperparameters, parameterCount, inputs maxSize, technicalRequirements
  - D-BOM: size, modality, availability, provenance, statistics
- CycloneDX 1.7 / AI-BOM v0.6 스키마 검증

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
