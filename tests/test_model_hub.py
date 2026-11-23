"""enrich_hub_models: 허브 모델을 Hub API 응답으로 채운다.
Hub API 는 tests/data/hf_api/hf_model_google-bert_bert-base-uncased.json (실제 GET /api/models/google-bert/bert-base-uncased 응답)
으로 바꿔 끼운다. OWASP aibom-generator 로 하는 보강은 test_owasp_aibom_generator.py 가 본다."""
import copy
import json
from pathlib import Path

import pytest

import sure_aibom.engine.common.hub as hub_api     # 이름 hub 는 아래의 Hub API 응답 fixture 가 쓴다
from sure_aibom.engine.common.component import _hf_id_of, hub_model_id
from sure_aibom.engine.model import _apply_model_info, _performance_metrics, enrich_hub_models
from sure_aibom.utils.facts import Facts

# 허브 조회는 시험마다 hub_api 모듈의 함수를 바꿔 끼운다 (model.py 가 그 모듈을 거쳐 부른다).

HUB = Path(__file__).parent / "data" / "hf_api" / "hf_model_google-bert_bert-base-uncased.json"
BERT = "pkg:huggingface/google-bert/bert-base-uncased"
HF_ID = "google-bert/bert-base-uncased"


@pytest.fixture
def hub() -> dict:
    return json.loads(HUB.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def hub_unreachable(monkeypatch):
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
    assert _hf_id_of(comp) == expected


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


def test_nothing_to_enrich_is_left_alone(logs):
    logs.clear()
    doc = doc_of({"bom-ref": "x", "type": "library", "name": "numpy"})
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich_hub_models(doc, report=report)) == before
    assert any("no hub model components" in m for m in logs)
    assert report["hub_skipped"] == "no Hugging Face models"


def test_offline_skips_without_fetching_anything(monkeypatch):
    """허브에 닿지 않으면 Hub API 모델 응답을 받지 않는다."""
    monkeypatch.setattr(hub_api, "fetch_model_info", lambda hf_id: pytest.fail("offline 인데 모델 응답을 받았다"))
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich_hub_models(doc, report=report)) == before
    assert report["hub_skipped"] == "huggingface.co unreachable"
    assert report["hub_reachable"] is False and report["model_infos"] == {}


def test_running_twice_adds_nothing_new(hub):
    once = enrich_hub_models(doc_of(bert_component()), model_infos={HF_ID: hub})
    twice = enrich_hub_models(copy.deepcopy(once), model_infos={HF_ID: hub})
    assert json.dumps(twice) == json.dumps(once)


# -- Hub API 응답으로 채우기 --------------------------------------------------------------
def test_hub_api_response_fills_the_empty_fields(hub):
    """실제 응답: sha · author · cardData.license · arxiv 태그 · config · pipeline_tag · safetensors.total. 이미 있는 값(cdxgen 의 task ·
    modelArchitecture)은 그대로이고, model-index 가 없으니 성능 지표는 없으며, base_model 이 없으니 계보도 없다."""
    report: dict = {}
    facts = Facts()
    comp = enrich_hub_models(doc_of(bert_component()), report=report, model_infos={HF_ID: hub}, facts=facts)["components"][0]
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
    monkeypatch.setattr(hub_api, "fetch_model_info", lambda hf_id: calls.append(hf_id) or copy.deepcopy(hub))
    report: dict = {}
    comp = enrich_hub_models(doc_of(bert_component()), report=report)["components"][0]
    assert calls == [HF_ID]
    assert report["hub_reachable"] is True and report["hub"] == 1 and report["model_infos"] == {HF_ID: hub}
    assert comp["version"] == hub["sha"]


def test_hub_models_without_a_response_are_reported(hub):
    other = "pkg:huggingface/acme/private"
    report: dict = {}
    doc = doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "private", "purl": other})
    out = enrich_hub_models(doc, report=report, model_infos={HF_ID: hub, "acme/private": None})
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
    _apply_model_info(comp, "acme/chat-GGUF", info)
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
    _apply_model_info(comp, "a/m", {"sha": "s", "cardData": {"license": "apache-2.0", "base_model": "a/b", "model_description": "x"},
                                    "pipeline_tag": "text-classification", "widgetData": [{"text": "hi"}]})
    assert {k: comp[k] for k in before} == {**before, "modelCard": comp["modelCard"]}
    assert comp["modelCard"]["modelParameters"] == {"inputs": [{"format": "image"}], "task": "text-classification"}   # 입출력이 있으면 손대지 않는다
    widget = {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m"}
    _apply_model_info(widget, "a/m", {"pipeline_tag": "text-classification", "widgetData": [{"text": "hi"}]})      # 표에 없는 task 는 widget 으로
    assert widget["modelCard"]["modelParameters"]["inputs"] == [{"format": "text"}]
    empty = {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m"}
    _apply_model_info(empty, "a/m", {"id": "a/m"})
    assert empty == {"type": "machine-learning-model", "name": "m", "purl": "pkg:huggingface/a/m",
                     "externalReferences": [{"type": "distribution", "url": "https://huggingface.co/a/m"}]}


def test_performance_metrics_match_cdxgen():
    index = [{"results": [{"dataset": {"name": "D", "split": "s"}, "metrics": [{"type": "acc", "value": 0.9}, {"name": "f1", "value": "0.8"},
                                                                             {"type": "x", "value": ""}, {"value": 1}]},
                          {"metrics": [{"type": "bleu", "value": 30}]}, "bad"]}, None]
    assert _performance_metrics(index) == [{"type": "acc", "value": "0.9", "slice": "D / s"}, {"type": "f1", "value": "0.8", "slice": "D / s"},
                                           {"type": "bleu", "value": "30"}]
    assert _performance_metrics(None) == [] and _performance_metrics({"results": []}) == []
