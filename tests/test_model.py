"""model — 스캔 대상 안의 모델 파일(config.json · gguf · safetensors)에서 규제 필드 둘을 읽고,
form 이 두 형태로 옮긴다. 네트워크는 쓰지 않는다."""
import copy
import json
import struct
from pathlib import Path

import pytest

import sure_aibom.engine.model as md
from sure_aibom.engine.merge import merge
from sure_aibom.engine.form import INTERNAL_MODEL_PREFIX, regulate
from sure_aibom.engine.validate import validate_cdx

MODEL_REF = "pkg:huggingface/acme/tiny"

BERT_CONFIG = {"architectures": ["BertForMaskedLM"], "model_type": "bert", "max_position_embeddings": 512,
               "num_hidden_layers": 12, "hidden_size": 768, "num_attention_heads": 12,
               "intermediate_size": 3072, "vocab_size": 30522}
BERT_HPARAMS = [("block_count", "12"), ("context_length", "512"), ("embedding_length", "768"),
                ("feed_forward_length", "3072"), ("attention_head_count", "12"), ("vocab_size", "30522")]


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(root: Path, rel: str, data) -> Path:
    return write(root, rel, json.dumps(data))


def write_safetensors(root: Path, rel: str, shapes: dict[str, list[int]], metadata: dict | None = None) -> Path:
    header: dict = {name: {"dtype": "F32", "shape": shape, "data_offsets": [0, 4]} for name, shape in shapes.items()}
    if metadata is not None:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode()
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * 8)
    return path


def gguf_bytes(kv: list[tuple[str, int, bytes]], tensors: list[tuple[str, list[int]]], version: int = 3) -> bytes:
    """GGUF 헤더를 형식 문서대로 짠다. kv 는 (키, 값 종류, 값 바이트)."""
    length = "<I" if version == 1 else "<Q"

    def text(v: str) -> bytes:
        b = v.encode()
        return struct.pack(length, len(b)) + b

    body = b"".join(text(k) + struct.pack("<I", kind) + payload for k, kind, payload in kv)
    info = b""
    for name, dims in tensors:
        info += (text(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack(length, d) for d in dims)
                 + struct.pack("<I", 1) + struct.pack("<Q", 0))
    return (GGUF_HEAD(version, len(tensors), len(kv), length) + body + info)


def GGUF_HEAD(version: int, tensors: int, kv: int, length: str) -> bytes:
    return b"GGUF" + struct.pack("<I", version) + struct.pack(length, tensors) + struct.pack(length, kv)


def u32(key: str, value: int) -> tuple[str, int, bytes]:
    return (key, 4, struct.pack("<I", value))


def string(key: str, value: str, length: str = "<Q") -> tuple[str, int, bytes]:
    b = value.encode()
    return (key, 8, struct.pack(length, len(b)) + b)


def string_array(key: str, values: list[str], length: str = "<Q") -> tuple[str, int, bytes]:
    payload = struct.pack("<I", 8) + struct.pack(length, len(values))
    for v in values:
        b = v.encode()
        payload += struct.pack(length, len(b)) + b
    return (key, 9, payload)


def float_array(key: str, values: list[float]) -> tuple[str, int, bytes]:
    return (key, 9, struct.pack("<I", 6) + struct.pack("<Q", len(values)) + b"".join(struct.pack("<f", v) for v in values))


def llama_gguf(**overrides) -> bytes:
    kv = [string("general.architecture", "llama"), string("general.name", "tiny-llama"),
          u32("llama.block_count", 16), u32("llama.context_length", 4096), u32("llama.embedding_length", 2048),
          u32("llama.feed_forward_length", 8192), u32("llama.attention.head_count", 32),
          u32("llama.attention.head_count_kv", 8), u32("llama.rope.dimension_count", 64),
          float_array("llama.rope.freqs", [1.0, 2.0]), string_array("tokenizer.ggml.tokens", ["a", "b", "c"])]
    tensors = [("token_embd.weight", [2048, 100]), ("blk.0.attn_q.weight", [2048, 2048])]
    return gguf_bytes(overrides.get("kv", kv), overrides.get("tensors", tensors), overrides.get("version", 3))


def model_component(*locations: str, **extra) -> dict:
    comp = {"bom-ref": MODEL_REF, "type": "machine-learning-model", "group": "acme", "name": "tiny", "purl": MODEL_REF}
    if locations:
        comp["evidence"] = {"occurrences": [{"location": loc} for loc in locations]}
    comp.update(extra)
    return comp


def doc_of(*components: dict) -> dict:
    return merge([{"bomFormat": "CycloneDX", "specVersion": "1.7", "components": list(components)}], root=("proj", "directory"))


def internal(comp: dict) -> dict[str, str]:
    return {p["name"][len(INTERNAL_MODEL_PREFIX):]: p["value"] for p in comp.get("properties") or []
            if p["name"].startswith(INTERNAL_MODEL_PREFIX)}


def hparams_of(comp: dict) -> list[tuple[str, str]]:
    facts = internal(comp)
    out = []
    for i in range(len(facts)):
        if f"hyperparameters:{i}:name" in facts:
            out.append((facts[f"hyperparameters:{i}:name"], facts[f"hyperparameters:{i}:value"]))
    return out


def model_of(doc: dict) -> dict:
    return next(c for c in doc["components"] if c["type"] == "machine-learning-model")


# -- config.json ---------------------------------------------------------------------
def test_parse_config_uses_llama_cpp_names_and_the_first_integer_candidate(tmp_path):
    assert list(md.parse_config(write_json(tmp_path, "config.json", BERT_CONFIG)).items()) == BERT_HPARAMS
    # 계열마다 다른 키도 같은 이름으로. null 인 앞 후보는 건너뛰고 다음 후보를 본다
    gpt2 = {"n_layer": 12, "n_ctx": None, "n_positions": 1024, "n_embd": 768, "n_inner": 3072, "n_head": 12,
            "rotary_dim": 64, "vocab_size": 50257}
    assert md.parse_config(write_json(tmp_path, "gpt2.json", gpt2)) == {
        "block_count": "12", "context_length": "1024", "embedding_length": "768", "feed_forward_length": "3072",
        "attention_head_count": "12", "rope_dimension_count": "64", "vocab_size": "50257"}


def test_parse_config_skips_non_integers_and_merges_text_config(tmp_path):
    odd = {"num_hidden_layers": "12", "hidden_size": 768.5, "num_attention_heads": True, "vocab_size": 30522,
           "max_position_embeddings": [512]}
    assert md.parse_config(write_json(tmp_path, "a.json", odd)) == {"vocab_size": "30522"}   # 문자열·실수·bool·목록은 버린다
    vlm = {"hidden_size": 1024, "text_config": {"hidden_size": 4096, "num_hidden_layers": 32}}
    assert md.parse_config(write_json(tmp_path, "b.json", vlm)) == {"block_count": "32", "embedding_length": "4096"}
    assert md.parse_config(write_json(tmp_path, "c.json", [1, 2])) == {}                     # 객체가 아니면 빈 dict
    with pytest.raises(ValueError):
        md.parse_config(write(tmp_path, "big.json", " " * (md.CONFIG_LIMIT + 1)))


# -- safetensors ---------------------------------------------------------------------
def test_safetensors_parameters_sums_shape_products(tmp_path):
    path = write_safetensors(tmp_path, "model.safetensors", {"a": [2, 3], "b": [4], "scalar": []}, metadata={"format": "pt"})
    assert md.safetensors_parameters(path) == 6 + 4 + 1                                      # __metadata__ 는 세지 않는다
    assert md.safetensors_parameters(write_safetensors(tmp_path, "empty.safetensors", {})) == 0
    bad = tmp_path / "bad.safetensors"
    bad.write_bytes(struct.pack("<Q", 0))
    with pytest.raises(ValueError):
        md.safetensors_parameters(bad)
    short = tmp_path / "short.safetensors"
    short.write_bytes(struct.pack("<Q", 100) + b"{}")
    with pytest.raises(ValueError):
        md.safetensors_parameters(short)
    huge = tmp_path / "huge.safetensors"
    huge.write_bytes(struct.pack("<Q", md.SAFETENSORS_HEADER_LIMIT + 1))
    with pytest.raises(ValueError):
        md.safetensors_parameters(huge)


def test_safetensors_total_follows_the_shard_index(tmp_path):
    root = tmp_path
    write_safetensors(root, "model-00001-of-00002.safetensors", {"a": [10]})
    write_safetensors(root, "model-00002-of-00002.safetensors", {"b": [20]})
    write_safetensors(root, "consolidated.safetensors", {"everything": [999]})               # 인덱스에 없으니 세지 않는다
    write_json(root, "model.safetensors.index.json",
               {"weight_map": {"a": "model-00001-of-00002.safetensors", "b": "model-00002-of-00002.safetensors"}})
    assert md._safetensors_total(root, root.resolve(), log=lambda m: None) == 30
    (root / "model.safetensors.index.json").unlink()
    assert md._safetensors_total(root, root.resolve(), log=lambda m: None) == 10 + 20 + 999   # 인덱스가 없으면 전부
    assert md._safetensors_total(root / "nowhere", root.resolve(), log=lambda m: None) is None


def test_safetensors_total_is_none_when_a_file_cannot_be_read(tmp_path):
    write_safetensors(tmp_path, "good.safetensors", {"a": [10]})
    (tmp_path / "torn.safetensors").write_bytes(b"\x01\x02")
    logs: list[str] = []
    assert md._safetensors_total(tmp_path, tmp_path.resolve(), logs.append) is None           # 일부만 세면 틀린 값이 된다
    assert any("torn.safetensors" in m for m in logs)


# -- gguf ----------------------------------------------------------------------------
def test_parse_gguf_reads_architecture_keys_and_counts_tensor_elements(tmp_path):
    path = tmp_path / "tiny.gguf"
    path.write_bytes(llama_gguf())
    hparams, count = md.parse_gguf(path)
    assert hparams == {"block_count": "16", "context_length": "4096", "embedding_length": "2048",
                       "feed_forward_length": "8192", "attention_head_count": "32", "attention_head_count_kv": "8",
                       "rope_dimension_count": "64", "vocab_size": "3"}                       # vocab 은 토큰 배열 길이
    assert count == 2048 * 100 + 2048 * 2048


def test_parse_gguf_prefers_an_explicit_vocab_size_and_handles_version_1_lengths(tmp_path):
    kv = [string("general.architecture", "llama"), u32("llama.vocab_size", 32000),
          string_array("tokenizer.ggml.tokens", ["a", "b"])]
    path = tmp_path / "v.gguf"
    path.write_bytes(gguf_bytes(kv, [("w", [2, 2])]))
    assert md.parse_gguf(path)[0]["vocab_size"] == "32000"
    old = tmp_path / "v1.gguf"
    old.write_bytes(gguf_bytes([string("general.architecture", "llama", "<I"), u32("llama.block_count", 4)], [("w", [3])], version=1))
    assert md.parse_gguf(old) == ({"block_count": "4"}, 3)


def test_parse_gguf_rejects_broken_files(tmp_path):
    for name, data in [("nomagic.gguf", b"XXXX" + b"\0" * 20),
                       ("badversion.gguf", b"GGUF" + struct.pack("<I", 9) + b"\0" * 16),
                       ("short.gguf", b"GGUF"),
                       ("torn.gguf", b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 1) + struct.pack("<Q", 1)),
                       ("manykv.gguf", b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", md.GGUF_MAX_KV + 1))]:
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(ValueError):
            md.parse_gguf(path)
    unknown = tmp_path / "unknownkind.gguf"
    unknown.write_bytes(gguf_bytes([("k", 99, b"\0")], []))
    with pytest.raises(ValueError):
        md.parse_gguf(unknown)
    nodims = tmp_path / "dims.gguf"
    nodims.write_bytes(gguf_bytes([], [("w", [1] * (md.GGUF_MAX_DIMS + 1))]))
    with pytest.raises(ValueError):
        md.parse_gguf(nodims)


def test_parse_gguf_without_architecture_yields_no_hyperparameters(tmp_path):
    path = tmp_path / "noarch.gguf"
    path.write_bytes(gguf_bytes([u32("llama.block_count", 16)], [("w", [5])]))
    assert md.parse_gguf(path) == ({}, 5)


# -- discover --------------------------------------------------------------------------
def test_discover_fills_hyperparameters_and_parameter_count_from_a_model_directory(tmp_path):
    write_json(tmp_path, "models/config.json", BERT_CONFIG)
    write_safetensors(tmp_path, "models/model.safetensors", {"w": [30522, 768]})
    logs: list[str] = []
    out = md.discover_models(doc_of(model_component("models/README.md", "models/config.json")), str(tmp_path), logs.append)
    comp = model_of(out)
    assert hparams_of(comp) == BERT_HPARAMS
    assert internal(comp)["parameterCount"] == str(30522 * 768)
    assert [m for m in logs if "[model]" in m] == []                                   # 잘 읽은 것은 조용하다


def test_discover_reads_gguf_named_in_the_evidence(tmp_path):
    (tmp_path / "weights").mkdir()
    (tmp_path / "weights" / "tiny.gguf").write_bytes(llama_gguf())
    comp = model_of(md.discover_models(doc_of(model_component("weights/tiny.gguf")), str(tmp_path), log=lambda m: None))
    assert dict(hparams_of(comp))["block_count"] == "16" and internal(comp)["parameterCount"] == str(2048 * 100 + 2048 * 2048)


def test_first_file_wins_when_two_files_disagree(tmp_path):
    write_json(tmp_path, "config.json", {"num_hidden_layers": 12, "hidden_size": 768})
    (tmp_path / "a.gguf").write_bytes(gguf_bytes([string("general.architecture", "llama"), u32("llama.block_count", 16),
                                                  u32("llama.context_length", 99)], []))
    logs: list[str] = []
    comp = model_of(md.discover_models(doc_of(model_component("config.json", "a.gguf")), str(tmp_path), logs.append))
    facts = dict(hparams_of(comp))
    assert facts["block_count"] == "16" and facts["context_length"] == "99"         # a.gguf 를 먼저 읽는다 (경로 정렬)
    assert facts["embedding_length"] == "768"                                       # 겹치지 않는 값은 뒤 파일에서 온다
    assert [m for m in logs if "dropped" in m] == [f"[model] {MODEL_REF}: hyperparameters[block_count] already has '16', '12' from config.json dropped"]


@pytest.mark.parametrize("component", [
    {"bom-ref": "x", "type": "library", "name": "numpy"},                            # 모델이 아니다
    model_component(),                                                               # evidence 가 없다
    model_component("models/README.md", "train.py"),                                 # 읽는 파일이 아니다
    model_component("models/missing.json", "gone.gguf"),                             # 파일이 없다
])
def test_documents_without_readable_model_files_are_byte_identical(tmp_path, component):
    write_json(tmp_path, "models/config.json", BERT_CONFIG)                          # 가리키지 않으면 읽지 않는다
    write(tmp_path, "models/README.md", "# card\n")
    write(tmp_path, "train.py", "import torch\n")
    doc = doc_of(component)
    before = json.dumps(doc, ensure_ascii=False)
    out = md.discover_models(doc, str(tmp_path), log=lambda m: None)
    assert json.dumps(out, ensure_ascii=False) == before
    assert json.dumps(regulate(copy.deepcopy(out), form="typed", log=lambda m: None), ensure_ascii=False) == before


def test_image_target_and_unreadable_config_change_nothing(tmp_path):
    doc = doc_of(model_component("config.json"))
    before = json.dumps(doc, ensure_ascii=False)
    assert json.dumps(md.discover_models(copy.deepcopy(doc), "alpine:3.20", log=lambda m: None), ensure_ascii=False) == before
    write(tmp_path, "config.json", "{not json")
    logs: list[str] = []
    assert json.dumps(md.discover_models(copy.deepcopy(doc), str(tmp_path), logs.append), ensure_ascii=False) == before
    assert any("config.json: skipped, cannot read" in m for m in logs)


def test_a_symlink_pointing_outside_the_target_is_skipped(tmp_path):
    outside = tmp_path / "outside"
    write_json(outside, "config.json", BERT_CONFIG)
    root = tmp_path / "proj"
    root.mkdir()
    try:
        (root / "config.json").symlink_to(outside / "config.json")
    except (OSError, NotImplementedError):
        pytest.skip("심볼릭 링크를 만들 수 없다")
    doc = doc_of(model_component("config.json"))
    before = json.dumps(doc, ensure_ascii=False)
    assert json.dumps(md.discover_models(doc, str(root), log=lambda m: None), ensure_ascii=False) == before


def test_evidence_locations_may_be_absolute_or_windows_style(tmp_path):
    write_json(tmp_path, "models/config.json", BERT_CONFIG)
    for location in (str(tmp_path / "models" / "config.json"), "models\\config.json", "/models/config.json"):
        comp = model_of(md.discover_models(doc_of(model_component(location)), str(tmp_path), log=lambda m: None))
        assert dict(hparams_of(comp))["block_count"] == "12", location


# -- form: 두 형태 ----------------------------------------------------------------
@pytest.fixture
def discovered(tmp_path) -> dict:
    write_json(tmp_path, "models/config.json", BERT_CONFIG)
    write_safetensors(tmp_path, "models/model.safetensors", {"w": [30522, 768]})
    return md.discover_models(doc_of(model_component("models/config.json")), str(tmp_path), log=lambda m: None)


def test_properties_form_moves_local_facts_to_aibom_model_keys(discovered):
    out = regulate(copy.deepcopy(discovered), form="properties", log=print)
    comp = model_of(out)
    card = {p["name"]: p["value"] for p in comp["modelCard"]["properties"]}
    assert (card["aibom:model:hyperparameters:0:name"], card["aibom:model:hyperparameters:0:value"]) == ("block_count", "12")
    assert card["aibom:model:parameterCount"] == str(30522 * 768)
    assert "properties" not in comp and "aibom-internal" not in json.dumps(out)      # 내부 키는 목록째 사라진다
    assert validate_cdx(out, "1.7", log=print) and validate_cdx(out, "v0.6", log=print)


def test_typed_form_fills_model_parameters(discovered):
    out = regulate(copy.deepcopy(discovered), form="typed", log=print)
    params = model_of(out)["modelCard"]["modelParameters"]
    assert params["hyperparameters"] == [{"name": n, "value": v} for n, v in BERT_HPARAMS]
    assert params["parameterCount"] == 30522 * 768 and isinstance(params["parameterCount"], int)
    assert "aibom-internal" not in json.dumps(out) and "aibom:model:" not in json.dumps(out)
    assert validate_cdx(out, "v0.6", log=print)


def test_tool_values_win_over_local_files_and_internal_keys_always_go(discovered):
    comp = model_of(discovered)
    comp["properties"] = [{"name": "safetensors_total_parameters", "value": "999"},
                          {"name": "genai:aibom:modelcard:blockCount", "value": "99"}] + comp["properties"]
    logs: list[str] = []
    out = regulate(copy.deepcopy(discovered), form="typed", log=logs.append)
    params = model_of(out)["modelCard"]["modelParameters"]
    assert params["parameterCount"] == 999                                            # 허브 값이 이긴다
    assert dict((h["name"], h["value"]) for h in params["hyperparameters"])["block_count"] == "99"
    assert "aibom-internal" not in json.dumps(out)
    assert sum("dropped" in m for m in logs) == 2


def test_applying_twice_changes_nothing(discovered):
    once = regulate(copy.deepcopy(discovered), form="typed", log=lambda m: None)
    assert json.dumps(regulate(copy.deepcopy(once), form="typed", log=lambda m: None)) == json.dumps(once)
