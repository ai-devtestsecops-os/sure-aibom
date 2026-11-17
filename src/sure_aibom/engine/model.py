"""M-BOM 보강. cdxgen 이 담지 못한 모델 컴포넌트 값을 채운다. 병합 뒤, 규제 정규화 앞에서 두 함수가 차례로 돈다.

    enrich_local_models 로컬 모델. 스캔 대상 안의 모델 파일에서 규제 필드 값을 읽는다
    enrich_hub_models   허브 모델. 코드가 부르는 Hugging Face 모델을 Hub API 응답과 OWASP aibom-generator 로 보강한다

[로컬 모델] 스캔 대상 안의 모델 파일에서 규제 필드 값을 읽는다.

컴포넌트를 만들지도, 규제 필드가 아닌 값을 더하지도 않는다. 읽는 값은 규제 필드 둘뿐이다.
    hyperparameters   config.json (HuggingFace 형식) · *.gguf 헤더
    parameterCount    *.safetensors 헤더 (샤드는 합산) · *.gguf 텐서 정보
이름은 llama.cpp 의 이름으로 맞춘다 (block_count, embedding_length …). 같은 값을 계열마다 다른 키로 적는 것을
막고, OWASP aibom-generator 가 허브에서 채우는 이름과도 같아야 한 모델에 두 이름이 들어가지 않는다.
아키텍처·토크나이저·양자화처럼 같은 파일에 있어도 규제 필드가 아닌 값은 읽지 않는다.

읽을 파일은 cdxgen 이 모델 컴포넌트에 남긴 evidence.occurrences 에서 온다 (config.json, *.gguf). cdxgen 은 이 두
파일을 이미 읽으면서 하이퍼파라미터만 버린다. *.safetensors 는 cdxgen 이 보지 않으므로 config.json 과 같은
디렉터리에서 찾는다. 컴포넌트가 없으면 만들지 않는다 (가중치 파일만 있고 config.json·README 가 없는 폴더는 그대로).

가중치는 절대 읽지 않는다 (헤더·메타데이터만). pickle 을 담은 것(.bin, .pt, .pth, .ckpt, .pkl)은 열지 않는다.
값은 aibom-internal:model:* 프로퍼티로 두고 form 이 고른 형태의 자리로 옮기며 지운다 (출력에는 남지 않는다).

[허브 모델] 허브 모델(코드가 부르는 Hugging Face 모델)을 보강한다. 두 단계다.

1) Hub API — 허브 모델마다 GET /api/models/<id> 응답을 받아 비어 있는 필드만 채운다. 받은 응답은 report["model_infos"] 로
   남겨, 뒤의 D-BOM 이 모델 카드의 데이터셋을 읽을 때 다시 쓴다 (같은 응답을 두 번 받지 않는다). 로컬 모델 카드에서 cdxgen 이
   읽는 것과 같은 키·같은 규칙이다.
       version                                     sha (조회 시점의 main 커밋. 허브 데이터셋과 같은 규칙)
       licenses                                    cardData.license (other 면 license_name · license_link)
       description                                 cardData.model_description, 없으면 cardData.description
       supplier.name                               author (저장소 소유 계정)
       externalReferences                          distribution https://huggingface.co/<id>, documentation arxiv:<번호> 태그의 논문
       pedigree.ancestors · notes                  cardData.base_model (+ base_model_relation 을 notes 앞에 "Hugging Face relation: …" 로)
       modelCard.modelParameters.task              pipeline_tag, 없으면 model-index 의 task
                                .architectureFamily  config.model_type, 없으면 gguf.architecture
                                .modelArchitecture   config.architectures[0]
                                .inputs/outputs[].format   task 를 cdxgen 과 같은 표로 바꾼 것, 표에 없으면 widget 예시로
       modelCard.quantitativeAnalysis.performanceMetrics   model-index 결과의 metrics (cdxgen 과 같은 모양: type, value, slice)
       (facts) releaseTime                          lastModified. CycloneDX 에 자리가 없어 메모리 부가 기록(facts.py)으로만 두고 SPDX 변환기가 적는다
   규제 필드 원본 (aibom-internal:model:*, form 이 옮기고 지운다): parameterCount ← safetensors.total, 없으면 gguf.total;
   inputs maxSize ← gguf.context_length.
2) OWASP aibom-generator — 규제 필드 원본만 가져온다 (OWASP_SOURCES: modelCard.properties 의 하이퍼파라미터 묶음과 개별 키,
   contextLength, runtimeRequirement, safetensors_total_parameters). 나머지 출력은 버린다: 값이 없을 때 고정값(description
   "No description available", task text-generation, modelArchitecture transformer)을 채우고, README 를 정규식으로 잘라
   technicalLimitations·datasets 를 만들며, 허브에 없는 저장소에도 실패하지 않고 그런 BOM 을 낸다. 가져온 원본이 없으면 실패로 센다.
   원본을 가져온 출력이 metadata.tools 에 자기를 적은 도구 항목은 문서의 도구 목록에 더한다 (한 번만).

허브 모델: purl 이 pkg:huggingface/<ns>/<name> 인 모델 컴포넌트 가운데 로컬 모델 파일(README.md, config.json, adapter_config.json,
Modelfile, *.gguf, *.safetensors)에서 찾은 것이 아닌 것. 로컬 폴더는 그 파일들이 근거다 (config 의 _name_or_path 는 베이스 모델
이름일 수 있어 허브 값이 그 모델의 것이 아닐 수 있다).
매칭 키: purl 의 pkg:huggingface/<ns>/<name> (리비전 제외 — 두 도구가 버전 표기를 달리 한다)
"""
from __future__ import annotations

import copy
import json
import re
import struct
from pathlib import Path, PurePosixPath
from typing import Iterable

from ..exceptions import RunnerError
# external 은 import 하지 않는다: enrich_hub_models 는 service 가 넘겨준 external 모듈(hub, aibom_generator)로 부른다
from ..utils.licenses import card_licenses
from .facts import Facts
from .form import HYPERPARAMETER_BY_PROPERTY, HYPERPARAMETER_JSON

MODEL_TYPE = "machine-learning-model"
INTERNAL_MODEL_PREFIX = "aibom-internal:model:"      # form 이 읽어 가고 지운다


# ── 로컬 모델: 스캔 대상 안의 모델 파일 ────────────────────────────────────────────────

CONFIG_NAME = "config.json"
GGUF_SUFFIX = ".gguf"
SAFETENSORS_SUFFIX = ".safetensors"

# config.json 키 → llama.cpp 이름. 후보 순서는 llama.cpp convert_hf_to_gguf.py 의 find_hparam 과 같다.
# 앞의 후보부터 보되, 값이 정수인 첫 후보를 쓴다 (null 로 비워 둔 키를 건너뛴다).
HPARAM_BY_CONFIG_KEY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("block_count", ("n_layers", "num_hidden_layers", "n_layer", "num_layers")),
    ("context_length", ("max_position_embeddings", "n_ctx", "n_positions", "max_length", "max_sequence_length",
                        "model_max_length")),
    ("embedding_length", ("hidden_size", "n_embd", "dim")),
    ("feed_forward_length", ("intermediate_size", "n_inner", "hidden_dim")),
    ("attention_head_count", ("num_attention_heads", "n_head", "n_heads")),
    ("attention_head_count_kv", ("num_key_value_heads", "n_kv_heads")),
    ("rope_dimension_count", ("rotary_dim", "rope_dim")),
    ("vocab_size", ("vocab_size",)),
)
# GGUF 헤더 키 → 같은 이름. 키 앞에는 general.architecture 값이 붙는다 (llama.block_count 처럼).
HPARAM_BY_GGUF_KEY: tuple[tuple[str, str], ...] = (
    ("block_count", "block_count"), ("context_length", "context_length"), ("embedding_length", "embedding_length"),
    ("feed_forward_length", "feed_forward_length"), ("attention_head_count", "attention.head_count"),
    ("attention_head_count_kv", "attention.head_count_kv"), ("rope_dimension_count", "rope.dimension_count"),
    ("vocab_size", "vocab_size"),
)
HPARAM_ORDER: tuple[str, ...] = tuple(name for name, _ in HPARAM_BY_CONFIG_KEY)   # 출력 순서

CONFIG_LIMIT = 16 * 1024 ** 2                   # 이보다 큰 config.json 은 읽지 않는다
SAFETENSORS_HEADER_LIMIT = 100 * 1024 ** 2
GGUF_MAGIC = b"GGUF"
GGUF_VERSIONS = (1, 2, 3)
GGUF_HEADER_LIMIT = 64 * 1024 ** 2              # 메타데이터 + 텐서 정보를 이보다 많이 읽지 않는다
GGUF_MAX_KV = 100_000
GGUF_MAX_TENSORS = 1_000_000
GGUF_MAX_STRING = 16 * 1024 ** 2
GGUF_MAX_DIMS = 8
# GGUF 값 종류 → struct 형식. 8=문자열, 9=배열은 따로 읽는다.
GGUF_FIXED: dict[int, str] = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
                              10: "<Q", 11: "<q", 12: "<d"}
GGUF_STRING, GGUF_ARRAY = 8, 9

_READ_ERRORS = (OSError, ValueError, UnicodeDecodeError, struct.error, RecursionError)


# ── 진입점 ──────────────────────────────────────────────────────────────────

def enrich_local_models(merged: dict, target: str, log=print) -> dict:
    """모델 컴포넌트마다 대상 안의 모델 파일을 읽어 사실을 붙인다. 읽을 것이 없으면 문서는 바이트 단위로 그대로다."""
    root = Path(target)
    if not root.is_dir():
        return merged
    try:
        root_resolved = root.resolve()
    except OSError:
        return merged
    for comp in _walk(merged.get("components") or []):
        if comp.get("type") == MODEL_TYPE:
            _apply(comp, root, root_resolved, log)
    return merged


def _walk(components: Iterable[dict]):
    for c in components:
        yield c
        yield from _walk(c.get("components") or [])


def _apply(comp: dict, root: Path, root_resolved: Path, log) -> None:
    label = comp.get("bom-ref") or comp.get("name") or "?"
    hparams: dict[str, str] = {}
    parameter_count: int | None = None
    for path in _model_files(comp, root, root_resolved):
        rel = _relative(path, root_resolved)
        if path.name == CONFIG_NAME:
            found = _read(_parse_config, path, rel, log)
            if found is None:
                continue
            _take(hparams, found, rel, label, log)
            if parameter_count is None:
                parameter_count = _safetensors_total(path.parent, root_resolved, log)
        else:
            got = _read(_parse_gguf, path, rel, log)
            if got is None:
                continue
            found, count = got
            _take(hparams, found, rel, label, log)
            if parameter_count is None:
                parameter_count = count

    props = _internal_properties(hparams, parameter_count)
    if props:
        comp["properties"] = (comp.get("properties") or []) + props


def _read(parse, path: Path, rel: str, log):
    try:
        return parse(path)
    except _READ_ERRORS as e:
        log(f"[model] {rel}: skipped, cannot read ({e.__class__.__name__}: {e})")
        return None


def _take(hparams: dict[str, str], found: dict[str, str], rel: str, label: str, log) -> None:
    """먼저 읽은 파일의 값이 이긴다. 값이 다르면 알리고 버린다 (한 이름이 두 번 나오지 않는다)."""
    for name, value in found.items():
        if name not in hparams:
            hparams[name] = value
        elif hparams[name] != value:
            log(f"[model] {label}: hyperparameters[{name}] already has {hparams[name]!r}, {value!r} from {rel} dropped")


# ── 읽을 파일 찾기 ───────────────────────────────────────────────────────────

def _model_files(comp: dict, root: Path, root_resolved: Path) -> list[Path]:
    """cdxgen 이 남긴 evidence.occurrences 중 config.json 과 *.gguf. 대상 밖을 가리키면 버린다. 경로 정렬 순."""
    found: set[Path] = set()
    for occurrence in ((comp.get("evidence") or {}).get("occurrences") or []):
        location = occurrence.get("location") if isinstance(occurrence, dict) else None
        if not isinstance(location, str) or not location:
            continue
        name = PurePosixPath(location.replace("\\", "/")).name
        if name != CONFIG_NAME and not name.lower().endswith(GGUF_SUFFIX):
            continue
        path = inside_file(root, root_resolved, location)
        if path is not None:
            found.add(path)
    return sorted(found, key=str)


def inside_file(root: Path, root_resolved: Path, location: str) -> Path | None:
    """대상 루트 기준 경로(cdxgen 이 쓰는 모양)를 실제 파일로. 링크를 따라간 뒤에도 대상 안이어야 한다."""
    text = location.replace("\\", "/")
    candidates = [root / text.lstrip("/")]
    if Path(text).is_absolute():
        candidates.insert(0, Path(text))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and _inside(resolved, root_resolved):
                return resolved
        except OSError:
            continue
    return None


def _inside(path: Path, root_resolved: Path) -> bool:
    try:
        path.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def _relative(path: Path, root_resolved: Path) -> str:
    try:
        return path.relative_to(root_resolved).as_posix()
    except ValueError:
        return path.name


# ── config.json ─────────────────────────────────────────────────────────────

def _parse_config(path: Path) -> dict[str, str]:
    """HuggingFace config.json → llama.cpp 이름의 하이퍼파라미터. 정수 값만 가져온다."""
    if path.stat().st_size > CONFIG_LIMIT:
        raise ValueError("config.json 이 너무 크다")
    with path.open(encoding="utf-8", errors="replace") as fh:
        config = json.load(fh)
    if not isinstance(config, dict):
        return {}
    text_config = config.get("text_config")
    if isinstance(text_config, dict):                  # 멀티모달은 텍스트 쪽 값이 이긴다 (llama.cpp 와 같다)
        config = {**config, **text_config}
    out: dict[str, str] = {}
    for name, keys in HPARAM_BY_CONFIG_KEY:
        for key in keys:
            if _is_int(config.get(key)):
                out[name] = str(int(config[key]))
                break
    return out


# ── safetensors ─────────────────────────────────────────────────────────────

def _safetensors_total(directory: Path, root_resolved: Path, log) -> int | None:
    """디렉터리의 *.safetensors 파라미터 수 합. 인덱스가 있으면 거기 적힌 샤드만 센다. 하나라도 못 읽으면 None."""
    try:
        files = sorted((p for p in directory.glob(f"*{SAFETENSORS_SUFFIX}")
                        if p.is_file() and _inside(p.resolve(), root_resolved)), key=str)
    except OSError:
        return None
    if not files:
        return None
    total = 0
    for path in _shards(directory, files):
        n = _read(_safetensors_parameters, path, _relative(path, root_resolved), log)
        if n is None:
            return None
        total += n
    return total or None


def _shards(directory: Path, files: list[Path]) -> list[Path]:
    """model.safetensors.index.json 의 weight_map 에 적힌 파일만. 인덱스가 없거나 못 읽으면 전부."""
    for index in sorted(directory.glob(f"*{SAFETENSORS_SUFFIX}.index.json")):
        try:
            with index.open(encoding="utf-8") as fh:
                weight_map = json.load(fh).get("weight_map")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(weight_map, dict):
            names = {v for v in weight_map.values() if isinstance(v, str)}
            chosen = [p for p in files if p.name in names]
            if chosen:
                return chosen
    return files


def _safetensors_parameters(path: Path) -> int:
    """safetensors 헤더(앞 8바이트 길이 + JSON)의 텐서 shape 곱의 합. 가중치는 읽지 않는다."""
    with path.open("rb") as fh:
        head = fh.read(8)
        if len(head) < 8:
            raise ValueError("safetensors 헤더가 잘렸다")
        length = struct.unpack("<Q", head)[0]
        if not 0 < length <= SAFETENSORS_HEADER_LIMIT:
            raise ValueError(f"safetensors 헤더 길이가 이상하다: {length}")
        raw = fh.read(length)
    if len(raw) != length:
        raise ValueError("safetensors 헤더가 잘렸다")
    header = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(header, dict):
        raise ValueError("safetensors 헤더가 객체가 아니다")
    total = 0
    for name, entry in header.items():
        if name == "__metadata__" or not isinstance(entry, dict):
            continue
        shape = entry.get("shape")
        if not isinstance(shape, list) or not all(_is_int(d) and d >= 0 for d in shape):
            continue
        count = 1
        for d in shape:
            count *= int(d)
        total += count
    return total


# ── gguf ────────────────────────────────────────────────────────────────────

def _parse_gguf(path: Path) -> tuple[dict[str, str], int | None]:
    """GGUF 헤더 → (하이퍼파라미터, 파라미터 수). 메타데이터 KV 표와 텐서 정보만 읽고 텐서 데이터는 읽지 않는다."""
    with path.open("rb") as fh:
        head = fh.read(8)
        if len(head) < 8 or head[:4] != GGUF_MAGIC:
            raise ValueError("GGUF 파일이 아니다")
        version = struct.unpack("<I", head[4:8])[0]
        if version not in GGUF_VERSIONS:
            raise ValueError(f"모르는 GGUF 판 {version}")
        reader = _Gguf(fh, version)
        tensor_count, kv_count = reader.count(), reader.count()
        if kv_count > GGUF_MAX_KV or tensor_count > GGUF_MAX_TENSORS:
            raise ValueError("gguf 헤더가 너무 크다")
        values: dict[str, object] = {}
        lengths: dict[str, int] = {}                   # 배열은 개수만 남긴다 (토큰 목록을 메모리에 올리지 않는다)
        for _ in range(kv_count):
            key = reader.string()
            value = reader.value(reader.number("<I"))
            if isinstance(value, _ArrayLength):
                lengths[key] = int(value)
            else:
                values[key] = value

        hparams: dict[str, str] = {}
        architecture = values.get("general.architecture")
        if isinstance(architecture, str) and architecture:
            for name, suffix in HPARAM_BY_GGUF_KEY:
                value = values.get(f"{architecture}.{suffix}")
                if _is_int(value):
                    hparams[name] = str(int(value))
        if "vocab_size" not in hparams and lengths.get("tokenizer.ggml.tokens"):
            hparams["vocab_size"] = str(lengths["tokenizer.ggml.tokens"])

        total = 0
        for _ in range(tensor_count):
            reader.string()                            # 텐서 이름
            dims = reader.number("<I")
            if dims > GGUF_MAX_DIMS:
                raise ValueError(f"텐서 차원이 {dims}개다")
            count = 1
            for _ in range(dims):
                count *= reader.count()
            reader.number("<I")                        # 텐서 종류
            reader.number("<Q")                        # 데이터 오프셋
            total += count
    return hparams, total or None


class _ArrayLength(int):
    """배열 값 자리에 개수만 담아 돌려준다."""


class _Gguf:
    """GGUF 헤더 판독기. 읽은 바이트를 세어 상한을 넘으면 멈춘다. 길이 필드는 판 1 이 32비트, 2·3 이 64비트다."""

    def __init__(self, fh, version: int) -> None:
        self.fh = fh
        self.read = 0
        self.length_format = "<I" if version == 1 else "<Q"

    def take(self, n: int) -> bytes:
        if n < 0 or self.read + n > GGUF_HEADER_LIMIT:
            raise ValueError("gguf 헤더가 너무 길다")
        data = self.fh.read(n)
        if len(data) != n:
            raise ValueError("gguf 헤더가 잘렸다")
        self.read += n
        return data

    def number(self, fmt: str):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def count(self) -> int:
        return self.number(self.length_format)

    def string(self) -> str:
        n = self.count()
        if n > GGUF_MAX_STRING:
            raise ValueError("gguf 문자열이 너무 길다")
        return self.take(n).decode("utf-8", "replace")

    def value(self, kind: int):
        fmt = GGUF_FIXED.get(kind)
        if fmt is not None:
            return self.number(fmt)
        if kind == GGUF_STRING:
            return self.string()
        if kind == GGUF_ARRAY:
            element, n = self.number("<I"), self.count()
            element_format = GGUF_FIXED.get(element)
            if element_format is not None:
                self.take(struct.calcsize(element_format) * n)     # 고정 길이는 통째로 건너뛴다
            else:
                for _ in range(n):
                    self.value(element)
            return _ArrayLength(n)
        raise ValueError(f"모르는 gguf 값 종류 {kind}")


# ── 내부 프로퍼티 ────────────────────────────────────────────────────────────

def _internal_properties(hparams: dict[str, str], parameter_count: int | None) -> list[dict]:
    """사실 → aibom-internal:model:* 프로퍼티. 키 모양은 정의서의 aibom:model:* 와 같다 (접두어만 다르다)."""
    props: list[dict] = []
    for i, name in enumerate(n for n in HPARAM_ORDER if n in hparams):
        props += [{"name": f"{INTERNAL_MODEL_PREFIX}hyperparameters:{i}:name", "value": name},
                  {"name": f"{INTERNAL_MODEL_PREFIX}hyperparameters:{i}:value", "value": hparams[name]}]
    if parameter_count is not None:
        props.append({"name": INTERNAL_MODEL_PREFIX + "parameterCount", "value": str(parameter_count)})
    return props


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ── 허브 모델: Hub API 와 OWASP aibom-generator ───────────────────────────────

_HF_PURL = re.compile(r"^pkg:huggingface/(?P<ns>[^/@]+)/(?P<name>[^/@]+)(?:@[^?#]+)?")
_HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")
LOCAL_MODEL_FILES = frozenset({"readme.md", "config.json", "adapter_config.json", "modelfile"})
LOCAL_MODEL_SUFFIXES = (".gguf", ".safetensors")
# OWASP 출력에서 가져오는 규제 필드 원본 (form 이 읽는 키 가운데 OWASP 가 내는 것)
OWASP_SOURCES = frozenset({HYPERPARAMETER_JSON, *HYPERPARAMETER_BY_PROPERTY, "genai:aibom:modelcard:contextLength",
                           "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"})
# cdxgen lib/parsers/huggingfaceManifest.js 의 HUGGING_FACE_TASK_IO_FORMATS
TASK_IO_FORMATS = {
    "automatic-speech-recognition": ("audio", "text"), "conversational": ("text", "text"),
    "feature-extraction": ("text", "vector"), "fill-mask": ("text", "text"), "image-classification": ("image", "text"),
    "image-segmentation": ("image", "image"), "image-text-to-text": ("image", "text"), "image-to-image": ("image", "image"),
    "image-to-text": ("image", "text"), "question-answering": ("text", "text"), "summarization": ("text", "text"),
    "translation": ("text", "text"), "text-generation": ("text", "text"), "text-to-audio": ("text", "audio"),
    "text-to-image": ("text", "image"), "text2text-generation": ("text", "text"), "token-classification": ("text", "text"),
}


def _hf_id_of(component: dict) -> str | None:
    m = _HF_PURL.match(component.get("purl") or "")
    if not m or component.get("type") != "machine-learning-model":
        return None
    return f"{m['ns']}/{m['name']}"


def hub_model_id(component: dict) -> str | None:
    """허브 모델이면 그 id (머리 설명). 로컬 모델 파일에서 찾은 모델이면 None."""
    hf_id = _hf_id_of(component)
    if hf_id is None:
        return None
    for occurrence in (component.get("evidence") or {}).get("occurrences") or []:
        location = occurrence.get("location") if isinstance(occurrence, dict) else None
        if isinstance(location, str):
            name = PurePosixPath(location.split("#", 1)[0].replace("\\", "/")).name.lower()
            if name in LOCAL_MODEL_FILES or name.endswith(LOCAL_MODEL_SUFFIXES):
                return None
    return hf_id


def enrich_hub_models(merged: dict, workdir: Path, log=print, report: dict | None = None, model_infos: dict | None = None,
           facts: Facts | None = None, *, hub, aibom_generator) -> dict:
    """hub 와 aibom_generator 는 service 가 넘겨주는 external 모듈이다 (external/hub.py, external/aibom_generator.py).
    engine 은 external 을 import 하지 않고 넘겨받은 것으로만 부른다. 쓰는 함수:
        hub.hf_reachable()                                  huggingface.co 에 닿는가
        hub.fetch_model_info(id, log)                       GET /api/models/<id> 응답 (실패면 None)
        aibom_generator.skip_reason()                       OWASP 를 건너뛸 이유 (돌려도 되면 None)
        aibom_generator.run_aibom_generator(id, workdir)    aibom-generator 출력 (실패면 RunnerError)
    model_infos 는 허브 모델 id → Hub API 응답 (실패면 None). 주지 않으면 허브에 닿는지 보고 허브 모델마다 받는다.
    facts 를 주면 응답의 lastModified 를 그 모델의 releaseTime 으로 적는다.
    report 를 주면 결과를 적는다: models(허브 모델 수) · hub(Hub API 로 채운 수) · hub_missing(응답이 없던 id) ·
    hub_skipped(Hub API 를 쓰지 못한 이유) · hub_reachable(허브에 닿는지 본 결과, 보지 않았으면 None) ·
    model_infos(쓴 응답, D-BOM 이 다시 쓴다) · enriched(OWASP 에서 원본을 가져온 수) · failed(실패한 id) ·
    errors(id → 이유 첫 줄) · skipped(OWASP 를 건너뛴 이유)."""
    report = {} if report is None else report
    targets = {hf: c for c in merged.get("components", []) if (hf := hub_model_id(c))}
    report.update(models=len(targets), hub=0, hub_missing=[], hub_skipped=None, hub_reachable=None, model_infos={},
                  enriched=0, failed=[], errors={}, skipped=None)
    if not targets:
        log("[enrich] no hub model components, nothing to enrich")
        report["skipped"] = report["hub_skipped"] = "no Hugging Face models"
        return merged

    if model_infos is None:
        report["hub_reachable"] = hub.hf_reachable()
        if report["hub_reachable"]:
            model_infos = {}
            for hf_id in targets:
                model_infos[hf_id] = hub.fetch_model_info(hf_id, log)
    if model_infos is None:
        report["hub_skipped"] = "huggingface.co unreachable"
    else:
        report["model_infos"] = model_infos
        for hf_id, comp in targets.items():
            info = model_infos.get(hf_id)
            if isinstance(info, dict):
                _apply_model_info(comp, hf_id, info)
                if facts is not None and comp.get("bom-ref"):
                    facts.set_time(comp["bom-ref"], "releaseTime", info.get("lastModified"))
                report["hub"] += 1
            else:
                report["hub_missing"].append(hf_id)
                log(f"[enrich] {hf_id}: no Hub API model info, fields left as cdxgen wrote them")

    reason = aibom_generator.skip_reason()
    if reason:
        log(f"[enrich] aibom-generator skipped for {len(targets)} hub model{'s' if len(targets) != 1 else ''}: {reason}")
        report["skipped"] = reason
        return merged
    used_tools: list[dict] = []
    for hf_id, comp in targets.items():
        try:
            owasp = aibom_generator.run_aibom_generator(hf_id, workdir)
        except RunnerError as e:
            log(f"[enrich] {hf_id}: {e}")
            report["failed"].append(hf_id)
            report["errors"][hf_id] = (str(e).splitlines() or ["failed"])[0]
            continue
        src = next((c for c in owasp.get("components", []) if c.get("type") == "machine-learning-model"), None)
        taken = _apply_owasp(comp, src) if src else 0
        if taken:
            report["enriched"] += 1
            used_tools += _tools_of(owasp)
        else:
            report["failed"].append(hf_id)
            report["errors"][hf_id] = ("no regulation values in the aibom-generator output" if src
                                       else "no model component in the aibom-generator output")
    _add_tools(merged, used_tools)
    return merged


def _tools_of(doc: dict) -> list[dict]:
    """문서가 metadata.tools 에 적은 도구 항목 (1.5 이후의 components 꼴, 그 전의 배열 꼴 모두)."""
    tools = (doc.get("metadata") or {}).get("tools")
    items = tools.get("components") if isinstance(tools, dict) else tools
    return [t for t in items or [] if isinstance(t, dict) and t.get("name")]


def _add_tools(merged: dict, tools: list[dict]) -> None:
    """값을 가져다 쓴 aibom-generator 의 도구 항목(그 출력이 자기를 적은 것)을 문서의 도구 목록에 더한다. 병합처럼
    (이름, 버전)이 같은 것은 한 번만 둔다. 가져다 쓴 값이 없으면 손대지 않는다."""
    if not tools:
        return
    listed = merged.setdefault("metadata", {}).setdefault("tools", {}).setdefault("components", [])
    seen = {(t.get("name"), t.get("version")) for t in listed if isinstance(t, dict)}
    for tool in tools:
        if (tool.get("name"), tool.get("version")) not in seen:
            seen.add((tool.get("name"), tool.get("version")))
            listed.append(copy.deepcopy(tool))


def _apply_owasp(dst: dict, src: dict) -> int:
    """OWASP 출력의 modelCard.properties 가운데 규제 필드 원본만 dst 의 modelCard.properties 에 더한다. 더한(또는 이미 있던) 수."""
    keep = [p for p in ((src.get("modelCard") or {}).get("properties") or [])
            if isinstance(p, dict) and p.get("name") in OWASP_SOURCES and isinstance(p.get("value"), str)]
    if keep:
        card = dst.setdefault("modelCard", {})
        seen = {(p.get("name"), p.get("value")) for p in card.get("properties") or []}
        card["properties"] = (card.get("properties") or []) + [p for p in keep if (p["name"], p["value"]) not in seen]
    return len(keep)


# ── Hub API 응답 → 필드 ────────────────────────────────────────────────────────

def _apply_model_info(comp: dict, hf_id: str, info: dict) -> None:
    """머리 설명 1) 의 표대로 비어 있는 필드만 채운다."""
    cid = info.get("id") if isinstance(info.get("id"), str) and _HF_ID.match(info["id"].strip("/")) else hf_id
    hf_id = cid.strip("/")
    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    if not comp.get("version") and isinstance(info.get("sha"), str) and info["sha"]:
        comp["version"] = info["sha"]
    if not comp.get("licenses") and (licenses := card_licenses(card)):
        comp["licenses"] = licenses
    if not comp.get("description"):
        text = next((t for t in (card.get("model_description"), card.get("description")) if isinstance(t, str) and t.strip()), None)
        if text:
            comp["description"] = " ".join(text.split())
    if not comp.get("supplier") and isinstance(info.get("author"), str) and info["author"]:
        comp["supplier"] = {"name": info["author"]}
    refs = [{"type": "distribution", "url": f"https://huggingface.co/{hf_id}"}]
    refs += [{"type": "documentation", "url": f"https://arxiv.org/abs/{t[len('arxiv:'):]}"}
             for t in _as_list(info.get("tags")) if isinstance(t, str) and t.startswith("arxiv:") and t[len("arxiv:"):]]
    existing = {(r.get("type"), r.get("url")) for r in comp.get("externalReferences") or []}
    new_refs = [r for r in refs if (r["type"], r["url"]) not in existing]
    if new_refs:
        comp["externalReferences"] = (comp.get("externalReferences") or []) + new_refs
    _pedigree(comp, card)
    _model_card(comp, info, card)
    _regulation_facts(comp, info)


def _pedigree(comp: dict, card: dict) -> None:
    pedigree = comp.get("pedigree") or {}
    if pedigree.get("ancestors"):
        return
    ancestors = []
    for base in _as_list(card.get("base_model")):
        base = base.strip() if isinstance(base, str) else ""
        if base and _HF_ID.match(base):
            group, _, name = base.rpartition("/")
            ancestors.append({"type": "machine-learning-model", **({"group": group} if group else {}), "name": name,
                              "purl": f"pkg:huggingface/{base}"})
    if not ancestors:
        return
    pedigree["ancestors"] = ancestors
    relation = card.get("base_model_relation")
    notes = pedigree.get("notes") if isinstance(pedigree.get("notes"), str) else ""
    if isinstance(relation, str) and relation.strip() and "Hugging Face relation:" not in notes:
        pedigree["notes"] = "; ".join(n for n in (f"Hugging Face relation: {relation.strip()}", notes) if n)   # cdxgen 의 로컬 카드와 같은 모양
    comp["pedigree"] = pedigree


def _model_card(comp: dict, info: dict, card: dict) -> None:
    config = info.get("config") if isinstance(info.get("config"), dict) else {}
    gguf = info.get("gguf") if isinstance(info.get("gguf"), dict) else {}
    task = next((t for t in (info.get("pipeline_tag"), card.get("pipeline_tag"), _model_index_task(card)) if isinstance(t, str) and t), None)
    architectures = config.get("architectures") if isinstance(config.get("architectures"), list) else []
    values = {
        "task": task,
        "architectureFamily": next((v for v in (config.get("model_type"), gguf.get("architecture")) if isinstance(v, str) and v), None),
        "modelArchitecture": architectures[0] if architectures and isinstance(architectures[0], str) else None,
    }
    io = TASK_IO_FORMATS.get(task.lower()) if task else None
    io = io or _widget_io(card.get("widget") or info.get("widgetData"))
    have = (comp.get("modelCard") or {}).get("modelParameters") or {}
    updates = {key: value for key, value in values.items() if value and not have.get(key)}
    if io and not have.get("inputs") and not have.get("outputs"):
        updates["inputs"], updates["outputs"] = [{"format": io[0]}], [{"format": io[1]}]
    if updates:
        comp.setdefault("modelCard", {}).setdefault("modelParameters", {}).update(updates)
    metrics = _performance_metrics(card.get("model-index") or info.get("model-index"))
    if metrics and not ((comp.get("modelCard") or {}).get("quantitativeAnalysis") or {}).get("performanceMetrics"):
        comp.setdefault("modelCard", {}).setdefault("quantitativeAnalysis", {})["performanceMetrics"] = metrics


def _model_index_task(card: dict) -> str | None:
    for entry in _as_list(card.get("model-index")):
        for result in _as_list(entry.get("results")) if isinstance(entry, dict) else []:
            task = (result.get("task") or {}).get("type") if isinstance(result, dict) and isinstance(result.get("task"), dict) else None
            if isinstance(task, str) and task:
                return task
    return None


def _widget_io(widgets) -> tuple[str, str] | None:
    """cdxgen inferModelIoParameters 의 widget 규칙: 글(text·messages·sentences) → text/text, 그림(src) → image/(text|image), 표 → structured-data/text."""
    for widget in _as_list(widgets):
        if not isinstance(widget, dict):
            continue
        if widget.get("messages") or widget.get("text") or widget.get("sentences"):
            return ("text", "text")
        if widget.get("src"):
            return ("image", "text" if (widget.get("output") or {}).get("text") else "image")
        if widget.get("table") or widget.get("structured_data"):
            return ("structured-data", "text")
    return None


def _performance_metrics(model_index) -> list[dict]:
    """cdxgen createPerformanceMetrics 와 같은 규칙: metric 마다 {type, value(문자열), slice "데이터셋 이름 / split"}. 값이 없으면 뺀다."""
    out = []
    for entry in _as_list(model_index):
        for result in _as_list(entry.get("results")) if isinstance(entry, dict) else []:
            if not isinstance(result, dict):
                continue
            dataset = result.get("dataset") if isinstance(result.get("dataset"), dict) else {}
            slice_ = " / ".join(str(x) for x in (dataset.get("name"), dataset.get("split")) if x)
            for metric in _as_list(result.get("metrics")):
                if not isinstance(metric, dict) or not (metric.get("type") or metric.get("name")):
                    continue
                value = metric.get("value")
                if value is None or str(value) == "":
                    continue
                out.append({"type": str(metric.get("type") or metric.get("name")), "value": str(value), **({"slice": slice_} if slice_ else {})})
    return out


def _regulation_facts(comp: dict, info: dict) -> None:
    safetensors = info.get("safetensors") if isinstance(info.get("safetensors"), dict) else {}
    gguf = info.get("gguf") if isinstance(info.get("gguf"), dict) else {}
    props = []
    count = next((v for v in (safetensors.get("total"), gguf.get("total")) if isinstance(v, int) and not isinstance(v, bool) and v >= 0), None)
    if count is not None:
        props.append({"name": INTERNAL_MODEL_PREFIX + "parameterCount", "value": str(count)})
    context = gguf.get("context_length")
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        props.append({"name": INTERNAL_MODEL_PREFIX + "maxSize", "value": str(context)})
    have = comp.get("properties") or []
    props = [p for p in props if p not in have]
    if props:
        comp["properties"] = have + props


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
