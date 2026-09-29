# aibom-cli

aibom-cli 는 syft, cdxgen, OWASP aibom-generator 를 활용해 데이터셋·모델·소프트웨어 BOM(D/M/S-BOM)을 생성한다.
스캔 대상에서 찾은 HuggingFace 데이터셋은 허브에서 정보를 받아 채우고, `--data` 로 지정한 로컬 데이터 파일은 직접 읽어
D-BOM 을 보강한 뒤, 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 필드를 더해 CycloneDX 1.7 한 문서로 낸다.

## 파이프라인

| 단계    | 작업                        | 도구                  | 커맨드                                                      |
| ------- | --------------------------- | --------------------- | ----------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                  | syft                  | `syft <target> --select-catalogers -ai -o cyclonedx-json` |
|         | M-BOM · D-BOM 생성         | cdxgen                | `cdxgen <target> -t ai --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합     | **aibom-cli**   |                                                             |
| 3. 보강 | D-BOM 보강                  | **aibom-cli**   | `aibom-cli scan --data <path>`                              |
|         | M-BOM 보강                  | OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | 규제 필드 추가              | **aibom-cli**   | `aibom-cli scan --spec 1.7 \| v0.6`                        |
| 4. 검증 | CycloneDX 1.7 / AI-BOM v0.6 | **aibom-cli**   | `aibom-cli validate --spec 1.7 \| v0.6`                    |

## 설치

사전 설치: Node.js 20 이상, git

```bash
# 파이썬 환경과 aibom-cli (conda 예시)
conda create -n aibom-cli python=3.12 && conda activate aibom-cli
pip install aibom_cli-0.1.0-py3-none-any.whl

# syft 1.52.0
curl -sSfL https://get.anchore.io/syft | sh -s -- -b /usr/local/bin v1.52.0

# cdxgen 12.8.4
npm install -g @cyclonedx/cdxgen@12.8.4

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
  scan <target>               디렉터리, 컨테이너 이미지 또는 이미지 .tar 를 스캔해 AI-BOM 을 만든다
  validate <bom>              BOM 을 --spec 이 고른 스키마로 검증한다

Options:
  -o, --output <path>         [scan] 출력 경로. 없으면 표준출력
  --data <path>               [scan] 로컬 데이터 경로. 여러 번 줄 수 있음 (없으면 로컬 데이터는 넣지 않음)
  --spec <1.7|v0.6>           [scan] 규제 필드를 넣을 스키마 (default: 1.7)
                                1.7   CycloneDX 1.7 의 properties 로 넣음
                                v0.6  AI-BOM v0.6 의 필드로 넣음 (문서의 specVersion 은 1.7 그대로)
                              [validate] 검증할 스키마 (필수)
  --version                   버전을 보여 준다
  -h, --help                  도움말을 보여 준다

Examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  aibom-cli scan ./project -o bom.cdx.json --spec v0.6        디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 필드로 넣음
  aibom-cli scan ./project -o bom.cdx.json --data ./dataset   로컬 데이터 경로를 함께 지정

  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  컨테이너 이미지를 스캔 (Docker/Podman 데몬이 없는 경우)

  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 스키마로 검증

Environment:
  AIBOM_GENERATOR_DIR         OWASP aibom-generator 클론 경로. 없으면 모델 보강을 건너뜀

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
- CycloneDX 1.7 / AI-BOM v0.6 스키마 검증

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
