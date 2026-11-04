# 스캔 대상

`scan` 은 스캔 대상 `<target>` 하나와 데이터셋 옵션 `--data` 를 받는다. `<target>` 과 `--data` 의 종류는 값의 형태로 판별하며 따로 지정하는 옵션은 없다.

| 입력 | 인자 | 판별 | 예 |
|---|---|---|---|
| 디렉터리 | `<target>` | 존재하는 디렉터리 경로 | `sure-aibom scan ./project` |
| 컨테이너 이미지 | `<target>` | 디렉터리도 아카이브도 아닌 모든 값 | `sure-aibom scan python:3.12-slim`, `sure-aibom scan ghcr.io/org/app:1.0` |
| 이미지 아카이브 | `<target>` | `.tar`, `.tar.gz`, `.tgz` 로 끝나는 파일 | `sure-aibom scan image.tar` |
| 로컬 데이터 | `--data <path>` | 데이터 파일이 든 폴더나 데이터 파일 하나. 여러 번 줄 수 있다 | `sure-aibom scan ./project --data ./dataset` |
| 허브 데이터셋 | `--data hf://datasets/<id>[@<revision>]` | `hf://datasets/` 로 시작하는 값. 여러 번 줄 수 있다 | `sure-aibom scan ./project --data hf://datasets/stanfordnlp/imdb` |

컨테이너 이미지와 이미지 아카이브의 경우 S-BOM 은 syft 가 직접 읽고, 모델과 데이터셋은 디렉터리로 푼 뒤 디렉터리와 같은 규칙으로 찾는다.
그 안에서 무엇을 찾는지는 [수집 항목](collected-items.md)에 있다.

## 디렉터리

소스 코드가 든 프로젝트 폴더다. 빌드나 설치 없이 폴더 안의 소스, 패키지 매니페스트, 받아 둔 모델 파일을 그대로 읽는다.

## 컨테이너 이미지

이미지를 이름으로 주는 경우다. 이 컴퓨터의 Docker 나 Podman 에 이미 받아 두었거나 직접 빌드한 이미지면 거기서 꺼내 쓰고, 없으면
레지스트리에서 받는다. 받는 데 쓰는 crane 은 설치 환경에 들어 있어 Docker 가 없어도 된다. tar 파일로 줄 때는 아래 이미지 아카이브를 본다.

S-BOM 은 syft 가 이미지를 직접 읽어 만든다. M-BOM 과 D-BOM 은 이미지를 그대로 주면 cdxgen 이 AI 수집을 건너뛰어 제대로 만들어지지 않으므로,
sure-aibom 이 이미지를 임시 디렉터리에 풀어 디렉터리 스캔과 같은 방식으로 돌린다.

## 이미지 아카이브

컨테이너 이미지를 파일 하나로 내보낸 것이다. Docker 형식과 OCI 레이아웃 둘 다 읽는다. 이미지 이름과 달리 데몬이나 네트워크 없이 스캔할 수 있다.
zstd 로 압축된 레이어는 지원하지 않는다.

## 로컬 데이터

로컬 데이터는 `--data <path>` 로 지정한 곳에서만 찾는다. 코드가 `pd.read_csv("data/train.csv")` 처럼 로컬 파일을 불러도 경로를 주지 않으면
D-BOM 에 들어가지 않는다. `--data` 는 여러 번 줄 수 있고, 하나당 데이터셋 컴포넌트 하나가 만들어진다. 경로는 데이터 파일이 든 폴더나 데이터 파일 하나다.

폴더는 Hugging Face 데이터셋 저장소처럼 데이터셋마다 하나씩 두고, 분할(train, test)과 클래스 폴더는 그 안에 둔 뒤 데이터셋의 최상위 폴더를
주는 것을 권장한다. 크기, 모달리티, 통계 같은 규제 필드가 컴포넌트에 하나씩 적혀서, `./data` 처럼 데이터셋 여러 개를 품은 폴더를 주면 값이
섞이기 때문이다.

```
data/
├── images/              # 데이터셋 하나
│   ├── train/
│   │   ├── cat/         a.jpg b.jpg …
│   │   └── dog/         c.jpg …
│   └── test/
│       ├── cat/         …
│       └── dog/         …
└── audio/               # 다른 데이터셋
    ├── metadata.csv
    └── x.wav y.wav …
```

```bash
sure-aibom scan ./project --data ./data/images --data ./data/audio   # 데이터셋 여러 개 지정
```

## 허브 데이터셋

Hugging Face 데이터셋은 코드의 `load_dataset("owner/name")` 호출과 모델 카드에서 자동으로 찾는다. 여기에 나오지 않는 데이터셋은
`--data hf://datasets/<id>` 로 지정한다. 학습을 다른 파이프라인에서 해서 스캔 대상에 학습 코드가 없거나, 코드가 데이터셋 이름을 변수로
넘겨 찾지 못하는 경우다. 표기는 [huggingface_hub 의 `hf://` 경로](https://huggingface.co/docs/huggingface_hub/guides/hf_file_system)와 같다.

지정한 데이터셋은 자동으로 찾은 것과 같은 모양의 컴포넌트가 되고, 같은 방식으로 Hub API 와 datasets-server 를 읽어 채운다.
코드에서도 찾았으면 컴포넌트 하나로 합친다. 허브에서 조회되지 않으면 경고를 내고 지정한 이름과 리비전만 남긴다.
허브는 없는 저장소와 비공개 저장소에 같은 응답(401)을 주어 둘을 구분할 수 없기 때문이다. 접근 권한이 있는 비공개 데이터셋은
`HF_TOKEN` 환경 변수에 토큰을 넣으면 조회된다.

리비전은 이렇게 정한다.

- `@<revision>` 을 붙이면 그 리비전(브랜치, 태그, 커밋 해시)으로 조회하고, 버전에는 허브가 돌려준 전체 커밋 해시를 적는다. 붙이지 않으면 최신 커밋이다.
- 저장소는 있는데 그 리비전이 없으면 스캔을 시작하지 않고 오류로 끝낸다.
- 코드가 `load_dataset("owner/name", revision="…")` 처럼 리비전을 정해 부른 데이터셋도 그 리비전으로 조회한다. 같은 데이터셋에 `--data` 로도 리비전을 주면 `--data` 의 것을 따른다.
- 코드에서 같은 데이터셋을 서로 다른 리비전으로 부르면(리비전이 없는 호출 포함) 하나로 정할 수 없어 최신 커밋으로 기록한다. 이 경우는 `-v` 로그에 나온다.
- datasets-server 는 최신 리비전만 제공하므로, 최신이 아닌 리비전으로 조회한 데이터셋은 datasets-server 에서 오는 크기와 열 통계를 채우지 않는다.

```bash
sure-aibom scan ./app --data ./data/train --data hf://datasets/stanfordnlp/imdb@e6281661   # 로컬과 허브를 함께 지정
```
