# 수집 항목

각 도구가 스캔 대상 안에서 무엇을 읽는지 BOM 별로 적는다. 컨테이너 이미지와 이미지 아카이브는 디렉터리로 풀어서 보므로 M-BOM 과 D-BOM 은
스캔 대상이 무엇이든 같은 곳을 읽는다. S-BOM 만 syft 가 이미지를 직접 읽어 디렉터리와 다르다.

## S-BOM

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">syft</td><td>디렉터리</td><td markdown>패키지 매니페스트: `requirements.txt`, `setup.py`, `poetry.lock`, `package-lock.json` 등<br><span class="note">※ 버전을 `==` 로 고정하지 않은 `requirements.txt` 항목은 세지 않는다</span></td></tr>
<tr markdown><td>디렉터리, 컨테이너 이미지, 이미지 아카이브</td><td markdown>설치된 패키지: `site-packages`, `node_modules`, dpkg·apk·rpm 데이터베이스 등</td></tr>
</tbody>
</table>

## M-BOM

허브 모델은 두 단계로 잡는다. cdxgen 이 코드에서 이름을 잡고, OWASP aibom-generator 가 그 이름으로 Hub API 와 모델 카드·설정 파일을 읽어 채운다.

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">cdxgen</td><td>허브 모델</td><td markdown>파이썬·자바스크립트 소스와 노트북의 `from_pretrained("owner/name")`, `pipeline("task", "owner/name")`, `model = "owner/name"` 같은 모델 이름 지정과 huggingface.co 링크</td></tr>
<tr markdown><td>로컬 모델</td><td markdown>`config.json`, `adapter_config.json`, 모델 카드 README.md 중 하나라도 있는 폴더, `*.gguf` 헤더, Ollama `Modelfile`<br><span class="note">※ 가중치 파일(`.safetensors`, `.bin`, `.pt`)은 보지 않는다</span></td></tr>
<tr markdown><td>aibom-cli</td><td>로컬 모델</td><td markdown>cdxgen 이 찾은 모델의 `config.json`, `*.gguf` 헤더, `config.json` 과 같은 폴더의 `*.safetensors` 헤더<br><span class="note">※ pickle 형식 가중치(`.bin`, `.pt`, `.pth`, `.ckpt`)는 열면 안에 든 코드가 실행될 수 있어 열지 않는다</span></td></tr>
<tr markdown><td>OWASP aibom-generator</td><td>허브 모델</td><td markdown>cdxgen 이 찾은 모델의 Hugging Face Hub 저장소: 모델 정보 API, 모델 카드 README.md, `config.json`, `tokenizer_config.json`, LICENSE 파일, gguf·safetensors 헤더</td></tr>
</tbody>
</table>

## D-BOM

허브 데이터셋도 두 단계로 잡는다. cdxgen 과 aibom-cli 가 모델 카드와 코드에서 이름을 잡고, aibom-cli 가 Hub API 로 채운다.

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td>cdxgen</td><td>허브 데이터셋</td><td markdown>로컬 모델 카드(README.md) YAML 헤더의 `datasets:` 와 `model-index:`(평가 결과)에 적힌 데이터셋, 소스의 huggingface.co/datasets 링크</td></tr>
<tr markdown><td rowspan="3">aibom-cli</td><td rowspan="2">허브 데이터셋</td><td markdown>파이썬 소스의 `load_dataset("owner/name")` 호출<br><span class="note">※ 첫 인자가 로컬 빌더(`csv`, `json`, `parquet` …)나 파일 경로인 호출은 허브 데이터셋이 아니라서 건너뛴다</span></td></tr>
<tr markdown><td markdown>cdxgen 이 찾은 참조와 위 `load_dataset` 참조의 [Hub API](https://huggingface.co/docs/hub/api)와 [datasets-server](https://huggingface.co/docs/dataset-viewer) 응답<br><span class="note">※ 데이터셋 파일은 내려받지 않는다</span></td></tr>
<tr markdown><td>로컬 데이터</td><td markdown>`--data` 로 지정한 경로</td></tr>
</tbody>
</table>

로컬 데이터는 읽은 파일을 데이터셋 단위로 묶어 적는다. 무엇을 데이터셋 하나로 보는지는 확장자에 따라 파일 단위와 폴더 단위로 나뉜다.

- 지원 확장자: `csv`, `tsv`, `json`, `jsonl`, `ndjson`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `txt`, `png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac`<br><span class="note">※ `requirements*.txt`, `README*`, `LICENSE*`, `*config.json`, `dataset_info.json` 같은 문서·설정 이름은 제외한다</span>
- 파일 단위: 표·레코드 파일(csv, tsv, json, jsonl, ndjson, parquet, arrow, feather, npy, npz, txt)은 파일 하나가 데이터셋 하나다. `train-00001-of-00004.parquet` 처럼 [허브의 파일 이름 규약](https://huggingface.co/docs/hub/datasets-file-names-and-splits)으로 나뉜 샤드는 한 분할이므로 데이터셋 하나(`train-*.parquet`)로 적는다. 내용은 표 파일(csv, tsv, json, jsonl, ndjson, parquet, arrow, feather)만 64 MB 까지 읽고, 레코드 파일(npy, npz, txt)은 크기만 본다.
- 폴더 단위: 이미지·오디오 파일(png, jpg, webp, wav, mp3, flac)은 같은 폴더의 같은 모달리티(이미지 또는 오디오) 파일 전부가 데이터셋 하나다 (`images/cat/*.jpg`, 형식이 섞이면 `images/cat/*.{jpg,png}`). 폴더 구조는 Hugging Face 의 [ImageFolder](https://huggingface.co/docs/datasets/image_dataset#imagefolder)·[AudioFolder](https://huggingface.co/docs/datasets/audio_dataset#audiofolder) 규약을 따른다. `train/cat/`, `train/dog/` 처럼 하위 폴더 둘 이상이 같은 모달리티의 매체만 들고 있으면 클래스 폴더로 보고 그 폴더(`train/*.jpg`)가 데이터셋 하나이며, 파일 바로 위 폴더 이름이 라벨이다. 파일 내용은 읽지 않고 헤더만 본다.

데이터를 설명하는 주석 파일은 보조 파일로 본다. `file_name` 열이 있는 `metadata.csv`, `metadata.jsonl`(Hugging Face ImageFolder·AudioFolder)과
`labels/`, `annotations/` 폴더 아래 파일(YOLO, COCO)이다. 둘 다 데이터셋 크기 계산에는 포함되고, metadata 파일은 내용도 읽어 열 통계를 낸다. 따로 데이터셋으로 여기지는
않는다.
