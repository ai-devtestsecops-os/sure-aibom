# SURE AI-BOM Generator

AI 시스템의 소프트웨어 패키지(S-BOM), 모델(M-BOM), 데이터셋(D-BOM)을 찾아 하나의 AI-BOM 으로 내는 CLI 도구다.
기존 CycloneDX 와 SPDX 가 다루지 않지만 EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 값을 추가하여, 규제에 맞는 AI-BOM 을 만든다.

| BOM 종류 | 대상 | 출처 |
|---|---|---|
| S-BOM | 소프트웨어 패키지 | 패키지 매니페스트, 설치된 패키지 |
| M-BOM | 모델 | 코드의 참조, 로컬 모델 |
| D-BOM | 데이터셋 | 코드와 모델의 참조, 지정한 로컬·허브 데이터셋 |

## 주요 기능

- **AI-BOM 생성**: 디렉터리와 컨테이너 이미지를 스캔하여 규제가 요구하는 값까지 담은 AI-BOM 을 만든다. 출력은 CycloneDX(기본) 또는 SPDX 로 내고, 규제 필드는 [AI-BOM v0.6 필드](compliance/aibom-v0.6.md)와 [확장 필드](compliance/regulation-fields.md) 두 방식 중 고른다.
- **검증**: 생성된 AI-BOM 을 CycloneDX 1.7, SPDX 3.0.1, AI-BOM v0.6 스키마로 검증한다.

## 문서

- [작동 방식](about.md)
- [가이드](guides/index.md)
- [규제 준수](compliance/index.md)

## 참고 자료

- [syft](https://github.com/anchore/syft), [cdxgen](https://github.com/CycloneDX/cdxgen), [OWASP aibom-generator](https://github.com/GenAI-Security-Project/aibom-generator)
- [CycloneDX 1.7](https://cyclonedx.org/docs/1.7/json/), [SPDX 3.0.1](https://spdx.github.io/spdx-spec/v3.0.1/)
- EU AI Act, ISO/IEC 42001, NIST AI RMF
- [Hugging Face Hub API](https://huggingface.co/docs/hub/api), [datasets-server](https://huggingface.co/docs/dataset-viewer), [ImageFolder](https://huggingface.co/docs/datasets/image_dataset#imagefolder)·[AudioFolder](https://huggingface.co/docs/datasets/audio_dataset#audiofolder), [File names and splits](https://huggingface.co/docs/hub/datasets-file-names-and-splits)
