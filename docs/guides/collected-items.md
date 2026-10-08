# 수집 항목

스캔 대상이 디렉터리든 컨테이너 이미지든 이미지 아카이브든 안을 훑는 규칙은 같다. 이미지와 아카이브는 디렉터리로 풀어서 보고,
S-BOM 만 syft 가 이미지를 직접 읽는다.
무엇을 어디서 찾는지를 BOM 별로 적는다.

## S-BOM

| 찾는 것 | 누가 | 어디서 |
|---|---|---|
| 소프트웨어 패키지 | syft | 패키지 매니페스트(`requirements.txt`, `package-lock.json`, `pyproject.toml` 등)와 설치된 패키지(`site-packages`, `node_modules`, dpkg·apk 데이터베이스 등) |
| 매니페스트 파일 | syft | 패키지를 찾은 근거 파일을 해시와 함께 `file` 컴포넌트로 남긴다 |

버전을 고정하지 않은 `requirements.txt` 항목은 기본으로 세지 않는다.

## M-BOM

| 찾는 것 | 누가 | 어디서 |
|---|---|---|
| 모델 컴포넌트 | cdxgen | 파이썬 소스와 노트북의 `from_pretrained("owner/name")` 호출, 로컬 모델(`config.json`, `adapter_config.json`, 모델 카드 README.md), `*.gguf`, Ollama `Modelfile`. 가중치 파일(`.safetensors`, `.bin`, `.pt`)만 있는 폴더는 모델로 잡지 않는다 |
| 하이퍼파라미터 · 파라미터 수 | aibom-cli | cdxgen 이 찾은 모델의 `config.json`, `*.gguf` 헤더, 같은 폴더의 `*.safetensors` 헤더. 가중치는 읽지 않고 pickle 파일(`.bin`, `.pt`, `.pth`, `.ckpt`)은 열지 않는다 |
| 허브 모델의 모델 카드 | OWASP aibom-generator | 코드가 허브에서 부르는 모델의 카드 정보를 Hugging Face Hub 에서 받는다 |

## D-BOM

| 찾는 것 | 누가 | 어디서 |
|---|---|---|
| 모델 카드의 데이터셋 참조 | cdxgen | 로컬 모델의 README.md 앞머리 `datasets:` |
| 코드의 데이터셋 참조 | aibom-cli | 파이썬 소스의 `load_dataset("owner/name")` 호출. 첫 인자가 로컬 빌더(`csv`, `json`, `parquet` …)이거나 경로이면 허브 참조가 아니라 넘긴다 |
| 허브 데이터셋 정보 | aibom-cli | [Hub API](https://huggingface.co/docs/hub/api)에서 정식 id, 커밋, 라이선스, 모달리티를, [datasets-server](https://huggingface.co/docs/dataset-viewer)에서 크기와 열 통계를 받는다. 데이터셋 파일을 내려받지는 않는다 |
| 로컬 데이터 | aibom-cli | `--data` 로 지정한 경로의 데이터 파일 |

로컬 데이터는 확장자로 가르고, 파일 종류에 따라 `data[]` 에 적는 단위가 다르다.

- 데이터 파일로 치는 확장자: `csv`, `tsv`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `jsonl`, `ndjson`, `json`, `txt`, `png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac`. `requirements*.txt`, `README*`, `LICENSE*`, `*config.json`, `dataset_info.json` 같은 문서·설정 이름은 뺀다.
- 표·레코드 파일(csv, tsv, parquet, arrow, feather, npy, npz, jsonl, ndjson, json, txt)은 파일마다 항목 하나다. 크기, 형식, sha256, 행 수, 열 이름을 적고, 표 형식(csv, tsv, json, jsonl, parquet, arrow, feather)은 열마다 통계를 낸다. 64 MB 까지만 통계를 내고, 2 GB 를 넘는 파일은 크기만 적는다. `train-00001-of-00004.parquet` 처럼 크기 때문에 나뉜 조각(샤드)은 분할 하나로 합쳐 항목 하나(`train-*.parquet`)로 적고, 행 수는 합치고 통계는 조각을 이어 붙여 낸다.
- 이미지·오디오 파일(png, jpg, webp, wav, mp3, flac)은 폴더와 형식 단위로 항목 하나다 (`images/cat/*.jpg`). 파일 수, 크기 합, 형식을 적고, 헤더만 읽어 이미지는 너비, 오디오는 길이(초)의 분포(min, max, mean, median, std)를 통계로 낸다. 허브의 image·audio 열 통계와 같은 종류이고 이름도 같은 꼴이다(`train:image:width:mean`). 내용은 읽지 않으므로 해시는 없다. 이미지 수십만 장이 항목 수십만 개가 되지 않게 하기 위해서다. `train/cat/`, `train/dog/` 처럼 하위 폴더 둘 이상이 같은 형식의 매체만 들고 있으면 클래스 폴더로 보고 그 폴더(`train/*.jpg`) 하나로 합치며, 폴더 이름을 라벨로 삼아 라벨 분포(n_unique, mode, frequencies)를 통계로 낸다. 형제 분할이 그렇게 합쳐졌으면 클래스가 하나뿐인 분할(`test/cat/`)도 같은 꼴로 합친다.
- 주석은 데이터 항목이 되지 않는다. `file_name` 열이 있는 `metadata.csv`, `metadata.jsonl`(Hugging Face imagefolder·audiofolder 규칙)은 파일을 가리키는 열을 뺀 나머지 열의 통계만 보태고, `labels/`, `annotations/` 폴더 아래 파일(YOLO, COCO 규칙)은 세지 않는다. 둘 다 크기는 데이터셋 크기에 든다.

## 건너뛰는 곳

- aibom-cli 의 소스 훑기와 데이터 경로 훑기: `node_modules`, `.git`, `venv`, `.venv`, `site-packages`, `dist-packages`, `__pycache__` 와 점으로 시작하는 폴더
- cdxgen: 경로에 `test`, `tests`, `fixture(s)`, `example(s)`, `sample(s)` 조각이 있는 소스

## 찾지 않는 것

- `--data` 로 주지 않은 로컬 데이터
- 코드에서 허브 모델을 부를 때 그 모델의 허브 모델 카드에 적힌 데이터셋 (OWASP 보강이 모델 카드 안에 inline 으로 적어 주지만 데이터셋 컴포넌트로는 만들지 않는다)
- 설정 파일 없이 `.pt`, `.pth`, `.onnx` 만 있는 체크포인트 (cdxgen 이 모델로 보지 않는다)
- 변수로 모델 이름을 넘기는 코드 (`from_pretrained(model_name)`)
