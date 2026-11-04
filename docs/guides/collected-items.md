# 수집 항목

각 도구가 무엇을 읽는지 BOM 별로 적는다. 읽는 곳이 갈리는 기준은 BOM 마다 다르다.

- S-BOM: 스캔 대상의 종류에 따라 다르다. 디렉터리는 패키지 매니페스트와 설치된 패키지를 읽고, 컨테이너 이미지와 이미지 아카이브는 설치된 패키지만 읽는다.
- M-BOM, D-BOM: 로컬에 있는지 허브에 있는지에 따라 다르다. 이미지는 디렉터리로 풀어서 같은 방식으로 읽으므로 스캔 대상의 종류와는 상관없다.

## S-BOM

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">syft</td><td>디렉터리</td><td markdown>패키지 매니페스트: `requirements.txt`, `setup.py`, `poetry.lock`, `package-lock.json` 등<br><span class="note">※ 버전을 `==` 로 고정하지 않은 `requirements.txt`·`setup.py` 항목은 세지 않는다</span></td></tr>
<tr markdown><td>디렉터리, 컨테이너 이미지, 이미지 아카이브</td><td markdown>설치된 패키지: `site-packages`, `node_modules`, dpkg·apk·rpm 데이터베이스 등</td></tr>
</tbody>
</table>

## M-BOM

허브 모델은 두 단계로 수집한다. cdxgen 이 코드에서 이름만 찾고, 그 이름으로 OWASP aibom-generator 와 sure-aibom 이 Hub API 로 받아 채운다.
로컬 모델은 cdxgen 과 sure-aibom 이 모델 파일을 읽어 채우며, 가중치는 읽지 않는다.

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td rowspan="2">cdxgen</td><td>허브 모델</td><td markdown>파이썬·자바스크립트 소스와 노트북의 `from_pretrained("owner/name")`, `pipeline("task", "owner/name")`, `model = "owner/name"` 같은 모델 이름 지정과 huggingface.co 링크</td></tr>
<tr markdown><td>로컬 모델</td><td markdown>`config.json`, `adapter_config.json`, 모델 카드 README.md 가운데 모델 파일이 하나라도 있는 폴더, `*.gguf` 헤더, Ollama `Modelfile`<br><span class="note">※ 이름이 같아도 모델 항목이 있어야 모델 파일로 본다</span><br><span class="note">※ 가중치 파일은 gguf 의 헤더만 읽고, `.safetensors`·`.bin`·`.pt`·`.pth`·`.ckpt` 같은 나머지는 보지 않는다</span></td></tr>
<tr markdown><td rowspan="2">sure-aibom</td><td>로컬 모델</td><td markdown>cdxgen 이 찾은 `config.json`, `*.gguf` 헤더, `Modelfile` 의 `FROM`·`LICENSE`, 그리고 `config.json` 과 같은 폴더의 `*.safetensors` 헤더<br><span class="note">※ 가중치 파일은 `.safetensors`·gguf 의 헤더만 읽는다. pickle 형식(`.bin`, `.pt`, `.pth`, `.ckpt`)은 열면 안에 든 코드가 실행될 수 있어 열지 않는다</span></td></tr>
<tr markdown><td>허브 모델</td><td markdown>cdxgen 이 찾은 모델의 [Hub API](https://huggingface.co/docs/hub/api) 응답</td></tr>
<tr markdown><td>OWASP aibom-generator</td><td>허브 모델</td><td markdown>cdxgen 이 찾은 모델의 [Hub API](https://huggingface.co/docs/hub/api) 응답과 모델 카드 README.md, `config.json`, `tokenizer_config.json`, LICENSE 파일, `*.safetensors`·`*.gguf` 헤더</td></tr>
</tbody>
</table>

## D-BOM

허브 데이터셋도 두 단계로 수집한다. cdxgen 과 sure-aibom 이 로컬·허브 모델 카드와 코드에서 이름을 찾고, sure-aibom 이 그 이름으로 Hub API 와 datasets-server 를 읽어 채운다.
`--data hf://datasets/<id>` 로 지정한 데이터셋도 같은 방식으로 채운다.
로컬 데이터는 sure-aibom 이 `--data` 로 지정한 경로의 파일을 읽어 채운다. 표 파일은 내용을 읽고, 레코드 파일은 크기만, 이미지·오디오는 헤더만 본다.

<table markdown>
<thead><tr><th>도구</th><th>대상</th><th>읽는 곳</th></tr></thead>
<tbody markdown>
<tr markdown><td>cdxgen</td><td>허브 데이터셋</td><td markdown>M-BOM 에서 찾은 로컬 모델의 모델 카드 YAML 헤더의 `datasets:` 에 적힌 데이터셋, 소스의 huggingface.co/datasets 링크</td></tr>
<tr markdown><td rowspan="7">sure-aibom</td><td rowspan="6">허브 데이터셋</td><td markdown>M-BOM 에서 찾은 로컬 모델의 모델 카드 YAML 헤더의 `datasets:` 와 `model-index:`(평가 결과)에 적힌 데이터셋<br><span class="note">※ cdxgen 은 `datasets:` 의 데이터셋을 모델의 데이터셋 목록에 하나만 남기고, `model-index:` 의 평가 데이터셋은 허브 데이터셋으로 적지 않아 sure-aibom 이 보완한다</span></td></tr>
<tr markdown><td markdown>M-BOM 에서 찾은 gguf 모델 헤더의 `general.datasets` 에 적힌 `owner/name` 데이터셋</td></tr>
<tr markdown><td markdown>M-BOM 에서 찾은 허브 모델의 모델 카드 YAML 헤더의 `datasets:` 와 `model-index:`(평가 결과)에 적힌 데이터셋</td></tr>
<tr markdown><td markdown>파이썬 소스와 노트북의 `load_dataset("owner/name")` 호출</td></tr>
<tr markdown><td markdown>`--data hf://datasets/<id>[@<revision>]` 로 지정한 데이터셋</td></tr>
<tr markdown><td markdown>cdxgen 과 sure-aibom 이 찾거나 지정한 데이터셋마다 [Hub API](https://huggingface.co/docs/hub/api)와 [datasets-server](https://huggingface.co/docs/dataset-viewer) 응답<br><span class="note">※ 데이터셋 파일은 내려받지 않는다</span></td></tr>
<tr markdown><td>로컬 데이터</td><td markdown>`--data` 로 지정한 경로</td></tr>
</tbody>
</table>

로컬 데이터로 읽는 확장자는 `csv`, `tsv`, `json`, `jsonl`, `ndjson`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `txt`, `png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac` 이다.
이 확장자라도 `requirements*.txt`, `README*`, `LICENSE*`, `*config.json`, `dataset_info.json` 같은 문서·설정 파일은 제외한다.

로컬 데이터는 `--data` 경로 하나가 데이터셋 컴포넌트 하나가 되고, 그 안의 파일을 `data[]` 항목으로 묶어 적는다. 무엇을 항목 하나로 보는지는 확장자에 따라 파일 단위와 폴더 단위로 나뉜다.

- 파일 단위: 표·레코드 파일(`csv`, `tsv`, `json`, `jsonl`, `ndjson`, `parquet`, `arrow`, `feather`, `npy`, `npz`, `txt`)은 파일 하나가 항목 하나다. `train-00001-of-00004.parquet` 처럼 [허브의 파일 이름 규약](https://huggingface.co/docs/hub/datasets-file-names-and-splits)으로 나뉜 샤드는 한 분할이므로 항목 하나(`train-*.parquet`)로 적는다. 내용은 표 파일(`csv`, `tsv`, `json`, `jsonl`, `ndjson`, `parquet`, `arrow`, `feather`)만 64 MB 까지 읽고, 레코드 파일(`npy`, `npz`, `txt`)은 크기만 본다.
- 폴더 단위: 이미지·오디오 파일(`png`, `jpg`, `jpeg`, `webp`, `wav`, `mp3`, `flac`)은 같은 폴더의 같은 모달리티(이미지 또는 오디오) 파일 전부가 항목 하나다 (`images/cat/*.jpg`, 형식이 섞이면 `images/cat/*.{jpg,png}`). 폴더 구조는 Hugging Face 의 [ImageFolder](https://huggingface.co/docs/datasets/image_dataset#imagefolder)·[AudioFolder](https://huggingface.co/docs/datasets/audio_dataset#audiofolder) 규약을 따른다. `train/cat/`, `train/dog/` 처럼 하위 폴더 둘 이상이 같은 모달리티의 매체만 들고 있으면 클래스 폴더로 보고 그 폴더(`train/*.jpg`)가 항목 하나이며, 파일 바로 위 폴더 이름이 라벨이다. 파일 내용은 읽지 않고 헤더만 본다.

데이터를 설명하는 주석 파일은 보조 파일로 본다. `file_name` 열이 있는 `metadata.csv`·`metadata.jsonl` 과 `labels/`·`annotations/` 폴더 아래 파일이다.
둘 다 데이터셋 크기 계산에는 포함되고, metadata 파일은 내용도 읽어 열 통계를 낸다. 따로 항목으로 만들지는 않는다.
