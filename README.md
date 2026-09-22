# aibom-cli

syft, cdxgen, OWASP aibom-generator 를 묶어 데이터셋·모델·소프트웨어를 한 AI-BOM 에 담는다.

## 파이프라인

```
입력 (디렉터리 / 이미지)
  ├─ syft   --select-catalogers -ai            → 소프트웨어
  └─ cdxgen -t ai --include-formulation        → 모델 · 데이터셋 · 관계
        │  pkg:huggingface/… purl 추출
        └─ aibom-generator (HF ID 별)          → 모델 컴포넌트 보강
병합 → CycloneDX 1.7      (검증·SPDX 변환은 별도 서브커맨드)
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
aibom-cli scan ./project -o out/bom.cdx.json            # 생성 — CycloneDX 1.7
aibom-cli scan alpine:latest -o out/alpine.cdx.json --no-enrich
aibom-cli validate out/bom.cdx.json                     # 검증 — aibom-v0.6 스키마
aibom-cli convert out/bom.cdx.json -o out/bom.spdx.json # SPDX 3.0.1 (실험 단계)
aibom-cli validate out/bom.spdx.json --strict           # 공식 3.0.1 스키마로 검증
```

| 서브커맨드 | 옵션 | 뜻 |
|---|---|---|
| `scan <target>` | `-o PATH` | CycloneDX 1.7 출력 경로. 없으면 표준출력 |
| | `--no-enrich` | aibom-generator 보강 생략 (HF 네트워크가 없을 때) |
| `validate <bom>` | `--strict` | SPDX 를 v0.6 대신 공식 3.0.1 스키마로. CycloneDX/SPDX 는 내용으로 판별 |
| `convert <bom>` | `-o PATH` | SPDX 3.0.1 JSON-LD 출력 경로. 없으면 표준출력 |
| | `--strict` | v0.6 전용 `aibom_*` 속성을 확장 항목으로 내려 공식 3.0.1 에 맞춘다 |

종료 코드: 0 성공 · 2 도구·입력 문제 · 3 검증 실패.
`scan` 은 대상 코드를 실행하지 않는다 (cdxgen 은 `--no-install-deps` 고정).

## 구조

```
src/aibom_cli/
  cli.py              진입점 — scan · validate · convert
  runners/            syft.py · cdxgen.py · aibom_generator.py (서브프로세스)
  merge.py            CycloneDX 병합 — 키는 purl → hashes → (type,name,version)
  enrich.py           owasp 결과를 HF 모델 컴포넌트에 덧붙임
  spdx/convert.py     CycloneDX 1.7 → SPDX 3.0.1 (_tables 어휘표 · _ids 식별자 · _props 라우터 · _modelcard · _datasets)
  validate.py         aibom-v0.6 스키마 검증 (CycloneDX draft-07 · SPDX 2020-12 + 참조 무결성)
schemas/              ai-bom/aibom-v0.6 에서 가져온 스키마 (CDX 네 파일은 같은 폴더에)
data/cdx_spdx_mapping.json   ai-bom 의 CDX↔SPDX 매핑표 — SPDX 변환기가 참조
```

`schemas/` 와 `data/` 는 `ai-bom` 저장소가 정의를 만들고 이 저장소가 소비한다. 갱신은 복사로 한다.

## 단계

| 단계                                   | 상태                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------- |
| 1. syft + cdxgen 병합 → CycloneDX 1.7 | 골격 완료                                                                  |
| 2. aibom-generator 보강                | 골격 완료                                                                  |
| 3. CycloneDX → SPDX 3.0.1 변환기 (`convert`) | **실험 단계** — 구현 완료, 3라운드 재검증 대기. formulation·annotations·services·evidence 는 보류 |
| 4. 규제 모듈                           | 미착수                                                                     |
