# aibom-cli

syft, cdxgen, OWASP aibom-generator 를 묶어 데이터셋·모델·소프트웨어를 한 AI-BOM 에 담는다.

## 파이프라인

```
입력 (디렉터리 / 이미지)
  ├─ syft   --select-catalogers -ai            → 소프트웨어
  └─ cdxgen -t ai                              → 모델 · 데이터셋 · 관계
        │  pkg:huggingface/… purl 추출
        └─ aibom-generator (HF ID 별)          → 모델 컴포넌트 보강
병합 → CycloneDX 1.7      (검증은 validate 서브커맨드)
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

```bash
aibom-cli scan ./project -o out/bom.cdx.json      # 생성 — CycloneDX 1.7
aibom-cli scan alpine:latest -o out/alpine.cdx.json
aibom-cli validate out/bom.cdx.json               # 검증 — 공식 1.7 에 맞으면 1.7, 아니면 v0.6 스키마로
```

| 서브커맨드 | 옵션 | 뜻 |
|---|---|---|
| `scan <target>` | `-o PATH` | CycloneDX 1.7 출력 경로. 없으면 표준출력 |
| `validate <bom>` | | 통과한 수준을 알려준다 — `1.7`(properties 형, 표준 소비자용) 또는 `v0.6`(typed 형) |

종료 코드: 0 성공 · 2 도구·입력 문제 · 3 검증 실패.
`scan` 은 대상 코드를 실행하지 않는다 (cdxgen 은 `--no-install-deps` 고정).
aibom-generator 보강은 `huggingface.co` 에 닿을 때만 자동으로 하고, `AIBOM_OFFLINE=1` 이면 강제로 생략한다.

## 구조

```
src/aibom_cli/
  cli.py              진입점 — scan · validate
  runners/            syft.py · cdxgen.py · aibom_generator.py (서브프로세스)
  merge.py            CycloneDX 병합 — 키는 purl → hashes → (type,name,version)
  enrich.py           owasp 결과를 HF 모델 컴포넌트에 덧붙임
  spdx/convert.py     CycloneDX 1.7 → SPDX 3.0.1 — 재검증 전이라 CLI 미노출 (_tables · _ids · _props · _modelcard · _datasets)
  validate.py         CycloneDX 검증 — 공식 1.7 → v0.6 순서 (SPDX 검증 함수는 남아 있으나 CLI 미노출)
schemas/              공식 CycloneDX 1.7 + ai-bom/aibom-v0.6 스키마 (참조 파일은 같은 폴더에)
data/cdx_spdx_mapping.json   ai-bom 의 CDX↔SPDX 매핑표 — SPDX 변환기가 참조
```

`schemas/` 와 `data/` 는 `ai-bom` 저장소가 정의를 만들고 이 저장소가 소비한다. 갱신은 복사로 한다.

## 단계

| 단계                                   | 상태                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| 1. syft + cdxgen 병합 → CycloneDX 1.7 | 골격 완료                                                                  |
| 2. aibom-generator 보강                | 골격 완료                                                                  |
| 3. CycloneDX → SPDX 3.0.1 변환기 | 미착수 (초안 코드만 `spdx/` 에 있음, 미검증·CLI 미노출) |
| 4. 규제 모듈 (`regulate`) | 미착수 |
