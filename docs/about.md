# 소개

aibom-cli 는 기존 오픈소스 도구가 잘하는 부분은 그대로 쓰고, 빠진 부분만 직접 채운다. S-BOM 은 syft, M-BOM 은 cdxgen,
허브 모델 정보는 OWASP aibom-generator 가 만들고, D-BOM 생성과 규제 필드 추출, 병합과 검증은 aibom-cli 가 맡는다.

## 파이프라인

![aibom-cli 파이프라인](images/cli_pipeline.png)

| 단계    | 작업                        | 도구                  | 커맨드                                                    |
| ------- | --------------------------- | --------------------- | --------------------------------------------------------- |
| 1. 스캔 | S-BOM 생성                  | syft                  | `syft <target> --select-catalogers -ai -o cyclonedx-json` |
|         | M-BOM · D-BOM 생성          | cdxgen                | `cdxgen <target> -t ai --no-install-deps`                 |
| 2. 병합 | 하나의 json 파일로 병합     | aibom-cli             |                                                           |
| 3. 보강 | D-BOM 보강                  | aibom-cli             | `aibom-cli scan --data <path>`                            |
|         | M-BOM 보강                  | OWASP aibom-generator | `python -m src.cli <owner/model>`                         |
|         | 규제 필드 추가              | aibom-cli             | `aibom-cli scan --spec 1.7 \| v0.6`                       |
| 4. 검증 | CycloneDX 1.7 / AI-BOM v0.6 | aibom-cli             | `aibom-cli validate --spec 1.7 \| v0.6`                   |

컨테이너 이미지는 syft 가 그대로 스캔하고, M-BOM · D-BOM 단계는 이미지를 푼 디렉터리에 대해 돌린다
(cdxgen 은 이미지를 받으면 AI 수집을 건너뛴다). 자세한 것은 [스캔 대상](guides/scan-targets.md)에 있다.

## 각 단계가 하는 일

- **S-BOM 생성 (syft)**: 패키지 매니페스트와 설치된 패키지에서 소프트웨어 컴포넌트를 찾는다.
- **M-BOM 생성 (cdxgen)**: 코드의 `from_pretrained` 호출, 받아 둔 모델 폴더, gguf, Modelfile 에서 모델 컴포넌트를 만들고, 모델 카드에 적힌 데이터셋을 참조로 적는다.
- **병합 (aibom-cli)**: 두 문서를 하나로 합친다. 같은 컴포넌트는 purl 이나 경로로 알아보고 하나로 두며, 루트 컴포넌트 하나 아래로 관계를 잇는다.
- **D-BOM 생성 · 보강 (aibom-cli)**: 코드의 `load_dataset` 호출과 모델 카드에서 찾은 HuggingFace 데이터셋은 허브 API 로 정보(정식 id, 라이선스, 크기, 모달리티, 열 통계)를 받아 채우고, `--data` 로 지정한 로컬 데이터는 파일을 직접 읽는다.
- **M-BOM 보강 (OWASP aibom-generator)**: 허브에서 부른 모델의 카드 정보를 받아 모델 컴포넌트를 채운다.
- **규제 필드 추가 (aibom-cli)**: EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 필드를 `--spec` 에 따라 properties 또는 AI-BOM v0.6 필드로 넣는다.
- **검증 (aibom-cli)**: CycloneDX 1.7 또는 AI-BOM v0.6 (CycloneDX) 스키마로 검증한다.

## 출처

- [syft](https://github.com/anchore/syft)
- [cdxgen](https://github.com/CycloneDX/cdxgen)
- [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
- [Hugging Face Hub API](https://huggingface.co/docs/hub/api), [datasets-server](https://huggingface.co/docs/datasets-server)
- [CycloneDX 1.7](https://cyclonedx.org/docs/1.7/json/), [SPDX 3.0.1](https://spdx.github.io/spdx-spec/v3.0.1/)
