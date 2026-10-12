"""form — 모아 둔 값을 고른 형태(properties 또는 v0.6 필드)의 자리로 옮긴다. CLI 의 scan --spec 1.7 · v0.6 이 고른다. 모델 쪽 네 필드를 본다.
정적 샘플(tests/data/merged_sample.cdx.json)의 bert 컴포넌트가 실제 owasp 보강 값을 가진다."""
import copy
import json
from pathlib import Path

import pytest

from aibom_cli.cli import main
from aibom_cli.form import apply
from aibom_cli.validate import validate_cdx

SAMPLE = Path(__file__).parent / "data" / "merged_sample.cdx.json"
BERT = "pkg:huggingface/google-bert/bert-base-uncased"

# 샘플 bert 의 원본 값 — modelCard.properties 의 genai:aibom:modelcard:hyperparameter JSON 과 vocabSize,
# contextLength(=component.properties 의 cdx:ai:contextWindow 와 같은 "512"), runtimeRequirement + cdx:ai:runtime
EXPECTED_HYPERPARAMETERS = [
    {"name": "context_length", "value": "512"},
    {"name": "embedding_length", "value": "768"},
    {"name": "block_count", "value": "12"},
    {"name": "attention_head_count", "value": "12"},
    {"name": "feed_forward_length", "value": "3072"},
    {"name": "vocab_size", "value": "30522"},
]
EXPECTED_MAX_SIZE = "512"
EXPECTED_TECHNICAL_REQUIREMENTS = ["python", "transformers"]
CONSUMED = {"genai:aibom:modelcard:hyperparameter", "genai:aibom:modelcard:vocabSize", "genai:aibom:modelcard:contextLength",
            "owasp:aibom:distribution:runtimeRequirement", "cdx:ai:runtime", "cdx:ai:contextWindow"}
UNTOUCHED_CARD = {"genai:aibom:trainingDataAvailable", "genai:aibom:trainingDataStatus", "owasp:aibom:distribution:modelFileSize"}
UNTOUCHED_COMPONENT = {"cdx:ai:provider", "cdx:ai:kind", "cdx:ai:modelFamily", "cdx:ai:source", "cdx:ai:confidence", "cdx:license:category"}


@pytest.fixture
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def component(doc: dict, ref: str) -> dict:
    return next(c for c in doc["components"] if c["bom-ref"] == ref)


def names(props: list[dict] | None) -> list[str]:
    return [p["name"] for p in props or []]


def card_props(comp: dict) -> dict[str, str]:
    return {p["name"]: p["value"] for p in comp["modelCard"].get("properties", [])}


def all_names(comp: dict) -> set[str]:
    return set(names(comp.get("properties"))) | set(names((comp.get("modelCard") or {}).get("properties")))


def model(properties=(), card_properties=(), **extra) -> dict:
    comp = {"type": "machine-learning-model", "name": "m", "bom-ref": "m", **extra}
    if properties:
        comp["properties"] = [{"name": n, "value": v} for n, v in properties]
    if card_properties:
        comp["modelCard"] = {"properties": [{"name": n, "value": v} for n, v in card_properties]}
    return comp


def doc_of(*components: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "components": list(components)}


# -- (a) properties 형 ---------------------------------------------------------------
def test_properties_form_promotes_into_aibom_model_properties(sample):
    out = apply(sample, form="properties", log=lambda m: None)
    bert = component(out, BERT)
    props = card_props(bert)

    for i, hp in enumerate(EXPECTED_HYPERPARAMETERS):
        assert props[f"aibom:model:hyperparameters:{i}:name"] == hp["name"]
        assert props[f"aibom:model:hyperparameters:{i}:value"] == hp["value"]
    assert f"aibom:model:hyperparameters:{len(EXPECTED_HYPERPARAMETERS)}:name" not in props
    assert props["aibom:model:inputs:0:maxSize"] == EXPECTED_MAX_SIZE
    assert [props[f"aibom:model:technicalRequirements:{i}"] for i in range(2)] == EXPECTED_TECHNICAL_REQUIREMENTS
    assert "aibom:model:technicalRequirements:2" not in props
    assert "aibom:model:parameterCount" not in props                  # 샘플에는 원본이 없다 — 아래 별도 테스트

    assert not CONSUMED & all_names(bert)                              # 승격한 원본은 두 목록 모두에서 사라진다
    assert UNTOUCHED_CARD <= set(props) and UNTOUCHED_COMPONENT <= set(names(bert["properties"]))
    assert bert["modelCard"]["modelParameters"]["inputs"] == [{"format": "text"}]                # typed 필드는 건드리지 않는다
    assert "hyperparameters" not in bert["modelCard"]["modelParameters"]
    assert "technicalRequirements" not in bert["modelCard"]["considerations"]
    # 값은 한 곳에만 있다
    assert sum(1 for v in props.values() if v == "30522") == 1
    assert validate_cdx(out, "1.7", log=print)


def test_properties_form_parameter_count(sample):
    bert = component(sample, BERT)
    bert["modelCard"]["properties"].append({"name": "safetensors_total_parameters", "value": "110106428"})
    bert["properties"].append({"name": "cdx:ai:parameterCount", "value": "110106428"})       # 같은 값 — 둘 다 소비
    out = apply(sample, form="properties", log=lambda m: None)
    bert = component(out, BERT)
    assert card_props(bert)["aibom:model:parameterCount"] == "110106428"
    assert not {"safetensors_total_parameters", "cdx:ai:parameterCount"} & all_names(bert)
    assert validate_cdx(out, "1.7", log=print)


# -- (b) typed 형 -------------------------------------------------------------------
def test_typed_form_fills_v06_fields_and_passes_v06_not_17(sample):
    out = apply(sample, form="typed", log=lambda m: None)
    bert = component(out, BERT)
    params, considerations = bert["modelCard"]["modelParameters"], bert["modelCard"]["considerations"]

    assert params["hyperparameters"] == EXPECTED_HYPERPARAMETERS
    assert params["inputs"] == [{"format": "text", "maxSize": EXPECTED_MAX_SIZE}]              # 기존 inputs[0] 에 덧붙인다
    assert considerations["technicalRequirements"] == EXPECTED_TECHNICAL_REQUIREMENTS
    assert "parameterCount" not in params

    assert not any(n.startswith("aibom:model:") for n in all_names(bert))
    assert not CONSUMED & all_names(bert)
    assert UNTOUCHED_CARD <= set(card_props(bert)) and UNTOUCHED_COMPONENT <= set(names(bert["properties"]))

    assert validate_cdx(out, "v0.6", log=print)
    # 공식 1.7 스키마는 modelParameters·considerations·inputOutputMLParameters 가 additionalProperties:false 라
    # hyperparameters / maxSize / technicalRequirements 를 거부한다
    logs: list[str] = []
    assert not validate_cdx(out, "1.7", log=logs.append)
    assert any("hyperparameters" in m for m in logs) and any("maxSize" in m for m in logs) and any("technicalRequirements" in m for m in logs)


def test_typed_form_parameter_count_is_integer_and_creates_inputs():
    doc = doc_of(model(card_properties=[("safetensors_total_parameters", " 1234 "), ("genai:aibom:modelcard:contextLength", "2048")]))
    out = apply(doc, form="typed", log=lambda m: None)
    params = out["components"][0]["modelCard"]["modelParameters"]
    assert params["parameterCount"] == 1234 and isinstance(params["parameterCount"], int)
    assert params["inputs"] == [{"maxSize": "2048"}]                           # format 은 v0.6 스키마상 필수가 아니다
    assert "properties" not in out["components"][0]["modelCard"]              # 모두 소비되어 비면 목록도 없다
    assert validate_cdx(out, "v0.6", log=print)


# -- (c)(d) 건드리지 않는 것 -----------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
def test_component_without_sources_is_byte_identical(form):
    comp = model(properties=[("cdx:ai:kind", "model"), ("syft:package:type", "python")],
                 card_properties=[("genai:aibom:trainingDataAvailable", "true"), ("owasp:aibom:distribution:modelFileSize", "1")],
                 description="desc")
    before = json.dumps(doc_of(comp), sort_keys=False)
    out = apply(doc_of(copy.deepcopy(comp)), form=form, log=lambda m: None)
    assert json.dumps(out, sort_keys=False) == before


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_library_component_is_never_touched(form):
    lib = {"type": "library", "name": "transformers", "bom-ref": "lib", "properties": [{"name": "cdx:ai:runtime", "value": "transformers"}],
           "modelCard": {"properties": [{"name": "genai:aibom:modelcard:contextLength", "value": "512"}]}}
    before = json.dumps(doc_of(lib))
    assert json.dumps(apply(doc_of(copy.deepcopy(lib)), form=form, log=lambda m: None)) == before


# -- (e) 파싱 실패 -----------------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
@pytest.mark.parametrize("raw", ["110M", "-5", "1.1e8", "1,234", ""])
def test_unparsable_parameter_count_is_not_promoted(form, raw):
    logs: list[str] = []
    out = apply(doc_of(model(card_properties=[("safetensors_total_parameters", raw)])), form=form, log=logs.append)
    comp = out["components"][0]
    assert card_props(comp) == {"safetensors_total_parameters": raw}
    assert "modelParameters" not in comp["modelCard"] and "aibom:model:parameterCount" not in card_props(comp)
    assert any("safetensors_total_parameters" in m and "not promoted" in m for m in logs)


def test_unparsable_first_source_falls_through_to_second():
    out = apply(doc_of(model(properties=[("cdx:ai:parameterCount", "42")], card_properties=[("safetensors_total_parameters", "n/a")])),
                form="typed", log=lambda m: None)
    comp = out["components"][0]
    assert comp["modelCard"]["modelParameters"]["parameterCount"] == 42
    assert "properties" not in comp and card_props(comp) == {"safetensors_total_parameters": "n/a"}


# -- 우선순위·불일치 ------------------------------------------------------------------
def test_disagreeing_sources_keep_the_loser_and_log():
    logs: list[str] = []
    comp = model(properties=[("cdx:ai:contextWindow", "4096"), ("cdx:ai:parameterCount", "2")],
                 card_properties=[("genai:aibom:modelcard:contextLength", "512"), ("safetensors_total_parameters", "1")])
    out = apply(doc_of(comp), form="typed", log=logs.append)
    params = out["components"][0]["modelCard"]["modelParameters"]
    assert params["inputs"] == [{"maxSize": "512"}] and params["parameterCount"] == 1          # 우선순위 첫 번째
    assert {p["name"]: p["value"] for p in out["components"][0]["properties"]} == {"cdx:ai:contextWindow": "4096", "cdx:ai:parameterCount": "2"}
    assert "properties" not in out["components"][0]["modelCard"]
    assert sum("differs" in m for m in logs) == 2


def test_hyperparameter_json_then_individual_keys_without_duplicates():
    logs: list[str] = []
    comp = model(card_properties=[
        ("genai:aibom:modelcard:hyperparameter", json.dumps({"vocab_size": 100, "block_count": 4, "tied": True, "note": "x"})),
        ("genai:aibom:modelcard:vocabSize", "100"),            # JSON 과 같은 값 → 소비
        ("genai:aibom:modelcard:blockCount", "5"),             # JSON 과 다른 값 → 남기고 로그
        ("genai:aibom:modelcard:ropeDimensionCount", "64"),    # JSON 에 없음 → 추가
    ])
    out = apply(doc_of(comp), form="properties", log=logs.append)
    props = card_props(out["components"][0])
    hps = [(props[f"aibom:model:hyperparameters:{i}:name"], props[f"aibom:model:hyperparameters:{i}:value"]) for i in range(5)]
    assert hps == [("vocab_size", "100"), ("block_count", "4"), ("tied", "true"), ("note", "x"), ("rope_dimension_count", "64")]
    assert {n for n in props if not n.startswith("aibom:model:")} == {"genai:aibom:modelcard:blockCount"}
    assert any("blockCount" in m for m in logs)


def test_hyperparameter_json_that_is_not_an_object_is_left_alone():
    logs: list[str] = []
    out = apply(doc_of(model(card_properties=[("genai:aibom:modelcard:hyperparameter", "[1, 2]")])), form="typed", log=logs.append)
    assert card_props(out["components"][0]) == {"genai:aibom:modelcard:hyperparameter": "[1, 2]"}
    assert "modelParameters" not in out["components"][0]["modelCard"] and any("JSON object" in m for m in logs)


def test_technical_requirements_union_is_deduplicated():
    comp = model(properties=[("cdx:ai:runtime", "python")], card_properties=[("owasp:aibom:distribution:runtimeRequirement", "python")])
    out = apply(doc_of(comp), form="typed", log=lambda m: None)
    assert out["components"][0]["modelCard"]["considerations"]["technicalRequirements"] == ["python"]
    assert "properties" not in out["components"][0] and "properties" not in out["components"][0]["modelCard"]


def test_existing_typed_value_wins_over_sources():
    comp = model(properties=[("cdx:ai:contextWindow", "4096")])
    comp["modelCard"] = {"modelParameters": {"inputs": [{"format": "text", "maxSize": "512"}]}}
    logs: list[str] = []
    out = apply(doc_of(comp), form="typed", log=logs.append)
    assert out["components"][0]["modelCard"]["modelParameters"]["inputs"] == [{"format": "text", "maxSize": "512"}]
    assert names(out["components"][0]["properties"]) == ["cdx:ai:contextWindow"] and logs


# -- 리뷰 회귀: 스키마상 유효한 입력에서 죽지 않고, 승격한 값 밖은 건드리지 않는다 ------------------
def test_typed_hyperparameter_entry_without_value_does_not_crash():
    """v0.6 스키마는 hyperparameters 항목의 name·value 를 둘 다 선택으로 둔다 — {"name": "lr"} 만 있어도 KeyError 없이 승격한다."""
    comp = model(card_properties=[("genai:aibom:modelcard:vocabSize", "100")])
    comp["modelCard"]["modelParameters"] = {"hyperparameters": [{"name": "lr"}]}
    out = apply(doc_of(comp), form="typed", log=lambda m: None)
    assert out["components"][0]["modelCard"]["modelParameters"]["hyperparameters"] == [{"name": "lr"}, {"name": "vocab_size", "value": "100"}]
    assert "properties" not in out["components"][0]["modelCard"]
    comp = model(card_properties=[("genai:aibom:modelcard:hyperparameter", json.dumps({"lr": "0.1"}))])
    comp["modelCard"]["modelParameters"] = {"hyperparameters": [{"name": "x"}]}
    out = apply(doc_of(comp), form="typed", log=lambda m: None)
    assert out["components"][0]["modelCard"]["modelParameters"]["hyperparameters"] == [{"name": "x"}, {"name": "lr", "value": "0.1"}]
    assert validate_cdx(out, "v0.6", log=print)


def test_typed_nameless_hyperparameter_entry_survives_promotion():
    """이름 없는 기존 항목은 읽지 못해도 지우지 않는다 — 새 항목은 뒤에 덧붙인다."""
    comp = model(card_properties=[("genai:aibom:modelcard:vocabSize", "100")])
    comp["modelCard"]["modelParameters"] = {"hyperparameters": [{"name": "lr", "value": "0.1"}, {"value": "orphan"}]}
    out = apply(doc_of(comp), form="typed", log=lambda m: None)
    assert out["components"][0]["modelCard"]["modelParameters"]["hyperparameters"] == [
        {"name": "lr", "value": "0.1"}, {"value": "orphan"}, {"name": "vocab_size", "value": "100"}]


def test_properties_form_appends_after_existing_indices_without_renumbering():
    comp = model(properties=[("cdx:ai:runtime", "python")], card_properties=[
        ("aibom:model:technicalRequirements:3", "cuda"),                            # 띄엄띄엄한 기존 인덱스도 그대로
        ("aibom:model:hyperparameters:0:name", "lr"),                               # :value 없는 기존 항목도 그대로
        ("genai:aibom:modelcard:blockCount", "4")])
    out = apply(doc_of(comp), form="properties", log=lambda m: None)
    assert [(p["name"], p["value"]) for p in out["components"][0]["modelCard"]["properties"]] == [
        ("aibom:model:technicalRequirements:3", "cuda"), ("aibom:model:hyperparameters:0:name", "lr"),
        ("aibom:model:hyperparameters:1:name", "block_count"), ("aibom:model:hyperparameters:1:value", "4"),
        ("aibom:model:technicalRequirements:4", "python")]


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_empty_modelcard_without_sources_is_byte_identical(form):
    """modelCard: {} 는 두 스키마 모두에서 유효하다 — 소비한 것이 없으면 지우지 않는다."""
    comp = {"type": "machine-learning-model", "name": "m", "bom-ref": "m", "modelCard": {}}
    before = json.dumps(doc_of(comp))
    assert json.dumps(apply(doc_of(copy.deepcopy(comp)), form=form, log=lambda m: None)) == before


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_originally_empty_properties_list_is_kept(form):
    """소비해서 비어 버린 목록만 없앤다 — 원래 [] 였던 component.properties 는 남는다."""
    comp = model(card_properties=[("cdx:ai:runtime", "t")])
    comp["properties"] = []
    out = apply(doc_of(comp), form=form, log=lambda m: None)
    assert out["components"][0]["properties"] == []
    assert "cdx:ai:runtime" not in all_names(out["components"][0])


def test_properties_form_existing_unparsable_parameter_count_wins_and_is_logged():
    """목표에 이미 값이 있으면(정수로 읽히지 않아도) 그 값이 이긴다 — 원본은 남기고 로그에 적는다."""
    logs: list[str] = []
    comp = model(properties=[("cdx:ai:parameterCount", "7")], card_properties=[("aibom:model:parameterCount", "seven")])
    out = apply(doc_of(comp), form="properties", log=logs.append)
    assert card_props(out["components"][0]) == {"aibom:model:parameterCount": "seven"}
    assert names(out["components"][0]["properties"]) == ["cdx:ai:parameterCount"]
    assert any("'seven'" in m and "kept as is" in m for m in logs) and any("cdx:ai:parameterCount" in m and "differs" in m for m in logs)


def test_existing_parameter_count_property_is_not_moved_when_source_agrees():
    comp = model(properties=[("cdx:ai:parameterCount", "7")],
                 card_properties=[("aibom:model:parameterCount", "7"), ("genai:aibom:trainingDataAvailable", "true")])
    out = apply(doc_of(comp), form="properties", log=lambda m: None)
    assert names(out["components"][0]["modelCard"]["properties"]) == ["aibom:model:parameterCount", "genai:aibom:trainingDataAvailable"]
    assert "properties" not in out["components"][0]                                # 같은 값이라 원본은 소비한다


# -- (f) 결정성 ------------------------------------------------------------------
@pytest.mark.parametrize("form", ["properties", "typed"])
def test_apply_is_idempotent(sample, form):
    once = apply(copy.deepcopy(sample), form=form, log=lambda m: None)
    logs: list[str] = []
    twice = apply(copy.deepcopy(once), form=form, log=logs.append)
    assert json.dumps(twice, ensure_ascii=False) == json.dumps(once, ensure_ascii=False)
    assert logs == []                                                              # 두 번째는 원본을 하나도 찾지 못한다


def test_apply_rejects_unknown_form(sample):
    with pytest.raises(ValueError):
        apply(sample, form="xml")


# -- validate CLI --------------------------------------------------------------------
def test_validate_cli_requires_spec_and_names_it(tmp_path, sample, capsys):
    with pytest.raises(SystemExit):
        main(["validate", str(SAMPLE)])                                            # --spec 은 필수
    typed = tmp_path / "typed.json"
    typed.write_text(json.dumps(apply(sample, form="typed", log=lambda m: None)), encoding="utf-8")
    assert main(["validate", str(typed), "--spec", "v0.6"]) == 0
    assert main(["validate", str(typed), "--spec", "1.7"]) == 3                    # 자동 전환 없음
    assert "--spec 1.7" in capsys.readouterr().err
    # properties 형은 1.7 에 맞으니 1.7 을 넓힌 v0.6 에도 맞는다. 메시지는 맞은 스키마만 말하고 문서 형태는 말하지 않는다
    props = tmp_path / "properties.json"
    props.write_text(json.dumps(apply(copy.deepcopy(json.loads(SAMPLE.read_text(encoding="utf-8"))), form="properties",
                                      log=lambda m: None)), encoding="utf-8")
    capsys.readouterr()
    assert main(["validate", str(props), "--spec", "v0.6"]) == 0
    err = capsys.readouterr().err
    assert "Valid against the AI-BOM v0.6 (CycloneDX) schema" in err and "typed" not in err


# -- (e) 완성도 ---------------------------------------------------------------

def dataset(ref: str, facts: dict, hub: bool = True) -> dict:
    name = ref.rsplit("/", 1)[-1].rstrip("@")
    comp = {"type": "data", "name": name, "bom-ref": ref, "data": [{"type": "dataset", "name": name}],
            "properties": [{"name": "aibom-internal:dataset:" + k, "value": v} for k, v in facts.items()]}
    if hub:
        comp["purl"] = ref
    return comp


@pytest.mark.parametrize("form", ["properties", "typed"])
def test_report_counts_filled_regulation_fields_per_component_kind(form):
    """모델은 네 필드, 허브 데이터셋은 일곱, 로컬 데이터는 셋이 분모다. 채운 수는 승격이 끝난 뒤의 상태로 센다."""
    full = model(properties=(("cdx:ai:parameterCount", "110000000"),),
                 card_properties=(("genai:aibom:modelcard:contextLength", "512"), ("genai:aibom:modelcard:vocabSize", "30522"),
                                  ("owasp:aibom:distribution:runtimeRequirement", "python")))
    bare = model()
    bare["bom-ref"] = "bare"
    hub = dataset("pkg:huggingface/datasets/x", {"size": "10", "availability": "direct-download", "modality:0": "text"})
    local = dataset("data:local/d@", {"size": "5", "modality:0": "image", "statistics:0:type": "label:n_unique", "statistics:0:value": "2"}, hub=False)
    report: dict = {}
    apply(doc_of(full, bare, hub, local), form=form, log=lambda m: None, report=report)
    assert report["models"] == {"filled": 4, "total": 8}
    assert report["datasets"] == {"filled": 6, "total": 10}                       # 허브 3/7 + 로컬 3/3
    assert (report["filled"], report["total"]) == (10, 18)


def test_report_ignores_components_that_are_not_models_or_datasets():
    apt = {"type": "data", "name": "apt", "bom-ref": "apt"}                        # cdxgen 의 저장소 설정: data[] 없는 type=data
    lib = {"type": "library", "name": "numpy", "bom-ref": "numpy"}
    report: dict = {}
    apply(doc_of(apt, lib), log=lambda m: None, report=report)
    assert report == {"models": {"filled": 0, "total": 0}, "datasets": {"filled": 0, "total": 0}, "filled": 0, "total": 0}


def test_report_logs_the_missing_fields_of_each_component():
    logs: list[str] = []
    apply(doc_of(model()), log=logs.append, report={})
    assert logs == ["[form] m: 0/4 regulation fields filled, missing hyperparameters, parameterCount, inputs maxSize, technicalRequirements"]

