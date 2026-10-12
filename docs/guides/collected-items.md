# 수집 항목

각 도구가 스캔 대상 안에서 무엇을 읽는지 BOM 별로 적는다. 컨테이너 이미지와 이미지 아카이브는 디렉터리로 풀어서 보므로 M-BOM 과 D-BOM 은
스캔 대상이 무엇이든 같은 곳을 읽는다. S-BOM 만 syft 가 이미지를 직접 읽어 디렉터리와 다르다.

## S-BOM

syft 가 만든다. 설치된 패키지는 어디서든 읽지만 패키지 매니페스트는 디렉터리에서만 읽는다. 이미지에서는 설치된 결과가 사실이고
매니페스트는 선언일 뿐이라고 보는 syft 의 기본 동작이다.

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">syft</td><td>디렉터리</td><td markdown>패키지 매니페스트: `requirements.txt`, `setup.py`, `poetry.lock`, `package-lock.json` 등 (버전을 `==` 로 고정하지 않은 `requirements.txt` 항목은 세지 않는다)</td></tr>
<tr markdown><td>디렉터리, 컨테이너 이미지, 이미지 아카이브</td><td markdown>설치된 패키지: `site-packages`, `node_modules`, dpkg·apk·rpm 데이터베이스 등</td></tr>
</tbody>
</table>

## M-BOM

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">cdxgen</td><td>허브 모델</td><td markdown>파이썬 소스와 노트북의 `from_pretrained("owner/name")` 호출</td></tr>
<tr markdown><td>로컬 모델</td><td markdown>`config.json`, `adapter_config.json`, 모델 카드 README.md 가 있는 폴더, `*.gguf`, Ollama `Modelfile`. 가중치 파일(`.safetensors`, `.bin`, `.pt`)만 있는 폴더는 모델로 보지 않는다</td></tr>
<tr markdown><td>aibom-cli</td><td>로컬 모델</td><td markdown>cdxgen 이 찾은 모델의 `config.json`, `*.gguf` 헤더, 같은 폴더의 `*.safetensors` 헤더. 가중치는 읽지 않고 pickle 파일(`.bin`, `.pt`, `.pth`, `.ckpt`)은 열지 않는다</td></tr>
<tr markdown><td>OWASP aibom-generator</td><td>허브 모델</td><td markdown>cdxgen 이 찾은 모델의 Hugging Face Hub 저장소: 모델 정보 API, 모델 카드 README.md, `config.json`, gguf·safetensors 헤더</td></tr>
</tbody>
</table>

## D-BOM

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td>cdxgen</td><td>허브 데이터셋</td><td markdown>로컬 모델의 README.md 앞머리 `datasets:`</td></tr>
<tr markdown><td rowspan="3">aibom-cli</td><td rowspan="2">허브 데이터셋</td><td markdown>파이썬 소스의 `load_dataset("owner/name")` 호출. 첫 인자가 로컬 빌더(`csv`, `json`, `parquet` …)이거나 경로이면 허브 참조가 아니라 넘긴다</td></tr>
<tr markdown><td markdown>위 두 참조의 [Hub API](https://huggingface.co/docs/hub/api)와 [datasets-server](https://huggingface.co/docs/dataset-viewer). 데이터셋 파일을 내려받지는 않는다</td></tr>
<tr markdown><td>로컬 데이터</td><td markdown>`--data` 로 지정한 경로. 호스트 경로라 이미지 안의 데이터는 읽지 않는다</td></tr>
</tbody>
</table>

로컬 데이터는 확장자로 가르고, 파일 종류에 따라 `data[]` 에 적는 단위가 다르다.

- 데이터 파일로 치는 확장자: `csv`, `tsv`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `jsonl`, `ndjson`, `json`, `txt`, `png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac`. `requirements*.txt`, `README*`, `LICENSE*`, `*config.json`, `dataset_info.json` 같은 문서·설정 이름은 뺀다.
- 표·레코드 파일(csv, tsv, parquet, arrow, feather, npy, npz, jsonl, ndjson, json, txt)은 파일마다 항목 하나다. `train-00001-of-00004.parquet` 처럼 크기 때문에 나뉜 조각(샤드)은 분할 하나로 합쳐 항목 하나(`train-*.parquet`)다. 내용은 표 형식(csv, tsv, json, jsonl, parquet, arrow, feather)만 64 MB 까지 읽는다.
- 이미지·오디오 파일(png, jpg, webp, wav, mp3, flac)은 폴더와 형식 단위로 항목 하나다 (`images/cat/*.jpg`). 이미지 수십만 장이 항목 수십만 개가 되지 않게 하기 위해서다. 파일은 헤더만 읽는다. `train/cat/`, `train/dog/` 처럼 하위 폴더 둘 이상이 같은 형식의 매체만 들고 있으면 클래스 폴더로 보고 그 폴더(`train/*.jpg`) 하나로 합치며, 형제 분할이 그렇게 합쳐졌으면 클래스가 하나뿐인 분할(`test/cat/`)도 같은 꼴로 합친다.
- 주석은 데이터 항목이 되지 않는다. `file_name` 열이 있는 `metadata.csv`, `metadata.jsonl`(Hugging Face imagefolder·audiofolder 규칙)은 내용을 읽고, `labels/`, `annotations/` 폴더 아래 파일(YOLO, COCO 규칙)은 열지 않는다. 둘 다 크기는 데이터셋 크기에 든다.

## 건너뛰는 곳

- aibom-cli 의 소스 훑기와 데이터 경로 훑기: `node_modules`, `.git`, `venv`, `.venv`, `site-packages`, `dist-packages`, `__pycache__` 와 점으로 시작하는 폴더
- cdxgen: 경로에 `test`, `tests`, `fixture(s)`, `example(s)`, `sample(s)` 조각이 있는 소스

## 찾지 않는 것

- `--data` 로 주지 않은 로컬 데이터
- 코드에서 허브 모델을 부를 때 그 모델의 허브 모델 카드에 적힌 데이터셋 (OWASP 보강이 모델 카드 안에 inline 으로 적어 주지만 데이터셋 컴포넌트로는 만들지 않는다)
- 설정 파일 없이 `.pt`, `.pth`, `.onnx` 만 있는 체크포인트 (cdxgen 이 모델로 보지 않는다)
- 변수로 모델 이름을 넘기는 코드 (`from_pretrained(model_name)`)
