# 작동 방식

aibom-cli 는 검증된 오픈소스 도구를 조합해 AI-BOM 을 만든다. S-BOM 은 syft, M-BOM 은 cdxgen, 허브 모델 정보는 OWASP aibom-generator 가
생성하고, 이 결과의 병합과 D-BOM 생성, 규제 필드 추가, 검증은 aibom-cli 가 담당한다.

## 파이프라인

![aibom-cli 파이프라인](images/cli_pipeline.png)

소프트웨어 패키지 탐지는 syft 가, 코드와 로컬 파일의 모델 탐지는 cdxgen 이 담당한다. 코드가 허브에서 부르는 모델은 로컬에 파일이 없어
이름만 잡히는데, 그 모델 카드는 OWASP aibom-generator 가 Hugging Face Hub 에서 받아 채운다. 데이터셋은 cdxgen 이 모델 카드에서 이름만
잡을 뿐 세 도구 모두 내용을 채우지 않는다. 그래서 D-BOM 과 규제 필드는 aibom-cli 가 맡는다. 허브 데이터셋은 코드와 모델 카드의 참조에서
찾아 Hub API 로 채우고, 로컬 데이터는 지정한 경로의 파일을 읽는다.

aibom-cli 는 세 도구의 결과를 병합하고, D-BOM 을 채우고, 규제 필드를 추가한다. 병합이 먼저인 것은 cdxgen 과 aibom-generator 가
같은 모델을 따로 내므로 하나로 모은 뒤에 채워야 하기 때문이다.

## 단계별 작업

- **S-BOM 생성 (syft)**: 패키지 매니페스트와 설치된 패키지에서 소프트웨어 컴포넌트를 찾는다.
- **M-BOM 생성 (cdxgen)**: 코드의 `from_pretrained` 호출, 로컬 모델(`config.json`, 모델 카드 README.md, gguf, Modelfile)에서 모델 컴포넌트를 만든다.
- **병합 (aibom-cli)**: 두 문서를 하나로 합친다. 같은 컴포넌트는 purl 이나 경로로 알아보고 하나로 두며, 루트 컴포넌트 하나 아래로 관계를 잇는다.
- **D-BOM 생성 · 보강 (aibom-cli)**: 데이터셋 참조는 두 곳에서 온다. cdxgen 이 로컬 모델의 모델 카드에서 이름만 적어 둔 데이터셋 컴포넌트와, 코드의 `load_dataset` 호출이다. 둘 다 Hub API 로 정식 id, 라이선스, 모달리티를 받고, 크기와 열 통계는 datasets-server 에서 받아 채운다. `--data` 로 지정한 로컬 데이터는 파일을 직접 읽어 컴포넌트를 만든다.
- **M-BOM 보강 (OWASP aibom-generator)**: 허브에서 부른 모델의 카드 정보를 받아 모델 컴포넌트를 채운다.
- **규제 필드 추가 (aibom-cli)**: EU AI Act, ISO/IEC 42001, NIST AI RMF 가 요구하는 필드를 `--spec` 에 따라 properties 또는 AI-BOM v0.6 필드로 넣는다. 두 방식은 [규제 준수](compliance/index.md)에 있다.
- **검증 (aibom-cli)**: BOM 을 CycloneDX 1.7 또는 AI-BOM v0.6 (CycloneDX) 스키마로 검증한다.

## 명령

`scan` 하나가 생성 세 단계를 모두 돌린다. `--data` 는 D-BOM 에 로컬 데이터를 더하고, `--spec` 은 규제 필드의 형식을 고른다.
`validate` 는 그 결과 파일을 따로 검증한다. 사용법은 [시작하기](guides/getting-started.md)에 있다.

생성 단계에서 aibom-cli 가 내부에서 부르는 도구 명령은 다음과 같다.

```bash
syft <target> --select-catalogers -ai -o cyclonedx-json   # S-BOM
cdxgen <target> -t ai --no-install-deps                   # M-BOM
python -m src.cli <owner/model>                           # OWASP aibom-generator, 허브 모델마다
```

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
