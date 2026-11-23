"""enrich_with_owasp_aibom_generator: 허브 모델마다 OWASP aibom-generator 를 돌려 규제 필드 원본만 가져온다.
도구 출력은 tests/data/owasp/bert-base-uncased.cdx.json (python -m src.cli google-bert/bert-base-uncased) 로 바꿔 끼운다."""
import copy
import json
import os
import tempfile
from pathlib import Path

import pytest

import sure_aibom.engine.owasp_aibom_generator as owasp_aibom_generator
import sure_aibom.engine.common.hub as hub_api
from sure_aibom.engine.owasp_aibom_generator import OWASP_SOURCES, _run_owasp_aibom_generator, _skip_reason, enrich_with_owasp_aibom_generator   # 바꿔 끼우기 전의 진짜 함수
from sure_aibom.engine.form import regulate
from sure_aibom.engine.model import enrich_hub_models
from sure_aibom.utils.exceptions import RunnerError
from test_model_hub import BERT, HF_ID, HUB, bert_component, card_props, doc_of

# 실행 가능 여부와 도구 실행은 시험마다 owasp_aibom_generator 모듈의 함수를 바꿔 끼운다 (enrich_with_owasp_aibom_generator 가 그 이름으로 부른다).

OWASP = Path(__file__).parent / "data" / "owasp" / "bert-base-uncased.cdx.json"
WORKDIR = Path("/nonexistent")                                   # 도구 실행을 바꿔 끼우므로 쓰이지 않는다

KEPT = {"genai:aibom:modelcard:hyperparameter", "genai:aibom:modelcard:vocabSize", "genai:aibom:modelcard:contextLength",
        "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"}         # 녹화본에 있는 규제 필드 원본


@pytest.fixture
def owasp() -> dict:
    return json.loads(OWASP.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def runnable(monkeypatch):
    monkeypatch.setattr(owasp_aibom_generator, "_skip_reason", lambda: None)      # 도구를 돌릴 수 있는 것으로 친다


def stub(monkeypatch, result, calls: list | None = None):
    def run(hf_id, workdir):
        if calls is not None:
            calls.append(hf_id)
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)
    monkeypatch.setattr(owasp_aibom_generator, "_run_owasp_aibom_generator", run)


# -- 돌리지 않는 경우 ------------------------------------------------------------------
def test_nothing_to_enrich_is_left_alone(monkeypatch):
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    doc = doc_of({"bom-ref": "x", "type": "library", "name": "numpy"})
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich_with_owasp_aibom_generator(doc, WORKDIR, report=report)) == before
    assert report["skipped"] == "no Hugging Face models"


def test_offline_skips_without_running_anything(monkeypatch, logs):
    """허브에 닿지 않으면 도구를 돌리지 않는다."""
    monkeypatch.setattr(owasp_aibom_generator, "_skip_reason", lambda: "huggingface.co unreachable")
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    logs.clear()
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    report: dict = {}
    assert json.dumps(enrich_with_owasp_aibom_generator(doc, WORKDIR, report=report)) == before
    assert [m for m in logs if "skipped" in m] == ["[enrich] aibom-generator skipped for 1 hub model: huggingface.co unreachable"]
    assert report["skipped"] == "huggingface.co unreachable"


def test_skip_reason_checks_the_clone_before_the_network(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: pytest.fail("클론이 틀렸는데 네트워크를 봤다"))
    monkeypatch.delenv("AIBOM_GENERATOR_DIR", raising=False)
    assert _skip_reason() == "AIBOM_GENERATOR_DIR not set"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path / "nope"))
    assert _skip_reason() == f"AIBOM_GENERATOR_DIR not found: {tmp_path / 'nope'}"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path))
    assert _skip_reason() == f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {tmp_path}"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: False)
    assert _skip_reason() == "huggingface.co unreachable"
    monkeypatch.setattr(hub_api, "hf_reachable", lambda: True)
    assert _skip_reason() is None


# -- 실패 ---------------------------------------------------------------------------
def test_report_carries_the_first_line_of_each_failure(monkeypatch):
    other = "pkg:huggingface/acme/other"

    def run(hf_id, workdir):
        if hf_id == "acme/other":
            raise RunnerError("aibom-generator exited with 1 for acme/other\nTraceback …")
        return {"bomFormat": "CycloneDX", "components": []}                     # 모델 컴포넌트가 없는 결과
    monkeypatch.setattr(owasp_aibom_generator, "_run_owasp_aibom_generator", run)
    report: dict = {}
    enrich_with_owasp_aibom_generator(doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "other", "purl": other}),
                                      WORKDIR, report=report)
    assert (report["models"], report["enriched"], sorted(report["failed"])) == (2, 0, ["acme/other", HF_ID])
    assert report["errors"] == {HF_ID: "no model component in the aibom-generator output",
                                "acme/other": "aibom-generator exited with 1 for acme/other"}


def test_a_missing_working_directory_is_not_reported_as_a_missing_program():
    from sure_aibom.engine.common.proc import run
    with pytest.raises(RunnerError, match="working directory not found: /nonexistent"):
        run(["python", "-c", "0"], cwd="/nonexistent")


def test_a_failing_run_is_logged_and_the_other_models_still_run(monkeypatch, owasp, logs):
    other = "pkg:huggingface/acme/other"
    calls: list[str] = []

    def run(hf_id, workdir):
        calls.append(hf_id)
        if hf_id == "acme/other":
            raise RunnerError("exit 1")
        return copy.deepcopy(owasp)
    monkeypatch.setattr(owasp_aibom_generator, "_run_owasp_aibom_generator", run)
    logs.clear()
    doc = doc_of(bert_component(), {"bom-ref": other, "type": "machine-learning-model", "name": "other", "purl": other})
    out = enrich_with_owasp_aibom_generator(doc, WORKDIR)
    assert sorted(calls) == ["acme/other", HF_ID]
    assert card_props(out["components"][0]) and "modelCard" not in out["components"][1]
    assert any("acme/other: exit 1" in m for m in logs)


def test_a_result_without_a_model_component_changes_nothing(monkeypatch):
    stub(monkeypatch, {"bomFormat": "CycloneDX", "components": [{"type": "library", "name": "x"}]})
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    assert json.dumps(enrich_with_owasp_aibom_generator(doc, WORKDIR)) == before


# -- 규제 필드 원본만 --------------------------------------------------------------------
def test_only_regulation_sources_are_taken_from_owasp(monkeypatch, owasp):
    calls: list[str] = []
    stub(monkeypatch, owasp, calls)
    report: dict = {}
    out = enrich_with_owasp_aibom_generator(doc_of(bert_component()), WORKDIR, report=report)
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
    out = enrich_with_owasp_aibom_generator(doc_of(comp), WORKDIR)["components"][0]
    assert set(out) == {"bom-ref", "type", "name", "purl", "modelCard"} and set(out["modelCard"]) == {"properties"}
    kept = enrich_with_owasp_aibom_generator(doc_of(bert_component(description="cdxgen 설명")), WORKDIR)["components"][0]
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
    assert json.dumps(enrich_with_owasp_aibom_generator(doc, WORKDIR, report=report)) == before
    assert report["failed"] == [HF_ID] and report["errors"] == {HF_ID: "no regulation values in the aibom-generator output"}


def test_the_generator_is_listed_as_a_tool_only_when_its_values_are_used(monkeypatch, owasp):
    """aibom-generator 에서 규제 필드 원본을 가져오면, 그 출력이 metadata.tools 에 자기를 적은 항목을 문서의 도구 목록에 더한다.
    모델이 여럿이어도, 두 번 돌려도 한 번만 둔다. 원본을 하나도 못 가져온 결과(비공개·없는 저장소)면 더하지 않는다."""
    stub(monkeypatch, owasp)
    other = bert_component(**{"bom-ref": "pkg:huggingface/acme/other", "purl": "pkg:huggingface/acme/other", "group": "acme", "name": "other"})
    out = enrich_with_owasp_aibom_generator(doc_of(bert_component(), other), WORKDIR)
    assert out["metadata"]["tools"]["components"] == owasp["metadata"]["tools"]["components"]
    assert enrich_with_owasp_aibom_generator(copy.deepcopy(out), WORKDIR)["metadata"] == out["metadata"]
    empty = copy.deepcopy(owasp)
    for comp in empty["components"]:
        card = comp.get("modelCard") or {}
        card["properties"] = [p for p in card.get("properties") or [] if p.get("name") not in OWASP_SOURCES]
    stub(monkeypatch, empty)
    assert "metadata" not in enrich_with_owasp_aibom_generator(doc_of(bert_component()), WORKDIR)


def test_running_twice_adds_nothing_new(monkeypatch, owasp):
    stub(monkeypatch, owasp)
    once = enrich_with_owasp_aibom_generator(doc_of(bert_component()), WORKDIR)
    twice = enrich_with_owasp_aibom_generator(copy.deepcopy(once), WORKDIR)
    assert json.dumps(twice) == json.dumps(once)


# -- form 으로 이어지는가 ----------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
def test_enriched_values_become_v06_fields(monkeypatch, owasp, form):
    """service 와 같은 순서로 돌린다: Hub API 보강, OWASP 보강, 규제 필드 배치."""
    stub(monkeypatch, owasp)
    hub = json.loads(HUB.read_text(encoding="utf-8"))
    doc = enrich_hub_models(doc_of(bert_component()), model_infos={HF_ID: hub})
    out = regulate(enrich_with_owasp_aibom_generator(doc, WORKDIR), form=form)
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
@pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")
def test_live_generator_returns_the_same_property_names():
    doc = _run_owasp_aibom_generator(HF_ID, Path(tempfile.mkdtemp()))
    src = next(c for c in doc["components"] if c["type"] == "machine-learning-model")
    names = {p["name"] for p in (src.get("modelCard") or {}).get("properties") or []}
    assert KEPT <= names, f"기록해 둔 응답에 있던 키가 사라졌다: {sorted(KEPT - names)}"
    assert os.environ.get("AIBOM_GENERATOR_DIR")
