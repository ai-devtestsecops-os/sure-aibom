# 시작하기

AI-BOM 은 AI 시스템을 이루는 소프트웨어 패키지(S-BOM), 모델(M-BOM), 데이터셋(D-BOM)의 목록이다. aibom-cli 는 디렉터리나
컨테이너 이미지를 스캔해 이 셋을 CycloneDX 문서 하나로 내고, 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 값을
함께 적는다. 이 문서는 설치부터 첫 스캔, 결과 확인, 검증까지를 한 번에 따라가 본다.

## 설치

aibom-cli 가 부르는 도구([syft](https://github.com/anchore/syft), [cdxgen](https://github.com/CycloneDX/cdxgen), crane)는 conda 환경 하나로 받는다.
그 위에 aibom-cli 와 [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator) 를 더한다.

```bash
# 1. 도구 환경
conda env create -f environment.yml
conda activate aibom-cli

# 2. aibom-cli
pip install aibom_cli-0.1.0-py3-none-any.whl

# 3. OWASP aibom-generator (허브 모델 정보를 받아 M-BOM 을 채운다. 커밋 9b8056a 고정)
git clone https://github.com/GenAI-Security-Project/aibom-generator
git -C aibom-generator checkout 9b8056a66c03d4f6cf707059b83b21f97923c27b
pip install -r aibom-generator/requirements.txt

# 4. aibom-generator 위치를 환경에 적고, 환경을 다시 켜서 반영
conda env config vars set AIBOM_GENERATOR_DIR=$PWD/aibom-generator
conda deactivate
conda activate aibom-cli
```

설치가 됐는지 본다.

```bash
aibom-cli --version
```

## 첫 스캔

프로젝트 디렉터리를 스캔해 BOM 파일 하나를 만든다. `-o` 를 빼면 표준출력으로 낸다.

```bash
aibom-cli scan ./project -o bom.cdx.json
```

컨테이너 이미지는 이름이나 `.tar` 파일로 준다. 이미지 이름은 로컬 데몬(Docker, Podman)이나 레지스트리에서 받는다.

```bash
aibom-cli scan python:3.12-slim -o python.cdx.json
aibom-cli scan image.tar -o image.cdx.json
```

코드가 로컬 파일을 데이터로 쓰면 `--data` 로 그 경로를 알려 준다. 여러 번 줄 수 있다.

```bash
aibom-cli scan ./project -o bom.cdx.json --data ./dataset --data ./more/train.csv
```

스캔은 네 단계로 돈다. syft 와 cdxgen 이 각각 S-BOM 과 M-BOM 을 만들고, aibom-cli 가 둘을 합친 뒤 데이터셋과 규제 필드를
채우고, 마지막으로 스키마 검증을 한다. 단계마다 무엇을 찾는지는 [스캔 대상](scan-targets.md)에 있다.

## 결과 살펴보기

결과는 CycloneDX 1.7 JSON 이다. 컴포넌트의 `type` 으로 셋을 가른다.

| `type` | 뜻 | 누가 만드나 |
|---|---|---|
| `library`, `file` | 소프트웨어 패키지와 매니페스트 파일 | syft |
| `machine-learning-model` | 모델 | cdxgen, OWASP aibom-generator |
| `data` | 데이터셋 | aibom-cli |

`jq` 로 종류별로 꺼내 본다.

```bash
# 모델
jq '.components[] | select(.type == "machine-learning-model") | {name, version, purl}' bom.cdx.json

# 데이터셋
jq '.components[] | select(.type == "data") | {name, version, purl}' bom.cdx.json

# 종류별 개수
jq '[.components[].type] | group_by(.) | map({(.[0]): length}) | add' bom.cdx.json
```

모델 카드 정보는 모델 컴포넌트의 `modelCard` 에, 데이터셋 정보는 데이터셋 컴포넌트의 `data` 에 들어 있다.

## 규제 필드를 넣는 두 가지 방식

규제가 요구하지만 CycloneDX 1.7 에 자리가 없는 값(하이퍼파라미터, 파라미터 수, 데이터셋 크기와 출처 등)은 `--spec` 에 따라 두 방식 중 하나로 적는다.

| `--spec` | 어디에 적나 | 검증 스키마 | 고르는 기준 |
|---|---|---|---|
| `1.7` (기본) | 기존 `properties` 배열에 `aibom:` 키로 | 공식 CycloneDX 1.7 | 기존 도구가 그대로 읽어야 할 때 |
| `v0.6` | AI-BOM v0.6 이 더한 전용 필드에 | AI-BOM v0.6 (CycloneDX) | 값의 타입과 허용값을 스키마로 묶고 싶을 때 |

```bash
aibom-cli scan ./project -o bom.cdx.json               # properties 로
aibom-cli scan ./project -o bom.cdx.json --spec v0.6   # v0.6 필드로
```

두 방식의 차이와 각 필드의 뜻은 [규제 준수](../compliance/index.md)에 있다.

## 검증

만든 BOM 을 같은 스키마로 다시 검증할 수 있다. `--spec` 은 필수다.

```bash
aibom-cli validate bom.cdx.json --spec 1.7
aibom-cli validate bom.cdx.json --spec v0.6
```

종료 코드는 셋이다.

| 코드 | 뜻 |
|---|---|
| 0 | 성공 |
| 2 | 실행 오류 (잘못된 인자나 입력, 도구 없음이나 실패) |
| 3 | 스키마 불일치 |

## 다음 단계

- [스캔 대상](scan-targets.md): 디렉터리, 이미지, `.tar`, 로컬 데이터에서 무엇을 어떻게 찾는지
- [규제 준수](../compliance/index.md): 규제가 요구하는 값이 BOM 의 어디에 어떤 이름으로 들어가는지
