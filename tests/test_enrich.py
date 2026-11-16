"""enrich — 허브 모델을 Hub API 응답으로 채우고, OWASP aibom-generator 에서 규제 필드 원본만 가져온다.
Hub API 는 tests/data/hf_api/hf_model_google-bert_bert-base-uncased.json (실제 GET /api/models/google-bert/bert-base-uncased 응답),
OWASP 는 tests/data/owasp/bert-base-uncased.cdx.json (python -m src.cli google-bert/bert-base-uncased) 로 바꿔 끼운다."""
import copy
import json
import os
from pathlib import Path

import pytest

import sure_aibom.engine.enrich as en
import sure_aibom.external.hub as hub_api          # 이름 hub 는 아래의 Hub API 응답 fixture 가 쓴다
from sure_aibom.engine.enrich import OWASP_SOURCES, apply_model_info, enrich, hf_id_of, hub_model_id, performance_metrics, skip_reason
from sure_aibom.engine.facts import Facts
from sure_aibom.engine.form import apply
from sure_aibom.exceptions import RunnerError

OWASP = Path(__file__).parent / "data" / "owasp" / "bert-base-uncased.cdx.json"
HUB = Path(__file__).parent / "data" / "hf_api" / "hf_model_google-bert_bert-base-uncased.json"
BERT = "pkg:huggingface/google-bert/bert-base-uncased"
HF_ID = "google-bert/bert-base-uncased"
WORKDIR = Path("/nonexistent")                                   # 러너를 바꿔 끼우므로 쓰이지 않는다

KEPT = {"genai:aibom:modelcard:hyperparameter", "genai:aibom:modelcard:vocabSize", "genai:aibom:modelcard:contextLength",
        "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"}         # 녹화본에 있는 규제 필드 원본
DROPPED = {"genai:aibom:trainingDataAvailable", "genai:aibom:trainingDataStatus", "owasp:aibom:distribution:modelFileSize",
           "serialNumber", "safetyRiskAssessment"}


@pytest.fixture
def owasp() -> dict:
    return json.loads(OWASP.read_text(encoding="utf-8"))


@pytest.fixture
def hub() -> dict:
    return json.loads(HUB.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(en, "skip_reason", lambda: None)
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: False)        # Hub API 응답은 시험마다 model_infos 로 준다. 안 주면 허브에 닿지 않는다


def bert_component(**extra) -> dict:
    """cdxgen 이 코드의 from_pretrained("google-bert/bert-base-uncased") 로 만드는 모델 (모델카드 일부는 시험용으로 미리 채움)."""
    comp = {"bom-ref": BERT, "type": "machine-learning-model", "group": "google-bert", "name": "bert-base-uncased",
            "purl": BERT, "properties": [{"name": "cdx:ai:runtime", "value": "transformers"}],
            "evidence": {"occurrences": [{"location": "src/train.py#L5"}]},
            "modelCard": {"modelParameters": {"task": "fill-mask", "modelArchitecture": "BertForMaskedLM"}}}
    comp.update(extra)
    return comp


def doc_of(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": list(components)}


def card_props(comp: dict) -> dict[str, str]:
    return {p["name"]: p["value"] for p in (comp.get("modelCard") or {}).get("properties") or []}


def stub(monkeypatch, result, calls: list | None = None):
    def run(hf_id, workdir):
        if calls is not None:
            calls.append(hf_id)
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)
    monkeypatch.setattr(en, "run_aibom_generator", run)


# -- 허브 모델 고르기 -----------------------------------------------------------------
@pytest.mark.parametrize("comp, expected", [
    ({"type": "machine-learning-model", "purl": BERT}, HF_ID),
    ({"type": "machine-learning-model", "purl": "pkg:huggingface/google-bert/bert-base-uncased@abc?x=1"}, HF_ID),
    ({"type": "data", "purl": "pkg:huggingface/datasets/stanfordnlp/imdb"}, None),                     # 데이터셋은 type 으로 걸러진다
    ({"type": "machine-learning-model", "purl": "pkg:generic/ollama/llama3.2:1b"}, None),              # 로컬 모델
    ({"type": "data", "purl": BERT}, None),
    ({"type": "machine-learning-model"}, None),
])
def test_hf_id_of(comp, expected):
    assert hf_id_of(comp) == expected


@pytest.mark.parametrize("locations, expected", [
    (["src/train.py#L5"], HF_ID),                                                  # 코드가 부른다
    (["notebooks/eval.ipynb", "app.js#L3"], HF_ID),
    ([], HF_ID),
    (["models/bert/README.md", "models/bert/config.json"], None),                  # 받아 둔 폴더 (config 의 _name_or_path 로 허브 id 를 얻은 것)
    (["src/train.py#L5", "models/bert/config.json"], None),                        # 코드도 부르지만 로컬 사본이 있다
    (["models/x.gguf"], None), (["models/x/model.safetensors"], None), (["deploy/Modelfile"], None), (["a/adapter_config.json"], None),
])
def test_hub_models_are_the_ones_without_local_model_files(locations, expected):
    comp = {"type": "machine-learning-model", "purl": BERT, "evidence": {"occurrences": [{"location": loc} for loc in locations]}}
    assert hub_model_id(comp) == expected


def test_nothing_to_enrich_is_left_alone(monkeypatch):
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    logs: list[str] = []
    doc = doc_of({"bom-ref": "x", "type": "library", "name": "numpy"})
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich(doc, WORKDIR, logs.append, report=report)) == before
    assert any("no hub model components" in m for m in logs)
    assert report["skipped"] == report["hub_skipped"] == "no Hugging Face models"


def test_offline_skips_without_running_anything(monkeypatch):
    """허브에 닿지 않으면 Hub API 모델 응답을 받지 않고, OWASP 도 건너뛴다."""
    monkeypatch.setattr(en, "skip_reason", lambda: "huggingface.co unreachable")
    monkeypatch.setattr(hub_api, "fetch_model_info", lambda hf_id, log=print: pytest.fail("offline 인데 모델 응답을 받았다"))
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    logs: list[str] = []
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich(doc, WORKDIR, logs.append, report=report)) == before
    assert [m for m in logs if "skipped" in m] == ["[enrich] aibom-generator skipped for 1 hub model: huggingface.co unreachable"]
    assert report["hub_skipped"] == report["skipped"] == "huggingface.co unreachable"
    assert report["hub_reachable"] is False and report["model_infos"] == {}


def test_skip_reason_checks_the_clone_before_the_network(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: pytest.fail("클론이 틀렸는데 네트워크를 봤다"))
    monkeypatch.delenv("AIBOM_GENERATOR_DIR", raising=False)
    assert skip_reason() == "AIBOM_GENERATOR_DIR not set"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path / "nope"))
    assert skip_reason() == f"AIBOM_GENERATOR_DIR not found: {tmp_path / 'nope'}"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path))
    assert skip_reason() == f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {tmp_path}"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: False)
    assert skip_reason() == "huggingface.co unreachable"
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: True)
    assert skip_reason() is None


def test_report_carries_the_first_line_of_each_failure(monkeypatch, owasp):
    other = "pkg:huggingface/acme/other"

    def run(hf_id, workdir):
        if hf_id == "acme/other":
            raise RunnerError("aibom-generator exited with 1 for acme/other\nTraceback …")
        return {"bomFormat": "CycloneDX", "components": []}                     # 모델 컴포넌트가 없는 결과
    monkeypatch.setattr(en, "run_aibom_generator", run)
    report: dict = {}
    enrich(doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "other", "purl": other}),
           WORKDIR, log=lambda m: None, report=report)
    assert (report["models"], report["enriched"], sorted(report["failed"])) == (2, 0, ["acme/other", HF_ID])
    assert report["errors"] == {HF_ID: "no model component in the aibom-generator output",
                                "acme/other": "aibom-generator exited with 1 for acme/other"}


def test_a_missing_working_directory_is_not_reported_as_a_missing_program():
    from sure_aibom.external._proc import run
    with pytest.raises(RunnerError, match="working directory not found: /nonexistent"):
        run(["python", "-c", "0"], cwd="/nonexistent")


# -- OWASP: 규제 필드 원본만 -------------------------------------------------------------
def test_only_regulation_sources_are_taken_from_owasp(monkeypatch, owasp):
    calls: list[str] = []
    stub(monkeypatch, owasp, calls)
    report: dict = {}
    out = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None, report=report)
    comp = out["components"][0]
    assert calls == [HF_ID] and report["enriched"] == 1
    props = card_props(comp)
    assert set(props) == KEPT and KEPT <= OWASP_SOURCES
    assert props["safetensors_total_parameters"] == "110106428"
    assert json.loads(props["genai:aibom:modelcard:hyperparameter"])["block_count"] == 12
    assert {p["name"] for p in comp["properties"]} == {"cdx:ai:runtime"}                # component.properties(model_type)는 안 가져온다


def test_owasp_fields_other_than_regulation_sources_are_not_taken(monkeypatch, owasp):
    """OWASP 의 description(자리표시자), licenses, task·modelArchitecture(계열 이름), datasets(이름뿐), technicalLimitations(README 조각),
    supplier·authors·version 은 하나도 들어오지 않는다. 비어 있는 자리여도 그렇다."""
    stub(monkeypatch, owasp)
    comp = {"bom-ref": BERT, "type": "machine-learning-model", "name": "bert-base-uncased", "purl": BERT}
    out = enrich(doc_of(comp), WORKDIR, log=lambda m: None)["components"][0]
    assert set(out) == {"bom-ref", "type", "name", "purl", "modelCard"} and set(out["modelCard"]) == {"properties"}
    kept = enrich(doc_of(bert_component(description="cdxgen 설명")), WORKDIR, log=lambda m: None)["components"][0]
    assert kept["modelCard"]["modelParameters"] == {"task": "fill-mask", "modelArchitecture": "BertForMaskedLM"}
    assert kept["description"] == "cdxgen 설명" and "considerations" not in kept["modelCard"]


def test_an_owasp_result_without_regulation_values_counts_as_failed(monkeypatch, owasp):
    """허브에 없는 저장소·비공개 저장소에도 OWASP 는 기본값(task text-generation, modelArchitecture transformer, 설명 자리표시자)으로
    채운 BOM 을 낸다. 가져올 원본이 없으니 아무것도 바뀌지 않고 실패로 센다."""
    defaults = copy.deepcopy(owasp)
    src = defaults["components"][0]
    src["modelCard"] = {"modelParameters": {"task": "text-generation", "modelArchitecture": "transformer"},
                        "properties": [{"name": "genai:aibom:trainingDataAvailable", "value": "false"}]}
    stub(monkeypatch, defaults)
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich(doc, WORKDIR, log=lambda m: None, report=report)) == before
    assert report["failed"] == [HF_ID] and report["errors"] == {HF_ID: "no regulation values in the aibom-generator output"}


def test_the_generator_is_listed_as_a_tool_only_when_its_values_are_used(monkeypatch, owasp):
    """aibom-generator 에서 규제 필드 원본을 가져오면, 그 출력이 metadata.tools 에 자기를 적은 항목을 문서의 도구 목록에 더한다.
    모델이 여럿이어도, 두 번 돌려도 한 번만 둔다. 원본을 하나도 못 가져온 결과(비공개·없는 저장소)면 더하지 않는다."""
    stub(monkeypatch, owasp)
    other = bert_component(**{"bom-ref": "pkg:huggingface/acme/other", "purl": "pkg:huggingface/acme/other", "group": "acme", "name": "other"})
    out = enrich(doc_of(bert_component(), other), WORKDIR, log=lambda m: None)
    assert out["metadata"]["tools"]["components"] == owasp["metadata"]["tools"]["components"]
    assert enrich(copy.deepcopy(out), WORKDIR, log=lambda m: None)["metadata"] == out["metadata"]
    empty = copy.deepcopy(owasp)
    for comp in empty["components"]:
        card = comp.get("modelCard") or {}
        card["properties"] = [p for p in card.get("properties") or [] if p.get("name") not in OWASP_SOURCES]
    stub(monkeypatch, empty)
    assert "metadata" not in enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None)


def test_running_twice_adds_nothing_new(monkeypatch, owasp, hub):
    stub(monkeypatch, owasp)
    once = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None, model_infos={HF_ID: hub})
    twice = enrich(copy.deepcopy(once), WORKDIR, log=lambda m: None, model_infos={HF_ID: hub})
    assert json.dumps(twice) == json.dumps(once)


def test_a_failing_run_is_logged_and_the_other_models_still_run(monkeypatch, owasp):
    other = "pkg:huggingface/acme/other"
    calls: list[str] = []

    def run(hf_id, workdir):
        calls.append(hf_id)
        if hf_id == "acme/other":
            raise RunnerError("exit 1")
        return copy.deepcopy(owasp)
    monkeypatch.setattr(en, "run_aibom_generator", run)
    logs: list[str] = []
    doc = doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "other", "purl": other})
    out = enrich(doc, WORKDIR, logs.append)
    assert sorted(calls) == ["acme/other", HF_ID]
    assert card_props(out["components"][0]) and "modelCard" not in out["components"][1]
    assert any("acme/other: exit 1" in m for m in logs)


def test_a_result_without_a_model_component_changes_nothing(monkeypatch):
    stub(monkeypatch, {"bomFormat": "CycloneDX", "components": [{"type": "library", "name": "x"}]})
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    assert json.dumps(enrich(doc, WORKDIR, log=lambda m: None)) == before


# -- Hub API 응답으로 채우기 --------------------------------------------------------------
def test_hub_api_response_fills_the_empty_fields(monkeypatch, hub):
    """실제 응답: sha · author · cardData.license · arxiv 태그 · config · pipeline_tag · safetensors.total. 이미 있는 값(cdxgen 의 task ·
    modelArchitecture)은 그대로이고, model-index 가 없으니 성능 지표는 없으며, base_model 이 없으니 계보도 없다."""
    stub(monkeypatch, RunnerError("OWASP 는 이 테스트의 관심 밖"))
    report: dict = {}
    facts = Facts()
    comp = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None, report=report, model_infos={HF_ID: hub}, facts=facts)["components"][0]
    assert (report["hub"], report["hub_missing"]) == (1, [])
    assert facts.times == {comp["bom-ref"]: {"releaseTime": "2024-02-19T11:06:12Z"}}     # lastModified 는 문서가 아니라 facts 에
    assert comp["version"] == "86b5e0934494bd15c9632b12f734a8a67f723594"
    assert comp["licenses"] == [{"license": {"id": "Apache-2.0"}}] and comp["supplier"] == {"name": "google-bert"}
    assert comp["externalReferences"] == [{"type": "distribution", "url": "https://huggingface.co/google-bert/bert-base-uncased"},
                                          {"type": "documentation", "url": "https://arxiv.org/abs/1810.04805"}]
    assert comp["modelCard"]["modelParameters"] == {"task": "fill-mask", "modelArchitecture": "BertForMaskedLM", "architectureFamily": "bert",
                                                    "inputs": [{"format": "text"}], "outputs": [{"format": "text"}]}
    assert "pedigree" not in comp and "quantitativeAnalysis" not in comp["modelCard"] and "description" not in comp
    assert {"name": "aibom-internal:model:parameterCount", "value": "110106428"} in comp["properties"]


def test_hub_model_responses_are_fetched_once_and_handed_to_the_d_bom(monkeypatch, hub):
    """model_infos 를 주지 않으면 허브에 닿는지 보고 허브 모델마다 Hub API 응답을 한 번 받아 채운다. 받은 응답은 report 에 남겨
    뒤의 D-BOM 이 모델 카드의 데이터셋을 읽을 때 다시 쓴다."""
    calls: list[str] = []
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: True)
    monkeypatch.setattr(hub_api, "fetch_model_info", lambda hf_id, log=print: calls.append(hf_id) or copy.deepcopy(hub))
    monkeypatch.setattr(en, "skip_reason", lambda: "not under test")
    report: dict = {}
    comp = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None, report=report)["components"][0]
    assert calls == [HF_ID]
    assert report["hub_reachable"] is True and report["hub"] == 1 and report["model_infos"] == {HF_ID: hub}
    assert comp["version"] == hub["sha"]


def test_hub_models_without_a_response_are_reported(monkeypatch, hub):
    other = "pkg:huggingface/acme/private"
    stub(monkeypatch, RunnerError("x"))
    report: dict = {}
    doc = doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "private", "purl": other})
    out = enrich(doc, WORKDIR, log=lambda m: None, report=report, model_infos={HF_ID: hub, "acme/private": None})
    assert (report["models"], report["hub"], report["hub_missing"]) == (2, 1, ["acme/private"])
    assert set(out["components"][1]) == {"bom-ref", "type", "name", "purl"}


def test_hub_api_fields_follow_the_cdxgen_rules_for_cards():
    """허구의 응답: other 라이선스 · base_model 관계 · model-index 성능 지표 · GGUF 저장소 (gguf.total · context_length · architecture)."""
    info = {"id": "acme/chat-GGUF", "author": "acme", "sha": "b2" * 20, "tags": ["gguf", "arxiv:2601.00001"],
            "cardData": {"license": "other", "license_name": "acme-license", "license_link": "https://acme.example/l",
                         "base_model": ["acme/base", "not a hub id"], "base_model_relation": "quantized", "model_description": "Acme  chat\\nmodel.",
                         "model-index": [{"name": "x", "results": [
                             {"task": {"type": "text-generation"}, "dataset": {"name": "Eval", "type": "acme/eval", "split": "test"},
                              "metrics": [{"type": "accuracy", "value": 0.5}, {"name": "f1", "value": None}, {"value": 1}]}]}]},
            "gguf": {"total": 15000000, "architecture": "llama", "context_length": 2048}}
    comp = {"type": "machine-learning-model", "name": "chat-GGUF", "purl": "pkg:huggingface/acme/chat-GGUF"}
    apply_model_info(comp, "acme/chat-GGUF", info)
    assert comp["licenses"] == [{"license": {"name": "acme-license", "url": "https://acme.example/l"}}]
    assert comp["description"] == "Acme chat\\nmodel."
    assert comp["pedigree"] == {"ancestors": [{"type": "machine-learning-model", "group": "acme", "name": "base", "purl": "pkg:huggingface/acme/base"}],
                                "notes": "Hugging Face relation: quantized"}
    params = comp["modelCard"]["modelParameters"]
    assert params == {"task": "text-generation", "architectureFamily": "llama", "inputs": [{"format": "text"}], "outputs": [{"format": "text"}]}
    assert comp["modelCard"]["quantitativeAnalysis"]["performanceMetrics"] == [{"type": "accuracy", "value": "0.5", "slice": "Eval / test"}]
    assert {p["name"]: p["value"] for p in comp["properties"]} == {"aibom-internal:model:parameterCount": "15000000",
                                                                    "aibom-internal:model:maxSize": "2048"}
    assert comp["externalReferences"][1] == {"type": "documentation", "url": "https://arxiv.org/abs/2601.00001"}


def test_hub_api_never_overwrites_and_infers_io_from_widgets_like_cdxgen():
    comp = {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m", "version": "1", "description": "d",
            "licenses": [{"license": {"id": "MIT"}}], "pedigree": {"ancestors": [{"name": "x"}]},
            "modelCard": {"modelParameters": {"inputs": [{"format": "image"}]}}}
    before = copy.deepcopy(comp)
    apply_model_info(comp, "a/m", {"sha": "s", "cardData": {"license": "apache-2.0", "base_model": "a/b", "model_description": "x"},
                                   "pipeline_tag": "text-classification", "widgetData": [{"text": "hi"}]})
    assert {k: comp[k] for k in before} == {**before, "modelCard": comp["modelCard"]}
    assert comp["modelCard"]["modelParameters"] == {"inputs": [{"format": "image"}], "task": "text-classification"}   # 입출력이 있으면 손대지 않는다
    widget = {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m"}
    apply_model_info(widget, "a/m", {"pipeline_tag": "text-classification", "widgetData": [{"text": "hi"}]})      # 표에 없는 task 는 widget 으로
    assert widget["modelCard"]["modelParameters"]["inputs"] == [{"format": "text"}]
    empty = {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m"}
    apply_model_info(empty, "a/m", {"id": "a/m"})
    assert empty == {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m",
                     "externalReferences": [{"type": "distribution", "url": "https://huggingface.co/a/m"}]}


def test_performance_metrics_match_cdxgen():
    index = [{"results": [{"dataset": {"name": "D", "split": "s"}, "metrics": [{"type": "acc", "value": 0.9}, {"name": "f1", "value": "0.8"},
                                                                             {"type": "x", "value": ""}, {"value": 1}]},
                          {"metrics": [{"type": "bleu", "value": 30}]}, "bad"]}, None]
    assert performance_metrics(index) == [{"type": "acc", "value": "0.9", "slice": "D / s"}, {"type": "f1", "value": "0.8", "slice": "D / s"},
                                          {"type": "bleu", "value": "30"}]
    assert performance_metrics(None) == [] and performance_metrics({"results": []}) == []


# -- form 으로 이어지는가 ----------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
def test_enriched_values_become_v06_fields(monkeypatch, owasp, hub, form):
    stub(monkeypatch, owasp)
    out = apply(enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None, model_infos={HF_ID: hub}), form=form, log=lambda m: None)
    card = out["components"][0]["modelCard"]
    if form == "properties":
        props = card_props(out["components"][0])
        assert props["aibom:model:parameterCount"] == "110106428" and props["aibom:model:inputs:0:maxSize"] == "512"
        assert (props["aibom:model:hyperparameters:0:name"], props["aibom:model:hyperparameters:0:value"]) == ("context_length", "512")
        assert all(name.startswith("aibom:") for name in props)                       # 가져온 원본은 모두 승격되어 소비된다
    else:
        assert card["modelParameters"]["parameterCount"] == 110106428
        assert card["modelParameters"]["inputs"][0] == {"format": "text", "maxSize": "512"}
        assert card["considerations"]["technicalRequirements"] == ["python", "transformers"]


# -- 실제 실행 (AIBOM_GENERATOR_DIR 과 네트워크가 있을 때만) ----------------------------------
@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_live_generator_returns_the_same_property_names():
    from sure_aibom.external.aibom_generator import run_aibom_generator
    import tempfile
    doc = run_aibom_generator(HF_ID, Path(tempfile.mkdtemp()))
    src = next(c for c in doc["components"] if c["type"] == "machine-learning-model")
    names = {p["name"] for p in (src.get("modelCard") or {}).get("properties") or []}
    assert KEPT <= names, f"기록해 둔 응답에 있던 키가 사라졌다: {sorted(KEPT - names)}"
    assert os.environ.get("AIBOM_GENERATOR_DIR")
