"""tests/data/project 를 실제 syft·cdxgen 으로 스캔해 병합 결과를 확인한다.
두 도구가 없으면 건너뛴다. owasp 보강은 네트워크와 클론이 필요해, 실제로 돌려 녹화해 둔 tests/data/owasp/ 의 출력으로 바꿔 끼운다
(허브 모델은 bert-base-uncased 하나다). 보강 로직의 세부는 test_enrich 가 본다.
모델 네 개가 서로 다른 경로로 들어온다: 소스의 from_pretrained (허브 참조, 파일 없음) · 받아 둔 HF 모델 디렉터리 ·
gguf 파일 하나 · LoRA 어댑터. 규제 필드는 cdxgen 프로퍼티와 우리가 읽은 config.json·gguf·safetensors 헤더에서 온다.
데이터셋과 허브 모델 카드의 조회도 네트워크가 필요해, 닿는 것으로 치고 tests/data/hf_api/ 에 기록해 둔 실제 응답으로 답한다.
imdb 는 세 엔드포인트가 다 있고, bookcorpus 는 /api/datasets 만 있다 (실제 허브도 /size 는 501, /statistics 는 404).
기록이 없으면 None 을 돌려준다 — 허브가 답하지 않은 것과 같다."""
import io
import json
import re
import shutil
import tarfile
from pathlib import Path

import pytest

import aibom_cli.dataset as ds
from aibom_cli.runners._proc import RunnerError
from aibom_cli.cli import main

FIXTURE = Path(__file__).parent / "data" / "project"
HF_API = Path(__file__).parent / "data" / "hf_api"
HUB_REDIRECTS = {"bookcorpus": "bookcorpus/bookcorpus", "wikipedia": "legacy-datasets/wikipedia"}      # 허브가 307 로 정식 id 에 돌려보내는 옛 이름
IMDB_REF = "pkg:huggingface/datasets/stanfordnlp/imdb"
LOCAL_REF = "data:local/data@"
LOCAL_SIZE = 80 + 1644 + 74 + 73 + 71 + 76               # train.csv, audio/x.wav, 세 png, images/metadata.csv (주석도 크기에 든다)
BOOK_REF = "pkg:huggingface/datasets/bookcorpus/bookcorpus"   # 모델 카드의 bookcorpus 가 정식 id 로 바뀐다
WIKI_REF = "pkg:huggingface/datasets/legacy-datasets/wikipedia"   # bert 의 허브 모델 카드가 적은 wikipedia 의 정식 id
BERT_REF = "pkg:huggingface/google-bert/bert-base-uncased"
OUT = Path(__file__).parents[1] / "out" / "test_scan"      # 스캔 결과를 남겨 둔다. .gitignore 의 out/ 라 올라가지 않는다


def out_file(name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / name


pytestmark = pytest.mark.skipif(
    not (shutil.which("syft") and shutil.which("cdxgen")),
    reason="syft 와 cdxgen 이 모두 있어야 한다",
)


def recorded(kind: str, hf_id: str, *rest: str) -> dict | None:
    """tests/data/hf_api/hf_<kind>_<owner>_<name>[_<config>_<split>].json. 없으면 None (허브가 답하지 않은 것)."""
    hf_id = HUB_REDIRECTS.get(hf_id, hf_id)
    path = HF_API / ("_".join(["hf", kind, hf_id.replace("/", "_"), *rest]) + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


OWASP = Path(__file__).parent / "data" / "owasp"


def recorded_owasp(hf_id: str, workdir) -> dict:
    """실제 aibom-generator 를 돌려 녹화한 출력. 없는 모델이면 도구가 실패한 것처럼 RunnerError."""
    path = OWASP / (hf_id.rsplit("/", 1)[-1] + ".cdx.json")
    if not path.exists():
        raise RunnerError(f"no recorded aibom-generator output for {hf_id}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("aibom_cli.enrich.skip_reason", lambda: None)                                     # 보강은 녹화본으로 돌린다
    monkeypatch.setattr("aibom_cli.enrich.run_aibom_generator", recorded_owasp)
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_model_info", lambda hf_id, log=print: recorded("model", hf_id))
    monkeypatch.setattr(ds, "fetch_dataset_info", lambda hf_id, log=print: recorded("dataset", hf_id))
    monkeypatch.setattr(ds, "fetch_dataset_size", lambda hf_id, log=print: recorded("size", hf_id))
    monkeypatch.setattr(ds, "fetch_dataset_statistics",
                        lambda hf_id, config, split, log=print: recorded("statistics", hf_id, config, split))


def scan(target, out: Path, *flags) -> dict:
    assert main(["scan", str(target), "-o", str(out), *flags]) == 0
    return json.loads(out.read_text())


def without_run_specifics(doc: dict) -> str:
    doc = json.loads(json.dumps(doc))
    doc.pop("serialNumber")
    doc["metadata"].pop("timestamp")
    return json.dumps(doc, ensure_ascii=False, sort_keys=True)


def test_project_fixture_yields_all_three_domains(tmp_path, monkeypatch):
    cdx = out_file("properties.cdx.json")
    assert main(["scan", str(FIXTURE), "-o", str(cdx), "--data", str(FIXTURE / "data")]) == 0   # 기본 --spec properties
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 0

    doc = json.loads(cdx.read_text())
    by_type = {}
    for c in doc["components"]:
        by_type.setdefault(c["type"], set()).add(c["name"])

    assert {"numpy", "requests"} <= by_type["library"]                      # syft → 소프트웨어
    assert by_type["machine-learning-model"] == {"bert-base-uncased", "llama3.2:1b", "llama", "tiny-random-gpt2",
                                                 "tiny-gpt2-lora"}
    #   src/train.py 의 from_pretrained · Modelfile · models/stories260K.gguf · models/tiny-random-gpt2/ · 어댑터
    assert by_type["data"] == {"bookcorpus", "imdb", "data", "wikipedia"}   # 모델 카드 · 코드의 load_dataset · 로컬 data/ · 허브 모델 카드
    assert {s["name"] for s in doc["services"]} == {"ollama-service", "google-bert-service"}

    # 스캔 머신 경로가 어디에도 새지 않는다 (파일 컴포넌트 이름, 데이터 파일 경로, evidence)
    text = cdx.read_text()
    assert str(FIXTURE) not in text and str(FIXTURE.resolve()) not in text and "aibom-internal" not in text

    datasets = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}
    assert set(datasets) == {BOOK_REF, IMDB_REF, LOCAL_REF, WIKI_REF}
    local = datasets[LOCAL_REF]
    # 표 파일은 파일마다, 매체는 묶어서: audio/x.wav 하나는 그 이름, images/train/{cat,dog}/*.png 는 클래스 폴더라 train 하나로. metadata.csv 는 주석
    assert [d["name"] for d in local["data"]] == ["data/audio/x.wav", "data/images/train/*.png", "data/train.csv"]
    props = {p["name"]: p["value"] for p in local["properties"]}
    assert props["aibom:dataset:size"] == str(LOCAL_SIZE)
    assert [props[f"aibom:dataset:modality:{i}"] for i in range(3)] == ["audio", "image", "structured"]
    assert not any(k.startswith("aibom:dataset:provenance") or k == "aibom:dataset:availability" for k in props)
    assert all(set(d) == {"type", "name"} for d in local["data"])                                                # 원소는 종류와 이름뿐
    stats = {props[k]: props[k.replace(":type", ":value")] for k in props if k.startswith("aibom:dataset:statistics") and k.endswith(":type")}
    assert stats["images/train:label:frequencies"] == "cat=2,dog=1" and stats["images/train:image:width:max"] == "4"     # 클래스 폴더 라벨, PNG 헤더 너비
    assert stats["images/train:image:height:min"] == "2" and stats["images/train:image:height:max"] == "4"               # 높이도 헤더에서
    assert stats["images:label:frequencies"] == "cat=2,dog=1" and stats["audio:audio:duration:min"] == "0.1"               # metadata.csv 의 label, WAV 길이
    imdb = datasets[IMDB_REF]
    props = {p["name"]: p["value"] for p in imdb["properties"]}
    assert props["aibom:dataset:size"] == "133190302" and props["aibom:dataset:modality:0"] == "text" and props["aibom:dataset:availability"] == "direct-download"
    assert imdb["licenses"] == [{"license": {"name": "other"}}] and imdb["evidence"]["occurrences"] == [{"location": "src/train.py"}]
    # bookcorpus: 저장소 정보는 받고 datasets-server 는 실패 → 크기는 모델 카드의 dataset_info 에서, 통계는 없다
    book = datasets[BOOK_REF]
    props = {p["name"]: p["value"] for p in book["properties"]}
    assert (book["group"], book["name"], book["version"][:8]) == ("bookcorpus", "bookcorpus", "d917559b")
    assert props["aibom:dataset:size"] == "4853859824" and props["aibom:dataset:availability"] == "direct-download"
    assert props["aibom:dataset:provenance:0"] == "https://huggingface.co/datasets/bookcorpus/bookcorpus"
    assert props["aibom:dataset:modality:0"] == "text"                          # modality 태그가 없어 task_categories 로
    assert not any(k.startswith("aibom:dataset:statistics") for k in props)
    assert book["data"][0]["contents"]["url"] == "https://huggingface.co/datasets/bookcorpus/bookcorpus"   # cdxgen 의 datasets/datasets/ 가 고쳐진다
    # wikipedia: bert 의 허브 모델 카드(datasets)가 적은 것. 옛 이름이라 허브가 legacy-datasets/wikipedia 로 돌려준다
    wiki = datasets[WIKI_REF]
    props = {p["name"]: p["value"] for p in wiki["properties"]}
    assert (wiki["group"], wiki["name"]) == ("legacy-datasets", "wikipedia") and props["aibom:dataset:availability"] == "direct-download"
    assert props["aibom:dataset:provenance:0"] == "https://huggingface.co/datasets/legacy-datasets/wikipedia"
    # 관계: 루트 → 로컬·코드 데이터셋, 모델 → README 데이터셋 (cdxgen 그대로), 허브 모델 → 그 카드의 데이터셋. modelCard 링크도 살아 있다
    deps = {d["ref"]: set(d["dependsOn"]) for d in doc["dependencies"]}
    assert {LOCAL_REF, IMDB_REF} <= deps["application:/project@"] and not {BOOK_REF, WIKI_REF} & deps["application:/project@"]
    assert deps["pkg:generic/huggingface/tiny-random-gpt2"] == {BOOK_REF}       # 모델 카드가 적은 데이터셋
    assert deps[BERT_REF] == {BOOK_REF, WIKI_REF}                                # 허브 모델 카드가 적은 데이터셋

    # 받아 둔 HF 모델 디렉터리: config.json 의 하이퍼파라미터 6개 + model.safetensors 헤더의 파라미터 수
    gpt2 = next(c for c in doc["components"] if c["name"] == "tiny-random-gpt2")
    assert gpt2["modelCard"]["modelParameters"]["datasets"][0]["ref"] == BOOK_REF
    card = {p["name"]: p["value"] for p in gpt2["modelCard"]["properties"]}
    assert (card["aibom:model:hyperparameters:0:name"], card["aibom:model:hyperparameters:0:value"]) == ("block_count", "5")
    assert card["aibom:model:hyperparameters:5:value"] == "1000"                # vocab_size
    assert card["aibom:model:parameterCount"] == "111968"                       # model.safetensors 헤더의 shape 합
    assert card["aibom:model:technicalRequirements:0"] == "transformers"
    assert "cdx:ai:runtime" not in {p["name"] for p in gpt2["properties"]}       # 승격한 원본은 소비된다
    assert [a["name"] for a in gpt2["pedigree"]["ancestors"]] == ["gpt2"]        # 카드의 base_model

    # gguf: 헤더의 하이퍼파라미터 8개와 텐서에서 센 파라미터 수 (stories260K 에는 general.parameter_count 가 없다)
    gguf = next(c for c in doc["components"] if c["name"] == "llama")
    gguf_card = {p["name"]: p["value"] for p in gguf["modelCard"]["properties"]}
    assert (gguf_card["aibom:model:hyperparameters:0:name"], gguf_card["aibom:model:hyperparameters:0:value"]) == ("block_count", "5")
    assert gguf_card["aibom:model:hyperparameters:7:name"] == "vocab_size" and "aibom:model:hyperparameters:8:name" not in gguf_card
    assert gguf_card["aibom:model:parameterCount"] == "292800" and gguf_card["aibom:model:technicalRequirements:0"] == "llama.cpp"

    # 소스의 from_pretrained: 로컬 파일이 없으니 하이퍼파라미터·파라미터 수·maxSize 는 aibom-generator 가 허브에서 받은 값(녹화본)에서 온다.
    # technicalRequirements 는 cdxgen 이 소스의 import 에서 읽은 것과 aibom-generator 의 runtimeRequirement 를 합친다.
    bert = next(c for c in doc["components"] if c["name"] == "bert-base-uncased")
    assert bert["purl"] == "pkg:huggingface/google-bert/bert-base-uncased"
    bert_card = {p["name"]: p["value"] for p in bert["modelCard"]["properties"]}
    recorded = {p["name"]: p["value"] for p in recorded_owasp("google-bert/bert-base-uncased", None)["components"][0]["modelCard"]["properties"]}
    assert bert_card["aibom:model:parameterCount"] == recorded["safetensors_total_parameters"]
    assert bert_card["aibom:model:inputs:0:maxSize"] == recorded["genai:aibom:modelcard:contextLength"]
    assert bert_card["aibom:model:hyperparameters:0:name"] and "aibom:model:technicalRequirements:0" in bert_card
    assert "genai:aibom:trainingDataAvailable" in bert_card and "safetensors_total_parameters" not in bert_card   # 승격한 원본은 지우고 나머지는 남긴다
    # 모델 카드의 데이터셋은 D-BOM 이 ref 로 먼저 적어서, aibom-generator 의 이름뿐인 목록은 들어오지 않는다
    assert bert["modelCard"]["modelParameters"]["datasets"] == [{"ref": BOOK_REF}, {"ref": WIKI_REF}]

    # adapter_config.json: 베이스 모델 계보만 나온다 (config.json 이 없으니 하이퍼파라미터는 없다)
    adapter = next(c for c in doc["components"] if c["name"] == "tiny-gpt2-lora")
    assert [a["name"] for a in adapter["pedigree"]["ancestors"]] == ["tiny-random-gpt2"]
    assert "modelCard" not in adapter or "properties" not in adapter["modelCard"]

    refs = {c["bom-ref"] for c in doc["components"]}
    assert len(refs) == len(doc["components"])                              # bom-ref 중복 없음
    assert {t["name"] for t in doc["metadata"]["tools"]["components"]} >= {"syft", "cdxgen", "aibom-cli"}

    assert doc["metadata"]["component"] == {"type": "application", "name": "project", "bom-ref": "application:/project@"}


def test_spec_v06_scan_validates_against_v06_only(tmp_path, capsys):
    cdx = out_file("typed.cdx.json")
    doc = scan(FIXTURE, cdx, "--spec", "v0.6", "--data", str(FIXTURE / "data"))
    # 첫 줄에 형식과 입력, 그 뒤 단계마다 한 줄. 모듈의 항목별 로그([dataset] 등)와 도구 명령은 찍지 않는다
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == f"[aibom-cli] Generating AI-BOM v0.6 (CycloneDX) for {FIXTURE}, data from {FIXTURE / 'data'}"
    assert [line.split(" .")[0] for line in lines[1:-1]] == [
        "[aibom-cli] Generating S-BOM (syft)", "[aibom-cli] Generating M-BOM (cdxgen)", "[aibom-cli] Generating D-BOM",
        "[aibom-cli] Enriching M-BOM (aibom-generator)", "[aibom-cli] Adding regulation fields"]
    assert lines[1].endswith(" 4 packages, 1 file") and lines[2].endswith(" 5 models, 2 files")   # cdxgen 의 데이터셋 참조는 D-BOM 에서 센다
    assert lines[3].endswith(" 4 datasets") and lines[4].endswith(" 1 hub model")
    assert lines[5].endswith(" 34 of 44 filled (models 12/20, datasets 22/24)")      # 모델 5개 × 4, 허브 데이터셋 3개 × 7 + 로컬 1개 × 3
    # 마지막 줄은 다 만든 BOM 을 다시 센 것 — 묶음을 더하면 전체와 같다
    total, groups, deps = re.fullmatch(rf"\[aibom-cli\] Wrote {re.escape(str(cdx))} \((\d+) components: (.+); (\d+) dependencies\)", lines[-1]).groups()
    assert groups == "4 packages, 5 models, 4 datasets, 3 files"
    assert int(total) == len(doc["components"]) == sum(int(g.split()[0]) for g in groups.split(", "))
    assert int(deps) == len(doc["dependencies"])
    assert main(["validate", str(cdx), "--spec", "v0.6"]) == 0
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 3                      # maxSize·technicalRequirements·componentData 필드는 공식 1.7 에 없다
    gpt2 = next(c for c in doc["components"] if c["name"] == "tiny-random-gpt2")
    assert gpt2["modelCard"]["considerations"]["technicalRequirements"] == ["transformers"]
    assert gpt2["modelCard"]["modelParameters"]["parameterCount"] == 111968
    assert gpt2["modelCard"]["modelParameters"]["hyperparameters"] == [
        {"name": n, "value": v} for n, v in [("block_count", "5"), ("context_length", "512"), ("embedding_length", "32"),
                                             ("feed_forward_length", "37"), ("attention_head_count", "4"), ("vocab_size", "1000")]]
    assert not any(p["name"].startswith("aibom:model:") for p in gpt2["modelCard"].get("properties", []))
    text = cdx.read_text()
    assert "aibom:dataset:" not in text and "aibom-internal" not in text and str(FIXTURE) not in text
    datasets = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}
    imdb, local = datasets[IMDB_REF]["data"][0], datasets[LOCAL_REF]["data"][0]
    assert imdb["size"] == 133190302 and imdb["modality"] == ["text"] and imdb["contents"]["availability"] == "direct-download"
    assert imdb["statistics"][:2] == [{"type": "train:label:nan_count", "value": "0"}, {"type": "train:label:n_unique", "value": "2"}]
    assert imdb["provenance"] == ["https://huggingface.co/datasets/stanfordnlp/imdb"]
    assert local["size"] == LOCAL_SIZE and local["modality"] == ["audio", "image", "structured"]
    assert "provenance" not in local and "availability" not in local.get("contents", {})       # 로컬은 셋만 채운다
    assert "size" not in datasets[LOCAL_REF]["data"][1]                          # 디렉터리 값은 data[0] 에만
    assert datasets[BOOK_REF]["data"][0]["size"] == 4853859824 and "statistics" not in datasets[BOOK_REF]["data"][0]


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
    for name in ("requirements.txt", "Modelfile"):
        (target / name).write_text((FIXTURE / name).read_text(encoding="utf-8"), encoding="utf-8")
    doc = scan(target, tmp_path / "plain.json")
    assert not any(c["type"] == "data" for c in doc["components"])
    assert {c["name"] for c in doc["components"]} == {"numpy", "requests", "datasets", "transformers",
                                                      "/requirements.txt", "Modelfile", "llama3.2:1b"}
    assert doc["dependencies"][0]["ref"] == "application:/plain@" and not any(r.startswith("data:") for r in doc["dependencies"][0]["dependsOn"])


def test_an_image_target_is_unpacked_and_the_unpacked_directory_is_scanned(tmp_path, monkeypatch, capsys):
    """이미지는 syft 만 그대로 읽고, cdxgen 은 이미지를 푼 디렉터리를 본다. 이름이면 먼저 받는다. 임시 디렉터리는 끝나면 지운다."""
    import aibom_cli.cli as cli
    seen: dict = {}
    def mkdtemp(prefix):
        (tmp_path / "work").mkdir(exist_ok=True)
        return str(tmp_path / "work")
    monkeypatch.setattr(cli.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(cli, "run_syft", lambda target, workdir: seen.setdefault("syft", target) and {
        "bomFormat": "CycloneDX", "specVersion": "1.7",
        "components": [{"bom-ref": "a", "type": "library", "name": "a", "version": "1", "purl": "pkg:pypi/a@1"}]})
    monkeypatch.setattr(cli, "run_cdxgen", lambda target, workdir: seen.setdefault("cdxgen", (target, Path(target).is_dir())) and {
        "bomFormat": "CycloneDX", "specVersion": "1.7", "components": []})
    monkeypatch.setattr(cli, "pull_image", lambda ref, workdir: seen.setdefault("pull", ref) and (workdir / "image.tar", "crane"))

    def extract(tar, rootfs):
        rootfs.mkdir()
        seen["extract"] = tar
        return 2, "some:tag"
    monkeypatch.setattr(cli, "extract_image", extract)

    out = tmp_path / "i.json"
    assert cli.main(["scan", "some-image:latest", "-o", str(out)]) == 0
    assert seen["syft"] == "some-image:latest" and seen["pull"] == "some-image:latest"
    assert seen["extract"] == tmp_path / "work" / "image.tar" and seen["cdxgen"] == (str(tmp_path / "work" / "rootfs"), True)
    lines = capsys.readouterr().err.splitlines()
    assert [line.split(" .")[0] for line in lines[1:4]] == ["[aibom-cli] Generating S-BOM (syft)", "[aibom-cli] Pulling image (crane)", "[aibom-cli] Unpacking image"]
    assert lines[2].endswith(" done") and lines[3].endswith(" 2 layers")
    doc = json.loads(out.read_text())
    assert (doc["metadata"]["component"]["type"], doc["metadata"]["component"]["name"]) == ("container", "some:tag")
    assert not (tmp_path / "work").exists()                                    # 푼 디렉터리째 지운다

    seen.clear()
    tar = tmp_path / "img.tar"
    tar.write_bytes(b"")
    assert cli.main(["scan", str(tar), "-o", str(out)]) == 0
    assert "pull" not in seen and seen["extract"] == tar                        # .tar 는 받지 않고 바로 푼다
    assert "Pulling image" not in capsys.readouterr().err

    seen.clear()
    assert cli.main(["scan", str(FIXTURE), "-o", str(out)]) == 0                # 디렉터리는 그대로
    assert "extract" not in seen and seen["cdxgen"] == (str(FIXTURE), True)


def test_an_image_that_cannot_be_unpacked_skips_the_m_bom_and_exits_2(tmp_path, monkeypatch, capsys):
    import aibom_cli.cli as cli
    from aibom_cli.runners._proc import RunnerError
    monkeypatch.setattr(cli, "run_syft", lambda target, workdir: {"bomFormat": "CycloneDX", "specVersion": "1.7",
        "components": [{"bom-ref": "a", "type": "library", "name": "a", "version": "1", "purl": "pkg:pypi/a@1"}]})
    monkeypatch.setattr(cli, "run_cdxgen", lambda target, workdir: pytest.fail("이미지를 못 풀었는데 cdxgen 을 돌렸다"))
    monkeypatch.setattr(cli, "pull_image", lambda ref, workdir: (_ for _ in ()).throw(RunnerError("could not fetch some-image:latest\ndocker: daemon down")))
    out = tmp_path / "i.json"
    assert cli.main(["scan", "some-image:latest", "-o", str(out)]) == 2
    lines = capsys.readouterr().err.splitlines()
    stages = {line.split(" .")[0]: line.rsplit(". ", 1)[-1] for line in lines if " ..." in line}
    assert stages["[aibom-cli] Pulling image"] == "failed: could not fetch some-image:latest"
    assert "[aibom-cli]   docker: daemon down" in lines
    assert stages["[aibom-cli] Generating M-BOM (cdxgen)"] == "skipped: image not unpacked"
    assert lines[-1] == "[aibom-cli] error: pulling image failed, so the BOM is incomplete"
    assert json.loads(out.read_text())["components"][0]["name"] == "a"      # S-BOM 은 그래도 쓴다


def test_an_image_tar_yields_the_models_inside_it(tmp_path):
    """픽스처 프로젝트를 /app 에 담은 docker-save 모양의 tar: 디렉터리 스캔과 같은 모델·데이터셋이 나오고 경로는 이미지 안 경로다."""
    from test_image import docker_tar
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        t.add(FIXTURE, arcname="app")
    tar = docker_tar(tmp_path / "aiapp.tar", [buf.getvalue()], tag="aiapp:test")
    doc = scan(tar, out_file("image.cdx.json"))
    assert main(["validate", str(out_file("image.cdx.json")), "--spec", "1.7"]) == 0
    assert (doc["metadata"]["component"]["type"], doc["metadata"]["component"]["name"]) == ("container", "aiapp:test")
    assert {c["name"] for c in doc["components"] if c["type"] == "machine-learning-model"} == {
        "bert-base-uncased", "llama3.2:1b", "llama", "tiny-random-gpt2", "tiny-gpt2-lora"}
    assert {c["bom-ref"] for c in doc["components"] if c["type"] == "data"} == {BOOK_REF, IMDB_REF, WIKI_REF}   # --data 가 없으니 로컬 데이터는 없다
    assert {c["bom-ref"] for c in doc["components"] if c["type"] == "file"} >= {"file:/app/Modelfile", "file:/app/models/stories260K.gguf"}
    gguf = next(c for c in doc["components"] if c["name"] == "llama")
    card = {p["name"]: p["value"] for p in gguf["modelCard"]["properties"]}
    assert card["aibom:model:parameterCount"] == "292800"                       # 푼 디렉터리의 gguf 를 읽었다
    imdb = next(c for c in doc["components"] if c["bom-ref"] == IMDB_REF)
    assert imdb["evidence"]["occurrences"] == [{"location": "app/src/train.py"}]
    assert str(tmp_path) not in out_file("image.cdx.json").read_text()


def test_a_missing_path_target_is_an_error_not_an_image(tmp_path, capsys):
    """경로처럼 생긴 대상이 없으면 이미지 이름으로 넘기지 않고 바로 2 로 끝낸다 (오타가 빈 BOM 이 되지 않게)."""
    out = tmp_path / "bom.json"
    for target in (str(tmp_path / "nope"), "./nope", "../nope", "~/definitely-not-here", "missing-image.tar"):
        assert main(["scan", target, "-o", str(out)]) == 2, target
        assert "error: target not found" in capsys.readouterr().err
    assert not out.exists()


def test_one_failing_tool_still_writes_the_bom_but_exits_2(tmp_path, monkeypatch, capsys):
    """syft·cdxgen 중 하나가 실패하면 만든 만큼은 쓰고, CI 가 모자란 BOM 을 성공으로 넘기지 않도록 2 로 끝낸다."""
    import aibom_cli.cli as cli
    from aibom_cli.runners._proc import RunnerError

    def broken(target, workdir):
        raise RunnerError("syft exited with 1\nfirst detail\nlast detail")
    monkeypatch.setattr(cli, "run_syft", broken)
    monkeypatch.setattr(cli, "run_cdxgen", lambda target, workdir: {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": [
        {"bom-ref": "m", "type": "machine-learning-model", "name": "m", "purl": "pkg:generic/m"}]})
    out = tmp_path / "bom.json"
    assert cli.main(["scan", str(FIXTURE), "-o", str(out)]) == 2
    err = capsys.readouterr().err.splitlines()[1:]                                 # 첫 줄은 형식·입력 안내
    assert err[0].endswith("failed: syft exited with 1") and err[1:3] == ["[aibom-cli]   first detail", "[aibom-cli]   last detail"]
    assert err[-1] == "[aibom-cli] error: syft failed, so the BOM is incomplete"
    assert any(c["name"] == "m" for c in json.loads(out.read_text())["components"])             # 부분 BOM 은 남는다


def test_without_data_paths_the_project_has_no_local_dataset(tmp_path):
    """로컬 데이터는 --data 로만 들어온다. 같은 프로젝트를 --data 없이 스캔하면 data/ 는 BOM 에 없다."""
    doc = scan(FIXTURE, tmp_path / "bom.json")
    assert LOCAL_REF not in {c["bom-ref"] for c in doc["components"]}
    assert {c["name"] for c in doc["components"] if c["type"] == "data"} == {"bookcorpus", "imdb", "wikipedia"}


def test_a_data_path_without_data_files_is_a_warning(tmp_path, monkeypatch, capsys):
    import aibom_cli.cli as cli
    monkeypatch.setattr(cli, "run_syft", lambda target, workdir: {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": []})
    monkeypatch.setattr(cli, "run_cdxgen", lambda target, workdir: {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": []})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("x", encoding="utf-8")
    assert cli.main(["scan", str(FIXTURE), "-o", str(tmp_path / "b.json"), "--data", str(tmp_path / "docs")]) == 0
    assert f"[aibom-cli] warning: no data files in {tmp_path / 'docs'}" in capsys.readouterr().err

