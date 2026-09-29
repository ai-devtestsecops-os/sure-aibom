"""enrich — OWASP aibom-generator 를 HF 모델마다 돌려 결과를 합친다.
실제 실행 결과는 tests/data/owasp/bert-base-uncased.cdx.json (python -m src.cli google-bert/bert-base-uncased) 로 바꿔 끼운다."""
import copy
import json
import os
from pathlib import Path

import pytest

import aibom_cli.enrich as en
from aibom_cli.enrich import enrich, hf_id_of, skip_reason
from aibom_cli.form import apply
from aibom_cli.runners._proc import RunnerError

OWASP = Path(__file__).parent / "data" / "owasp" / "bert-base-uncased.cdx.json"
BERT = "pkg:huggingface/google-bert/bert-base-uncased"
HF_ID = "google-bert/bert-base-uncased"
WORKDIR = Path("/nonexistent")                                   # 러너를 바꿔 끼우므로 쓰이지 않는다

KEPT = {"genai:aibom:modelcard:hyperparameter", "genai:aibom:modelcard:vocabSize", "genai:aibom:modelcard:contextLength",
        "genai:aibom:trainingDataAvailable", "genai:aibom:trainingDataStatus", "owasp:aibom:distribution:modelFileSize",
        "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"}
DROPPED = {"serialNumber", "safetyRiskAssessment"}               # 접두어 없는 키는 safetensors_total_parameters 만 남긴다


@pytest.fixture
def owasp() -> dict:
    return json.loads(OWASP.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def reachable(monkeypatch):
    monkeypatch.setattr(en, "skip_reason", lambda: None)


def bert_component(**extra) -> dict:
    comp = {"bom-ref": BERT, "type": "machine-learning-model", "group": "google-bert", "name": "bert-base-uncased",
            "purl": BERT, "properties": [{"name": "cdx:ai:runtime", "value": "transformers"}],
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


# -- HF 모델 고르기 ------------------------------------------------------------------
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


def test_nothing_to_enrich_is_left_alone(monkeypatch):
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    logs: list[str] = []
    doc = doc_of({"bom-ref": "x", "type": "library", "name": "numpy"})
    before = json.dumps(doc)
    assert json.dumps(enrich(doc, WORKDIR, logs.append)) == before
    assert any("모델 컴포넌트가 없어" in m for m in logs)


def test_offline_skips_without_running_anything(monkeypatch):
    monkeypatch.setattr(en, "skip_reason", lambda: "huggingface.co 에 닿지 않음")
    stub(monkeypatch, RunnerError("불려서는 안 된다"))
    logs: list[str] = []
    doc = doc_of(bert_component())
    before = json.dumps(doc)
    assert json.dumps(enrich(doc, WORKDIR, logs.append)) == before
    assert [m for m in logs if "건너뛴다" in m] == ["[enrich] huggingface.co 에 닿지 않음 — 보강을 건너뛴다 (1개 모델)"]


def test_skip_reason_checks_the_clone_before_the_network(tmp_path, monkeypatch):
    monkeypatch.setattr(en, "hf_reachable", lambda: pytest.fail("클론이 틀렸는데 네트워크를 봤다"))
    monkeypatch.delenv("AIBOM_GENERATOR_DIR", raising=False)
    assert skip_reason() == "AIBOM_GENERATOR_DIR not set"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path / "nope"))
    assert skip_reason() == f"AIBOM_GENERATOR_DIR not found: {tmp_path / 'nope'}"
    monkeypatch.setenv("AIBOM_GENERATOR_DIR", str(tmp_path))
    assert skip_reason() == f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {tmp_path}"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cli.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(en, "hf_reachable", lambda: False)
    assert skip_reason() == "huggingface.co unreachable"
    monkeypatch.setattr(en, "hf_reachable", lambda: True)
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
    from aibom_cli.runners._proc import run
    with pytest.raises(RunnerError, match="working directory not found: /nonexistent"):
        run(["python", "-c", "0"], cwd="/nonexistent")


# -- 합치기 ------------------------------------------------------------------------
def test_owasp_properties_are_filtered_and_merged_into_the_model_card(monkeypatch, owasp):
    calls: list[str] = []
    stub(monkeypatch, owasp, calls)
    out = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None)
    comp = out["components"][0]
    assert calls == [HF_ID]
    props = card_props(comp)
    assert set(props) == KEPT                                     # 접두어 없는 키는 safetensors_total_parameters 만
    assert not (set(props) & DROPPED)
    assert props["safetensors_total_parameters"] == "110106428"
    assert json.loads(props["genai:aibom:modelcard:hyperparameter"])["block_count"] == 12
    assert "model_type" not in {p["name"] for p in comp.get("properties") or []}       # component.properties 는 안 가져온다
    assert {p["name"] for p in comp["properties"]} == {"cdx:ai:runtime"}                # cdxgen 값은 그대로


def test_cdxgen_values_are_not_overwritten(monkeypatch, owasp):
    stub(monkeypatch, owasp)
    comp = bert_component(description="cdxgen 설명")
    out = enrich(doc_of(comp), WORKDIR, log=lambda m: None)
    card = out["components"][0]["modelCard"]
    assert card["modelParameters"]["task"] == "fill-mask"                                # 있던 하위 키는 유지
    assert card["modelParameters"]["modelArchitecture"] == "BertForMaskedLM"
    assert out["components"][0]["description"] == "cdxgen 설명"                          # 설명도 먼저 있던 것이 이긴다


def test_description_and_considerations_come_from_owasp_when_missing(monkeypatch, owasp):
    src = next(c for c in owasp["components"] if c["type"] == "machine-learning-model")
    stub(monkeypatch, owasp)
    out = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None)
    comp = out["components"][0]
    assert comp.get("description") == src.get("description")
    if src.get("modelCard", {}).get("considerations"):
        assert comp["modelCard"]["considerations"] == src["modelCard"]["considerations"]


def test_document_level_score_properties_move_to_the_component(monkeypatch, owasp):
    owasp["metadata"]["properties"] = [{"name": "aibom:completeness:score", "value": "83"},
                                       {"name": "generated_at", "value": "2026-01-01"}]
    stub(monkeypatch, owasp)
    comp = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None)["components"][0]
    names = {p["name"]: p["value"] for p in comp["properties"]}
    assert names["owasp:aibom:aibom:completeness:score"] == "83" and "generated_at" not in names


def test_running_twice_adds_nothing_new(monkeypatch, owasp):
    stub(monkeypatch, owasp)
    once = enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None)
    twice = enrich(copy.deepcopy(once), WORKDIR, log=lambda m: None)
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


# -- form 으로 이어지는가 ----------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
def test_enriched_values_become_v06_fields(monkeypatch, owasp, form):
    stub(monkeypatch, owasp)
    out = apply(enrich(doc_of(bert_component()), WORKDIR, log=lambda m: None), form=form, log=lambda m: None)
    card = out["components"][0]["modelCard"]
    if form == "properties":
        props = card_props(out["components"][0])
        assert props["aibom:model:parameterCount"] == "110106428" and props["aibom:model:inputs:0:maxSize"] == "512"
        assert (props["aibom:model:hyperparameters:0:name"], props["aibom:model:hyperparameters:0:value"]) == ("context_length", "512")
        assert set(props) & KEPT == {"genai:aibom:trainingDataAvailable", "genai:aibom:trainingDataStatus",
                                     "owasp:aibom:distribution:modelFileSize"}          # 승격한 원본만 사라진다
    else:
        assert card["modelParameters"]["parameterCount"] == 110106428
        assert card["modelParameters"]["inputs"][0]["maxSize"] == "512"
        assert card["considerations"]["technicalRequirements"] == ["python", "transformers"]


# -- 실제 실행 (AIBOM_GENERATOR_DIR 과 네트워크가 있을 때만) ----------------------------------
@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_live_generator_returns_the_same_property_names():
    from aibom_cli.runners.aibom_generator import run_aibom_generator
    import tempfile
    doc = run_aibom_generator(HF_ID, Path(tempfile.mkdtemp()))
    src = next(c for c in doc["components"] if c["type"] == "machine-learning-model")
    names = {p["name"] for p in (src.get("modelCard") or {}).get("properties") or []}
    assert KEPT <= names, f"기록해 둔 응답에 있던 키가 사라졌다: {sorted(KEPT - names)}"
    assert os.environ.get("AIBOM_GENERATOR_DIR")
