# 시작하기

AI-BOM 은 AI 시스템을 이루는 소프트웨어 패키지(S-BOM), 모델(M-BOM), 데이터셋(D-BOM)의 목록이다. aibom-cli 는 디렉터리나
컨테이너 이미지를 스캔해 이 셋을 CycloneDX 문서 하나로 내고, 규제(EU AI Act, ISO/IEC 42001, NIST AI RMF)가 요구하는 값을
함께 적는다. 이 문서는 설치부터 생성, 출력 확인, 검증까지를 한 번에 따라가 본다.

## 설치

실행에 필요한 도구는 conda 환경으로 받고, 그 위에 aibom-cli 를 설치한다.
OWASP aibom-generator 는 패키지로 배포되지 않아 저장소를 받아 두고, 그 위치를 환경 변수로 알려 준다.

```bash
# 1. 도구 환경 세팅
conda env create -f environment.yml
conda activate aibom-cli

# 2. aibom-cli 설치
pip install aibom_cli-0.1.0-py3-none-any.whl

# 3. OWASP aibom-generator 설치 (커밋 9b8056a 고정)
git clone https://github.com/GenAI-Security-Project/aibom-generator
git -C aibom-generator checkout 9b8056a66c03d4f6cf707059b83b21f97923c27b
pip install -r aibom-generator/requirements.txt

# 4. aibom-generator 위치를 환경 변수에 저장 (환경을 다시 켜서 반영)
conda env config vars set AIBOM_GENERATOR_DIR=$PWD/aibom-generator
conda deactivate
conda activate aibom-cli
```

설치를 확인한다.

```bash
aibom-cli --version
```

## 생성

프로젝트 디렉터리를 스캔해 AI-BOM 파일 하나를 만든다. `-o` 를 빼면 표준출력으로 낸다.

```bash
aibom-cli scan ./project -o bom.cdx.json
```

컨테이너 이미지는 이름이나 아카이브(`.tar`)를 그대로 준다.

```bash
aibom-cli scan python:3.12-slim -o python.cdx.json
```

입력으로 무엇을 줄 수 있는지는 [스캔 대상](scan-targets.md)에, 그 안에서 무엇을 찾는지는 [수집 항목](collected-items.md)에,
결과 문서의 구조와 `--spec` 으로 고르는 두 가지 규제 필드 자리는 [출력 포맷](output-format.md)에 있다.

## 출력 확인

생성된 BOM 은 JSON 파일이라 [jq](https://jqlang.org/) 로 원하는 정보만 간단히 꺼내 볼 수 있다. 컴포넌트 이름을 뽑으면 무엇이 잡혔는지 바로 보인다.

```bash
jq '.components[].name' bom.cdx.json
```

```
"numpy"
"transformers"
"llama"
"bert-base-uncased"
"bookcorpus"
"imdb"
...
```

`type` 을 함께 출력하면 패키지, 모델, 데이터셋이 구분된다.

```bash
jq -r '.components[] | "\(.type)\t\(.name)"' bom.cdx.json
```

```
library                 numpy
library                 transformers
machine-learning-model  llama
machine-learning-model  bert-base-uncased
data                    bookcorpus
data                    imdb
...
```

컴포넌트 종류와 각 정보가 문서의 어디에 들어가는지는 [출력 포맷](output-format.md)에 있다.

## 검증

생성된 AI-BOM 을 같은 스키마로 다시 검증할 수 있다. `--spec` 은 필수다.

```bash
aibom-cli validate bom.cdx.json --spec 1.7
aibom-cli validate bom.cdx.json --spec v0.6
```
