"""tests/fixtures/mixed 를 실제 syft·cdxgen 으로 스캔해 병합 결과를 확인한다.
두 도구가 없으면 건너뛴다. owasp 보강은 네트워크가 필요해 skip_reason 을 패치해=1 로 뺀다 — regulation 은 cdxgen 의
cdx:ai:runtime / cdx:ai:contextWindow 로 technicalRequirements 와 inputs[0].maxSize 를, models/config.json 에서 직접 읽은
하이퍼파라미터로 hyperparameters 를 채운다 (파라미터 수는 가중치 파일이 없어 비어 있다).
데이터셋의 허브 조회도 네트워크가 필요해, 닿는 것으로 치고 stanfordnlp/imdb 만 기록해 둔 응답으로 답한다 (bookcorpus 는 조회 실패)."""
import json
import shutil
from pathlib import Path

import pytest

import aibom_cli.dataset as ds
from aibom_cli.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "mixed"
IMDB_FIXTURE = Path(__file__).parent / "fixtures" / "bom" / "hf_dataset_stanfordnlp_imdb.json"
IMDB_ID = "stanfordnlp/imdb"
IMDB_REF = "pkg:huggingface/datasets/stanfordnlp/imdb"
LOCAL_REF = "data:local/data@"
BOOK_REF = "data:datasets/bookcorpus@"


pytestmark = pytest.mark.skipif(
    not (shutil.which("syft") and shutil.which("cdxgen")),
    reason="syft 와 cdxgen 이 모두 있어야 한다",
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("aibom_cli.enrich.skip_reason", lambda: "테스트")                                # 보강은 네트워크가 필요해 강제 생략
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    imdb = json.loads(IMDB_FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: json.loads(json.dumps(imdb)) if hf_id == "stanfordnlp/imdb" else None)
    fixtures = IMDB_FIXTURE.parent
    monkeypatch.setattr(ds, "fetch_dataset_size", lambda hf_id, log=print: json.loads((fixtures / "hf_size_stanfordnlp_imdb.json").read_text()) if hf_id == IMDB_ID else None)
    monkeypatch.setattr(ds, "fetch_dataset_statistics", lambda hf_id, config, split, log=print:
                        json.loads((fixtures / f"hf_statistics_stanfordnlp_imdb_{config}_{split}.json").read_text()) if hf_id == IMDB_ID else None)


def scan(target, out: Path, *flags) -> dict:
    assert main(["scan", str(target), "-o", str(out), *flags]) == 0
    return json.loads(out.read_text())


def without_run_specifics(doc: dict) -> str:
    doc = json.loads(json.dumps(doc))
    doc.pop("serialNumber")
    doc["metadata"].pop("timestamp")
    return json.dumps(doc, ensure_ascii=False, sort_keys=True)


def test_mixed_fixture_yields_all_three_domains(tmp_path, monkeypatch):
    cdx = tmp_path / "bom.cdx.json"
    assert main(["scan", str(FIXTURE), "-o", str(cdx)]) == 0                       # 기본 --form properties
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 0

    doc = json.loads(cdx.read_text())
    by_type = {}
    for c in doc["components"]:
        by_type.setdefault(c["type"], set()).add(c["name"])

    assert {"numpy", "requests"} <= by_type["library"]                      # syft → 소프트웨어
    assert "bert-base-uncased" in by_type["machine-learning-model"]         # cdxgen → HF 모델
    assert "llama3.2:1b" in by_type["machine-learning-model"]               # cdxgen → Modelfile
    assert by_type["data"] == {"bookcorpus", "imdb", "data"}                # cdxgen(README) · 코드의 load_dataset · 로컬 data/
    assert "fixture" not in by_type.get("application", set())               # package.json 은 -t ai 가 막는다

    # 스캔 머신 경로가 어디에도 새지 않는다 (파일 컴포넌트 이름, 데이터 파일 경로, evidence)
    text = cdx.read_text()
    assert str(FIXTURE) not in text and str(FIXTURE.resolve()) not in text and "aibom-internal" not in text

    datasets = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}
    assert set(datasets) == {BOOK_REF, IMDB_REF, LOCAL_REF}
    local = datasets[LOCAL_REF]
    assert [d["name"] for d in local["data"]] == ["data/labels.jsonl", "data/train.csv"]      # 디렉터리 하나에 파일 둘, 정렬 순
    props = {p["name"]: p["value"] for p in local["properties"]}
    assert props["aibom:dataset:size"] == "149" and props["aibom:dataset:modality:1"] == "structured" and props["aibom:dataset:provenance:0"] == "data"
    assert {p["name"]: p["value"] for p in local["data"][1]["contents"]["properties"]}["aibom-cli:file:columns"] == "id,text,label"
    imdb = datasets[IMDB_REF]
    props = {p["name"]: p["value"] for p in imdb["properties"]}
    assert props["aibom:dataset:size"] == "133190302" and props["aibom:dataset:modality:0"] == "text" and props["aibom:dataset:availability"] == "direct-download"
    assert imdb["licenses"] == [{"license": {"name": "other"}}] and imdb["evidence"]["occurrences"] == [{"location": "src/train.py"}]
    assert "properties" in datasets[BOOK_REF] and not any(p["name"].startswith("aibom:") for p in datasets[BOOK_REF]["properties"])   # 조회 실패 → cdxgen 값만
    # 관계: 루트 → 로컬·코드 데이터셋, 모델 → README 데이터셋 (cdxgen 그대로), modelCard 링크도 살아 있다
    deps = {d["ref"]: set(d["dependsOn"]) for d in doc["dependencies"]}
    assert {LOCAL_REF, IMDB_REF} <= deps["application:/mixed@"] and BOOK_REF not in deps["application:/mixed@"]
    assert deps["pkg:huggingface/google-bert/bert-base-uncased"] == {BOOK_REF}

    bert = next(c for c in doc["components"] if c["name"] == "bert-base-uncased")
    assert bert["modelCard"]["modelParameters"]["datasets"][0]["ref"] == BOOK_REF
    card = {p["name"]: p["value"] for p in bert["modelCard"]["properties"]}
    assert card["aibom:model:technicalRequirements:0"] == "transformers" and card["aibom:model:inputs:0:maxSize"] == "512"
    assert (card["aibom:model:hyperparameters:0:name"], card["aibom:model:hyperparameters:0:value"]) == ("block_count", "12")
    assert card["aibom:model:hyperparameters:5:value"] == "30522" and "aibom:model:parameterCount" not in card
    assert "cdx:ai:runtime" not in {p["name"] for p in bert["properties"]}       # 승격한 원본은 소비된다

    refs = {c["bom-ref"] for c in doc["components"]}
    assert len(refs) == len(doc["components"])                              # bom-ref 중복 없음
    assert {t["name"] for t in doc["metadata"]["tools"]["components"]} >= {"syft", "cdxgen", "aibom-cli"}

    assert doc["metadata"]["component"] == {"type": "application", "name": "mixed", "bom-ref": "application:/mixed@"}


def test_typed_form_scan_validates_against_v06_only(tmp_path):
    cdx = tmp_path / "typed.cdx.json"
    doc = scan(FIXTURE, cdx, "--form", "typed")
    assert main(["validate", str(cdx), "--spec", "v0.6"]) == 0
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 3                      # maxSize·technicalRequirements·componentData 필드는 공식 1.7 에 없다
    bert = next(c for c in doc["components"] if c["name"] == "bert-base-uncased")
    assert bert["modelCard"]["considerations"]["technicalRequirements"] == ["transformers"]
    assert bert["modelCard"]["modelParameters"]["inputs"][0]["maxSize"] == "512"
    assert bert["modelCard"]["modelParameters"]["hyperparameters"] == [
        {"name": n, "value": v} for n, v in [("block_count", "12"), ("context_length", "512"), ("embedding_length", "768"),
                                             ("feed_forward_length", "3072"), ("attention_head_count", "12"), ("vocab_size", "30522")]]
    assert not any(p["name"].startswith("aibom:model:") for p in bert["modelCard"].get("properties", []))
    text = cdx.read_text()
    assert "aibom:dataset:" not in text and "aibom-internal" not in text and str(FIXTURE) not in text
    datasets = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}
    imdb, local = datasets[IMDB_REF]["data"][0], datasets[LOCAL_REF]["data"][0]
    assert imdb["size"] == 133190302 and imdb["modality"] == ["text"] and imdb["contents"]["availability"] == "direct-download"
    assert imdb["statistics"][0] == {"type": "train:label:n_unique", "value": "2"} and imdb["provenance"] == ["https://huggingface.co/datasets/stanfordnlp/imdb"]
    assert local["size"] == 149 and local["modality"] == ["text", "structured"] and local["provenance"] == ["data"]
    assert "size" not in datasets[LOCAL_REF]["data"][1] and "size" not in datasets[BOOK_REF]["data"][0]


def test_scanning_twice_is_byte_identical_apart_from_serial_and_timestamp(tmp_path):
    first = scan(FIXTURE, tmp_path / "1.json")
    second = scan(FIXTURE, tmp_path / "2.json")
    assert first["serialNumber"] != second["serialNumber"]
    assert without_run_specifics(first) == without_run_specifics(second)


def test_directory_without_datasets_gets_no_data_components(tmp_path, monkeypatch):
    """데이터 파일도 데이터셋 참조도 없는 디렉터리: 데이터 컴포넌트가 없고 허브를 보지 않는다 (이전 버전과 같은 문서)."""
    monkeypatch.setattr(ds, "hf_reachable", lambda: pytest.fail("조회할 것이 없는데 네트워크를 봤다"))
    target = tmp_path / "plain"
    target.mkdir()
    for name in ("requirements.txt", "package.json", "Modelfile"):
        (target / name).write_text((FIXTURE / name).read_text(encoding="utf-8"), encoding="utf-8")
    doc = scan(target, tmp_path / "plain.json")
    assert not any(c["type"] == "data" for c in doc["components"])
    assert {c["name"] for c in doc["components"]} == {"numpy", "requests", "/requirements.txt", "Modelfile", "llama3.2:1b"}
    assert doc["dependencies"][0]["ref"] == "application:/plain@" and not any(r.startswith("data:") for r in doc["dependencies"][0]["dependsOn"])


def test_image_target_with_empty_cdxgen_result_warns(tmp_path, monkeypatch, capsys):
    """이미지 입력에서 cdxgen 이 빈 결과를 내면(데몬 없음) 경고가 남아야 한다. 디렉터리 입력에서는 조용하다."""
    import aibom_cli.cli as cli
    empty = {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": []}
    monkeypatch.setattr(cli, "run_syft", lambda target, workdir: {"bomFormat": "CycloneDX", "specVersion": "1.7",
                        "components": [{"bom-ref": "a", "type": "library", "name": "a", "version": "1", "purl": "pkg:pypi/a@1"}]})
    monkeypatch.setattr(cli, "run_cdxgen", lambda target, workdir: dict(empty))
    assert cli.main(["scan", "some-image:latest", "-o", str(tmp_path / "i.json")]) == 0
    assert "데몬" in capsys.readouterr().err
    assert cli.main(["scan", str(FIXTURE), "-o", str(tmp_path / "d.json")]) == 0
    assert "데몬" not in capsys.readouterr().err
