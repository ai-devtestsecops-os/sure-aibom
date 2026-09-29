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

import aibom_cli.dataset as ds
from aibom_cli.enrich import skip_reason
from aibom_cli.merge import merge
from aibom_cli.form import INTERNAL_PREFIX, apply
from aibom_cli.validate import validate_cdx

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


REAL_FETCH_SIZE, REAL_FETCH_STATISTICS = ds.fetch_dataset_size, ds.fetch_dataset_statistics     # 실제 허브를 치는 테스트가 되돌려 쓴다


@pytest.fixture(autouse=True)
def no_datasets_server(monkeypatch):
    """datasets-server 조회는 기본으로 실패(None)로 친다. 필요한 테스트가 다시 끼운다."""
    monkeypatch.setattr(ds, "fetch_dataset_size", lambda hf_id, log=print: None)
    monkeypatch.setattr(ds, "fetch_dataset_statistics", lambda hf_id, config, split, log=print: None)


@pytest.fixture
def online(monkeypatch, imdb):
    """허브에 닿는 것으로 치고, imdb 만 픽스처(허브 정보 · /size · split 별 /statistics)로 답한다. 다른 id 는 None (조회 실패)."""
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    calls: list[str] = []

    def fetch(hf_id, log=print):
        calls.append(hf_id)
        return copy.deepcopy(imdb) if hf_id == IMDB else None
    monkeypatch.setattr(ds, "fetch_dataset_info", fetch)
    monkeypatch.setattr(ds, "fetch_dataset_size", lambda hf_id, log=print: imdb_size() if hf_id == IMDB else None)
    monkeypatch.setattr(ds, "fetch_dataset_statistics",
                        lambda hf_id, config, split, log=print: imdb_statistics(config, split) if hf_id == IMDB else None)
    return calls


def cdxgen_bookcorpus() -> dict:
    """cdxgen 이 모델 README 에서 만드는 데이터셋 컴포넌트 모양 (purl 없음, data[0].name "datasets/<id>")."""
    return {"bom-ref": "cdxgen:ai:dataset:huggingface:datasets-bookcorpus", "type": "data", "group": "datasets", "name": "bookcorpus",
            "version": "", "data": [{"type": "dataset", "name": "datasets/bookcorpus", "contents": {"url": "https://huggingface.co/datasets/datasets/bookcorpus"}}],
            "properties": [{"name": "cdx:ai:kind", "value": "dataset"}]}


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


IMDB_TRAIN_STATS = [("train:label:n_unique", "2"), ("train:label:frequencies", "neg=12500,pos=12500"),      # 동률이라 mode 없음
                    ("train:text:length:min", "52"), ("train:text:length:max", "13704"), ("train:text:length:mean", "1325.06964"),
                    ("train:text:length:median", "979"), ("train:text:length:std", "1003.13367")]


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project(tmp_path: Path) -> Path:
    """tests/data/project 와 같은 모양의 임시 프로젝트. 로컬 데이터는 data/ 에 있고 --data 로 지목한다."""
    write(tmp_path, "data/train.csv", 'id,text,label\n1,"good movie",1\n2,"bad movie",0\n3,"fine",1\n4,"meh",0\n5,"great",1\n')
    write(tmp_path, "data/labels.jsonl", '{"id":1,"label":"pos"}\n{"id":2,"label":"neg"}\n{"id":3,"label":"pos"}\n')
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
    ({"type": "data", "group": "datasets", "name": "wikitext"}, "wikitext"),
    ({"type": "data", "name": "data", "data": [{"type": "dataset", "name": "data/train.csv"}]}, None),
    ({"type": "library", "purl": "pkg:huggingface/datasets/x/y"}, None),
])
def test_hf_dataset_id_of(comp, expected):
    assert ds.hf_dataset_id_of(comp) == expected


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
    assert ds._parse_python(src, log=print) == ["stanfordnlp/imdb", "imdb"]    # 빌더 이름 · 경로 · 다른 호출은 허브 id 가 아니다


def test_unparsable_python_is_skipped_with_a_log(tmp_path):
    logs: list[str] = []
    assert ds._parse_python(write(tmp_path, "bad.py", "def (:\n"), log=logs.append) == []
    assert any("bad.py" in m for m in logs)


# -- 로컬 파일 분석 ------------------------------------------------------------------
def test_file_analysis_by_format(tmp_path):
    csv_path = write(tmp_path, "t.csv", 'a,b\n1,"x\ny"\n2,z\n\n')
    a = ds._analyze_file(csv_path, "t.csv", log=print)
    assert a["rows"] == 2 and a["columns"] == ["a", "b"] and a["format"] == "csv" and a["modality"] == "structured"
    assert a["sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest() and a["size"] == csv_path.stat().st_size
    assert ds._analyze_file(write(tmp_path, "t.tsv", "a\tb\n1\t2\n"), "t.tsv", log=print)["columns"] == ["a", "b"]
    assert ds._analyze_file(write(tmp_path, "l.jsonl", '{"a":1}\n\n{"a":2}\n'), "l.jsonl", log=print)["rows"] == 2
    assert ds._analyze_file(write(tmp_path, "arr.json", "[1, 2, 3]"), "arr.json", log=print)["rows"] == 3
    assert "rows" not in ds._analyze_file(write(tmp_path, "obj.json", '{"a": 1}'), "obj.json", log=print)
    assert ds._analyze_file(write(tmp_path, "w.txt", "a\nb\n\nc\n"), "w.txt", log=print)["rows"] == 3
    png = tmp_path / "i.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    i = ds._analyze_file(png, "i.png", log=print)
    assert i["modality"] == "image" and "rows" not in i and i["sha256"]


def test_npy_header_is_parsed_without_numpy(tmp_path):
    header = "{'descr': '<f8', 'fortran_order': False, 'shape': (7, 3), }"
    header = header + " " * (64 - (10 + len(header) + 1) % 64) + "\n"
    npy = tmp_path / "e.npy"
    npy.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin-1") + b"\0" * (7 * 3 * 8))
    assert ds._analyze_file(npy, "e.npy", log=print)["rows"] == 7
    assert "rows" not in ds._analyze_file(write(tmp_path, "not.npy", "nope"), "not.npy", log=print)


def test_unreadable_content_falls_back_to_size_and_hash(tmp_path):
    logs: list[str] = []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    a = ds._analyze_file(bad, "bad.json", log=logs.append)
    assert a["sha256"] and "rows" not in a and any("bad.json" in m for m in logs)


def test_large_files_record_size_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "HASH_LIMIT", 10)
    logs: list[str] = []
    a = ds._analyze_file(write(tmp_path, "big.csv", "a,b\n" * 10), "big.csv", log=logs.append)
    assert "sha256" not in a and "rows" not in a and a["size"] == 40 and any("2 GB" in m for m in logs)


# -- discover: --data 경로 + 코드 ------------------------------------------------------------
def test_discover_builds_one_component_per_data_path_and_links_from_root(tmp_path, online):
    root = project(tmp_path)
    out = ds.discover(doc_of(), str(root), log=lambda m: None, data_paths=data_of(root))
    found = datasets(out)
    assert set(found) == {"data:local/data@", IMDB_REF}

    local = found["data:local/data@"]
    assert local["name"] == "data" and [d["name"] for d in local["data"]] == ["data/labels.jsonl", "data/train.csv"]
    train = {p["name"]: p["value"] for p in local["data"][1]["contents"]["properties"]}
    assert train["aibom-cli:file:rows"] == "5" and train["aibom-cli:file:columns"] == "id,text,label" and train["aibom-cli:file:format"] == "csv"
    # 열 통계: 파일이 둘이라 파일 이름이 앞에 붙는다. labels.jsonl 의 label 은 범주(pos 2, neg 1), train.csv 의 text 는 글(길이 통계), label 0/1 은 숫자로 읽힌다
    assert internal(local) == {"size": str(80 + 69), "modality:0": "text", "modality:1": "structured", **stats_props([
                                   ("labels:id:min", "1"), ("labels:id:max", "3"), ("labels:id:mean", "2"), ("labels:id:median", "2"), ("labels:id:std", "1"),
                                   ("labels:label:n_unique", "2"), ("labels:label:mode", "pos"), ("labels:label:frequencies", "pos=2,neg=1"),
                                   ("train:id:min", "1"), ("train:id:max", "5"), ("train:id:mean", "3"), ("train:id:median", "3"), ("train:id:std", "1.58114"),
                                   ("train:text:length:min", "3"), ("train:text:length:max", "10"), ("train:text:length:mean", "6.2"),
                                   ("train:text:length:median", "5"), ("train:text:length:std", "3.11448"),
                                   ("train:label:min", "0"), ("train:label:max", "1"), ("train:label:mean", "0.6"), ("train:label:median", "1"), ("train:label:std", "0.54772")])}

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
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=[str(tmp_path / "corpus")]))
    assert [d["name"] for d in found["data:local/corpus@"]["data"]] == ["corpus/a.txt", "corpus/b.csv", "corpus/labels.json"]


def test_skip_dirs_and_hidden_dirs_are_not_walked(tmp_path, online):
    for d in ("node_modules", ".git", "venv", ".venv", "site-packages", "__pycache__", ".cache"):
        write(tmp_path, f"data/{d}/x.csv", "a\n1\n")                          # 데이터 경로 안에서도
        write(tmp_path, f"{d}/x.py", 'load_dataset("hidden/one")\n')            # 대상의 소스를 걸을 때도
    write(tmp_path, "data/ok/y.csv", "a\n1\n")
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=data_of(tmp_path)))
    assert set(found) == {"data:local/data@"} and [d["name"] for d in found["data:local/data@"]["data"]] == ["data/ok/y.csv"]


def test_a_single_file_data_path_is_its_own_component(tmp_path, online):
    write(tmp_path, "train.csv", "a\n1\n")
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=[str(tmp_path / "train.csv")]))
    assert set(found) == {"data:local/train@"} and found["data:local/train@"]["name"] == "train"
    assert [d["name"] for d in found["data:local/train@"]["data"]] == ["train.csv"]
    facts = internal(found["data:local/train@"])
    assert "provenance:0" not in facts and "availability" not in facts       # 로컬 파일로는 출처·가용성을 알 수 없다


def test_data_files_in_the_target_are_not_read_without_a_data_path(tmp_path, monkeypatch):
    """로컬 데이터는 --data 로 지목한 곳에서만 읽는다. 확장자만 보고 추측하면 아이콘 같은 것도 데이터셋이 된다."""
    monkeypatch.setattr(ds, "hf_reachable", lambda: pytest.fail("조회할 것이 없는데 네트워크를 봤다"))
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "static/icon.png", "x")
    write(tmp_path, "app.py", 'import pandas as pd\npd.read_csv("data/train.csv")\n')       # 코드가 읽어도 넣지 않는다
    doc = doc_of()
    before = json.dumps(doc)
    assert json.dumps(ds.discover(doc, str(tmp_path), log=lambda m: None)) == before


def test_data_paths_are_deduplicated_and_names_do_not_collide(tmp_path, online):
    write(tmp_path, "a/data/x.csv", "v\n1\n")
    write(tmp_path, "b/data/y.csv", "v\n2\n")
    write(tmp_path, "empty/notes.md", "docs\n")
    report: dict = {}
    paths = [str(tmp_path / "a/data"), str(tmp_path / "a/data") + "/", str(tmp_path / "a/data/x.csv"),   # 같은 곳 · 이미 들어간 파일
             str(tmp_path / "b/data"), str(tmp_path / "empty"), str(tmp_path / "missing")]
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, report=report, data_paths=paths))
    assert set(found) == {"data:local/data@", "data:local/data-2@"}                  # 폴더 이름이 같으면 -2
    assert [d["name"] for d in found["data:local/data@"]["data"]] == ["data/x.csv"]
    assert [d["name"] for d in found["data:local/data-2@"]["data"]] == ["data/y.csv"]
    assert report["empty_data_paths"] == [str(tmp_path / "a/data/x.csv"), str(tmp_path / "empty"), str(tmp_path / "missing")]


def test_nested_files_keep_their_path_and_statistics_prefix(tmp_path, online):
    write(tmp_path, "imdb/train/part-0.csv", "v\n1\n3\n")
    write(tmp_path, "imdb/test/part-0.csv", "v\n5\n")
    local = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=[str(tmp_path / "imdb")]))["data:local/imdb@"]
    assert [d["name"] for d in local["data"]] == ["imdb/test/part-0.csv", "imdb/train/part-0.csv"]
    kinds = {v for k, v in internal(local).items() if k.endswith(":type")}
    assert {"test/part-0:v:min", "train/part-0:v:min"} <= kinds                   # 같은 파일 이름도 경로로 갈린다


# -- discover: 허브 -------------------------------------------------------------------
def test_hub_info_fills_component_and_facts(imdb):
    comp = ds._new_hf_component(IMDB)
    ds.apply_hub_info(comp, IMDB, imdb)
    assert comp["version"] == imdb["sha"] and comp["supplier"] == {"name": "stanfordnlp"}
    assert comp["licenses"] == [{"license": {"name": "other"}}]                   # "other" 는 SPDX id 가 아니다
    assert comp["description"].startswith('Dataset Card for "imdb" Dataset Summary Large Movie Review Dataset.') and "\n" not in comp["description"]
    assert comp["externalReferences"] == [{"type": "distribution", "url": "https://huggingface.co/datasets/stanfordnlp/imdb"},
                                          {"type": "website", "url": "https://paperswithcode.com/dataset/imdb-movie-reviews"}]
    assert internal(comp) == {"size": "133190302", "modality:0": "text", "availability": "direct-download",
                              "provenance:0": "https://huggingface.co/datasets/stanfordnlp/imdb"}          # 통계 응답이 없으면 statistics 도 없다
    # datasets-server 통계를 주면 split:열:통계 로 들어간다. 라벨 열은 n_unique·frequencies, 글 열은 길이의 min·max·mean·median·std
    comp = ds._new_hf_component(IMDB)
    ds.apply_hub_info(comp, IMDB, imdb, imdb_size(), [("plain_text", "train", imdb_statistics("plain_text", "train"))])
    assert {k: v for k, v in internal(comp).items() if k.startswith("statistics")} == stats_props(IMDB_TRAIN_STATS)


def test_hub_facts_variants():
    gated = ds.hub_facts("a/b", {"gated": "auto", "cardData": {"license": "apache-2.0", "task_categories": ["image-classification", "audio-classification", "tabular-regression", "weird"],
                                                              "dataset_info": [{"config_name": "x", "download_size": 10, "splits": [{"name": "train", "num_examples": 3}], "features": [{}]},
                                                                               {"config_name": "y", "dataset_size": 5}]}})
    assert gated["availability"] == "registration" and gated["size"] == 15 and gated["modality"] == ["image", "audio", "structured", "other"]
    assert gated["statistics"] == []                                                       # 행 수·feature 수·config 수는 통계가 아니다
    empty = ds.hub_facts("a/b", {"id": "a/b"})
    assert empty["size"] is None and empty["modality"] == [] and empty["statistics"] == [] and empty["availability"] == "direct-download"
    # README 앞머리에 크기가 없으면 datasets-server /size 의 원본 파일 바이트. 앞머리에 있으면 그것이 이긴다
    assert ds.hub_facts("a/b", {"id": "a/b"}, imdb_size())["size"] == 83446840
    assert ds.hub_facts("a/b", {"id": "a/b", "cardData": {"dataset_info": {"dataset_size": 7}}}, imdb_size())["size"] == 7
    assert ds.hub_facts("a/b", {"id": "a/b"}, {"size": {}})["size"] is None
    # 허브의 modality: 태그가 있으면 task_categories 보다 먼저다. 모르는 태그 값은 other, 태그 값은 v0.6 허용값으로 옮긴다
    tagged = ds.hub_facts("a/b", {"tags": ["modality:tabular", "modality:text", "modality:3d", "format:parquet", "modality:text"],
                                  "cardData": {"task_categories": ["image-classification"]}})
    assert tagged["modality"] == ["structured", "text", "other"]
    assert ds.hub_facts("a/b", {"tags": ["format:parquet"], "cardData": {"task_categories": ["image-classification"]}})["modality"] == ["image"]
    assert ds._license("apache-2.0") == {"license": {"id": "Apache-2.0"}} and ds._license("MIT") == {"license": {"id": "MIT"}}
    assert ds._license("unknown") == {"license": {"name": "unknown"}}


def test_existing_cdxgen_component_is_enriched_in_place_not_duplicated(tmp_path, monkeypatch, imdb):
    write(tmp_path, "train.py", 'load_dataset("bookcorpus")\n')
    doc = doc_of(cdxgen_bookcorpus())
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: {**copy.deepcopy(imdb), "id": "bookcorpus", "sha": "abc"} if hf_id == "bookcorpus" else None)
    deps_before = copy.deepcopy(doc["dependencies"])
    out = ds.discover(doc, str(tmp_path), log=lambda m: None)
    found = datasets(out)
    assert set(found) == {"data:datasets/bookcorpus@"}                                # 병합 키 그대로, 새 컴포넌트 없음
    book = found["data:datasets/bookcorpus@"]
    assert book["version"] == "abc" and book["evidence"]["occurrences"] == [{"location": "train.py"}]
    assert {(r["type"], r["url"]) for r in book["externalReferences"]} >= {("distribution", "https://huggingface.co/datasets/bookcorpus")}
    assert internal(book)["provenance:0"] == "https://huggingface.co/datasets/bookcorpus"
    assert props(book)["cdx:ai:kind"] == "dataset"                                     # cdxgen 프로퍼티는 그대로
    assert out["dependencies"] == deps_before                                          # 새 컴포넌트가 없으니 관계도 그대로


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
        out |= {e["ref"] for e in ((c.get("modelCard") or {}).get("modelParameters") or {}).get("datasets") or []}
    return out


def deps_of(doc: dict) -> dict[str, list[str]]:
    return {d["ref"]: d["dependsOn"] for d in doc["dependencies"]}


@pytest.mark.parametrize("info_id", ["imdb", "stanfordnlp/imdb", "", None, "../x", 3])
def test_canonical_id_takes_a_well_formed_hub_id_only(info_id):
    expected = info_id if info_id in ("imdb", "stanfordnlp/imdb") else "a/b"
    assert ds.canonical_id("a/b", {"id": info_id}) == expected
    assert ds.canonical_id("a/b", None) == "a/b" and ds.canonical_id("a/b", {}) == "a/b"


def test_same_dataset_under_two_ids_becomes_one_component_and_one_hub_call(tmp_path, monkeypatch, imdb):
    """README 의 bookcorpus 와 코드의 bookcorpus/bookcorpus. 허브는 둘 다 bookcorpus/bookcorpus 라 답한다."""
    write(tmp_path, "train.py", 'load_dataset("bookcorpus/bookcorpus")\n')
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: calls.append(hf_id) or bookcorpus_hub(imdb))
    logs: list[str] = []
    out = ds.discover(readme_doc(), str(tmp_path), log=logs.append)
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
    assert [m for m in logs if "합쳤다" in m] == ["[dataset] bookcorpus 은 bookcorpus/bookcorpus 과 같은 데이터셋, 하나로 합쳤다"]
    for form in ("properties", "typed"):
        assert validate_cdx(apply(copy.deepcopy(out), form=form, log=print), "1.7" if form == "properties" else "v0.6", log=print)


def test_readme_only_component_is_renamed_to_the_hub_id_and_refs_follow(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: bookcorpus_hub(imdb))
    logs: list[str] = []
    out = ds.discover(readme_doc(), str(tmp_path), log=logs.append)
    found = datasets(out)
    assert set(found) == {BOOK_CANON}
    book = found[BOOK_CANON]
    assert (book["group"], book["name"], book["purl"]) == ("bookcorpus", "bookcorpus", BOOK_CANON)
    assert book["data"][0]["name"] == "datasets/bookcorpus/bookcorpus"                    # cdxgen 의 이름 모양은 그대로, id 만 바뀐다
    assert book["data"][0]["contents"]["url"] == "https://huggingface.co/datasets/bookcorpus/bookcorpus"
    assert props(book)["cdx:ai:kind"] == "dataset"
    bert = next(c for c in out["components"] if c["bom-ref"] == BERT_REF)
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": BOOK_CANON}]
    deps = deps_of(out)
    assert deps[BERT_REF] == [BOOK_CANON] and deps[out["metadata"]["component"]["bom-ref"]] == [BERT_REF]   # 코드에서 안 불렀으니 루트 → 데이터셋 엣지는 없다
    assert "[dataset] bookcorpus → bookcorpus/bookcorpus (허브 정식 id)" in logs


def test_old_hub_name_in_code_is_renamed_and_two_spellings_collapse(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: calls.append(hf_id) or copy.deepcopy(imdb))
    write(tmp_path, "a.py", 'load_dataset("imdb")\n')
    write(tmp_path, "b.py", 'load_dataset("stanfordnlp/imdb")\n')
    out = ds.discover(doc_of(), str(tmp_path), log=lambda m: None)
    found = datasets(out)
    assert set(found) == {IMDB_REF} and calls == ["imdb"]
    hf = found[IMDB_REF]
    assert (hf["group"], hf["name"], hf["purl"], hf["data"][0]["name"]) == ("stanfordnlp", "imdb", IMDB_REF, IMDB)
    assert hf["evidence"]["occurrences"] == [{"location": "a.py"}, {"location": "b.py"}]
    assert deps_of(out)[out["metadata"]["component"]["bom-ref"]] == [IMDB_REF]           # 옛 이름의 purl 은 관계에서도 사라진다
    assert internal(hf)["size"] == "133190302"


def test_alias_whose_lookup_fails_stays_a_separate_component(tmp_path, monkeypatch, imdb):
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: copy.deepcopy(imdb) if hf_id == IMDB else None)
    write(tmp_path, "a.py", 'load_dataset("imdb")\nload_dataset("stanfordnlp/imdb")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {IMDB_REF, "pkg:huggingface/datasets/imdb"}                     # 같은 것인지 알 길이 없으니 둔다
    assert "properties" not in found["pkg:huggingface/datasets/imdb"]


# -- 통계 (datasets-server · 로컬 열) ------------------------------------------------------
def test_statistics_requests_follow_dataset_info_then_size_and_are_capped(monkeypatch):
    info_with_splits = {"id": "a/b", "cardData": {"dataset_info": [{"config_name": "x", "splits": [{"name": "train"}, {"name": "test"}]},
                                                                    {"config_name": "y", "splits": [{"name": "train"}]}]}}
    assert ds._config_splits(info_with_splits, imdb_size()) == [("x", "train"), ("x", "test"), ("y", "train")]       # 앞머리가 있으면 /size 는 안 본다
    assert ds._config_splits({"id": "a/b"}, imdb_size()) == [("plain_text", "train"), ("plain_text", "test"), ("plain_text", "unsupervised")]
    assert ds._config_splits({"id": "a/b"}, None) == [] and ds._config_splits({"id": "a/b"}, {"size": {"splits": [{"config": "c"}]}}) == []
    calls: list[tuple[str, str]] = []
    def fetch(hf_id, config, split, log=print):
        calls.append((config, split))
        return {"statistics": [], "partial": config == "c3"} if config != "c5" else None
    monkeypatch.setattr(ds, "fetch_dataset_statistics", fetch)
    many = {"id": "a/b", "cardData": {"dataset_info": [{"config_name": f"c{i}", "splits": [{"name": "train"}, {"name": "test"}]} for i in range(8)]}}
    logs: list[str] = []
    got = ds._fetch_statistics("a/b", many, None, logs.append)
    assert len(calls) == ds.STATISTICS_REQUEST_LIMIT == 12 and calls[0] == ("c0", "train") and calls[-1] == ("c5", "test")
    assert [c for c, _, _ in got] == ["c0", "c0", "c1", "c1", "c2", "c2", "c3", "c3", "c4", "c4"]                    # c5 는 조회 실패
    assert any("16개 중 앞 12개만" in m for m in logs) and sum("partial" in m for m in logs) == 2


def test_hub_column_statistics_by_column_type():
    resp = {"statistics": [
        {"column_name": "y", "column_type": "class_label", "column_statistics": {"n_unique": 12, "frequencies": {str(i): 1 for i in range(12)}}},   # 범주 11개 이상 → n_unique 만
        {"column_name": "img", "column_type": "image", "column_statistics": {"min": 32, "max": 32.0, "mean": 32.0, "median": 32.0, "std": 0.0, "nan_count": 0}},
        {"column_name": "dur", "column_type": "audio", "column_statistics": {"mean": 6.589523, "histogram": {}}},
        {"column_name": "flag", "column_type": "bool", "column_statistics": {"n_unique": 2, "frequencies": {"True": 3, "False": 3}}},
        {"column_name": "sp", "column_type": "string_label", "column_statistics": {"n_unique": 3, "frequencies": {"b": 1, "a": 5, "c": 2}}},
        {"column_name": "n", "column_type": "float", "column_statistics": {"min": "bad", "max": True, "mean": 1.5}},
        {"column_name": "", "column_type": "int", "column_statistics": {"min": 1}}, "garbage", {"column_name": "z", "column_statistics": None}]}
    single = ds._hub_statistics([("only", "train", resp)])
    assert single == [("train:y:n_unique", "12"),
                      ("train:img:width:min", "32"), ("train:img:width:max", "32"), ("train:img:width:mean", "32"), ("train:img:width:median", "32"), ("train:img:width:std", "0"),
                      ("train:dur:duration:mean", "6.58952"),
                      ("train:flag:n_unique", "2"), ("train:flag:frequencies", "False=3,True=3"),                  # 동률 → mode 없음, 이름순
                      ("train:sp:n_unique", "3"), ("train:sp:mode", "a"), ("train:sp:frequencies", "a=5,c=2,b=1"),
                      ("train:n:mean", "1.5")]
    multi = ds._hub_statistics([("c1", "train", resp), ("c2", "test", {"statistics": []})])
    assert multi[0] == ("c1:train:y:n_unique", "12") and len(multi) == len(single)


@pytest.mark.parametrize("values, expected", [
    (["1", "2", "3", ""], [("min", "1"), ("max", "3"), ("mean", "2"), ("median", "2"), ("std", "1")]),                 # 빈 칸은 뺀다
    ([1.5, 2, None], [("min", "1.5"), ("max", "2"), ("mean", "1.75"), ("median", "1.75"), ("std", "0.35355")]),
    (["7"], [("min", "7"), ("max", "7"), ("mean", "7"), ("median", "7")]),                                         # 하나면 std 없음
    (["1", "inf", "2"], [("length:min", "1"), ("length:max", "3"), ("length:mean", "1.66667"), ("length:median", "1"), ("length:std", "1.1547")]),   # inf 는 수가 아니다 → 글
    ([True, False, True], [("n_unique", "2"), ("mode", "true"), ("frequencies", "true=2,false=1")]),
    (["cat", "dog", "cat", "cat"], [("n_unique", "2"), ("mode", "cat"), ("frequencies", "cat=3,dog=1")]),
    (["a", "b", "c"], [("length:min", "1"), ("length:max", "1"), ("length:mean", "1"), ("length:median", "1"), ("length:std", "0")]),   # 전부 달라 범주가 아니다
    ([f"w{i}" for i in range(11)] * 2, [("length:min", "2"), ("length:max", "3"), ("length:mean", "2.09091"), ("length:median", "2"), ("length:std", "0.29424")]),  # 범주 11개 → 글
    ([None, ""], []),
    ([{"nested": 1}, "x"], [("length:min", "1"), ("length:max", "13"), ("length:mean", "7"), ("length:median", "7"), ("length:std", "8.48528")]),
])
def test_local_values_statistics_rules(values, expected):
    assert ds._values_statistics(values) == expected


def test_local_file_statistics_for_jsonl_json_tsv_and_limits(tmp_path, monkeypatch):
    write(tmp_path, "a.jsonl", '{"x": 1, "tags": ["p"], "y": "u"}\n{"x": 3, "tags": [], "y": "u"}\n{"x": 2, "y": "v"}\n')
    assert ds._file_statistics(tmp_path / "a.jsonl", "jsonl") == [("x:min", "1"), ("x:max", "3"), ("x:mean", "2"), ("x:median", "2"), ("x:std", "1"),
                                                                   ("y:n_unique", "2"), ("y:mode", "u"), ("y:frequencies", "u=2,v=1")]   # tags 는 중첩 값이라 뺀다
    write(tmp_path, "b.json", '[{"k": 2}, {"k": 4}, 5, {"k": null}]')
    assert ds._file_statistics(tmp_path / "b.json", "json") == [("k:min", "2"), ("k:max", "4"), ("k:mean", "3"), ("k:median", "3"), ("k:std", "1.41421")]
    write(tmp_path, "c.tsv", "h1\t\th3\n1\tx\ta\n2\ty\tb\n")
    assert ds._file_statistics(tmp_path / "c.tsv", "tsv") == [("h1:min", "1"), ("h1:max", "2"), ("h1:mean", "1.5"), ("h1:median", "1.5"), ("h1:std", "0.70711"),
                                                              ("h3:length:min", "1"), ("h3:length:max", "1"), ("h3:length:mean", "1"), ("h3:length:median", "1"), ("h3:length:std", "0")]   # 이름 없는 열은 뺀다
    assert ds._file_statistics(tmp_path / "c.tsv", "png") == [] and ds._file_statistics(write(tmp_path, "e.csv", ""), "csv") == []
    write(tmp_path, "bad.json", "{not json")
    assert "statistics" not in ds._analyze_file(tmp_path / "bad.json", "bad.json", log=lambda m: None)             # 파싱 실패 → 크기·해시만
    monkeypatch.setattr(ds, "STATISTICS_FILE_LIMIT", 10)
    a = ds._analyze_file(tmp_path / "a.jsonl", "a.jsonl", log=lambda m: None)
    assert a["rows"] == 3 and "statistics" not in a                                                                 # 상한을 넘으면 통계는 건너뛴다


def test_local_statistics_prefix_only_when_a_directory_has_several_files(tmp_path):
    write(tmp_path, "data/only.csv", "v\n1\n2\n")
    facts = internal(datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=data_of(tmp_path)))["data:local/data@"])
    assert facts["statistics:0:type"] == "v:min" and facts["statistics:2:value"] == "1.5"                           # 파일 하나면 파일 이름을 붙이지 않는다


def test_offline_keeps_name_and_purl_and_logs_once(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "hf_reachable", lambda: False)
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: pytest.fail("offline 인데 조회했다"))
    write(tmp_path, "train.py", 'load_dataset("stanfordnlp/imdb")\nload_dataset("imdb")\n')
    logs: list[str] = []
    out = ds.discover(doc_of(), str(tmp_path), log=logs.append)
    found = datasets(out)
    assert set(found) == {IMDB_REF, "pkg:huggingface/datasets/imdb"}
    assert all("properties" not in c and "version" not in c for c in found.values())
    assert sum("닿지 않음" in m for m in logs) == 1
    for form in ("properties", "typed"):
        doc = apply(copy.deepcopy(out), form=form, log=print)
        assert validate_cdx(doc, "1.7" if form == "properties" else "v0.6", log=print)


def test_fetch_failure_is_logged_and_component_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: None)
    write(tmp_path, "train.py", 'load_dataset("nobody/nothing")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {"pkg:huggingface/datasets/nobody/nothing"} and "properties" not in found["pkg:huggingface/datasets/nobody/nothing"]


def test_image_target_only_enriches_existing_components(online):
    out = ds.discover(doc_of(cdxgen_bookcorpus(), root=("img:latest", "image")), "img:latest", log=lambda m: None)
    assert set(datasets(out)) == {"data:datasets/bookcorpus@"} and online == ["bookcorpus"]


# -- 회귀 보호: 데이터셋이 없으면 문서는 그대로다 ----------------------------------------------
def test_directory_without_datasets_leaves_the_document_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "hf_reachable", lambda: pytest.fail("조회할 것이 없는데 네트워크를 봤다"))
    write(tmp_path, "requirements.txt", "numpy==2.5.1\n")
    write(tmp_path, "package.json", '{"name": "x"}')
    write(tmp_path, "app.py", 'import numpy as np\nopen("README.md")\n')
    doc = doc_of({"bom-ref": "pkg:pypi/numpy@2.5.1", "type": "library", "name": "numpy", "version": "2.5.1", "purl": "pkg:pypi/numpy@2.5.1"})
    before = json.dumps(doc, ensure_ascii=False)
    out = ds.discover(doc, str(tmp_path), log=lambda m: None)
    assert json.dumps(out, ensure_ascii=False) == before
    for form in ("properties", "typed"):
        assert json.dumps(apply(copy.deepcopy(out), form=form, log=lambda m: None), ensure_ascii=False) == before


# -- form: 두 형태 --------------------------------------------------------------
@pytest.fixture
def discovered(tmp_path, online) -> dict:
    root = project(tmp_path)
    return ds.discover(doc_of(), str(root), log=lambda m: None, data_paths=data_of(root))


def test_properties_form_moves_facts_to_aibom_dataset_keys(discovered):
    out = apply(copy.deepcopy(discovered), form="properties", log=print)
    hf = datasets(out)[IMDB_REF]
    p = props(hf)
    assert p["aibom:dataset:size"] == "133190302" and p["aibom:dataset:modality:0"] == "text"
    assert p["aibom:dataset:availability"] == "direct-download" and p["aibom:dataset:provenance:0"] == "https://huggingface.co/datasets/stanfordnlp/imdb"
    assert (p["aibom:dataset:statistics:0:type"], p["aibom:dataset:statistics:0:value"]) == ("train:label:n_unique", "2")
    assert p["aibom:dataset:statistics:20:type"] == "unsupervised:text:length:std" and "aibom:dataset:statistics:21:type" not in p   # split 3개 × 7개
    assert not any(k.startswith(INTERNAL_PREFIX) for k in p) and "aibom-internal" not in json.dumps(out)
    assert "size" not in hf["data"][0] and "availability" not in hf["data"][0]["contents"]                  # typed 필드는 건드리지 않는다
    local = datasets(out)["data:local/data@"]
    assert props(local)["aibom:dataset:size"] == "149" and props(local)["aibom:dataset:statistics:6:value"] == "pos"          # labels:label:mode
    assert validate_cdx(out, "1.7", log=print) and validate_cdx(out, "v0.6", log=print)


def test_typed_form_fills_componentdata_fields_on_data0(discovered):
    out = apply(copy.deepcopy(discovered), form="typed", log=print)
    hf = datasets(out)[IMDB_REF]
    entry = hf["data"][0]
    assert entry["size"] == 133190302 and isinstance(entry["size"], int) and entry["modality"] == ["text"]
    assert entry["contents"] == {"url": "https://huggingface.co/datasets/stanfordnlp/imdb", "availability": "direct-download"}
    assert entry["provenance"] == ["https://huggingface.co/datasets/stanfordnlp/imdb"]
    assert entry["statistics"][:7] == [{"type": t, "value": v} for t, v in IMDB_TRAIN_STATS] and len(entry["statistics"]) == 21
    assert "properties" not in hf                                                     # 내부 키만 있었으니 목록째 사라진다
    local = datasets(out)["data:local/data@"]
    assert local["data"][0]["size"] == 149 and local["data"][0]["modality"] == ["text", "structured"] and "size" not in local["data"][1]
    assert local["data"][0]["contents"]["properties"][0]["name"] == "aibom-cli:file:size"          # 파일 사실은 그대로
    assert "aibom-internal" not in json.dumps(out) and "aibom:dataset:" not in json.dumps(out)
    assert validate_cdx(out, "v0.6", log=print)
    logs: list[str] = []
    assert not validate_cdx(out, "1.7", log=logs.append) and any("data/0" in m for m in logs)


def test_typed_form_creates_data_entry_when_missing():
    comp = {"type": "data", "name": "d", "bom-ref": "d", "properties": [{"name": INTERNAL_PREFIX + "size", "value": "5"}]}
    out = apply({"components": [comp]}, form="typed", log=print)
    assert out["components"][0] == {"type": "data", "name": "d", "bom-ref": "d", "data": [{"type": "dataset", "name": "d", "size": 5}]}


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_existing_values_win_and_internal_keys_are_always_removed(form):
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
    logs: list[str] = []
    out = apply({"components": [comp]}, form=form, log=logs.append)
    c = out["components"][0]
    assert not any(p["name"].startswith(INTERNAL_PREFIX) for p in c["properties"])
    assert sum("버린다" in m for m in logs) == 2 and any("허용값" in m for m in logs)
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
def test_dataset_form_is_idempotent(discovered, form):
    once = apply(copy.deepcopy(discovered), form=form, log=lambda m: None)
    logs: list[str] = []
    assert json.dumps(apply(copy.deepcopy(once), form=form, log=logs.append)) == json.dumps(once) and logs == []


def test_data_component_without_internal_keys_is_untouched():
    comp = {"type": "data", "name": "d", "bom-ref": "d", "properties": [{"name": "cdx:ai:kind", "value": "dataset"}], "data": [{"type": "dataset"}]}
    for form in ("properties", "typed"):
        assert json.dumps(apply({"components": [copy.deepcopy(comp)]}, form=form, log=print)) == json.dumps({"components": [comp]})


# -- 회귀: 확인된 결함 ------------------------------------------------------------------
def test_unknown_extensions_are_not_data_and_the_analyser_accepts_them(tmp_path, online):
    """모르는 확장자가 KeyError 로 스캔을 죽였다. 데이터 경로에서는 빼고, 분석기에 직접 넣으면 'other' 로 받는다."""
    write(tmp_path, "data/train.dat", "a,b\n1,2\n")
    write(tmp_path, "data/train", "a,b\n1,2\n")
    write(tmp_path, "data/x.xlsx", "x")
    report: dict = {}
    out = ds.discover(doc_of(), str(tmp_path), log=lambda m: None, report=report, data_paths=data_of(tmp_path))
    assert datasets(out) == {} and report["empty_data_paths"] == data_of(tmp_path)
    a = ds._analyze_file(tmp_path / "data/train.dat", "data/train.dat", log=print)
    assert a["modality"] == "other" and a["format"] == "dat" and a["sha256"] and "rows" not in a


def test_a_symlink_leaving_the_data_path_is_skipped(tmp_path, monkeypatch, online):
    """데이터 경로 밖을 가리키는 링크가 절대 경로(또는 ../ 경로)를 data[].name 에 흘렸다."""
    outside = write(tmp_path, "elsewhere/outside_secret.csv", "a\n1\n")
    root = tmp_path / "T"
    write(root, "data/train.csv", "a\n1\n2\n")
    (root / "data/link.csv").symlink_to(outside)
    (root / "data/inner.csv").symlink_to(root / "data/train.csv")             # 안을 가리키는 링크는 경로 안의 이름으로 남는다
    for data in (str(root / "data"), "T/data"):
        monkeypatch.chdir(tmp_path)
        logs: list[str] = []
        out = ds.discover(doc_of(), str(root), log=logs.append, data_paths=[data])
        local = datasets(out)["data:local/data@"]
        assert [d["name"] for d in local["data"]] == ["data/inner.csv", "data/train.csv"]
        text = json.dumps(out)
        assert "outside_secret" not in text and str(tmp_path) not in text and ".." not in text
        assert any("link.csv" in m and "경로 밖" in m for m in logs)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root 는 권한을 무시한다")
def test_unreadable_file_records_size_only(tmp_path, online):
    """권한이 없는 파일에서 PermissionError 가 스캔을 죽였다. 크기만 적고 알린다."""
    secret = write(tmp_path, "data/secret.csv", "a,b\n1,2\n")
    write(tmp_path, "data/ok.csv", "a\n1\n")
    secret.chmod(0)
    try:
        logs: list[str] = []
        a = ds._analyze_file(secret, "data/secret.csv", log=logs.append)
        assert a == {"path": "data/secret.csv", "size": 8, "format": "csv", "modality": "structured"}
        assert any("data/secret.csv" in m and "크기만" in m for m in logs)
        local = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None, data_paths=data_of(tmp_path)))["data:local/data@"]
        assert [d["name"] for d in local["data"]] == ["data/ok.csv", "data/secret.csv"] and internal(local)["size"] == "12"
    finally:
        secret.chmod(0o644)


def test_csv_with_a_very_wide_field_still_counts_rows(tmp_path, monkeypatch):
    """csv 모듈 기본 칸 한도(131072)를 넘는 문서 한 칸이 _csv.Error 로 스캔을 죽였다. 한도를 올리고, 그래도 나는 csv.Error 는 잡는다."""
    big = write(tmp_path, "big.csv", "a,b\n1," + "x" * 200000 + "\n")
    a = ds._analyze_file(big, "big.csv", log=print)
    assert a["rows"] == 1 and a["columns"] == ["a", "b"]

    def boom(path, ext):
        raise csv.Error("field larger than field limit")
    monkeypatch.setattr(ds, "_shape", boom)
    logs: list[str] = []
    a = ds._analyze_file(big, "big.csv", log=logs.append)
    assert a["sha256"] and "rows" not in a and any("Error" in m for m in logs)


def npy_bytes(header: str, payload: bytes = b"") -> bytes:
    """npy v1 파일: magic, 버전, 헤더 길이(리틀 엔디언 2 바이트), 헤더."""
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin-1") + payload


def test_npy_headers_longer_than_512_bytes_and_malformed_headers(tmp_path):
    """구조체 dtype 의 헤더는 512 바이트를 쉽게 넘는데 그만큼만 읽어 SyntaxError 로 죽었다. 깨진 헤더도 죽였다."""
    descr = "[" + ", ".join(f"('field_{i:03d}', '<f8')" for i in range(40)) + "]"
    header = f"{{'descr': {descr}, 'fortran_order': False, 'shape': (3,), }}"
    header = header + " " * (64 - (10 + len(header) + 1) % 64) + "\n"
    assert len(header) > 512
    struct_npy = tmp_path / "s.npy"
    struct_npy.write_bytes(npy_bytes(header, b"\0" * (3 * 40 * 8)))
    assert ds._analyze_file(struct_npy, "s.npy", log=print)["rows"] == 3

    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:                                                         # 실제 numpy 가 쓴 파일도 같다
        real = tmp_path / "real.npy"
        np.save(real, np.zeros(5, dtype=np.dtype([(f"f{i:03d}", "<f8") for i in range(40)])))
        assert ds._analyze_file(real, "real.npy", log=print)["rows"] == 5

    for name, header in (("garbage.npy", "garbage((("), ("int.npy", "123 "), ("list.npy", "[1, 2]"), ("short.npy", "{'shape': ()}")):
        bad = tmp_path / name
        bad.write_bytes(npy_bytes(header))
        a = ds._analyze_file(bad, name, log=print)
        assert "rows" not in a and a["sha256"]
    truncated = tmp_path / "trunc.npy"
    truncated.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", 900) + b"{'shape': (1,)")
    assert "rows" not in ds._analyze_file(truncated, "trunc.npy", log=print)
    npz = tmp_path / "s.npz"
    with zipfile.ZipFile(npz, "w") as zf:
        zf.writestr("arr.npy", npy_bytes(header if False else f"{{'descr': {descr}, 'fortran_order': False, 'shape': (9,), }}" + "\n"))
    assert ds._analyze_file(npz, "s.npz", log=print)["rows"] == 9


@pytest.mark.parametrize("text, expected", [
    ("stanfordnlp/imdb", True), ("imdb", True), ("HuggingFaceFW/fineweb-2", True), ("org/data-v0.1", True), ("Qwen/Qwen2.5-Math", True),
    ("my_script.py", False), ("./local_script.py", False), ("data/train.xlsx", False), ("data/train.csv", False), ("corpus.tar.gz", False),
    ("archive.7z", False), ("../x", False), ("a\\b", False),
])
def test_looks_like_hub_id_rejects_any_file_extension(text, expected):
    assert ds._looks_like_hub_id(text) is expected


def test_load_dataset_with_script_or_file_path_makes_no_hub_component(tmp_path, monkeypatch):
    """load_dataset("my_script.py") · load_dataset("data/train.xlsx") 가 가짜 허브 컴포넌트(pkg:huggingface/datasets/my_script.py)가 되었다."""
    monkeypatch.setattr(ds, "hf_reachable", lambda: pytest.fail("허브 id 가 없는데 네트워크를 봤다"))
    write(tmp_path, "my_script.py", "")
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "t.py", 'load_dataset("my_script.py")\nload_dataset("data/train.xlsx")\nload_dataset("data/train.csv")\n')
    assert datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None)) == {}


@pytest.mark.parametrize("task, modality", [
    ("text-to-speech", "audio"), ("text-to-audio", "audio"), ("text-to-video", "video"),
    ("text-classification", "text"), ("text-generation", "text"), ("text-to-image", "text"), ("automatic-speech-recognition", "audio"),
])
def test_specific_text_to_tasks_map_before_the_text_prefix(task, modality):
    assert ds._modality_of_task(task) == modality


# -- 실제 허브 (하나뿐) ------------------------------------------------------------------
@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_live_hub_returns_size_and_modality_for_imdb(monkeypatch):
    monkeypatch.setattr(ds, "fetch_dataset_size", REAL_FETCH_SIZE)
    monkeypatch.setattr(ds, "fetch_dataset_statistics", REAL_FETCH_STATISTICS)
    info = ds.fetch_dataset_info(IMDB, log=print)
    assert info and info["id"] == IMDB
    size = ds.fetch_dataset_size(IMDB, log=print)
    assert size and size["size"]["dataset"]["num_bytes_original_files"] > 0
    statistics = ds._fetch_statistics(IMDB, info, size, log=print)
    assert [(c, s) for c, s, _ in statistics] == [("plain_text", "train"), ("plain_text", "test"), ("plain_text", "unsupervised")]
    facts = ds.hub_facts(IMDB, info, size, statistics)
    assert facts["size"] and facts["size"] > 0 and facts["modality"] == ["text"] and facts["availability"] == "direct-download"
    kinds = dict(facts["statistics"])
    assert kinds["train:label:n_unique"] == "2" and float(kinds["train:text:length:mean"]) > 0
