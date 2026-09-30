# aibom-cli

aibom-cli 는 디렉터리와 컨테이너 이미지를 스캔해 AI-BOM(D/M/S-BOM) 을 CycloneDX 문서 하나로 내는 CLI 도구다.

## 파이프라인

| 단계    | 작업                        | 도구                  | 커맨드                                                      |
| ------- | --------------------------- | --------------------- | ----------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                  | syft                  | `syft <target> --select-catalogers -ai -o cyclonedx-json` |
|         | M-BOM · D-BOM 생성         | cdxgen                | `cdxgen <target> -t ai --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합     | **aibom-cli**   |                                                             |
| 3. 보강 | D-BOM 보강                  | **aibom-cli**   | `aibom-cli scan --data <path>`                            |
|         | M-BOM 보강                  | OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | 규제 필드 추가              | **aibom-cli**   | `aibom-cli scan --spec 1.7 \| v0.6`                        |
| 4. 검증 | CycloneDX 1.7 / AI-BOM v0.6 | **aibom-cli**   | `aibom-cli validate --spec 1.7 \| v0.6`                    |

## 주요 기능

- 오픈소스 도구 활용: S-BOM 은 syft, M-BOM 은 cdxgen, 허브 모델 정보는 OWASP aibom-generator 로 생성하고 aibom-cli 가 하나로 병합
- D-BOM 생성: 코드와 모델 카드에서 찾은 HuggingFace 데이터셋은 허브 API 로, `--data` 로 지정한 로컬 데이터는 파일을 직접 읽어 데이터셋 컴포넌트 구성
- 규제 필드 추가: EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 필드를 모델과 데이터셋에 기재
- 출력과 검증: CycloneDX 1.7 (properties) 또는 AI-BOM v0.6 (필드) 형식으로 출력하고 같은 스키마로 검증

## 설치

```bash
# 환경 세팅 및 aibom-cli 설치 (conda 예시)
conda env create -f environment.yml
conda activate aibom-cli
pip install aibom_cli-0.1.0-py3-none-any.whl

# OWASP aibom-generator (커밋 9b8056a)
git clone https://github.com/GenAI-Security-Project/aibom-generator
git -C aibom-generator checkout 9b8056a66c03d4f6cf707059b83b21f97923c27b
pip install -r aibom-generator/requirements.txt

# aibom-generator 경로를 환경변수에 저장하고, 환경을 다시 켜서 반영
conda env config vars set AIBOM_GENERATOR_DIR=$PWD/aibom-generator
conda deactivate
conda activate aibom-cli
```

## 사용

```
    ___    ________  ____  __  ___   ________    ____
   /   |  /  _/ __ )/ __ \/  |/  /  / ____/ /   /  _/
  / /| |  / // __  / / / / /|_/ /  / /   / /    / /
 / ___ |_/ // /_/ / /_/ / /  / /  / /___/ /____/ /
/_/  |_/___/_____/\____/_/  /_/   \____/_____/___/

Usage:
  aibom-cli scan <target> [options]
  aibom-cli validate <bom> --spec <1.7|v0.6>

Commands:
  scan <target>               디렉터리 또는 컨테이너 이미지를 스캔해 AI-BOM 을 만든다
  validate <bom>              BOM 을 --spec 이 고른 스키마로 검증한다

Options:
  -o, --output <path>         [scan] 출력 경로 (default: 표준출력)
  --data <path>               [scan] 로컬 데이터 경로. 여러 번 줄 수 있음 (optional)
  --spec <1.7|v0.6>           [scan] 규제 필드를 넣을 스키마 (default: 1.7)
                                1.7   CycloneDX 1.7 의 properties 로 넣음
                                v0.6  AI-BOM v0.6 (CycloneDX) 의 필드로 넣음
                              [validate] 검증할 스키마 (required)
  --version                   버전을 보여 준다
  -h, --help                  도움말을 보여 준다

Examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  aibom-cli scan ./project -o bom.cdx.json --spec v0.6        디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 (CycloneDX) 필드로 넣음
  aibom-cli scan ./project -o bom.cdx.json --data ./dataset   로컬 데이터 경로를 함께 지정

  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  이미지 .tar 를 스캔

  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 (CycloneDX) 스키마로 검증

Exit codes:
  0  성공        2  실행 오류        3  스키마 불일치
```

## Updates

### 0.1.0

- syft, cdxgen, OWASP aibom-generator 결과를 병합해 CycloneDX 1.7 로 출력
- D-BOM 생성기 추가 (HuggingFace 데이터셋 · 로컬 데이터 폴더)
- 규제 필드 9개 추가 (properties 또는 v0.6 필드)
  - M-BOM: hyperparameters, parameterCount, inputs maxSize, technicalRequirements
  - D-BOM: size, modality, availability, provenance, statistics
- CycloneDX 1.7 / AI-BOM v0.6 (CycloneDX) 스키마 검증

## 추가 예정

- SPDX 3.0.1 출력
- 규제 완성도: 규제별로 요구 필드 중 채워진 것과 빈 것 표시
- 스캔 대상 문서: 디렉터리와 컨테이너 이미지에서 무엇을 어떻게 찾는지에 대한 상세 설명

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
