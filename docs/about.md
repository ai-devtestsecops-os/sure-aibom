# 작동 방식

aibom-cli 는 검증된 오픈소스 도구를 조합해 AI-BOM 을 만든다. S-BOM 은 syft, M-BOM 은 cdxgen, 허브 모델 정보는 OWASP aibom-generator 가
생성하고, 이 결과의 병합과 D-BOM 생성, 규제 필드 추가, 검증은 aibom-cli 가 담당한다.

## 설계

소프트웨어 패키지 탐지는 syft 가, 코드와 로컬 파일의 모델 탐지는 cdxgen 이 담당하는 영역이다. 둘 다 CycloneDX 를 내지만 각자 자기 영역의
컴포넌트만 내고, 데이터셋은 어느 쪽도 컴포넌트로 만들지 않는다. 규제가 요구하는 값(하이퍼파라미터, 파라미터 수, 데이터셋의 크기와 출처 등)은
CycloneDX 1.7 에 담을 자리가 없어 어느 도구도 적지 않는다.

aibom-cli 는 이 빈자리를 맡는다. 두 도구의 결과를 하나로 병합하고, 데이터셋 컴포넌트를 생성해 채우고, 규제 필드를 더한 뒤 검증한다.
탐지기를 새로 만드는 대신 기존 도구를 조합한 것은, 패키지와 모델을 탐지하는 규칙이 계속 늘어나는 영역이라 그 도구들의 갱신을 그대로 받기 위해서다.

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

## 단계별 작업

- **S-BOM 생성 (syft)**: 패키지 매니페스트와 설치된 패키지에서 소프트웨어 컴포넌트를 찾는다.
- **M-BOM 생성 (cdxgen)**: 코드의 `from_pretrained` 호출, 로컬 모델(`config.json`, 모델 카드 README.md, gguf, Modelfile)에서 모델 컴포넌트를 만들고, 모델 카드에 적힌 데이터셋을 참조로 적는다.
- **병합 (aibom-cli)**: 두 문서를 하나로 합친다. 같은 컴포넌트는 purl 이나 경로로 알아보고 하나로 두며, 루트 컴포넌트 하나 아래로 관계를 잇는다.
- **D-BOM 생성 · 보강 (aibom-cli)**: 코드의 `load_dataset` 호출과 모델 카드에서 찾은 HuggingFace 데이터셋은 허브 API 로 정보(정식 id, 라이선스, 크기, 모달리티, 열 통계)를 받아 채우고, `--data` 로 지정한 로컬 데이터는 파일을 직접 읽는다.
- **M-BOM 보강 (OWASP aibom-generator)**: 허브에서 부른 모델의 카드 정보를 받아 모델 컴포넌트를 채운다.
- **규제 필드 추가 (aibom-cli)**: EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 필드를 `--spec` 에 따라 properties 또는 AI-BOM v0.6 필드로 넣는다. 두 방식은 [규제 준수](compliance/index.md)에 있다.
- **검증 (aibom-cli)**: CycloneDX 1.7 또는 AI-BOM v0.6 (CycloneDX) 스키마로 검증한다.

## 범위

0.1.0 기준이다.

| 하는 것 | 안 하는 것 (예정) |
|---|---|
| CycloneDX 1.7 출력, properties 와 v0.6 필드 두 방식 | SPDX 3.0.1 출력 |
| 규제 필드 9개 채우기 (모델 4, 데이터셋 5) | 규제별 완성도 표시 (요구 필드 중 채워진 것과 빈 것) |
| 디렉터리, 컨테이너 이미지, 이미지 `.tar`, 로컬 데이터 스캔 | |

채우는 필드 아홉 개가 무엇인지는 [AI-BOM v0.6 필드](compliance/aibom-v0.6.md)에 있다.

## 참고 자료

- [Hugging Face Hub API](https://huggingface.co/docs/hub/api), [datasets-server](https://huggingface.co/docs/datasets-server)
