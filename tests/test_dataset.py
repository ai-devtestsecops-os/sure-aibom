"""dataset — 스캔 대상 안의 데이터셋(HF 참조 · 로컬 데이터 파일)을 type=data 컴포넌트로 만들고, regulation 이 두 형태로 옮긴다.
허브 조회는 tests/fixtures/bom/hf_dataset_stanfordnlp_imdb.json (실제 GET /api/datasets/stanfordnlp/imdb 응답)으로 바꿔 끼운다.
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
from aibom_cli.regulation import INTERNAL_PREFIX, apply
from aibom_cli.validate import validate_cdx

IMDB_FIXTURE = Path(__file__).parent / "fixtures" / "bom" / "hf_dataset_stanfordnlp_imdb.json"
IMDB = "stanfordnlp/imdb"
IMDB_REF = "pkg:huggingface/datasets/stanfordnlp/imdb"


@pytest.fixture
def imdb() -> dict:
    return json.loads(IMDB_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def online(monkeypatch, imdb):
    """허브에 닿는 것으로 치고, imdb 만 픽스처로 답한다. 다른 id 는 None (조회 실패)."""
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    calls: list[str] = []

    def fetch(hf_id, log=print):
        calls.append(hf_id)
        return copy.deepcopy(imdb) if hf_id == IMDB else None
    monkeypatch.setattr(ds, "fetch_dataset_info", fetch)
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


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project(tmp_path: Path) -> Path:
    """tests/fixtures/mixed 의 데이터 부분과 같은 모양의 임시 프로젝트."""
    write(tmp_path, "data/train.csv", 'id,text,label\n1,"good movie",1\n2,"bad movie",0\n3,"fine",1\n4,"meh",0\n5,"great",1\n')
    write(tmp_path, "data/labels.jsonl", '{"id":1,"label":"pos"}\n{"id":2,"label":"neg"}\n{"id":3,"label":"pos"}\n')
    write(tmp_path, "src/train.py", 'from datasets import load_dataset\nimport pandas as pd\n'
                                    'imdb = load_dataset("stanfordnlp/imdb")\ndf = pd.read_csv("data/train.csv")\n'
                                    'local = load_dataset("csv", data_files="data/train.csv")\n')
    write(tmp_path, "package.json", '{"name": "x"}')                     # 약한 확장자 홀로 → 데이터가 아니다
    write(tmp_path, "models/config.json", '{"model_type": "bert"}')
    return tmp_path


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
def test_python_source_yields_hub_ids_and_routes_local_builders_to_data_files(tmp_path):
    src = write(tmp_path, "a.py", '''
from datasets import load_dataset
import datasets, numpy as np
a = load_dataset("stanfordnlp/imdb", split="train")
b = datasets.load_dataset("imdb")
c = load_dataset("csv", data_files="data/train.csv")
d = load_dataset("json", data_files=["a.jsonl", "b.jsonl"])
e = load_dataset("parquet", data_files={"train": "t.parquet", "test": ["u.parquet"]})
f = load_dataset("./local_script.py")
g = load_dataset("data/train.csv")
h = load_dataset(name)
df = pd.read_csv("data/train.csv")
arr = np.load("emb.npy")
fh = open("labels.txt")
cfg = open("config.yaml")
''')
    logs: list[str] = []
    ids, paths = ds._parse_python(src, log=logs.append)
    assert ids == ["stanfordnlp/imdb", "imdb"]
    # load_dataset("data/train.csv") 는 허브 id 가 아니라 경로라 출처 2 로 간다; open("config.yaml") 은 데이터 형식이 아니라 버린다
    assert paths == ["data/train.csv", "a.jsonl", "b.jsonl", "t.parquet", "u.parquet", "data/train.csv", "data/train.csv", "emb.npy", "labels.txt"]
    assert [m for m in logs if "건너뛴다" in m] == ["[dataset] a.py: './local_script.py' 은 아는 데이터 형식이 아니라 건너뛴다",
                                                 "[dataset] a.py: 'config.yaml' 은 아는 데이터 형식이 아니라 건너뛴다"]


def test_unparsable_python_is_skipped_with_a_log(tmp_path):
    logs: list[str] = []
    assert ds._parse_python(write(tmp_path, "bad.py", "def (:\n"), log=logs.append) == ([], [])
    assert any("bad.py" in m for m in logs)


def test_code_paths_resolve_inside_the_target_only(tmp_path):
    root = tmp_path / "proj"
    write(root, "data/a.csv", "x\n1\n")
    write(root, "src/b.csv", "x\n1\n")
    write(tmp_path, "outside.csv", "x\n1\n")
    found = ds._resolve_paths(["data/a.csv", "b.csv", "../outside.csv", "/etc/passwd", "s3://bucket/x.csv", "missing.csv", "*.csv"],
                              root / "src", root)
    assert found == {root / "data/a.csv", root / "src" / "b.csv"}


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


# -- discover: 로컬 + 코드 ------------------------------------------------------------
def test_discover_builds_one_component_per_directory_and_links_from_root(tmp_path, online):
    root = project(tmp_path)
    out = ds.discover(doc_of(), str(root), log=lambda m: None)
    found = datasets(out)
    assert set(found) == {"data:local/data@", IMDB_REF}                          # package.json / models/config.json 은 데이터가 아니다

    local = found["data:local/data@"]
    assert local["name"] == "data" and [d["name"] for d in local["data"]] == ["data/labels.jsonl", "data/train.csv"]
    train = {p["name"]: p["value"] for p in local["data"][1]["contents"]["properties"]}
    assert train["aibom-cli:file:rows"] == "5" and train["aibom-cli:file:columns"] == "id,text,label" and train["aibom-cli:file:format"] == "csv"
    assert internal(local) == {"size": str(80 + 69), "modality:0": "text", "modality:1": "structured", "availability": "direct-download",
                               "provenance:0": "data", "statistics:0:type": "files", "statistics:0:value": "2",
                               "statistics:1:type": "rows", "statistics:1:value": "8", "statistics:2:type": "columns", "statistics:2:value": "3"}

    hf = found[IMDB_REF]
    assert hf["group"] == "stanfordnlp" and hf["name"] == "imdb" and hf["purl"] == IMDB_REF
    assert hf["data"] == [{"type": "dataset", "name": IMDB, "contents": {"url": "https://huggingface.co/datasets/stanfordnlp/imdb"}}]
    assert hf["evidence"]["occurrences"] == [{"location": "src/train.py"}]
    assert online == [IMDB]

    root_row = next(d for d in out["dependencies"] if d["ref"] == "application:/proj@")
    assert root_row["dependsOn"] == ["data:local/data@", IMDB_REF]
    assert str(tmp_path) not in json.dumps(out)                                   # 절대 경로가 새지 않는다


def test_weak_extensions_count_only_with_evidence(tmp_path, online):
    write(tmp_path, "notes/readme.txt", "hello\n")                                # 홀로 → 아니다
    write(tmp_path, "corpus/a.txt", "a\nb\n")                                     # 같은 디렉터리에 강한 파일 → 데이터
    write(tmp_path, "corpus/b.csv", "x\n1\n")
    write(tmp_path, "cfg/labels.json", '["a", "b"]')                              # 코드가 읽는다 → 데이터
    write(tmp_path, "run.py", 'import pandas as pd\npd.read_json("cfg/labels.json")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {"data:local/corpus@", "data:local/cfg@"}
    assert [d["name"] for d in found["data:local/corpus@"]["data"]] == ["corpus/a.txt", "corpus/b.csv"]


def test_skip_dirs_and_hidden_dirs_are_not_walked(tmp_path, online):
    for d in ("node_modules", ".git", "venv", ".venv", "site-packages", "__pycache__", ".cache"):
        write(tmp_path, f"{d}/x.csv", "a\n1\n")
        write(tmp_path, f"{d}/x.py", 'load_dataset("hidden/one")\n')
    write(tmp_path, "ok/y.csv", "a\n1\n")
    out = ds.discover(doc_of(), str(tmp_path), log=lambda m: None)
    assert set(datasets(out)) == {"data:local/ok@"}


def test_root_level_files_use_the_target_name(tmp_path, online):
    write(tmp_path, "train.csv", "a\n1\n")
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {"data:local/.@"} and found["data:local/.@"]["name"] == tmp_path.name
    assert internal(found["data:local/.@"])["provenance:0"] == "."


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
                              "provenance:0": "https://huggingface.co/datasets/stanfordnlp/imdb",
                              "statistics:0:type": "rows:train", "statistics:0:value": "25000",
                              "statistics:1:type": "rows:test", "statistics:1:value": "25000",
                              "statistics:2:type": "rows:unsupervised", "statistics:2:value": "50000",
                              "statistics:3:type": "features", "statistics:3:value": "2",
                              "statistics:4:type": "configs", "statistics:4:value": "1"}


def test_hub_facts_variants():
    gated = ds.hub_facts("a/b", {"gated": "auto", "cardData": {"license": "apache-2.0", "task_categories": ["image-classification", "audio-classification", "tabular-regression", "weird"],
                                                              "dataset_info": [{"config_name": "x", "download_size": 10, "splits": [{"name": "train", "num_examples": 3}], "features": [{}]},
                                                                               {"config_name": "y", "dataset_size": 5}]}})
    assert gated["availability"] == "registration" and gated["size"] == 15 and gated["modality"] == ["image", "audio", "structured", "other"]
    assert gated["statistics"] == [("rows:x:train", "3"), ("features:x", "1"), ("configs", "2")]
    empty = ds.hub_facts("a/b", {"id": "a/b"})
    assert empty["size"] is None and empty["modality"] == [] and empty["statistics"] == [] and empty["availability"] == "direct-download"
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


# -- regulation: 두 형태 --------------------------------------------------------------
@pytest.fixture
def discovered(tmp_path, online) -> dict:
    return ds.discover(doc_of(), str(project(tmp_path)), log=lambda m: None)


def test_properties_form_moves_facts_to_aibom_dataset_keys(discovered):
    out = apply(copy.deepcopy(discovered), form="properties", log=print)
    hf = datasets(out)[IMDB_REF]
    p = props(hf)
    assert p["aibom:dataset:size"] == "133190302" and p["aibom:dataset:modality:0"] == "text"
    assert p["aibom:dataset:availability"] == "direct-download" and p["aibom:dataset:provenance:0"] == "https://huggingface.co/datasets/stanfordnlp/imdb"
    assert (p["aibom:dataset:statistics:0:type"], p["aibom:dataset:statistics:0:value"]) == ("rows:train", "25000")
    assert not any(k.startswith(INTERNAL_PREFIX) for k in p) and "aibom-internal" not in json.dumps(out)
    assert "size" not in hf["data"][0] and "availability" not in hf["data"][0]["contents"]                  # typed 필드는 건드리지 않는다
    local = datasets(out)["data:local/data@"]
    assert props(local)["aibom:dataset:size"] == "149" and props(local)["aibom:dataset:statistics:2:type"] == "columns"
    assert validate_cdx(out, "1.7", log=print) and validate_cdx(out, "v0.6", log=print)


def test_typed_form_fills_componentdata_fields_on_data0(discovered):
    out = apply(copy.deepcopy(discovered), form="typed", log=print)
    hf = datasets(out)[IMDB_REF]
    entry = hf["data"][0]
    assert entry["size"] == 133190302 and isinstance(entry["size"], int) and entry["modality"] == ["text"]
    assert entry["contents"] == {"url": "https://huggingface.co/datasets/stanfordnlp/imdb", "availability": "direct-download"}
    assert entry["provenance"] == ["https://huggingface.co/datasets/stanfordnlp/imdb"]
    assert entry["statistics"][0] == {"type": "rows:train", "value": "25000"} and len(entry["statistics"]) == 5
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
def test_dataset_regulation_is_idempotent(discovered, form):
    once = apply(copy.deepcopy(discovered), form=form, log=lambda m: None)
    logs: list[str] = []
    assert json.dumps(apply(copy.deepcopy(once), form=form, log=logs.append)) == json.dumps(once) and logs == []


def test_data_component_without_internal_keys_is_untouched():
    comp = {"type": "data", "name": "d", "bom-ref": "d", "properties": [{"name": "cdx:ai:kind", "value": "dataset"}], "data": [{"type": "dataset"}]}
    for form in ("properties", "typed"):
        assert json.dumps(apply({"components": [copy.deepcopy(comp)]}, form=form, log=print)) == json.dumps({"components": [comp]})


# -- 회귀: 확인된 결함 ------------------------------------------------------------------
def test_code_referenced_file_with_unknown_extension_is_dropped_not_crashing(tmp_path, online):
    """pd.read_csv("data/train.dat") 같은 참조가 KeyError 로 스캔을 죽였다. 이제 알리고 버린다; 분석기도 모르는 확장자를 'other' 로 받는다."""
    write(tmp_path, "data/train.dat", "a,b\n1,2\n")
    write(tmp_path, "data/train", "a,b\n1,2\n")
    write(tmp_path, "w.bin", "x")
    write(tmp_path, "d/x.xlsx", "x")
    write(tmp_path, "t.py", 'import pandas as pd, numpy as np\nfrom datasets import load_dataset\n'
                            'pd.read_csv("data/train.dat")\npd.read_csv("data/train")\nnp.load("w.bin")\n'
                            'load_dataset("csv", data_files="d/x.xlsx")\n')
    logs: list[str] = []
    out = ds.discover(doc_of(), str(tmp_path), log=logs.append)
    assert datasets(out) == {}
    assert sorted(m.split(": ", 1)[1] for m in logs if "건너뛴다" in m) == [
        "'d/x.xlsx' 은 아는 데이터 형식이 아니라 건너뛴다", "'data/train' 은 아는 데이터 형식이 아니라 건너뛴다",
        "'data/train.dat' 은 아는 데이터 형식이 아니라 건너뛴다", "'w.bin' 은 아는 데이터 형식이 아니라 건너뛴다"]
    a = ds._analyze_file(tmp_path / "data/train.dat", "data/train.dat", log=print)
    assert a["modality"] == "other" and a["format"] == "dat" and a["sha256"] and "rows" not in a


def test_symlink_to_a_file_outside_the_target_is_skipped(tmp_path, monkeypatch, online):
    """대상 밖을 가리키는 링크가 절대 경로(또는 ../ 경로)를 data[].name 에 흘렸다."""
    outside = write(tmp_path, "elsewhere/outside_secret.csv", "a\n1\n")
    root = tmp_path / "T"
    write(root, "data/train.csv", "a\n1\n2\n")
    (root / "data/link.csv").symlink_to(outside)
    (root / "data/inner.csv").symlink_to(root / "data/train.csv")             # 안을 가리키는 링크는 대상 안의 이름으로 남는다
    for target in (str(root), "T"):
        monkeypatch.chdir(tmp_path)
        logs: list[str] = []
        out = ds.discover(doc_of(), target, log=logs.append)
        local = datasets(out)["data:local/data@"]
        assert [d["name"] for d in local["data"]] == ["data/inner.csv", "data/train.csv"]
        text = json.dumps(out)
        assert "outside_secret" not in text and str(tmp_path) not in text and ".." not in text
        assert any("data/link.csv" in m and "대상 밖" in m for m in logs)


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
        local = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))["data:local/data@"]
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
    write(tmp_path, "data/train.xlsx", "x")
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "t.py", 'load_dataset("my_script.py")\nload_dataset("data/train.xlsx")\nload_dataset("data/train.csv")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {"data:local/data@"}                                  # 경로 인자는 출처 2 로, 파일은 한 번만
    assert [d["name"] for d in found["data:local/data@"]["data"]] == ["data/train.csv"]


def test_windows_style_code_paths_resolve_and_drive_paths_are_rejected(tmp_path, online):
    """cfg\\labels.json 을 글자 그대로 찾아 조용히 잃었다."""
    write(tmp_path, "cfg/labels.json", '["a"]')
    write(tmp_path, "data/train.csv", "a\n1\n")
    write(tmp_path, "t.py", 'import pandas as pd\npd.read_json("cfg\\\\labels.json")\npd.read_csv("data\\\\train.csv")\n'
                            'pd.read_csv("C:\\\\x.csv")\npd.read_csv("C:/x.csv")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert set(found) == {"data:local/cfg@", "data:local/data@"}
    assert [d["name"] for d in found["data:local/cfg@"]["data"]] == ["cfg/labels.json"]
    assert ds._resolve_paths(["C:/x.csv", "C:\\x.csv", "cfg\\labels.json"], tmp_path, tmp_path) == {tmp_path / "cfg/labels.json"}


def test_parent_segments_in_code_paths_do_not_duplicate_a_file(tmp_path, online):
    """src/train.py 의 "../data/train.csv" 가 걷기로 찾은 같은 파일과 따로 세어져 크기·행·파일 수가 두 배였다."""
    write(tmp_path, "data/train.csv", "id,text\n1,a\n2,b\n")
    write(tmp_path, "src/train.py", 'import pandas as pd\npd.read_csv("../data/train.csv")\npd.read_csv("./data/train.csv")\n')
    local = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))["data:local/data@"]
    assert [d["name"] for d in local["data"]] == ["data/train.csv"]
    facts = internal(local)
    assert facts["size"] == "16" and facts["statistics:0:value"] == "1" and facts["statistics:1:value"] == "2"


@pytest.mark.parametrize("task, modality", [
    ("text-to-speech", "audio"), ("text-to-audio", "audio"), ("text-to-video", "video"),
    ("text-classification", "text"), ("text-generation", "text"), ("text-to-image", "text"), ("automatic-speech-recognition", "audio"),
])
def test_specific_text_to_tasks_map_before_the_text_prefix(task, modality):
    assert ds._modality_of_task(task) == modality


def test_well_known_manifests_are_not_promoted_by_a_neighbouring_data_file(tmp_path, online):
    """train.csv 옆의 requirements.txt · README.txt · package.json 이 데이터 파일로 잡혔다. 코드가 직접 읽으면 여전히 데이터다."""
    write(tmp_path, "requirements.txt", "numpy\n")
    write(tmp_path, "README.txt", "hello\n")
    write(tmp_path, "package.json", '{"name": "x"}')
    write(tmp_path, "train.csv", "a\n1\n")
    write(tmp_path, "d/a.csv", "x\n1\n")
    write(tmp_path, "d/README.txt", "docs\n")
    write(tmp_path, "d/LICENSE.txt", "MIT\n")
    write(tmp_path, "d/model_config.json", "{}")
    write(tmp_path, "d/notes.txt", "a\nb\n")
    write(tmp_path, "e/labels.json", '["a"]')
    write(tmp_path, "e/tsconfig.json", "{}")
    write(tmp_path, "e/run.py", 'import pandas as pd\npd.read_json("e/tsconfig.json")\n')
    found = datasets(ds.discover(doc_of(), str(tmp_path), log=lambda m: None))
    assert [d["name"] for d in found["data:local/.@"]["data"]] == ["train.csv"]
    assert [d["name"] for d in found["data:local/d@"]["data"]] == ["d/a.csv", "d/notes.txt"]
    assert [d["name"] for d in found["data:local/e@"]["data"]] == ["e/tsconfig.json"]          # 코드가 읽는다; labels.json 은 홀로 약한 파일


# -- 실제 허브 (하나뿐) ------------------------------------------------------------------
@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_live_hub_returns_size_and_modality_for_imdb():
    info = ds.fetch_dataset_info(IMDB, log=print)
    assert info and info["id"] == IMDB
    facts = ds.hub_facts(IMDB, info)
    assert facts["size"] and facts["size"] > 0 and facts["modality"] == ["text"] and facts["availability"] == "direct-download"
