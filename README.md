# aibom-cli

aibom-cli 는 디렉터리와 컨테이너 이미지를 스캔해 AI-BOM(D/M/S-BOM) 을 CycloneDX 또는 SPDX 문서 하나로 내는 CLI 도구다.

## 파이프라인

| 단계    | 작업                        | 도구                  | 커맨드                                                      |
| ------- | --------------------------- | --------------------- | ----------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                  | syft                  | `SYFT_COMPLIANCE_MISSING_VERSION=keep syft <target> --select-catalogers -ai -o cyclonedx-json@1.7` |
|         | M-BOM · D-BOM 생성         | cdxgen                | `cdxgen <target> -t ai --spec-version 1.7 --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합     | **aibom-cli**   |                                                             |
| 3. 보강 | M-BOM 보강                  | **aibom-cli**, OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | D-BOM 보강                  | **aibom-cli**   | `aibom-cli scan --data <path>`                            |
|         | 규제 필드 추가              | **aibom-cli**   | `aibom-cli scan --spec 1.7 \| v0.6 \| 3.0.1`               |
| 4. 출력 | SPDX 변환 (선택)            | **aibom-cli**   | `aibom-cli scan --format spdx`                             |
| 5. 검증 | CycloneDX 1.7 / SPDX 3.0.1 / AI-BOM v0.6 | **aibom-cli**   | `aibom-cli validate --spec 1.7 \| v0.6 \| 3.0.1`           |

## 주요 기능

- 오픈소스 도구 활용: S-BOM 은 syft, M-BOM 은 cdxgen 으로 생성하고 aibom-cli 가 정리해 하나로 병합. 허브 모델은 Hub API 와 OWASP aibom-generator 로 보강
- D-BOM 생성: 코드와 모델 카드에서 찾은 HuggingFace 데이터셋은 허브 API 로, `--data` 로 지정한 로컬 데이터는 파일을 직접 읽어 데이터셋 컴포넌트 구성
- 규제 필드 추가: EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 필드를 모델과 데이터셋에 기재
- 출력과 검증: CycloneDX 1.7 또는 SPDX 3.0.1 로 내고(규제 필드는 properties 나 확장에), AI-BOM v0.6 이면 두 형식 모두 v0.6 필드로 낸다. 같은 스키마로 검증

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
  aibom-cli validate <bom> --spec <1.7|v0.6|3.0.1>

Commands:
  scan <target>               디렉터리 또는 컨테이너 이미지를 스캔해 AI-BOM 을 만든다
  validate <bom>              BOM 을 --spec 이 고른 스키마로 검증한다. 형식(CycloneDX, SPDX)은 문서에서 알아낸다

Options:
  -o, --output <path>         [scan] 출력 경로 (default: 표준출력)
  --data <path>               [scan] 로컬 데이터 경로. 여러 번 줄 수 있음 (optional)
  --format <cyclonedx|spdx>   [scan] 출력 형식 (default: cyclonedx)
  --spec <1.7|v0.6|3.0.1>     [scan] 규제 필드를 넣을 스키마 (default: cyclonedx 는 1.7, spdx 는 3.0.1)
                                1.7    CycloneDX 1.7 의 properties 로 넣음
                                3.0.1  SPDX 3.0.1 의 CdxPropertiesExtension 으로 넣음
                                v0.6   AI-BOM v0.6 의 필드로 넣음 (cyclonedx, spdx 모두)
                              [validate] 검증할 스키마 (required)
  -v, --verbose               [scan] 항목별 상세 로그
  --version                   버전을 보여 준다
  -h, --help                  도움말을 보여 준다

Examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  aibom-cli scan ./project -o bom.cdx.json --spec v0.6        디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 (CycloneDX) 필드로 넣음
  aibom-cli scan ./project -o bom.spdx.json --format spdx     SPDX 3.0.1 로 냄
  aibom-cli scan ./project -o bom.spdx.json --format spdx --spec v0.6
                                                              AI-BOM v0.6 (SPDX) 로 냄
  aibom-cli scan ./project -o bom.cdx.json --data ./dataset   로컬 데이터 경로를 함께 지정

  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  이미지 .tar 를 스캔

  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 (CycloneDX) 스키마로 검증
  aibom-cli validate bom.spdx.json --spec 3.0.1               SPDX 3.0.1 스키마로 검증
  aibom-cli validate bom.spdx.json --spec v0.6                AI-BOM v0.6 (SPDX) 스키마로 검증

Exit codes:
  0  성공        2  실행 오류        3  스키마 불일치
```

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
