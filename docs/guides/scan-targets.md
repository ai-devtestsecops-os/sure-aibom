# 스캔 대상

`scan` 은 스캔 대상 `<target>` 하나와 로컬 데이터 옵션 `--data` 를 받는다. `<target>` 의 종류는 값의 형태로 판별하며 따로 지정하는 옵션은 없다.

| 입력 | 인자 | 판별 | 예 |
|---|---|---|---|
| 디렉터리 | `<target>` | 존재하는 디렉터리 경로 | `aibom-cli scan ./project` |
| 컨테이너 이미지 | `<target>` | 경로도 `.tar` 도 아닌 값. 이미지 참조로 본다 | `aibom-cli scan python:3.12-slim`, `aibom-cli scan ghcr.io/org/app:1.0` |
| 이미지 .tar | `<target>` | `.tar`, `.tar.gz`, `.tgz` 로 끝나는 파일 | `aibom-cli scan image.tar` |
| 로컬 데이터 | `--data <path>` | 폴더 또는 파일. 여러 번 줄 수 있다 | `aibom-cli scan ./project --data ./dataset` |

## 디렉터리

프로젝트 폴더 하나를 애플리케이션 하나로 본다. 루트 컴포넌트는 `application <폴더 이름>` 이다. 폴더 안에서 도구마다 보는 것이 다르다.

| 찾는 것 | 누가 | 어디서 |
|---|---|---|
| 소프트웨어 패키지 | syft | 패키지 매니페스트와 설치된 패키지 (`requirements.txt`, `package-lock.json`, `pyproject.toml` 등). 매니페스트 파일은 `file` 컴포넌트로도 남는다 |
| 모델 | cdxgen | 파이썬 소스와 노트북의 `from_pretrained("owner/name")` 호출, 로컬 모델(`config.json`, `adapter_config.json`, 모델 카드 README.md), `*.gguf`, Ollama `Modelfile`. 가중치 파일(`.safetensors`, `.bin`, `.pt`)만 있는 폴더는 모델로 잡지 않는다 |
| 모델 카드의 데이터셋 참조 | cdxgen | 로컬 모델의 README.md 앞머리 `datasets:` |
| 코드의 데이터셋 참조 | aibom-cli | 파이썬 소스의 `load_dataset("owner/name")` 호출. 첫 인자가 로컬 빌더(`csv`, `json`, `parquet` …)이거나 경로이면 허브 참조가 아니라 넘긴다 |
| 모델의 하이퍼파라미터 · 파라미터 수 | aibom-cli | cdxgen 이 찾은 모델의 `config.json`, `*.gguf` 헤더, 같은 폴더의 `*.safetensors` 헤더 |

찾은 HuggingFace 데이터셋은 허브 API 로 정보를 받아 채운다 (정식 id, 커밋, 라이선스, 크기, 모달리티, 열 통계). 데이터셋 파일을 내려받지는 않는다.

건너뛰는 곳이 있다.

- aibom-cli 의 소스 훑기와 데이터 경로 훑기: `node_modules`, `.git`, `venv`, `.venv`, `site-packages`, `dist-packages`, `__pycache__` 와 점으로 시작하는 폴더
- cdxgen: 경로에 `test`, `tests`, `fixture(s)`, `example(s)`, `sample(s)` 조각이 있는 소스
- syft: 버전을 고정하지 않은 `requirements.txt` 항목은 기본으로 세지 않는다

## 컨테이너 이미지

이미지 이름을 주면 두 갈래로 처리한다.

1. syft 는 이름을 그대로 받아 S-BOM 을 만든다. 로컬 데몬(Docker, Podman)에 있으면 그것을, 없으면 레지스트리에서 직접 받는다. Docker 가 없어도 된다.
2. aibom-cli 는 같은 이미지를 .tar 로 받아 임시 디렉터리에 푼 뒤, 그 디렉터리에 대해 M-BOM·D-BOM 단계(cdxgen, 하이퍼파라미터 읽기, 데이터셋 참조 찾기)를 돌린다. cdxgen 은 이미지를 직접 받으면 AI 수집을 건너뛰기 때문이다.

이미지를 받는 도구는 PATH 에서 docker, podman, crane 순으로 찾는다. docker 와 podman 은 데몬에 있는 이미지를 `image save` 하고, 없으면 `pull` 한 뒤 다시 save 한다. crane 은 레지스트리에서 이 머신의 플랫폼(`linux/<arch>`)으로 받는다. 하나가 실패하면 다음 것을 쓰고, 셋 다 없으면 `Pulling image … failed` 로 M-BOM 단계를 건너뛰고 S-BOM 만 쓴 뒤 종료 코드 2 로 끝난다. 이 경우 이미지를 .tar 로 만들어 주면 된다.

루트 컴포넌트는 `container <이미지 이름>` 이고, 풀어 둔 임시 디렉터리는 스캔이 끝나면 지운다.

## 이미지 .tar

`docker save`, `crane pull`, `skopeo copy` 가 만든 tar 를 받는다. 데몬도 네트워크도 필요 없다.

- 안쪽 모양은 `manifest.json` (docker save, crane) 과 OCI 레이아웃 (`index.json`, `blobs/`) 둘 다 읽는다.
- 플랫폼이 여럿 담겨 있으면 이 머신의 것(`linux/<arch>`)을 고르고, 없으면 첫 번째를 쓴다.
- 레이어는 순서대로 겹치며 화이트아웃(`.wh.<이름>`, `.wh..wh..opq`)으로 지워진 파일은 빼고, 이미지 안 절대경로를 가리키는 심볼릭 링크는 푼 디렉터리 안을 가리키게 고친다. 장치 파일과 밖으로 나가는 링크는 건너뛴다.
- zstd 로 압축된 레이어는 지원하지 않는다 (`zstd-compressed layers are not supported`).

루트 컴포넌트 이름은 tar 에 적힌 이미지 이름(`RepoTags`, OCI 의 `org.opencontainers.image.ref.name`)이고, 없으면 파일 이름이다.

## 로컬 데이터 (`--data`)

로컬 데이터는 `--data <path>` 로 지정한 곳에서만 찾는다. 코드가 `pd.read_csv("data/train.csv")` 처럼 로컬 파일을 불러도 경로를 주지 않으면 D-BOM 에 들어가지 않는다.

- 경로는 폴더든 파일 하나든 되고, 옵션을 여러 번 써서 더한다 (`--data ./dataset --data ./more/train.csv`).
- 경로마다 데이터셋 컴포넌트 하나가 생기고, 그 안의 데이터 파일이 `data[]` 항목이 된다. 같은 파일은 먼저 지정한 쪽에만 들어간다.
- 데이터 파일로 치는 확장자: `csv`, `tsv`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `jsonl`, `ndjson`, `json`, `txt`, `png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac`. `requirements*.txt`, `README*`, `LICENSE*`, `*config.json`, `dataset_info.json` 같은 문서·설정 이름은 뺀다.
- 표 형식 파일(csv, tsv, json, jsonl, parquet, arrow, feather)은 열마다 통계를 낸다. 64 MB 까지만 통계를 내고, 2 GB 를 넘는 파일은 크기만 적는다.
- 지정한 경로 밖을 가리키는 심볼릭 링크는 따라가지 않는다.

## 찾지 않는 것

- `--data` 로 주지 않은 로컬 데이터
- 코드에서 허브 모델을 부를 때 그 모델의 허브 모델 카드에 적힌 데이터셋 (OWASP 보강이 모델 카드 안에 inline 으로 적어 주지만 데이터셋 컴포넌트로는 만들지 않는다)
- 설정 파일 없이 `.pt`, `.pth`, `.onnx` 만 있는 체크포인트 (cdxgen 이 모델로 보지 않는다)
- 변수로 모델 이름을 넘기는 코드 (`from_pretrained(model_name)`)
