"""dataset — 스캔 대상 안의 데이터셋(HF 참조 · 로컬 데이터 파일)을 type=data 컴포넌트로 만들고, form 이 두 형태로 옮긴다.
허브 조회는 tests/data/hf_api/hf_dataset_stanfordnlp_imdb.json (실제 GET /api/datasets/stanfordnlp/imdb 응답)으로 바꿔 끼운다.
실제 허브를 치는 테스트는 마지막 하나뿐이고, 네트워크·AIBOM_GENERATOR_DIR 이 없으면 건너뛴다."""
import copy
import csv
import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

import sure_aibom.engine.common.hub as hub
import sure_aibom.engine.dataset as ds
from sure_aibom.engine.common.aibom_generator import skip_reason
from sure_aibom.engine.common.component import INTERNAL_PREFIX
from sure_aibom.engine.common.licenses import card_licenses, license_entry
from sure_aibom.engine.dataset import discover_datasets, missing_revisions
from sure_aibom.engine.merge import merge
from sure_aibom.engine.form import regulate
from sure_aibom.engine.validation import _validate_cdx
from sure_aibom.utils.dataset_utils import hf_dataset_id_of, is_dataset
from sure_aibom.utils.facts import Facts

# 허브 조회는 시험마다 hub 모듈의 함수를 바꿔 끼운다 (dataset.py 가 그 모듈을 거쳐 부른다).

IMDB_FIXTURE = Path(__file__).parent / "data" / "hf_api" / "hf_dataset_stanfordnlp_imdb.json"
IMDB = "stanfordnlp/imdb"
IMDB_REF = "pkg:huggingface/datasets/stanfordnlp/imdb"


@pytest.fixture
def imdb() -> dict:
    return json.loads(IMDB_FIXTURE.read_text(encoding="utf-8"))


def hub_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent / "data" / "hf_api" / name).read_text(encoding="utf-8"))


def imdb_size() -> dict:
    return hub_fixture("hf_size_stanfordnlp_imdb.json")


def imdb_statistics(config: str, split: str) -> dict | None:
    try:
        return hub_fixture(f"hf_statistics_stanfordnlp_imdb_{config}_{split}.json")
    except FileNotFoundError:
        return None


REAL_FETCH_SIZE, REAL_FETCH_STATISTICS = hub.fetch_dataset_size, hub.fetch_dataset_statistics     # 실제 허브를 치는 테스트가 되돌려 쓴다


@pytest.fixture(autouse=True)
def no_datasets_server(monkeypatch):
    """datasets-server 조회는 기본으로 실패(None)로 친다. 필요한 테스트가 다시 끼운다."""
    monkeypatch.setattr(hub, "fetch_dataset_size", lambda hf_id: None)
    monkeypatch.setattr(hub, "fetch_dataset_statistics", lambda hf_id, config, split: None)


@pytest.fixture(autouse=True)
def no_model_cards(monkeypatch):
    """허브 모델 카드 조회도 기본으로 실패(None)로 친다. 모델 카드의 데이터셋을 보는 테스트가 다시 끼운다."""
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: None)


@pytest.fixture
def online(monkeypatch, imdb):
    """허브에 닿는 것으로 치고, imdb 만 픽스처(허브 정보 · /size · split 별 /statistics)로 답한다. 다른 id 는 None (조회 실패)."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    calls: list[str] = []

    def fetch(hf_id):
        calls.append(hf_id)
        return copy.deepcopy(imdb) if hf_id == IMDB else None
    monkeypatch.setattr(hub, "fetch_dataset_info", fetch)
    monkeypatch.setattr(hub, "fetch_dataset_size", lambda hf_id: imdb_size() if hf_id == IMDB else None)
    monkeypatch.setattr(hub, "fetch_dataset_statistics",
                        lambda hf_id, config, split: imdb_statistics(config, split) if hf_id == IMDB else None)
    return calls


BOOK_HUB = "pkg:huggingface/datasets/bookcorpus"       # 허브 조회 뒤 cdxgen 의 bookcorpus 가 받는 purl·bom-ref (정식 id 가 bookcorpus 일 때)


def cdxgen_bookcorpus() -> dict:
    """cdxgen 이 모델 README 에서 만드는 데이터셋 컴포넌트 모양 (purl 없음, data[0].name "datasets/<id>")."""
    return {"bom-ref": "cdxgen:ai:dataset:huggingface:datasets-bookcorpus", "type": "data", "group": "datasets", "name": "bookcorpus",
            "version": "", "data": [{"type": "dataset", "name": "datasets/bookcorpus", "contents": {"url": "https://huggingface.co/datasets/datasets/bookcorpus"}}],
            "properties": [{"name": "cdx:ai:kind", "value": "dataset"}]}


def cdxgen_imdb() -> dict:
    """cdxgen 이 모델 README 의 datasets: [stanfordnlp/imdb] 로 만드는 모양. owner/name 은 group·name 으로 나뉘고 purl 없이 주소에만 남는다."""
    return {"bom-ref": "pkg:huggingface/stanfordnlp/imdb?repository_url=https%3A%2F%2Fhuggingface.co%2Fdatasets", "type": "data",
            "group": "stanfordnlp", "name": "imdb", "version": "",
            "data": [{"type": "dataset", "name": IMDB, "contents": {"url": "https://huggingface.co/datasets/stanfordnlp/imdb"}}],
            "properties": [{"name": "cdx:ai:kind", "value": "dataset"}]}


def cdxgen_link(hf_id: str) -> dict:
    """cdxgen 이 코드의 https://huggingface.co/datasets/<id> 링크로 만드는 모양 (실측: purl 도 data[] 도 없이 externalReferences 에만 주소)."""
    group, _, name = hf_id.rpartition("/")
    return {"bom-ref": f"cdxgen:ai:dataset:{group}:{name}", "type": "data", "group": group, "name": name, "version": "",
            "externalReferences": [{"type": "distribution", "url": f"https://huggingface.co/datasets/{hf_id}"}],
            "evidence": {"occurrences": [{"location": "src/train.py#L8"}]}}


def doc_of(*components: dict, root=("proj", "directory")) -> dict:
    return merge([{"bomFormat": "CycloneDX", "specVersion": "1.7", "components": list(components)}], root=root)


def datasets(doc: dict) -> dict[str, dict]:
    return {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}


def props(comp: dict) -> dict[str, str]:
    return {p["name"]: p["value"] for p in comp.get("properties") or []}


def internal(comp: dict) -> dict[str, str]:
    return {k[len(INTERNAL_PREFIX):]: v for k, v in props(comp).items() if k.startswith(INTERNAL_PREFIX)}


def stats_props(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """(종류, 값) 목록 → internal() 이 돌려주는 statistics:<i>:type / :value 키."""
    out: dict[str, str] = {}
    for i, (kind, value) in enumerate(pairs):
        out[f"statistics:{i}:type"], out[f"statistics:{i}:value"] = kind, value
    return out


IMDB_TRAIN_STATS = [("train:label:nan_count", "0"), ("train:label:n_unique", "2"), ("train:label:frequencies", "neg=12500,pos=12500"),      # 동률이라 mode 없음
                    ("train:text:nan_count", "0"), ("train:text:length:min", "52"), ("train:text:length:max", "13704"), ("train:text:length:mean", "1325.06964"),
                    ("train:text:length:median", "979"), ("train:text:length:std", "1003.13367")]


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project(tmp_path: Path) -> Path:
    """tests/data/project 와 같은 모양의 임시 프로젝트. 로컬 데이터는 data/ 에 있고 --data 로 지목한다."""
    write(tmp_path, "data/train.csv", 'id,text,label\n1,"good movie",1\n2,"bad movie",0\n3,"fine",1\n4,"meh",0\n5,"great",1\n')
    write(tmp_path, "src/train.py", 'from datasets import load_dataset\nfrom transformers import AutoModel\n'
                                    'bert = AutoModel.from_pretrained("google-bert/bert-base-uncased")\n'
                                    'imdb = load_dataset("stanfordnlp/imdb")\n')
    return tmp_path


def data_of(root: Path) -> list[str]:
    return [str(root / "data")]


# -- HF id 읽기 ----------------------------------------------------------------------
@pytest.mark.parametrize("comp, expected", [
    ({"type": "data", "purl": "pkg:huggingface/datasets/stanfordnlp/imdb@abc?x=1"}, "stanfordnlp/imdb"),
    (cdxgen_bookcorpus(), "bookcorpus"),
    (cdxgen_imdb(), "stanfordnlp/imdb"),                                                                  # purl 없이 허브 주소에만
    (cdxgen_link("acme/eval-set"), "acme/eval-set"),                                                      # 코드의 링크: externalReferences 에만
    ({"type": "data", "name": "x", "externalReferences": [{"type": "website", "url": "https://example.org/datasets/a/b"}]}, None),
    ({"type": "data", "group": "datasets", "name": "wikitext"}, "wikitext"),
    ({"type": "data", "name": "data", "data": [{"type": "dataset", "name": "data/train.csv"}]}, None),
    ({"type": "data", "name": "x", "data": [{"type": "dataset", "name": "a/b", "contents": {"url": "https://example.org/datasets/a/b"}}]}, None),
    ({"type": "library", "purl": "pkg:huggingface/datasets/x/y"}, None),
])
def test_hf_dataset_id_of(comp, expected):
    assert hf_dataset_id_of(comp) == expected


@pytest.mark.parametrize("comp, expected", [
    (cdxgen_bookcorpus(), True),
    ({"type": "data", "purl": "pkg:huggingface/datasets/stanfordnlp/imdb"}, True),                       # 허브 id 면 data[] 없어도 데이터셋
    ({"type": "data", "name": "data", "data": [{"type": "dataset", "name": "data/train.csv"}]}, True),   # 로컬 데이터
    # cdxgen 이 이미지의 apt 저장소 설정을 내는 모양: type=data 인데 data[] 가 비어 있다
    ({"type": "data", "name": "deb.debian.org/debian", "data": [],
      "purl": "pkg:generic/os-repository/deb.debian.org%2Fdebian@trixie?path=/etc/apt/sources.list.d/debian.sources&repo_type=apt-source"}, False),
    ({"type": "data", "name": "snippet", "data": [{"type": "source-code", "name": "snippet"}]}, False),
    ({"type": "library", "data": [{"type": "dataset", "name": "x"}]}, False),
])
def test_is_dataset(comp, expected):
    assert is_dataset(comp) is expected


# -- 파이썬 소스 ---------------------------------------------------------------------
def test_python_source_yields_only_hub_ids(tmp_path):
    src = write(tmp_path, "a.py", '''
from datasets import load_dataset
import datasets, numpy as np
a = load_dataset("stanfordnlp/imdb", split="train")
b = datasets.load_dataset("imdb")
c = load_dataset("csv", data_files="data/train.csv")
d = load_dataset("json", data_files=["a.jsonl", "b.jsonl"])
f = load_dataset("./local_script.py")
g = load_dataset("data/train.csv")
h = load_dataset(name)
df = pd.read_csv("data/train.csv")
fh = open("labels.txt")
''')
    assert ds._parse_python(src) == [("stanfordnlp/imdb", None), ("imdb", None)]              # 빌더 이름 · 경로 · 다른 호출은 허브 id 가 아니다


def test_python_source_yields_the_revision_argument_when_it_is_a_string(tmp_path):
    src = write(tmp_path, "a.py", '''
a = load_dataset("stanfordnlp/imdb", revision="94a9845c", split="train")
b = load_dataset("stanfordnlp/imdb", revision="94a9845c")
c = load_dataset("acme/eval-set", "cfg", revision=REV)
''')
    assert ds._parse_python(src) == [("stanfordnlp/imdb", "94a9845c"), ("acme/eval-set", None)]              # 변수인 리비전은 읽지 않는다


def test_notebook_code_cells_yield_hub_ids_like_python_source(tmp_path, logs):
    """노트북도 코드 셀은 파이썬이라 같은 규칙으로 찾는다. 마크다운 셀과 %magic·!shell 줄은 건너뛰고, 깨진 노트북은 건너뛰고 알린다."""
    nb = {"cells": [
        {"cell_type": "markdown", "source": ["load_dataset(\"not/code\")"]},
        {"cell_type": "code", "source": ["%pip install datasets\n", "!ls\n", "from datasets import load_dataset\n"]},
        {"cell_type": "code", "source": "ds = load_dataset(\"stanfordnlp/imdb\", split=\"train\")\nother = load_dataset(\"csv\", data_files=\"x.csv\")"},
    ], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    path = write(tmp_path, "explore.ipynb", json.dumps(nb))
    assert ds._parse_python(path) == [("stanfordnlp/imdb", None)]
    logs.clear()
    assert ds._parse_python(write(tmp_path, "bad.ipynb", "{not json")) == []
    assert any("bad.ipynb" in m and "cannot parse" in m for m in logs)
    found = ds._scan_sources(tmp_path)
    assert found == {"stanfordnlp/imdb": [("explore.ipynb", None)]}


def test_unparsable_python_is_skipped_with_a_log(tmp_path, logs):
    assert ds._parse_python(write(tmp_path, "bad.py", "def (:\n")) == []
    assert any("bad.py" in m for m in logs)


# -- 로컬 파일 분석 ------------------------------------------------------------------
def test_file_analysis_by_format(tmp_path):
    """파일 사실은 크기·형식·모달리티와 표 형식의 열 통계뿐이다. 해시·행 수·열 이름은 정의서에 없는 값이라 내지 않는다."""
    csv_path = write(tmp_path, "t.csv", 'a,b\n1,"x\ny"\n2,z\n\n')
    a = ds._analyze_file(csv_path, "t.csv")
    assert a["format"] == "csv" and a["modality"] == "structured" and a["size"] == csv_path.stat().st_size
    assert a["statistics"][:3] == [("a:nan_count", "0"), ("a:min", "1"), ("a:max", "2")]
    assert set(a) == {"path", "size", "format", "modality", "statistics"}
    assert ds._analyze_file(write(tmp_path, "l.jsonl", '{"a":1}\n\n{"a":2}\n'), "l.jsonl")["statistics"][0] == ("a:nan_count", "0")
    assert "statistics" not in ds._analyze_file(write(tmp_path, "obj.json", '{"a": 1}'), "obj.json")                  # 객체 하나는 표가 아니다
    assert "statistics" not in ds._analyze_file(write(tmp_path, "w.txt", "a\nb\n\nc\n"), "w.txt")                  # 글 파일은 열이 없다
    png = tmp_path / "i.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    i = ds._analyze_file(png, "i.png")
    assert i["modality"] == "image" and set(i) == {"path", "size", "format", "modality"}


def test_unreadable_content_falls_back_to_size(tmp_path, logs):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    a = ds._analyze_file(bad, "bad.json")
    assert set(a) == {"path", "size", "format", "modality"} and any("bad.json" in m for m in logs)


def test_large_files_record_size_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "STATISTICS_FILE_LIMIT", 10)
    a = ds._analyze_file(write(tmp_path, "big.csv", "a,b\n" * 10), "big.csv")
    assert "statistics" not in a and a["size"] == 40


# -- discover: --data 경로 + 코드 ------------------------------------------------------------
def test_discover_builds_one_component_per_data_path_and_links_from_root(tmp_path, online):
    root = project(tmp_path)
    out = discover_datasets(doc_of(), str(root), data_paths=data_of(root))
    found = datasets(out)
    assert set(found) == {"data:local/data@", IMDB_REF}

    local = found["data:local/data@"]
    assert local["name"] == "data" and local["data"] == [{"type": "dataset", "name": "data/train.csv"}]      # 원소는 종류와 이름뿐
    # 열 통계: 열마다 nan_count 가 먼저. text 는 글(길이 통계), label 0/1 은 숫자로 읽힌다. 원소가 하나라 파일 이름을 앞에 붙이지 않는다
    assert internal(local) == {"size": "80", "modality:0": "structured", **stats_props([
                                   ("id:nan_count", "0"), ("id:min", "1"), ("id:max", "5"), ("id:mean", "3"), ("id:median", "3"), ("id:std", "1.58114"),
                                   ("text:nan_count", "0"), ("text:length:min", "3"), ("text:length:max", "10"), ("text:length:mean", "6.2"),
                                   ("text:length:median", "5"), ("text:length:std", "3.11448"),
                                   ("label:nan_count", "0"), ("label:min", "0"), ("label:max", "1"), ("label:mean", "0.6"), ("label:median", "1"), ("label:std", "0.54772")])}

    hf = found[IMDB_REF]
    assert hf["group"] == "stanfordnlp" and hf["name"] == "imdb" and hf["purl"] == IMDB_REF
    assert hf["data"] == [{"type": "dataset", "name": IMDB, "contents": {"url": "https://huggingface.co/datasets/stanfordnlp/imdb"}}]
    assert hf["evidence"]["occurrences"] == [{"location": "src/train.py"}]
    assert online == [IMDB]

    root_row = next(d for d in out["dependencies"] if d["ref"] == "application:/proj@")
    assert root_row["dependsOn"] == ["data:local/data@", IMDB_REF]
    assert str(tmp_path) not in json.dumps(out)                                   # 절대 경로가 새지 않는다


def test_data_path_counts_json_and_txt_but_not_metadata_names(tmp_path, online):
    """지목한 경로 안에서는 json·txt 도 데이터다. 문서·설정·save_to_disk 메타데이터 이름, 숨은 파일, 모르는 확장자는 뺀다."""
    for rel in ("a.txt", "labels.json", "b.csv", "README.md", "README.txt", "LICENSE.txt", "model_config.json",
                "dataset_info.json", "state.json", "x.xlsx", ".hidden.csv"):
        write(tmp_path, f"corpus/{rel}", "a\n1\n")
    found = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "corpus")]))
    assert [d["name"] for d in found["data:local/corpus@"]["data"]] == ["corpus/a.txt", "corpus/b.csv", "corpus/labels.json"]


def test_skip_dirs_and_hidden_dirs_are_not_walked(tmp_path, online):
    for d in ("node_modules", ".git", "venv", ".venv", "site-packages", "__pycache__", ".cache"):
        write(tmp_path, f"data/{d}/x.csv", "a\n1\n")                          # 데이터 경로 안에서도
        write(tmp_path, f"{d}/x.py", 'load_dataset("hidden/one")\n')            # 대상의 소스를 훑을 때도
    write(tmp_path, "data/ok/y.csv", "a\n1\n")
    found = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=data_of(tmp_path)))
    assert set(found) == {"data:local/data@"} and [d["name"] for d in found["data:local/data@"]["data"]] == ["data/ok/y.csv"]


def test_a_single_file_data_path_is_its_own_component(tmp_path, online):
    write(tmp_path, "train.csv", "a\n1\n")
    found = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "train.csv")]))
    assert set(found) == {"data:local/train@"} and found["data:local/train@"]["name"] == "train"
    assert [d["name"] for d in found["data:local/train@"]["data"]] == ["train.csv"]
    facts = internal(found["data:local/train@"])
    assert "provenance:0" not in facts and "availability" not in facts       # 로컬 파일로는 출처·가용성을 알 수 없다


def test_media_files_are_grouped_by_folder_and_modality(tmp_path, online):
    """이미지·오디오는 파일마다가 아니라 (폴더, 모달리티) 단위로 data[] 원소 하나다. 확장자가 섞여도 한 폴더의 이미지는 한 묶음이고
    이름에 형식을 나열한다. 파일 수와 크기 합만 적고 내용은 읽지 않는다. 표 파일은 파일마다 하나이고 통계도 표 파일에서만 나온다."""
    for rel, content in (("data/images/cat/a.jpg", b"\xff\xd8" + b"a" * 10), ("data/images/cat/b.jpeg", b"\xff\xd8" + b"b" * 20),
                         ("data/images/cat/c.png", b"\x89PNG" + b"c" * 5), ("data/photos/d.png", b"\x89PNG" + b"d" * 5),
                         ("data/audio/x.wav", b"RIFF" + b"x" * 4)):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(content)
    write(tmp_path, "data/train.csv", "a,b\n1,2\n")
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "data")]))["data:local/data@"]
    assert [d["name"] for d in local["data"]] == ["data/audio/x.wav", "data/images/cat/*.{jpg,png}", "data/photos/d.png", "data/train.csv"]   # 파일 하나뿐인 묶음은 그 이름
    assert all(set(d) == {"type", "name"} for d in local["data"])                                 # 파일 사실은 원소에 적지 않는다
    facts = internal(local)
    assert facts["size"] == str(12 + 22 + 9 + 9 + 8 + 8)
    assert [facts[f"modality:{i}"] for i in range(3)] == ["audio", "image", "structured"]
    assert all(v.startswith("train:") for k, v in facts.items() if k.endswith(":type"))         # 통계는 train.csv 것뿐


def test_mixed_formats_in_class_folders_are_one_dataset(tmp_path, online):
    """ImageFolder 처럼 jpg 와 png 가 섞인 클래스 폴더도 데이터셋 하나이고 라벨 수에 전부 든다."""
    local = fake_jpgs(tmp_path, "imgset", ["train/cat/0.jpg", "train/cat/2.jpg", "train/dog/0.jpg", "train/dog/1.jpg"])
    (tmp_path / "imgset/train/cat/1.png").write_bytes(b"\x89PNG" + bytes(8))
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "imgset")]))["data:local/imgset@"]
    assert [d["name"] for d in local["data"]] == ["imgset/train/*.{jpg,png}"]
    assert stats_of(local)["label:frequencies"] == "cat=3,dog=2"


def test_a_single_media_file_data_path_keeps_its_file_name(tmp_path, online):
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8" + b"p" * 3)
    found = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "photo.jpg")]))
    items = found["data:local/photo@"]["data"]
    assert items == [{"type": "dataset", "name": "photo.jpg"}]
    assert internal(found["data:local/photo@"])["size"] == "5"


def stats_of(comp: dict) -> dict[str, str]:
    facts = internal(comp)
    return {facts[k]: facts[k.replace(":type", ":value")] for k in facts if k.endswith(":type")}


def test_shards_of_one_split_are_merged_into_one_entry(tmp_path, online):
    """train-00000-of-00002 처럼 크기 때문에 나뉜 조각은 분할 하나로 합친다. 행 수·크기는 합, 통계는 조각을 이어 붙여 낸다.
    조각이 하나뿐이면 보통 파일이되 통계 앞머리는 분할 이름이다."""
    a, b, t = "a,b\n1,x\n2,y\n", "a,b\n3,z\n", "a,b\n9,q\n"
    write(tmp_path, "data/train-00000-of-00002.csv", a)
    write(tmp_path, "data/train-00001-of-00002.csv", b)
    write(tmp_path, "data/test-00000-of-00001.csv", t)
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "data")]))["data:local/data@"]
    assert [d["name"] for d in local["data"]] == ["data/test-00000-of-00001.csv", "data/train-*.csv"]
    stats = stats_of(local)
    assert (stats["train:a:min"], stats["train:a:max"], stats["train:a:mean"]) == ("1", "3", "2")
    assert stats["test:a:min"] == "9"
    assert internal(local)["size"] == str(len(a) + len(b) + len(t))


def test_class_folders_merge_into_one_entry_with_label_statistics(tmp_path, online):
    """train/cat, train/dog 처럼 하위 폴더가 둘 이상 같은 형식의 매체만 들고 있으면 그 폴더(train) 하나로 합치고 폴더 이름이 라벨이 된다.
    형제 분할이 합쳐졌으면 클래스가 하나뿐인 test/cat 도 test 로 합친다. metadata.csv 는 원소가 아니라 주석 표라 label 열 통계만 보태고,
    labels/ 아래는 주석 파일이라 세지 않는다."""
    for rel in ("imgset/train/cat/0.jpg", "imgset/train/cat/1.jpg", "imgset/train/dog/0.jpg", "imgset/test/cat/0.jpg"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"\xff\xd8" + bytes(10))
    meta = "file_name,label\ntrain/cat/0.jpg,cat\ntrain/cat/1.jpg,cat\ntrain/dog/0.jpg,dog\n"
    write(tmp_path, "imgset/metadata.csv", meta)
    write(tmp_path, "imgset/labels/0.txt", "0 0.5 0.5 0.1 0.1\n")
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "imgset")]))["data:local/imgset@"]
    assert [d["name"] for d in local["data"]] == ["imgset/test/*.jpg", "imgset/train/*.jpg"]    # train 이 합쳐졌으니 클래스 하나뿐인 test 도 같은 꼴로
    stats = stats_of(local)
    assert (stats["train:label:n_unique"], stats["train:label:mode"], stats["train:label:frequencies"]) == ("2", "cat", "cat=2,dog=1")
    assert (stats["test:label:n_unique"], stats["test:label:frequencies"]) == ("1", "cat=1")
    assert not any(":width:" in k for k in stats)                                                            # 가짜 jpg 라 헤더를 못 읽어 너비 통계는 없다
    assert (stats["imgset:label:n_unique"], stats["imgset:label:frequencies"]) == ("2", "cat=2,dog=1")       # metadata.csv 의 label 열
    assert not any(k.startswith("imgset:file_name") for k in stats)                                           # 파일을 가리키는 열은 통계 없음
    assert internal(local)["size"] == str(4 * 12 + len(meta) + len("0 0.5 0.5 0.1 0.1\n"))                   # 주석도 데이터셋 크기에는 든다
    assert internal(local)["modality:0"] == "image" and "modality:1" not in internal(local)


def fake_jpgs(tmp_path, root: str, rels: list[str]) -> dict:
    for rel in rels:
        (tmp_path / root / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / root / rel).write_bytes(b"\xff\xd8" + bytes(10))
    doc = discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / root)])
    return datasets(doc)[f"data:local/{root}@"]


def test_nested_class_folders_take_labels_from_the_folder_right_above_the_files(tmp_path, online):
    """ImageFolder 규약: train/animals/cat/0.jpg 의 라벨은 animals 가 아니라 cat 이다. 중간 폴더는 거쳐 올라가기만 한다."""
    local = fake_jpgs(tmp_path, "imgset", ["train/animals/cat/0.jpg", "train/animals/cat/1.jpg", "train/animals/dog/0.jpg",
                                           "train/vehicles/car/0.jpg", "train/vehicles/bus/0.jpg"])
    assert [d["name"] for d in local["data"]] == ["imgset/train/*.jpg"]
    stats = stats_of(local)
    assert (stats["label:n_unique"], stats["label:mode"]) == ("4", "cat")                 # 원소가 하나라 통계 이름에 폴더 접두어가 없다
    assert stats["label:frequencies"] == "cat=2,bus=1,car=1,dog=1"


def test_split_folders_are_never_merged_as_classes(tmp_path, online):
    """train·test 는 분할이지 클래스가 아니다. 파일이 바로 들어 있어도 라벨 없이 분할마다 데이터셋 하나이고, 클래스 폴더를 품었어도
    분할끼리 다시 합치지 않는다."""
    local = fake_jpgs(tmp_path, "plain", ["train/0.jpg", "train/1.jpg", "test/0.jpg", "test/1.jpg"])
    assert [d["name"] for d in local["data"]] == ["plain/test/*.jpg", "plain/train/*.jpg"]
    assert not any(":label:" in k for k in stats_of(local))
    local = fake_jpgs(tmp_path, "classed", ["train/cat/0.jpg", "train/dog/0.jpg", "test/cat/0.jpg", "test/dog/0.jpg"])
    assert [d["name"] for d in local["data"]] == ["classed/test/*.jpg", "classed/train/*.jpg"]
    stats = stats_of(local)
    assert stats["train:label:frequencies"] == "cat=1,dog=1" and stats["test:label:frequencies"] == "cat=1,dog=1"


def test_mixed_depth_class_folders_merge_without_labels(tmp_path, online):
    """train/cat/0.jpg 와 train/animals/{dog,bird}/0.jpg 처럼 깊이가 섞이면 ImageFolder 도 라벨을 붙이지 않는다. 묶음은 train 하나다."""
    local = fake_jpgs(tmp_path, "mixed", ["train/cat/0.jpg", "train/animals/dog/0.jpg", "train/animals/bird/0.jpg"])
    assert [d["name"] for d in local["data"]] == ["mixed/train/*.jpg"]
    assert not any(":label:" in k for k in stats_of(local))


def png(width: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, 10) + bytes(5) + bytes(4)


def jpeg(width: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + bytes(9)                    # 길이 16 짜리 APP0 세그먼트
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 600, width, 3) + bytes(9)
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def webp(width: int) -> bytes:
    w = (width - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 22) + b"WEBP" + b"VP8X" + struct.pack("<I", 10) + bytes(4) + w + (9).to_bytes(3, "little")


def wav(seconds: float, byte_rate: int = 16000) -> bytes:
    data = bytes(int(seconds * byte_rate))
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, byte_rate, 2, 16)
    return b"RIFF" + struct.pack("<I", 4 + len(fmt) + 8 + len(data)) + b"WAVE" + fmt + b"data" + struct.pack("<I", len(data)) + data


def flac(seconds: float, sample_rate: int = 44100) -> bytes:
    packed = (sample_rate << 44) | (1 << 41) | (15 << 36) | int(seconds * sample_rate)       # 2채널, 16비트
    streaminfo = struct.pack(">HH", 4096, 4096) + bytes(6) + packed.to_bytes(8, "big") + bytes(16)
    return b"fLaC" + bytes([0x80]) + (34).to_bytes(3, "big") + streaminfo


def mp3(seconds: float) -> bytes:
    header = bytes([0xFF, 0xFB, 0x90, 0x00])                                               # MPEG1 Layer III, 128 kbps, 44.1 kHz, 스테레오
    return header + bytes(int(seconds * 128000 / 8) - 4)                                    # Xing 없음 → 고정 비트레이트로 본다


def test_media_statistics_come_from_file_headers(tmp_path, online):
    """이미지는 너비, 오디오는 길이의 분포. 헤더만 읽는다. 이름은 허브의 image·audio 열 통계와 같은 꼴(train:image:width:min)이다."""
    files = {"media/img/a.png": png(640), "media/img/b.png": png(320), "media/snd/a.wav": wav(2.0), "media/snd/b.wav": wav(1.0),
             "media/c.jpg": jpeg(800), "media/d.webp": webp(300), "media/e.flac": flac(2.0), "media/f.mp3": mp3(1.0)}
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(content)
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "media")]))["data:local/media@"]
    stats = stats_of(local)
    assert (stats["img:image:width:min"], stats["img:image:width:max"], stats["img:image:width:mean"], stats["img:image:width:std"]) == ("320", "640", "480", "226.27417")
    assert (stats["img:image:height:min"], stats["img:image:height:max"]) == ("10", "10")                     # png() 는 높이 10 으로 만든다
    assert (stats["snd:audio:duration:min"], stats["snd:audio:duration:max"], stats["snd:audio:duration:mean"], stats["snd:audio:duration:std"]) == ("1", "2", "1.5", "0.70711")
    assert (stats["media:image:width:min"], stats["media:image:width:max"]) == ("300", "800")                  # 폴더 바로 아래의 jpg·webp 는 한 묶음
    assert (stats["media:audio:duration:min"], stats["media:audio:duration:max"]) == ("1", "2")
    assert [d["name"] for d in local["data"]] == ["media/*.{flac,mp3}", "media/*.{jpg,webp}", "media/img/*.png", "media/snd/*.wav"]
    assert all(set(d) == {"type", "name"} for d in local["data"])


@pytest.mark.parametrize("make, fmt, expected", [(png, "png", {"width": 640.0, "height": 10.0}), (jpeg, "jpg", {"width": 800.0, "height": 600.0}),
                                                 (webp, "webp", {"width": 300.0, "height": 10.0}),
                                                 (wav, "wav", {"duration": 2.0}), (flac, "flac", {"duration": 2.0}), (mp3, "mp3", {"duration": 1.0})])
def test_media_header_parsers(tmp_path, make, fmt, expected):
    arg = {"png": 640, "jpg": 800, "webp": 300, "wav": 2.0, "flac": 2.0, "mp3": 1.0}[fmt]
    path = tmp_path / f"x.{fmt}"
    path.write_bytes(make(arg))
    assert ds._media_measure(path, fmt) == pytest.approx(expected)
    (tmp_path / f"bad.{fmt}").write_bytes(b"garbage" * 10)
    assert ds._media_statistics([tmp_path / f"bad.{fmt}"], fmt) == []                        # 못 읽는 파일은 통계에서 빠진다


def test_data_files_in_the_target_are_not_read_without_a_data_path(tmp_path, monkeypatch):
    """로컬 데이터는 --data 로 지목한 곳에서만 읽는다. 확장자만 보고 추측하면 아이콘 같은 것도 데이터셋이 된다."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("조회할 것이 없는데 네트워크를 봤다"))
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "static/icon.png", "x")
    write(tmp_path, "app.py", 'import pandas as pd\npd.read_csv("data/train.csv")\n')       # 코드가 읽어도 넣지 않는다
    doc = doc_of()
    before = json.dumps(doc)
    assert json.dumps(discover_datasets(doc, str(tmp_path))) == before


def test_data_paths_are_deduplicated_and_names_do_not_collide(tmp_path, online):
    write(tmp_path, "a/data/x.csv", "v\n1\n")
    write(tmp_path, "b/data/y.csv", "v\n2\n")
    write(tmp_path, "empty/notes.md", "docs\n")
    report: dict = {}
    paths = [str(tmp_path / "a/data"), str(tmp_path / "a/data") + "/", str(tmp_path / "a/data/x.csv"),   # 같은 곳 · 이미 들어간 파일
             str(tmp_path / "b/data"), str(tmp_path / "empty"), str(tmp_path / "missing")]
    found = datasets(discover_datasets(doc_of(), str(tmp_path), report=report, data_paths=paths))
    assert set(found) == {"data:local/data@", "data:local/data-2@"}                  # 폴더 이름이 같으면 -2
    assert [d["name"] for d in found["data:local/data@"]["data"]] == ["data/x.csv"]
    assert [d["name"] for d in found["data:local/data-2@"]["data"]] == ["data/y.csv"]
    assert report["empty_data_paths"] == [str(tmp_path / "a/data/x.csv"), str(tmp_path / "empty"), str(tmp_path / "missing")]


def test_nested_files_keep_their_path_and_statistics_prefix(tmp_path, online):
    write(tmp_path, "imdb/train/part-0.csv", "v\n1\n3\n")
    write(tmp_path, "imdb/test/part-0.csv", "v\n5\n")
    local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=[str(tmp_path / "imdb")]))["data:local/imdb@"]
    assert [d["name"] for d in local["data"]] == ["imdb/test/part-0.csv", "imdb/train/part-0.csv"]
    kinds = {v for k, v in internal(local).items() if k.endswith(":type")}
    assert {"test/part-0:v:min", "train/part-0:v:min"} <= kinds                   # 같은 파일 이름도 경로로 갈린다


# -- discover: 허브 -------------------------------------------------------------------
def test_hub_info_fills_component_and_facts(imdb):
    comp = ds._new_hf_component(IMDB)
    ds._apply_hub_info(comp, IMDB, imdb)
    assert comp["version"] == imdb["sha"] and comp["supplier"] == {"name": "stanfordnlp"}
    assert comp["licenses"] == [{"license": {"name": "other"}}]                   # "other" 는 SPDX id 가 아니다
    assert comp["description"].startswith('Dataset Card for "imdb" Dataset Summary Large Movie Review Dataset.') and "\n" not in comp["description"]
    assert comp["externalReferences"] == [{"type": "distribution", "url": "https://huggingface.co/datasets/stanfordnlp/imdb"},
                                          {"type": "website", "url": "https://paperswithcode.com/dataset/imdb-movie-reviews"}]
    assert internal(comp) == {"size": "133190302", "modality:0": "text", "availability": "direct-download",
                              "provenance:0": "https://huggingface.co/datasets/stanfordnlp/imdb",
                              "intendedUse": "text-classification, sentiment-classification",             # task_categories + task_ids
                              "collectionProcess": "annotations expert-generated; language expert-generated"}   # 통계 응답이 없으면 statistics 도 없다
    # datasets-server 통계를 주면 split:열:통계 로 들어간다. 라벨 열은 n_unique·frequencies, 글 열은 길이의 min·max·mean·median·std
    comp = ds._new_hf_component(IMDB)
    ds._apply_hub_info(comp, IMDB, imdb, imdb_size(), [("plain_text", "train", imdb_statistics("plain_text", "train"))])
    assert {k: v for k, v in internal(comp).items() if k.startswith("statistics")} == stats_props(IMDB_TRAIN_STATS)


def test_hub_facts_variants():
    gated = ds._hub_facts("a/b", {"gated": "auto", "cardData": {"license": "apache-2.0", "task_categories": ["image-classification", "audio-classification", "tabular-regression", "weird"],
                                                               "dataset_info": [{"config_name": "x", "download_size": 10, "splits": [{"name": "train", "num_examples": 3}], "features": [{}]},
                                                                                {"config_name": "y", "dataset_size": 5}]}})
    assert gated["availability"] == "registration" and gated["size"] == 15 and gated["modality"] == ["image", "audio", "structured", "other"]
    assert gated["statistics"] == []                                                       # 행 수·feature 수·config 수는 통계가 아니다
    assert gated["intendedUse"] == "image-classification, audio-classification, tabular-regression, weird" and gated["collectionProcess"] is None
    empty = ds._hub_facts("a/b", {"id": "a/b"})
    assert empty["size"] is None and empty["modality"] == [] and empty["statistics"] == [] and empty["availability"] == "direct-download"
    assert empty["intendedUse"] is None and empty["collectionProcess"] is None and empty["provenance"] == ["https://huggingface.co/datasets/a/b"]
    # source_datasets: 상위 데이터셋은 provenance 에 더한다. original·extended 는 id 가 아니고, extended|<id> 는 id 만
    card = {"source_datasets": ["original", "extended|squad", "rajpurkar/squad_v2", "extended"], "annotations_creators": ["crowdsourced", "crowdsourced"],
            "language_creators": ["found"]}
    facts = ds._hub_facts("a/b", {"id": "a/b", "cardData": card})
    assert facts["provenance"] == ["https://huggingface.co/datasets/a/b", "https://huggingface.co/datasets/squad", "https://huggingface.co/datasets/rajpurkar/squad_v2"]
    assert facts["collectionProcess"] == "annotations crowdsourced; language found"
    # README 앞머리에 크기가 없으면 datasets-server /size 의 원본 파일 바이트. 앞머리에 있으면 그것이 이긴다
    assert ds._hub_facts("a/b", {"id": "a/b"}, imdb_size())["size"] == 83446840
    assert ds._hub_facts("a/b", {"id": "a/b", "cardData": {"dataset_info": {"dataset_size": 7}}}, imdb_size())["size"] == 7
    assert ds._hub_facts("a/b", {"id": "a/b"}, {"size": {}})["size"] is None
    # 허브의 modality: 태그가 있으면 task_categories 보다 먼저다. 모르는 태그 값은 other, 태그 값은 v0.6 허용값으로 옮긴다
    tagged = ds._hub_facts("a/b", {"tags": ["modality:tabular", "modality:text", "modality:3d", "format:parquet", "modality:text"],
                                   "cardData": {"task_categories": ["image-classification"]}})
    assert tagged["modality"] == ["structured", "text", "other"]
    assert ds._hub_facts("a/b", {"tags": ["format:parquet"], "cardData": {"task_categories": ["image-classification"]}})["modality"] == ["image"]
    assert license_entry("apache-2.0") == {"license": {"id": "Apache-2.0"}} and license_entry("MIT") == {"license": {"id": "MIT"}}
    assert license_entry("unknown") == {"license": {"name": "unknown"}}
    # 카드의 other 는 license_name 이 있으면 그 이름, license_link 는 url. 이름이 없으면 other 그대로
    assert card_licenses({"license": "other", "license_name": "acme-eval", "license_link": "https://acme.example/l"}) == [
        {"license": {"name": "acme-eval", "url": "https://acme.example/l"}}]
    assert card_licenses({"license": ["other", "mit"], "license_link": "LICENSE.md"}) == [{"license": {"name": "other"}}, {"license": {"id": "MIT"}}]
    assert card_licenses({"license": ""}) == [] and card_licenses({}) == []


def test_existing_cdxgen_component_is_enriched_in_place_not_duplicated(tmp_path, monkeypatch, imdb):
    write(tmp_path, "train.py", 'load_dataset("bookcorpus")\n')
    doc = doc_of(cdxgen_bookcorpus())
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: {**copy.deepcopy(imdb), "id": "bookcorpus", "sha": "abc"} if hf_id == "bookcorpus" else None)
    deps_before = copy.deepcopy(doc["dependencies"])
    out = discover_datasets(doc, str(tmp_path))
    found = datasets(out)
    assert set(found) == {BOOK_HUB}                                                    # 새 컴포넌트 없이, purl 없던 cdxgen 것이 정식 purl·bom-ref 로
    book = found[BOOK_HUB]
    assert book["purl"] == BOOK_HUB and book["data"][0]["contents"]["url"] == "https://huggingface.co/datasets/bookcorpus"   # cdxgen 의 datasets/datasets 주소도 고친다
    assert book["version"] == "abc" and book["evidence"]["occurrences"] == [{"location": "train.py"}]
    assert {(r["type"], r["url"]) for r in book["externalReferences"]} >= {("distribution", "https://huggingface.co/datasets/bookcorpus")}
    assert internal(book)["provenance:0"] == "https://huggingface.co/datasets/bookcorpus"
    assert props(book)["cdx:ai:kind"] == "dataset"                                     # cdxgen 프로퍼티는 그대로
    assert out["dependencies"] == json.loads(json.dumps(deps_before).replace("data:datasets/bookcorpus@", BOOK_HUB))   # 관계는 새 bom-ref 를 따라갈 뿐


# -- 허브 정식 id 로 모으기 -------------------------------------------------------------
BERT_REF = "pkg:huggingface/google-bert/bert-base-uncased"
BOOK_CANON = "pkg:huggingface/datasets/bookcorpus/bookcorpus"


def cdxgen_bert() -> dict:
    """cdxgen 이 README 에서 만드는 모델. modelCard 의 데이터셋 ref 는 purl 문자열이라 merge 가 data:datasets/bookcorpus@ 로 잇는다."""
    return {"bom-ref": BERT_REF, "type": "machine-learning-model", "group": "google-bert", "name": "bert-base-uncased", "purl": BERT_REF,
            "modelCard": {"modelParameters": {"datasets": [{"ref": "pkg:huggingface/datasets/bookcorpus"}]}}}


def readme_doc() -> dict:
    doc = merge([{"bomFormat": "CycloneDX", "specVersion": "1.7", "components": [cdxgen_bert(), cdxgen_bookcorpus()],
                  "dependencies": [{"ref": BERT_REF, "dependsOn": ["cdxgen:ai:dataset:huggingface:datasets-bookcorpus"]}]}],
                root=("proj", "directory"))
    assert next(c for c in doc["components"] if c["bom-ref"] == BERT_REF)["modelCard"]["modelParameters"]["datasets"] == [{"ref": "data:datasets/bookcorpus@"}]
    return doc


def bookcorpus_hub(imdb: dict) -> dict:
    return {**copy.deepcopy(imdb), "id": "bookcorpus/bookcorpus", "author": "bookcorpus", "sha": "abc", "paperswithcode_id": None}


def refs_in(doc: dict) -> set[str]:
    out = {t for d in doc["dependencies"] for t in [d["ref"], *d["dependsOn"]]}
    for c in doc["components"]:
        out |= {e["ref"] for e in ((c.get("modelCard") or {}).get("modelParameters") or {}).get("datasets") or [] if e.get("ref")}
    return out


def deps_of(doc: dict) -> dict[str, list[str]]:
    return {d["ref"]: d["dependsOn"] for d in doc["dependencies"]}


@pytest.mark.parametrize("info_id", ["imdb", "stanfordnlp/imdb", "", None, "../x", 3])
def test_canonical_id_takes_a_well_formed_hub_id_only(info_id):
    expected = info_id if info_id in ("imdb", "stanfordnlp/imdb") else "a/b"
    assert ds._canonical_id("a/b", {"id": info_id}) == expected
    assert ds._canonical_id("a/b", None) == "a/b" and ds._canonical_id("a/b", {}) == "a/b"


def test_same_dataset_under_two_ids_becomes_one_component_and_one_hub_call(tmp_path, monkeypatch, imdb, logs):
    """README 의 bookcorpus 와 코드의 bookcorpus/bookcorpus. 허브는 둘 다 bookcorpus/bookcorpus 라 답한다."""
    write(tmp_path, "train.py", 'load_dataset("bookcorpus/bookcorpus")\n')
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: calls.append(hf_id) or bookcorpus_hub(imdb))
    logs.clear()
    out = discover_datasets(readme_doc(), str(tmp_path))
    found = datasets(out)
    assert set(found) == {BOOK_CANON} and calls == ["bookcorpus"]                       # 하나로, 조회도 한 번
    book = found[BOOK_CANON]
    assert (book["group"], book["name"], book["purl"], book["version"]) == ("bookcorpus", "bookcorpus", BOOK_CANON, "abc")
    assert book["data"] == [{"type": "dataset", "name": "bookcorpus/bookcorpus", "contents": {"url": "https://huggingface.co/datasets/bookcorpus/bookcorpus"}}]
    assert book["evidence"]["occurrences"] == [{"location": "train.py"}]
    assert props(book)["cdx:ai:kind"] == "dataset" and book["supplier"] == {"name": "bookcorpus"}   # cdxgen 값은 남고 허브 값이 더해진다
    assert internal(book)["provenance:0"] == "https://huggingface.co/datasets/bookcorpus/bookcorpus"
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": BOOK_CANON}]      # 모델 → 데이터셋 참조가 따라간다
    deps = deps_of(out)
    assert deps[BERT_REF] == [BOOK_CANON] and set(deps[out["metadata"]["component"]["bom-ref"]]) == {BERT_REF, BOOK_CANON}
    assert refs_in(out) <= {c["bom-ref"] for c in out["components"]} | {out["metadata"]["component"]["bom-ref"]}   # 끊긴 참조 없음
    assert [m for m in logs if "merged into" in m] == ["[dataset] bookcorpus: merged into bookcorpus/bookcorpus, same dataset"]
    for form in ("properties", "typed"):
        assert _validate_cdx(regulate(copy.deepcopy(out), form=form), "1.7" if form == "properties" else "v0.6")


def test_readme_only_component_is_renamed_to_the_hub_id_and_refs_follow(tmp_path, monkeypatch, imdb, logs):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: bookcorpus_hub(imdb))
    logs.clear()
    facts = Facts()
    out = discover_datasets(readme_doc(), str(tmp_path), facts=facts)
    found = datasets(out)
    assert set(found) == {BOOK_CANON}
    assert facts.times == {BOOK_CANON: {"releaseTime": "2024-01-04T12:09:45Z"}} and not facts.roles   # cdxgen 이 이은 것이라 역할은 모른다
    book = found[BOOK_CANON]
    assert (book["group"], book["name"], book["purl"]) == ("bookcorpus", "bookcorpus", BOOK_CANON)
    assert book["data"][0]["name"] == "bookcorpus/bookcorpus"                             # cdxgen 이 붙인 datasets/ 앞머리는 빼고 정식 id 로
    assert book["data"][0]["contents"]["url"] == "https://huggingface.co/datasets/bookcorpus/bookcorpus"
    assert props(book)["cdx:ai:kind"] == "dataset"
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": BOOK_CANON}]
    deps = deps_of(out)
    assert deps[BERT_REF] == [BOOK_CANON] and deps[out["metadata"]["component"]["bom-ref"]] == [BERT_REF]   # 코드에서 안 불렀으니 루트 → 데이터셋 엣지는 없다
    assert "[dataset] bookcorpus: renamed to bookcorpus/bookcorpus (canonical id)" in logs


def test_old_hub_name_in_code_is_renamed_and_two_spellings_collapse(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: calls.append(hf_id) or copy.deepcopy(imdb))
    write(tmp_path, "a.py", 'load_dataset("imdb")\n')
    write(tmp_path, "b.py", 'load_dataset("stanfordnlp/imdb")\n')
    out = discover_datasets(doc_of(), str(tmp_path))
    found = datasets(out)
    assert set(found) == {IMDB_REF} and calls == ["imdb"]
    hf = found[IMDB_REF]
    assert (hf["group"], hf["name"], hf["purl"], hf["data"][0]["name"]) == ("stanfordnlp", "imdb", IMDB_REF, IMDB)
    assert hf["evidence"]["occurrences"] == [{"location": "a.py"}, {"location": "b.py"}]
    assert deps_of(out)[out["metadata"]["component"]["bom-ref"]] == [IMDB_REF]           # 옛 이름의 purl 은 관계에서도 사라진다
    assert internal(hf)["size"] == "133190302"


def test_alias_whose_lookup_fails_stays_a_separate_component(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: copy.deepcopy(imdb) if hf_id == IMDB else None)
    write(tmp_path, "a.py", 'load_dataset("imdb")\nload_dataset("stanfordnlp/imdb")\n')
    found = datasets(discover_datasets(doc_of(), str(tmp_path)))
    assert set(found) == {IMDB_REF, "pkg:huggingface/datasets/imdb"}                     # 같은 것인지 알 길이 없으니 둔다
    assert "properties" not in found["pkg:huggingface/datasets/imdb"]


# -- 통계 (datasets-server · 로컬 열) ------------------------------------------------------
# -- 허브 모델 카드의 데이터셋 ----------------------------------------------------------
def hub_bert(**extra) -> dict:
    """코드의 from_pretrained 로 cdxgen 이 만드는 허브 모델. 모델 카드 값은 없다."""
    return {"bom-ref": BERT_REF, "type": "machine-learning-model", "group": "google-bert", "name": "bert-base-uncased", "purl": BERT_REF, **extra}


def model_info(datasets=(), evaluated=()) -> dict:
    """GET /api/models/<id> 응답 모양. cardData 의 datasets 가 학습, model-index 결과의 dataset 이 평가 데이터셋이다."""
    card: dict = {"datasets": list(datasets)}
    if evaluated:
        card["model-index"] = [{"name": "m", "results": [{"task": {"type": "x"}, "dataset": d} for d in evaluated]}]
    return {"id": "google-bert/bert-base-uncased", "cardData": card}


def test_hub_model_card_datasets_become_components_linked_from_the_model(tmp_path, monkeypatch, online, logs):
    """코드가 부르는 허브 모델의 카드에 적힌 학습·평가 데이터셋이 데이터셋 컴포넌트가 되고 허브 정보로 채워진다. 같은 id 의 컴포넌트는
    다시 쓰고, 모델카드에는 ref 로 적고 모델이 dependsOn 한다. 루트에는 잇지 않는다. 허브 id 꼴이 아닌 이름은 건너뛰고 알린다."""
    calls: list[str] = []
    info = model_info(["bookcorpus", IMDB], [{"name": "GLUE SST2", "type": "glue"}, {"name": "x", "type": "./eval.csv"}, {"name": "imdb", "type": IMDB}])
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: calls.append(hf_id) or copy.deepcopy(info))
    logs.clear()
    facts = Facts()
    out = discover_datasets(doc_of(hub_bert(), cdxgen_bookcorpus()), str(tmp_path), facts=facts)
    glue = "pkg:huggingface/datasets/glue"
    assert calls == ["google-bert/bert-base-uncased"]
    assert facts.roles == {(BERT_REF, BOOK_HUB): {"training"}, (BERT_REF, IMDB_REF): {"training", "evaluation"}, (BERT_REF, glue): {"evaluation"}}
    assert facts.times == {IMDB_REF: {"releaseTime": "2024-01-04T12:09:45Z"}}            # 역할은 바뀐 bom-ref 를 따라가고, 시각은 허브 응답에서
    assert set(datasets(out)) == {BOOK_HUB, IMDB_REF, glue}                              # bookcorpus 는 cdxgen 것을 다시 쓴다 (purl 만 정식으로)
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": BOOK_HUB}, {"ref": IMDB_REF}, {"ref": glue}]
    deps = deps_of(out)
    assert deps[BERT_REF] == sorted([BOOK_HUB, IMDB_REF, glue])
    assert not {IMDB_REF, glue} & set(deps[out["metadata"]["component"]["bom-ref"]])     # 코드가 부른 것이 아니라 루트는 잇지 않는다
    assert internal(datasets(out)[IMDB_REF])["size"] == "133190302"                       # 그 뒤는 허브 데이터셋과 같게 채운다
    assert any("'./eval.csv' is not a hub id" in m for m in logs)
    assert refs_in(out) <= {c["bom-ref"] for c in out["components"]} | {out["metadata"]["component"]["bom-ref"]}


def test_model_infos_from_the_m_bom_step_are_read_without_asking_the_hub_again(tmp_path, monkeypatch, online):
    """M-BOM 보강이 받아 둔 응답(model_infos)과 허브에 닿는지 본 결과(hub_reachable)를 주면, 모델 카드를 다시 받지 않고
    허브 연결도 다시 보지 않는다. 데이터셋 조회는 그대로 한다."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("M-BOM 보강이 본 결과가 있는데 허브 연결을 다시 봤다"))
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: pytest.fail("M-BOM 보강이 받은 응답이 있는데 다시 받았다"))
    out = discover_datasets(doc_of(hub_bert()), str(tmp_path),
                      model_infos={"google-bert/bert-base-uncased": model_info([IMDB])}, hub_reachable=True)
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": IMDB_REF}]
    assert internal(datasets(out)[IMDB_REF])["size"] == "133190302"


def test_name_only_entries_become_refs_and_a_model_card_that_cannot_be_read_changes_nothing(tmp_path, monkeypatch, online):
    """같은 데이터셋을 이름만 적은 항목(aibom-generator 꼴)은 ref 로 바뀌어 한 번만 남고 다른 항목은 그대로다.
    모델 카드를 못 읽은 모델은 손대지 않는다."""
    named = hub_bert(modelCard={"modelParameters": {"datasets": [
        {"type": "dataset", "name": "glue", "contents": {"url": "https://huggingface.co/datasets/glue"}}, {"type": "dataset", "name": "kept"}]}})
    other = {"bom-ref": "pkg:huggingface/acme/other", "type": "machine-learning-model", "name": "other", "purl": "pkg:huggingface/acme/other",
             "modelCard": {"modelParameters": {"datasets": [{"type": "dataset", "name": "x"}]}}}
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: model_info(["glue"]) if hf_id == "google-bert/bert-base-uncased" else None)
    doc = doc_of(named, other)
    before = json.dumps(next(c for c in doc["components"] if c["name"] == "other"))
    out = discover_datasets(doc, str(tmp_path))
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"type": "dataset", "name": "kept"}, {"ref": "pkg:huggingface/datasets/glue"}]
    assert json.dumps(next(c for c in out["components"] if c["name"] == "other")) == before


def test_offline_reads_no_model_card_and_says_so_once(tmp_path, monkeypatch, logs):
    """허브에 닿는지는 한 번만 보고, 닿지 않으면 모델 카드도 데이터셋도 묻지 않는다. 알림도 한 줄이다."""
    checks: list[bool] = []
    monkeypatch.setattr(hub, "hf_reachable", lambda: checks.append(True) or False)
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: pytest.fail("offline 인데 모델 카드를 읽었다"))
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: pytest.fail("offline 인데 데이터셋을 조회했다"))
    logs.clear()
    report: dict = {}
    doc = doc_of(hub_bert(), cdxgen_bookcorpus())
    before = json.dumps(doc)
    out = discover_datasets(doc, str(tmp_path), report=report)
    assert json.dumps(out) == before and report["hub_unreachable"] is True and checks == [True]
    assert logs == ["[dataset] huggingface.co unreachable: 1 dataset keeps name and purl only, 1 hub model card not read"]


@pytest.mark.parametrize("card, expected", [
    (None, []),
    ({"datasets": "glue"}, ["glue"]),                                                         # 목록이 아니라 문자열 하나여도
    ({"datasets": ["a/b", " a/b ", "c"], "model-index": [{"results": [{"dataset": {"type": "c"}}, {"dataset": {"name": "no type"}}, "junk"]}, "junk"]},
     ["a/b", "c"]),                                                                            # 겹치면 한 번, 모양이 다른 항목은 넘긴다
    ({"model-index": [{"results": [{"dataset": {"name": "GLUE SST2", "type": "glue"}}]}]}, ["glue"]),     # 평가 데이터셋은 name 이 아니라 type 이 id
    ({"datasets": ["https://example.org/data", "train.csv"]}, []),                            # 허브 id 꼴이 아닌 것
])
def test_model_card_dataset_ids(card, expected):
    assert ds._model_card_dataset_ids(card, "m") == expected


# -- 로컬 모델 카드의 데이터셋 ----------------------------------------------------------
TINY_REF = "pkg:generic/huggingface/tiny"
TINY_CARD = """---
license: apache-2.0
datasets:
  - bookcorpus
model-index:
- name: tiny
  results:
  - task: {type: text-classification}
    dataset: {name: GLUE SST2, type: glue, split: validation}
    metrics: [{type: accuracy, value: 0.91}]
  - task: {type: text-classification}
    dataset: {name: IMDB, type: stanfordnlp/imdb}
    metrics: [{type: accuracy, value: 0.93}]
  - task: {type: text-classification}
    dataset: {name: private eval, type: ./eval.csv}
---
# tiny
"""


def local_model(root: Path, readme: str, entries=()) -> dict:
    """cdxgen 이 로컬 모델 폴더에서 만드는 모델. evidence 에 README.md 가 있고, 모델카드 datasets 는 cdxgen 이 적은 그대로다."""
    write(root, "models/tiny/README.md", readme)
    write(root, "models/tiny/config.json", "{}")
    return {"bom-ref": "cdxgen:ai:model:huggingface:tiny", "type": "machine-learning-model", "group": "huggingface", "name": "tiny",
            "purl": TINY_REF, "evidence": {"occurrences": [{"location": "models/tiny/README.md"}, {"location": "models/tiny/config.json"}]},
            "modelCard": {"modelParameters": {"datasets": list(entries)}}}


def with_cdxgen_imdb(model: dict) -> dict:
    """모델과, 모델 카드의 datasets: 로 cdxgen 이 만든 stanfordnlp/imdb 컴포넌트·관계를 병합한 문서."""
    return merge([{"bomFormat": "CycloneDX", "specVersion": "1.7", "components": [model, cdxgen_imdb()],
                   "dependencies": [{"ref": model["bom-ref"], "dependsOn": [cdxgen_imdb()["bom-ref"]]}]}], root=("proj", "directory"))


def test_owner_name_dataset_from_a_local_model_card_is_filled_and_gets_its_purl(tmp_path, online):
    """cdxgen 은 모델 카드의 stanfordnlp/imdb 를 purl 없이 group·name 과 허브 주소로만 적는다. 그래도 허브 데이터셋으로 알아보고
    조회해 채우며, purl·bom-ref 를 정식 id 로 맞춘다. 모델카드 ref 와 모델 → 데이터셋 관계도 따라간다."""
    out = discover_datasets(with_cdxgen_imdb(local_model(tmp_path, "# tiny\n", [{"ref": cdxgen_imdb()["bom-ref"]}])), str(tmp_path))
    found = datasets(out)
    assert set(found) == {IMDB_REF} and online == [IMDB]
    imdb = found[IMDB_REF]
    assert (imdb["group"], imdb["name"], imdb["purl"]) == ("stanfordnlp", "imdb", IMDB_REF) and internal(imdb)["size"] == "133190302"
    tiny = next(c for c in out["components"] if c["bom-ref"] == TINY_REF)
    assert tiny["modelCard"]["modelParameters"]["datasets"] == [{"ref": IMDB_REF}]
    assert deps_of(out)[TINY_REF] == [IMDB_REF]
    assert refs_in(out) <= {c["bom-ref"] for c in out["components"]} | {out["metadata"]["component"]["bom-ref"]}


def test_local_model_card_datasets_become_components_linked_from_the_model(tmp_path, online, logs):
    """로컬 모델 README 의 datasets(학습)와 model-index 평가 데이터셋(dataset.type)이 데이터셋 컴포넌트가 되고, 모델카드에 ref 로
    적히며 모델이 dependsOn 한다. cdxgen 이 표시 이름만 적은 항목(GLUE SST2, IMDB)은 ref 로 바뀌고, 같은 데이터셋의 cdxgen 컴포넌트는
    다시 쓴다. cdxgen 은 datasets: 의 ref 를 마지막 하나만 남기므로 학습 데이터셋도 다시 적는다 (여기서는 cdxgen 의 bookcorpus
    컴포넌트가 없어 새로 만든다). README 는 데이터셋의 evidence 가 되고, 허브 id 꼴이 아닌 것은 알린다. 루트는 잇지 않는다."""
    model = local_model(tmp_path, TINY_CARD, [{"ref": cdxgen_imdb()["bom-ref"]}, {"type": "dataset", "name": "GLUE SST2"},
                                              {"type": "dataset", "name": "IMDB"}, {"type": "dataset", "name": "private eval"}])
    logs.clear()
    facts = Facts()
    out = discover_datasets(with_cdxgen_imdb(model), str(tmp_path), facts=facts)
    glue = "pkg:huggingface/datasets/glue"
    found = datasets(out)
    assert set(found) == {IMDB_REF, glue, BOOK_HUB} and online == ["bookcorpus", "glue", IMDB]
    assert facts.roles == {(TINY_REF, BOOK_HUB): {"training"}, (TINY_REF, glue): {"evaluation"}, (TINY_REF, IMDB_REF): {"evaluation"}}
    tiny = next(c for c in out["components"] if c["bom-ref"] == TINY_REF)
    assert tiny["modelCard"]["modelParameters"]["datasets"] == [{"ref": IMDB_REF}, {"type": "dataset", "name": "private eval"},
                                                                {"ref": BOOK_HUB}, {"ref": glue}]
    deps = deps_of(out)
    assert deps[TINY_REF] == sorted([IMDB_REF, glue, BOOK_HUB]) and glue not in deps[out["metadata"]["component"]["bom-ref"]]
    assert found[glue]["evidence"]["occurrences"] == found[BOOK_HUB]["evidence"]["occurrences"] == [{"location": "models/tiny/README.md"}]
    assert "[dataset] models/tiny/README.md: model card dataset './eval.csv' is not a hub id, skipped" in logs
    assert refs_in(out) <= {c["bom-ref"] for c in out["components"]} | {out["metadata"]["component"]["bom-ref"]}


@pytest.mark.parametrize("readme, error", [
    ("# 헤더 없음\n", None),
    ("---\n- 목록뿐인 헤더\n---\n", None),
    ("---\nmodel-index: [닫히지 않음\n---\n", "ParserError"),
])
def test_a_local_model_card_without_a_usable_header_changes_nothing(tmp_path, monkeypatch, readme, error, logs):
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("물을 것이 없는데 네트워크를 봤다"))
    doc = doc_of(local_model(tmp_path, readme, [{"type": "dataset", "name": "GLUE SST2"}]))
    before = json.dumps(doc)
    logs.clear()
    assert json.dumps(discover_datasets(doc, str(tmp_path))) == before
    assert logs == ([f"[dataset] models/tiny/README.md: model card header skipped, cannot parse ({error})"] if error else [])


def test_statistics_requests_follow_dataset_info_then_size_and_are_capped(monkeypatch, logs):
    info_with_splits = {"id": "a/b", "cardData": {"dataset_info": [{"config_name": "x", "splits": [{"name": "train"}, {"name": "test"}]},
                                                                    {"config_name": "y", "splits": [{"name": "train"}]}]}}
    assert ds._config_splits(info_with_splits, imdb_size()) == [("x", "train"), ("x", "test"), ("y", "train")]       # 앞머리가 있으면 /size 는 안 본다
    assert ds._config_splits({"id": "a/b"}, imdb_size()) == [("plain_text", "train"), ("plain_text", "test"), ("plain_text", "unsupervised")]
    assert ds._config_splits({"id": "a/b"}, None) == [] and ds._config_splits({"id": "a/b"}, {"size": {"splits": [{"config": "c"}]}}) == []
    calls: list[tuple[str, str]] = []
    def fetch(hf_id, config, split):
        calls.append((config, split))
        return {"statistics": [], "partial": config == "c3"} if config != "c5" else None
    monkeypatch.setattr(hub, "fetch_dataset_statistics", fetch)
    many = {"id": "a/b", "cardData": {"dataset_info": [{"config_name": f"c{i}", "splits": [{"name": "train"}, {"name": "test"}]} for i in range(8)]}}
    logs.clear()
    got = ds._fetch_statistics("a/b", many, None)
    assert len(calls) == ds.STATISTICS_REQUEST_LIMIT == 12 and calls[0] == ("c0", "train") and calls[-1] == ("c5", "test")
    assert [c for c, _, _ in got] == ["c0", "c0", "c1", "c1", "c2", "c2", "c3", "c3", "c4", "c4"]                    # c5 는 조회 실패
    assert any("first 12 of 16" in m for m in logs) and sum("partial" in m for m in logs) == 2


def test_hub_column_statistics_by_column_type():
    resp = {"statistics": [
        {"column_name": "y", "column_type": "class_label", "column_statistics": {"nan_count": 3, "n_unique": 12, "frequencies": {str(i): 1 for i in range(12)}}},   # 범주 11개 이상 → n_unique 만
        {"column_name": "img", "column_type": "image", "column_statistics": {"min": 32, "max": 32.0, "mean": 32.0, "median": 32.0, "std": 0.0, "nan_count": 0}},
        {"column_name": "dur", "column_type": "audio", "column_statistics": {"mean": 6.589523, "histogram": {}}},
        {"column_name": "flag", "column_type": "bool", "column_statistics": {"n_unique": 2, "frequencies": {"True": 3, "False": 3}}},
        {"column_name": "sp", "column_type": "string_label", "column_statistics": {"n_unique": 3, "frequencies": {"b": 1, "a": 5, "c": 2}}},
        {"column_name": "n", "column_type": "float", "column_statistics": {"nan_count": True, "min": "bad", "max": True, "mean": 1.5}},     # bool 은 개수가 아니다
        {"column_name": "", "column_type": "int", "column_statistics": {"min": 1}}, "garbage", {"column_name": "z", "column_statistics": None}]}
    single = ds._hub_statistics([("only", "train", resp)])
    assert single == [("train:y:nan_count", "3"), ("train:y:n_unique", "12"),
                      ("train:img:nan_count", "0"), ("train:img:width:min", "32"), ("train:img:width:max", "32"), ("train:img:width:mean", "32"), ("train:img:width:median", "32"), ("train:img:width:std", "0"),
                      ("train:dur:duration:mean", "6.58952"),
                      ("train:flag:n_unique", "2"), ("train:flag:frequencies", "False=3,True=3"),                  # 동률 → mode 없음, 이름순
                      ("train:sp:n_unique", "3"), ("train:sp:mode", "a"), ("train:sp:frequencies", "a=5,c=2,b=1"),
                      ("train:n:mean", "1.5")]
    multi = ds._hub_statistics([("c1", "train", resp), ("c2", "test", {"statistics": []})])
    assert multi[0] == ("c1:train:y:nan_count", "3") and len(multi) == len(single)


@pytest.mark.parametrize("values, expected", [
    (["1", "2", "3", ""], [("nan_count", "1"), ("min", "1"), ("max", "3"), ("mean", "2"), ("median", "2"), ("std", "1")]),   # 빈 칸은 세고, 통계에서는 뺀다
    ([1.5, 2, None], [("nan_count", "1"), ("min", "1.5"), ("max", "2"), ("mean", "1.75"), ("median", "1.75"), ("std", "0.35355")]),
    (["7"], [("nan_count", "0"), ("min", "7"), ("max", "7"), ("mean", "7"), ("median", "7")]),                          # 하나면 std 없음
    (["1", "inf", "2"], [("nan_count", "0"), ("length:min", "1"), ("length:max", "3"), ("length:mean", "1.66667"), ("length:median", "1"), ("length:std", "1.1547")]),   # inf 는 수가 아니다 → 글
    ([True, False, True], [("nan_count", "0"), ("n_unique", "2"), ("mode", "true"), ("frequencies", "true=2,false=1")]),
    (["cat", "dog", "cat", "cat"], [("nan_count", "0"), ("n_unique", "2"), ("mode", "cat"), ("frequencies", "cat=3,dog=1")]),
    (["a", "b", "c"], [("nan_count", "0"), ("length:min", "1"), ("length:max", "1"), ("length:mean", "1"), ("length:median", "1"), ("length:std", "0")]),   # 전부 달라 범주가 아니다
    ([f"w{i}" for i in range(11)] * 2, [("nan_count", "0"), ("length:min", "2"), ("length:max", "3"), ("length:mean", "2.09091"), ("length:median", "2"), ("length:std", "0.29424")]),  # 범주 11개 → 글
    ([None, "", "  "], [("nan_count", "2"), ("length:min", "2"), ("length:max", "2"), ("length:mean", "2"), ("length:median", "2")]),   # 공백만 있는 값은 값이다 (CSV 는 읽을 때 strip 한다)
    ([None, ""], [("nan_count", "2")]),                                                                                   # 전부 비면 개수만
    ([], []),
    ([{"nested": 1}, "x"], [("nan_count", "0"), ("length:min", "1"), ("length:max", "13"), ("length:mean", "7"), ("length:median", "7"), ("length:std", "8.48528")]),
])
def test_local_values_statistics_rules(values, expected):
    assert ds._values_statistics(values) == expected


def test_local_file_statistics_for_jsonl_json_tsv_and_limits(tmp_path, monkeypatch):
    write(tmp_path, "a.jsonl", '{"x": 1, "tags": ["p"], "y": "u"}\n{"x": 3, "tags": [], "y": "u"}\n{"x": 2, "y": "v"}\n')
    assert ds._file_statistics(tmp_path / "a.jsonl", "jsonl") == [("x:nan_count", "0"), ("x:min", "1"), ("x:max", "3"), ("x:mean", "2"), ("x:median", "2"), ("x:std", "1"),
                                                                   ("y:nan_count", "0"), ("y:n_unique", "2"), ("y:mode", "u"), ("y:frequencies", "u=2,v=1")]   # tags 는 중첩 값이라 뺀다
    write(tmp_path, "b.json", '[{"k": 2}, {"k": 4}, 5, {"k": null}, {"j": 1}]')
    assert ds._file_statistics(tmp_path / "b.json", "json") == [("k:nan_count", "2"), ("k:min", "2"), ("k:max", "4"), ("k:mean", "3"), ("k:median", "3"), ("k:std", "1.41421"),
                                                                 ("j:nan_count", "3"), ("j:min", "1"), ("j:max", "1"), ("j:mean", "1"), ("j:median", "1")]   # null 도, 키가 없는 것도 빈 값
    write(tmp_path, "c.tsv", "h1\t\th3\n1\tx\ta\n2\ty\tb\n")
    assert ds._file_statistics(tmp_path / "c.tsv", "tsv") == [("h1:nan_count", "0"), ("h1:min", "1"), ("h1:max", "2"), ("h1:mean", "1.5"), ("h1:median", "1.5"), ("h1:std", "0.70711"),
                                                              ("h3:nan_count", "0"), ("h3:length:min", "1"), ("h3:length:max", "1"), ("h3:length:mean", "1"), ("h3:length:median", "1"), ("h3:length:std", "0")]   # 이름 없는 열은 뺀다
    assert ds._file_statistics(tmp_path / "c.tsv", "png") == [] and ds._file_statistics(write(tmp_path, "e.csv", ""), "csv") == []
    write(tmp_path, "bad.json", "{not json")
    assert "statistics" not in ds._analyze_file(tmp_path / "bad.json", "bad.json")                                 # 파싱 실패 → 크기만
    monkeypatch.setattr(ds, "STATISTICS_FILE_LIMIT", 10)
    assert "statistics" not in ds._analyze_file(tmp_path / "a.jsonl", "a.jsonl")                                  # 상한을 넘으면 통계는 건너뛴다


def test_local_statistics_prefix_only_when_a_directory_has_several_files(tmp_path):
    write(tmp_path, "data/only.csv", "v\n1\n2\n")
    facts = internal(datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=data_of(tmp_path)))["data:local/data@"])
    assert facts["statistics:0:type"] == "v:nan_count" and facts["statistics:3:value"] == "1.5"                     # 파일 하나면 파일 이름을 붙이지 않는다


def test_offline_keeps_name_and_purl_and_logs_once(tmp_path, monkeypatch, logs):
    monkeypatch.setattr(hub, "hf_reachable", lambda: False)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: pytest.fail("offline 인데 조회했다"))
    write(tmp_path, "train.py", 'load_dataset("stanfordnlp/imdb")\nload_dataset("imdb")\n')
    logs.clear()
    out = discover_datasets(doc_of(), str(tmp_path))
    found = datasets(out)
    assert set(found) == {IMDB_REF, "pkg:huggingface/datasets/imdb"}
    assert all("properties" not in c and "version" not in c for c in found.values())
    assert sum("unreachable" in m for m in logs) == 1
    for form in ("properties", "typed"):
        doc = regulate(copy.deepcopy(out), form=form)
        assert _validate_cdx(doc, "1.7" if form == "properties" else "v0.6")


def test_fetch_failure_is_logged_and_component_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: None)
    write(tmp_path, "train.py", 'load_dataset("nobody/nothing")\n')
    found = datasets(discover_datasets(doc_of(), str(tmp_path)))
    assert set(found) == {"pkg:huggingface/datasets/nobody/nothing"} and "properties" not in found["pkg:huggingface/datasets/nobody/nothing"]


def test_image_target_only_enriches_existing_components(online):
    out = discover_datasets(doc_of(cdxgen_bookcorpus(), root=("img:latest", "image")), "img:latest")
    assert set(datasets(out)) == {BOOK_HUB} and online == ["bookcorpus"]


# -- discover: --data 로 준 허브 데이터셋 --------------------------------------------------
OLD_IMDB_SHA = "94a9845cc862de210d27b3556c1cb6fe94d7a0f2"            # stanfordnlp/imdb 의 예전 커밋 (실제 허브: 2022-11-18)


@pytest.mark.parametrize("values, local, given", [
    (["data", "hf://datasets/stanfordnlp/imdb"], ["data"], {IMDB: None}),
    (["hf://datasets/stanfordnlp/imdb@e6281661", "hf://datasets/stanfordnlp/imdb@e6281661"], [], {IMDB: "e6281661"}),   # 같은 것 두 번은 한 번
    (["hf://datasets/imdb@refs/pr/1", "hf://datasets/acme/eval-set/"], [], {"imdb": "refs/pr/1", "acme/eval-set": None}),  # 이름만 있는 id, 끝 슬래시
])
def test_split_data_args_separates_local_paths_and_hub_datasets(values, local, given):
    assert ds.split_data_args(values) == (local, given)


@pytest.mark.parametrize("value", ["hf://datasets/", "hf://datasets/a/b/train.csv", "hf://datasets/a/b@", "hf://datasets/a/b@v 1",
                                   "hf://stanfordnlp/imdb", "hf://models/a/b"])
def test_split_data_args_rejects_anything_but_one_dataset_repository(value):
    with pytest.raises(ValueError, match="not a Hugging Face dataset"):
        ds.split_data_args([value])


def test_split_data_args_rejects_one_dataset_with_two_revisions():
    with pytest.raises(ValueError, match=r"two revisions \(main, latest\)"):
        ds.split_data_args(["hf://datasets/stanfordnlp/imdb@main", "hf://datasets/stanfordnlp/imdb"])


def test_hub_dataset_given_with_data_is_built_like_one_found_in_code(tmp_path, online):
    write(tmp_path, "code/src/train.py", 'load_dataset("stanfordnlp/imdb")\n')
    (tmp_path / "empty").mkdir()
    from_code = datasets(discover_datasets(doc_of(), str(tmp_path / "code")))[IMDB_REF]
    out = discover_datasets(doc_of(), str(tmp_path / "empty"), data_paths=["hf://datasets/stanfordnlp/imdb"])
    given = datasets(out)[IMDB_REF]
    assert {k: v for k, v in given.items() if k != "evidence"} == {k: v for k, v in from_code.items() if k != "evidence"}
    assert given["version"] == from_code["version"] == "e6281661ce1c48d982bc483cf8a173c1bbeb5d31"     # 리비전을 안 주면 최신 커밋
    assert "evidence" not in given and from_code["evidence"]["occurrences"] == [{"location": "src/train.py"}]   # 출처는 코드에서 찾은 것만
    assert next(d for d in out["dependencies"] if d["ref"] == "application:/proj@")["dependsOn"] == [IMDB_REF]
    image = discover_datasets(doc_of(root=("img:latest", "image")), "img:latest", data_paths=["hf://datasets/stanfordnlp/imdb"])
    assert set(datasets(image)) == {IMDB_REF}                                                      # 이미지를 스캔할 때도 같다


def test_a_given_revision_is_looked_up_at_that_revision_and_becomes_the_version(tmp_path, monkeypatch, imdb, logs):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    old = {**copy.deepcopy(imdb), "sha": OLD_IMDB_SHA, "lastModified": "2022-11-18T20:09:16.000Z"}
    calls: list[tuple[str, str | None]] = []

    def fetch(hf_id, revision=None):
        calls.append((hf_id, revision))
        return copy.deepcopy(old if revision else imdb)
    monkeypatch.setattr(hub, "fetch_dataset_info", fetch)
    monkeypatch.setattr(hub, "fetch_dataset_size", lambda hf_id: pytest.fail("최신이 아닌 리비전인데 /size 를 물었다"))
    monkeypatch.setattr(hub, "fetch_dataset_statistics", lambda *a, **k: pytest.fail("최신이 아닌 리비전인데 /statistics 를 물었다"))
    logs.clear()
    facts = Facts()
    out = discover_datasets(doc_of(), str(tmp_path), data_paths=["hf://datasets/stanfordnlp/imdb@94a9845c"], facts=facts)
    comp = datasets(out)[IMDB_REF]
    assert comp["version"] == OLD_IMDB_SHA                                       # 짧은 해시를 줘도 허브가 돌려준 전체 해시
    assert calls == [(IMDB, "94a9845c"), (IMDB, None)]                          # 그 리비전으로 한 번, 최신인지 보려고 한 번
    assert facts.times[IMDB_REF]["releaseTime"].startswith("2022-11-18")
    assert any("revision 94a9845c is not the latest" in m for m in logs)


def test_a_given_revision_that_is_the_latest_still_gets_datasets_server_statistics(tmp_path, monkeypatch, imdb, online):
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id, revision=None: copy.deepcopy(imdb) if hf_id == IMDB else None)
    comp = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=["hf://datasets/stanfordnlp/imdb@main"]))[IMDB_REF]
    assert comp["version"] == imdb["sha"] and any(k.startswith("statistics:") for k in internal(comp))


def test_offline_keeps_the_given_revision_as_the_version(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "hf_reachable", lambda: False)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda *a, **k: pytest.fail("offline 인데 조회했다"))
    found = datasets(discover_datasets(doc_of(), str(tmp_path),
                                 data_paths=["hf://datasets/stanfordnlp/imdb@e6281661", "hf://datasets/acme/eval-set"]))
    assert found[IMDB_REF]["version"] == "e6281661" and "version" not in found["pkg:huggingface/datasets/acme/eval-set"]


def test_a_given_dataset_the_hub_cannot_look_up_is_kept_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id, revision=None: None)
    write(tmp_path, "train.py", 'load_dataset("nobody/nothing")\n')
    report: dict = {}
    found = datasets(discover_datasets(doc_of(), str(tmp_path), report=report,
                                 data_paths=["hf://datasets/acme/eval-set@v2", "hf://datasets/acme/other"]))
    assert set(found) == {"pkg:huggingface/datasets/acme/eval-set", "pkg:huggingface/datasets/acme/other", "pkg:huggingface/datasets/nobody/nothing"}
    assert found["pkg:huggingface/datasets/acme/eval-set"]["version"] == "v2"                     # 조회가 안 돼도 준 리비전은 남는다
    assert report["unresolved_hub_data"] == ["hf://datasets/acme/eval-set@v2", "hf://datasets/acme/other"]   # 코드에서 찾은 것은 알리지 않는다


def test_a_revision_in_code_is_looked_up_at_that_revision(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    old = {**copy.deepcopy(imdb), "sha": OLD_IMDB_SHA}
    calls: list[tuple[str, str | None]] = []

    def fetch(hf_id, revision=None):
        calls.append((hf_id, revision))
        return copy.deepcopy(old if revision else imdb)
    monkeypatch.setattr(hub, "fetch_dataset_info", fetch)
    monkeypatch.setattr(hub, "fetch_dataset_size", lambda hf_id: pytest.fail("최신이 아닌 리비전인데 /size 를 물었다"))
    write(tmp_path, "src/train.py", 'load_dataset("stanfordnlp/imdb", revision="94a9845c")\n')
    report: dict = {}
    comp = datasets(discover_datasets(doc_of(), str(tmp_path), report=report))[IMDB_REF]
    assert comp["version"] == OLD_IMDB_SHA and calls == [(IMDB, "94a9845c"), (IMDB, None)]
    assert report["unresolved_hub_data"] == []                                                    # 코드에서 찾은 것은 경고하지 않는다


def test_one_dataset_loaded_at_several_revisions_in_code_is_looked_up_at_the_latest(tmp_path, online, logs):
    write(tmp_path, "src/train.py", 'load_dataset("stanfordnlp/imdb", revision="94a9845c")\n')
    write(tmp_path, "src/eval.py", 'load_dataset("stanfordnlp/imdb")\n')
    logs.clear()
    comp = datasets(discover_datasets(doc_of(), str(tmp_path)))[IMDB_REF]
    assert comp["version"] == "e6281661ce1c48d982bc483cf8a173c1bbeb5d31" and online == [IMDB]
    assert comp["evidence"]["occurrences"] == [{"location": "src/eval.py"}, {"location": "src/train.py"}]
    assert any("several revisions in code (94a9845c, no revision)" in m for m in logs)


def test_the_data_revision_wins_over_the_revision_in_code_and_offline_both_keep_one(tmp_path, monkeypatch, imdb, logs):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    calls: list[str | None] = []
    monkeypatch.setattr(hub, "fetch_dataset_info",
                        lambda hf_id, revision=None: calls.append(revision) or (copy.deepcopy(imdb) if hf_id == IMDB else None))
    write(tmp_path, "src/train.py", 'load_dataset("stanfordnlp/imdb", revision="aaaa")\nload_dataset("acme/eval-set", revision="v1")\n')
    logs.clear()
    discover_datasets(doc_of(), str(tmp_path), data_paths=["hf://datasets/stanfordnlp/imdb@main"])
    assert "main" in calls and "aaaa" not in calls and any("--data revision main used over aaaa in code" in m for m in logs)
    monkeypatch.setattr(hub, "hf_reachable", lambda: False)
    found = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=["hf://datasets/stanfordnlp/imdb@main"]))
    assert found[IMDB_REF]["version"] == "main" and found["pkg:huggingface/datasets/acme/eval-set"]["version"] == "v1"   # 못 물으면 리비전 그대로


def test_missing_revisions_reports_only_what_the_hub_says_does_not_exist(monkeypatch):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    answers = {"stanfordnlp/imdb": (404, "Invalid rev id: nope"), "nobody/private": (401, "Invalid username or password.")}
    asked: list[str] = []
    monkeypatch.setattr(hub, "fetch_revision_error", lambda hf_id, revision: asked.append(hf_id) or answers.get(hf_id))
    given = {"stanfordnlp/imdb": "nope", "nobody/private": "v1", "acme/ok": "main", "acme/latest": None}
    assert missing_revisions(given) == [("hf://datasets/stanfordnlp/imdb@nope", "Invalid rev id: nope")]   # 401 은 없는 것인지 비공개인지 모른다
    assert sorted(asked) == ["acme/ok", "nobody/private", "stanfordnlp/imdb"]                              # 리비전을 안 준 것은 묻지 않는다
    monkeypatch.setattr(hub, "hf_reachable", lambda: False)
    assert missing_revisions(given) == []                                                              # 허브에 닿지 않으면 판단하지 않는다
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("리비전이 없는데 네트워크를 봤다"))
    assert missing_revisions({"acme/latest": None}) == []


def test_a_dataset_both_given_and_found_in_code_is_one_component_at_the_given_revision(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    old = {**copy.deepcopy(imdb), "sha": OLD_IMDB_SHA}
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id, revision=None: copy.deepcopy(old if revision else imdb))
    write(tmp_path, "src/train.py", 'load_dataset("imdb")\n')                                      # 코드는 옛 이름으로 부른다
    out = discover_datasets(doc_of(), str(tmp_path), data_paths=["hf://datasets/stanfordnlp/imdb@94a9845c"])
    comp = datasets(out)[IMDB_REF]
    assert set(datasets(out)) == {IMDB_REF} and comp["version"] == OLD_IMDB_SHA                    # 겹치면 하나로, 리비전은 준 것
    assert comp["evidence"]["occurrences"] == [{"location": "src/train.py"}]
    assert next(d for d in out["dependencies"] if d["ref"] == "application:/proj@")["dependsOn"] == [IMDB_REF]


# -- 회귀 보호: 데이터셋이 없으면 문서는 그대로다 ----------------------------------------------
def test_directory_without_datasets_leaves_the_document_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("조회할 것이 없는데 네트워크를 봤다"))
    write(tmp_path, "requirements.txt", "numpy==2.5.1\n")
    write(tmp_path, "package.json", '{"name": "x"}')
    write(tmp_path, "app.py", 'import numpy as np\nopen("README.md")\n')
    doc = doc_of({"bom-ref": "pkg:pypi/numpy@2.5.1", "type": "library", "name": "numpy", "version": "2.5.1", "purl": "pkg:pypi/numpy@2.5.1"})
    before = json.dumps(doc, ensure_ascii=False)
    out = discover_datasets(doc, str(tmp_path))
    assert json.dumps(out, ensure_ascii=False) == before
    for form in ("properties", "typed"):
        assert json.dumps(regulate(copy.deepcopy(out), form=form), ensure_ascii=False) == before


# -- form: 두 형태 --------------------------------------------------------------
@pytest.fixture
def discovered(tmp_path, online) -> dict:
    root = project(tmp_path)
    return discover_datasets(doc_of(), str(root), data_paths=data_of(root))


def test_properties_form_moves_facts_to_aibom_dataset_keys(discovered):
    out = regulate(copy.deepcopy(discovered), form="properties")
    hf = datasets(out)[IMDB_REF]
    p = props(hf)
    assert p["aibom:dataset:size"] == "133190302" and p["aibom:dataset:modality:0"] == "text"
    assert p["aibom:dataset:availability"] == "direct-download" and p["aibom:dataset:provenance:0"] == "https://huggingface.co/datasets/stanfordnlp/imdb"
    assert (p["aibom:dataset:statistics:0:type"], p["aibom:dataset:statistics:0:value"]) == ("train:label:nan_count", "0")
    assert p["aibom:dataset:statistics:26:type"] == "unsupervised:text:length:std" and "aibom:dataset:statistics:27:type" not in p   # split 3개 × 9개
    assert not any(k.startswith(INTERNAL_PREFIX) for k in p) and "aibom-internal" not in json.dumps(out)
    assert "size" not in hf["data"][0] and "availability" not in hf["data"][0]["contents"]                  # typed 필드는 건드리지 않는다
    local = datasets(out)["data:local/data@"]
    assert props(local)["aibom:dataset:size"] == "80" and props(local)["aibom:dataset:statistics:0:type"] == "id:nan_count"
    assert "aibom:dataset:statistics:17:type" in props(local) and "aibom:dataset:statistics:18:type" not in props(local)       # 열 셋 × 6개
    assert _validate_cdx(out, "1.7") and _validate_cdx(out, "v0.6")


def test_typed_form_fills_componentdata_fields_on_data0(discovered, logs):
    out = regulate(copy.deepcopy(discovered), form="typed")
    hf = datasets(out)[IMDB_REF]
    entry = hf["data"][0]
    assert entry["size"] == 133190302 and isinstance(entry["size"], int) and entry["modality"] == ["text"]
    assert entry["contents"] == {"url": "https://huggingface.co/datasets/stanfordnlp/imdb", "availability": "direct-download"}
    assert entry["provenance"] == ["https://huggingface.co/datasets/stanfordnlp/imdb"]
    assert entry["statistics"][:9] == [{"type": t, "value": v} for t, v in IMDB_TRAIN_STATS] and len(entry["statistics"]) == 27
    assert "properties" not in hf                                                     # 내부 키만 있었으니 목록째 사라진다
    local = datasets(out)["data:local/data@"]
    assert local["data"][0]["size"] == 80 and local["data"][0]["modality"] == ["structured"] and len(local["data"]) == 1
    assert "contents" not in local["data"][0] and "properties" not in local["data"][0]              # 원소에 도구 속성은 없다
    assert "aibom-internal" not in json.dumps(out) and "aibom:dataset:" not in json.dumps(out)
    assert _validate_cdx(out, "v0.6")
    logs.clear()
    assert not _validate_cdx(out, "1.7") and any("data/0" in m for m in logs)


def test_typed_form_creates_data_entry_when_missing():
    comp = {"type": "data", "name": "d", "bom-ref": "d", "properties": [{"name": INTERNAL_PREFIX + "size", "value": "5"}]}
    out = regulate({"components": [comp]}, form="typed")
    assert out["components"][0] == {"type": "data", "name": "d", "bom-ref": "d", "data": [{"type": "dataset", "name": "d", "size": 5}]}


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_existing_values_win_and_internal_keys_are_always_removed(form, logs):
    comp = {"type": "data", "name": "d", "bom-ref": "d", "data": [{"type": "dataset", "name": "d"}],
            "properties": [{"name": "cdx:ai:kind", "value": "dataset"},
                           {"name": INTERNAL_PREFIX + "size", "value": "10"},
                           {"name": INTERNAL_PREFIX + "availability", "value": "direct-download"},
                           {"name": INTERNAL_PREFIX + "modality:0", "value": "text"},
                           {"name": INTERNAL_PREFIX + "modality:1", "value": "image"},
                           {"name": INTERNAL_PREFIX + "modality:2", "value": "hologram"},                 # 허용값 아님 → 버림
                           {"name": INTERNAL_PREFIX + "statistics:0:type", "value": "rows"},
                           {"name": INTERNAL_PREFIX + "statistics:0:value", "value": "3"},
                           {"name": INTERNAL_PREFIX + "statistics:1:type", "value": "files"},
                           {"name": INTERNAL_PREFIX + "statistics:1:value", "value": "1"}]}
    if form == "typed":
        comp["data"][0].update({"size": 99, "modality": ["text"], "statistics": [{"type": "rows", "value": "7"}]})
    else:
        comp["properties"] = [{"name": "aibom:dataset:size", "value": "99"}, {"name": "aibom:dataset:modality:0", "value": "text"},
                              {"name": "aibom:dataset:statistics:0:type", "value": "rows"}, {"name": "aibom:dataset:statistics:0:value", "value": "7"}] + comp["properties"]
    logs.clear()
    out = regulate({"components": [comp]}, form=form)
    c = out["components"][0]
    assert not any(p["name"].startswith(INTERNAL_PREFIX) for p in c["properties"])
    assert sum("dropped" in m for m in logs) == 2 and any("not an allowed value" in m for m in logs)
    if form == "typed":
        e = c["data"][0]
        assert e["size"] == 99 and e["modality"] == ["text", "image"] and e["contents"] == {"availability": "direct-download"}
        assert e["statistics"] == [{"type": "rows", "value": "7"}, {"type": "files", "value": "1"}]
        assert c["properties"] == [{"name": "cdx:ai:kind", "value": "dataset"}]
    else:
        p = props(c)
        assert p["aibom:dataset:size"] == "99" and p["aibom:dataset:modality:1"] == "image" and "aibom:dataset:modality:2" not in p
        assert (p["aibom:dataset:statistics:0:value"], p["aibom:dataset:statistics:1:type"], p["aibom:dataset:statistics:1:value"]) == ("7", "files", "1")
        assert p["aibom:dataset:availability"] == "direct-download" and p["cdx:ai:kind"] == "dataset"


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_dataset_form_is_idempotent(discovered, form, logs):
    once = regulate(copy.deepcopy(discovered), form=form)
    logs.clear()
    assert json.dumps(regulate(copy.deepcopy(once), form=form)) == json.dumps(once) and logs == []


def test_data_component_without_internal_keys_is_untouched():
    comp = {"type": "data", "name": "d", "bom-ref": "d", "properties": [{"name": "cdx:ai:kind", "value": "dataset"}], "data": [{"type": "dataset"}]}
    for form in ("properties", "typed"):
        assert json.dumps(regulate({"components": [copy.deepcopy(comp)]}, form=form)) == json.dumps({"components": [comp]})


# -- 회귀: 확인된 결함 ------------------------------------------------------------------
def test_unknown_extensions_are_not_data_and_the_analyser_accepts_them(tmp_path, online):
    """모르는 확장자가 KeyError 로 스캔을 죽였다. 데이터 경로에서는 빼고, 분석기에 직접 넣으면 'other' 로 받는다."""
    write(tmp_path, "data/train.dat", "a,b\n1,2\n")
    write(tmp_path, "data/train", "a,b\n1,2\n")
    write(tmp_path, "data/x.xlsx", "x")
    report: dict = {}
    out = discover_datasets(doc_of(), str(tmp_path), report=report, data_paths=data_of(tmp_path))
    assert datasets(out) == {} and report["empty_data_paths"] == data_of(tmp_path)
    a = ds._analyze_file(tmp_path / "data/train.dat", "data/train.dat")
    assert a == {"path": "data/train.dat", "size": 8, "format": "dat", "modality": "other"}


def test_a_symlink_leaving_the_data_path_is_skipped(tmp_path, monkeypatch, online, logs):
    """데이터 경로 밖을 가리키는 링크가 절대 경로(또는 ../ 경로)를 data[].name 에 흘렸다."""
    outside = write(tmp_path, "elsewhere/outside_secret.csv", "a\n1\n")
    root = tmp_path / "T"
    write(root, "data/train.csv", "a\n1\n2\n")
    (root / "data/link.csv").symlink_to(outside)
    (root / "data/inner.csv").symlink_to(root / "data/train.csv")             # 안을 가리키는 링크는 경로 안의 이름으로 남는다
    for data in (str(root / "data"), "T/data"):
        monkeypatch.chdir(tmp_path)
        logs.clear()
        out = discover_datasets(doc_of(), str(root), data_paths=[data])
        local = datasets(out)["data:local/data@"]
        assert [d["name"] for d in local["data"]] == ["data/inner.csv", "data/train.csv"]
        text = json.dumps(out)
        assert "outside_secret" not in text and str(tmp_path) not in text and ".." not in text
        assert any("link.csv" in m and "outside the data path" in m for m in logs)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root 는 권한을 무시한다")
def test_unreadable_file_records_size_only(tmp_path, online, logs):
    """권한이 없는 파일에서 PermissionError 가 스캔을 죽였다. 크기만 적고 알린다."""
    secret = write(tmp_path, "data/secret.csv", "a,b\n1,2\n")
    write(tmp_path, "data/ok.csv", "a\n1\n")
    secret.chmod(0)
    try:
        logs.clear()
        a = ds._analyze_file(secret, "data/secret.csv")
        assert a == {"path": "data/secret.csv", "size": 8, "format": "csv", "modality": "structured"}
        assert any("data/secret.csv" in m and "cannot read content" in m for m in logs)
        local = datasets(discover_datasets(doc_of(), str(tmp_path), data_paths=data_of(tmp_path)))["data:local/data@"]
        assert [d["name"] for d in local["data"]] == ["data/ok.csv", "data/secret.csv"] and internal(local)["size"] == "12"
    finally:
        secret.chmod(0o644)


def test_csv_with_a_very_wide_field_still_yields_statistics(tmp_path, monkeypatch, logs):
    """csv 모듈 기본 칸 한도(131072)를 넘는 문서 한 칸이 _csv.Error 로 스캔을 죽였다. 한도를 올리고, 그래도 나는 csv.Error 는 잡는다."""
    big = write(tmp_path, "big.csv", "a,b\n1," + "x" * 200000 + "\n")
    a = ds._analyze_file(big, "big.csv")
    assert ("b:length:max", "200000") in a["statistics"]

    def boom(path, ext):
        raise csv.Error("field larger than field limit")
    monkeypatch.setattr(ds, "_file_statistics", boom)
    logs.clear()
    a = ds._analyze_file(big, "big.csv")
    assert "statistics" not in a and any("Error" in m for m in logs)


@pytest.mark.parametrize("text, expected", [
    ("stanfordnlp/imdb", True), ("imdb", True), ("HuggingFaceFW/fineweb-2", True), ("org/data-v0.1", True), ("Qwen/Qwen2.5-Math", True),
    ("my_script.py", False), ("./local_script.py", False), ("data/train.xlsx", False), ("data/train.csv", False), ("corpus.tar.gz", False),
    ("archive.7z", False), ("../x", False), ("a\\b", False),
])
def test_looks_like_hub_id_rejects_any_file_extension(text, expected):
    assert ds._looks_like_hub_id(text) is expected


def test_load_dataset_with_script_or_file_path_makes_no_hub_component(tmp_path, monkeypatch):
    """load_dataset("my_script.py") · load_dataset("data/train.xlsx") 가 가짜 허브 컴포넌트(pkg:huggingface/datasets/my_script.py)가 되었다."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: pytest.fail("허브 id 가 없는데 네트워크를 봤다"))
    write(tmp_path, "my_script.py", "")
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "t.py", 'load_dataset("my_script.py")\nload_dataset("data/train.xlsx")\nload_dataset("data/train.csv")\n')
    assert datasets(discover_datasets(doc_of(), str(tmp_path))) == {}


@pytest.mark.parametrize("task, modality", [
    ("text-to-speech", "audio"), ("text-to-audio", "audio"), ("text-to-video", "video"),
    ("text-classification", "text"), ("text-generation", "text"), ("text-to-image", "text"), ("automatic-speech-recognition", "audio"),
])
def test_specific_text_to_tasks_map_before_the_text_prefix(task, modality):
    assert ds._modality_of_task(task) == modality


# -- 실제 허브 (하나뿐) ------------------------------------------------------------------
@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_live_hub_returns_size_and_modality_for_imdb(monkeypatch):
    monkeypatch.setattr(hub, "fetch_dataset_size", REAL_FETCH_SIZE)
    monkeypatch.setattr(hub, "fetch_dataset_statistics", REAL_FETCH_STATISTICS)
    info = hub.fetch_dataset_info(IMDB)
    assert info and info["id"] == IMDB
    size = hub.fetch_dataset_size(IMDB)
    assert size and size["size"]["dataset"]["num_bytes_original_files"] > 0
    statistics = ds._fetch_statistics(IMDB, info, size)
    assert [(c, s) for c, s, _ in statistics] == [("plain_text", "train"), ("plain_text", "test"), ("plain_text", "unsupervised")]
    facts = ds._hub_facts(IMDB, info, size, statistics)
    assert facts["size"] and facts["size"] > 0 and facts["modality"] == ["text"] and facts["availability"] == "direct-download"
    kinds = dict(facts["statistics"])
    assert kinds["train:label:n_unique"] == "2" and float(kinds["train:text:length:mean"]) > 0


# -- cdxgen 이 다르게 적는 허브 데이터셋 ------------------------------------------------------
def test_a_dataset_link_in_code_is_one_component_with_the_model_card_dataset(tmp_path, online, monkeypatch):
    """코드의 huggingface.co/datasets 링크로 cdxgen 이 만든 데이터셋을 알아본다. 허브 모델 카드가 같은 데이터셋을 적어도 하나로 남고,
    조회한 뒤 purl·bom-ref 와 data[] 가 생긴다 (전에는 같은 데이터셋이 둘이고 링크 쪽은 조회되지 않았다)."""
    monkeypatch.setattr(hub, "fetch_model_info", lambda hf_id: {"cardData": {"datasets": [IMDB]}})
    hub_bert = {"bom-ref": BERT_REF, "type": "machine-learning-model", "group": "google-bert", "name": "bert-base-uncased", "purl": BERT_REF,
                "evidence": {"occurrences": [{"location": "src/train.py#L5"}]}}                  # 코드가 부르는 허브 모델
    out = discover_datasets(doc_of(cdxgen_link(IMDB), hub_bert), str(tmp_path))
    found = datasets(out)
    assert set(found) == {IMDB_REF} and online == [IMDB]
    link = found[IMDB_REF]
    assert link["data"][0] == {"type": "dataset", "name": IMDB, "contents": {"url": "https://huggingface.co/datasets/stanfordnlp/imdb"}}
    assert link["externalReferences"] == [{"type": "distribution", "url": "https://huggingface.co/datasets/stanfordnlp/imdb"},
                                          {"type": "website", "url": "https://paperswithcode.com/dataset/imdb-movie-reviews"}]
    assert link["evidence"]["occurrences"] == [{"location": "src/train.py#L8"}]
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": IMDB_REF}]


def test_renaming_rewrites_the_broken_datasets_datasets_url(tmp_path, monkeypatch, imdb):
    """이름만 있는 id(bookcorpus)에 cdxgen 은 https://huggingface.co/datasets/datasets/bookcorpus 주소를 적는다 (401). 정식 id 로 바꿀 때
    data[] 와 externalReferences 의 그 주소도 정식 주소로 바꾸고, 겹치면 하나만 남긴다."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub, "fetch_dataset_info", lambda hf_id: bookcorpus_hub(imdb))
    book = cdxgen_bookcorpus()
    book["externalReferences"] = [{"type": "distribution", "url": "https://huggingface.co/datasets/datasets/bookcorpus"},
                                  {"type": "website", "url": "https://example.org/bookcorpus"}]
    out = discover_datasets(doc_of(book), str(tmp_path))
    found = datasets(out)["pkg:huggingface/datasets/bookcorpus/bookcorpus"]
    assert found["externalReferences"] == [{"type": "distribution", "url": "https://huggingface.co/datasets/bookcorpus/bookcorpus"},
                                           {"type": "website", "url": "https://example.org/bookcorpus"}]
    assert "datasets/datasets" not in json.dumps(out)


def test_owner_name_datasets_named_in_a_model_header_become_components(tmp_path, monkeypatch):
    """cdxgen 은 GGUF 헤더의 general.datasets 를 모델카드에 이름뿐인 항목으로 적는다 (contents.url 에도 id 를 그대로). owner/name 꼴이면
    데이터셋 컴포넌트로 만들어 ref 로 바꾸고, 모델 파일을 evidence 로 둔다. 표시 이름·이름 하나뿐인 것은 그대로 둔다."""
    monkeypatch.setattr(hub, "hf_reachable", lambda: False)
    gguf = {"bom-ref": "cdxgen:ai:model:Acme:Tiny", "type": "machine-learning-model", "group": "Acme", "name": "Tiny", "purl": "pkg:generic/Acme/Tiny",
            "evidence": {"occurrences": [{"location": "models/tiny.gguf"}]},
            "modelCard": {"modelParameters": {"datasets": [{"type": "dataset", "name": "acme/chat-sft", "contents": {"url": "acme/chat-sft"}},
                                                           {"type": "dataset", "name": "wikitext"}, {"type": "dataset", "name": "Acme Eval"}]}}}
    facts = Facts()
    out = discover_datasets(doc_of(gguf), str(tmp_path), facts=facts)
    model = next(c for c in out["components"] if c["type"] == "machine-learning-model")
    ref = "pkg:huggingface/datasets/acme/chat-sft"
    assert facts.roles == {(model["bom-ref"], ref): {"training"}}                       # general.datasets 는 학습 데이터셋
    assert model["modelCard"]["modelParameters"]["datasets"] == [{"type": "dataset", "name": "wikitext"}, {"type": "dataset", "name": "Acme Eval"}, {"ref": ref}]
    assert datasets(out)[ref]["evidence"]["occurrences"] == [{"location": "models/tiny.gguf"}]
    assert ref in deps_of(out)[model["bom-ref"]]
