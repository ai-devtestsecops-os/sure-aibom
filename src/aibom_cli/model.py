"""스캔 대상 안의 모델 파일에서 규제 필드 값을 읽는다. 병합 뒤, 규제 정규화 앞에서 돈다.

M-BOM 을 보강하지 않는다 — 컴포넌트를 만들지도, 규제 필드가 아닌 값을 더하지도 않는다. 읽는 값은 규제 필드 둘뿐이다.
    hyperparameters   config.json (HuggingFace 형식) · *.gguf 헤더
    parameterCount    *.safetensors 헤더 (샤드는 합산) · *.gguf 텐서 정보
이름은 llama.cpp 의 이름으로 맞춘다 (block_count, embedding_length …). 같은 값을 계열마다 다른 키로 적는 것을
막고, OWASP aibom-generator 가 허브에서 채우는 이름과도 같아야 한 모델에 두 이름이 들어가지 않는다.
아키텍처·토크나이저·양자화처럼 같은 파일에 있어도 규제 필드가 아닌 값은 읽지 않는다.

읽을 파일은 cdxgen 이 모델 컴포넌트에 남긴 evidence.occurrences 에서 온다 (config.json, *.gguf). cdxgen 은 이 두
파일을 이미 읽으면서 하이퍼파라미터만 버린다. *.safetensors 는 cdxgen 이 보지 않으므로 config.json 과 같은
디렉터리에서 찾는다. 컴포넌트가 없으면 만들지 않는다 (가중치 파일만 있고 config.json·README 가 없는 폴더는 그대로).

가중치는 절대 읽지 않는다 (헤더·메타데이터만). pickle 을 담은 것(.bin, .pt, .pth, .ckpt, .pkl)은 열지 않는다.
값은 aibom-internal:model:* 프로퍼티로 두고 regulation 이 --form 에 맞는 자리로 옮기며 지운다 (출력에는 남지 않는다).
"""
from __future__ import annotations

import json
import struct
from pathlib import Path, PurePosixPath
from typing import Iterable

MODEL_TYPE = "machine-learning-model"
INTERNAL_MODEL_PREFIX = "aibom-internal:model:"      # regulation 이 읽어 가고 지운다

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

def discover(merged: dict, target: str, log=print) -> dict:
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
            found = _read(parse_config, path, rel, log)
            if found is None:
                continue
            _take(hparams, found, rel, label, log)
            if parameter_count is None:
                parameter_count = _safetensors_total(path.parent, root_resolved, log)
        else:
            got = _read(parse_gguf, path, rel, log)
            if got is None:
                continue
            found, count = got
            _take(hparams, found, rel, label, log)
            if parameter_count is None:
                parameter_count = count

    props = internal_properties(hparams, parameter_count)
    if props:
        comp["properties"] = (comp.get("properties") or []) + props
        counted = " · 파라미터 수" if parameter_count is not None else ""
        log(f"[model] {label}: 로컬 파일에서 하이퍼파라미터 {len(hparams)}개{counted} 를 읽었다")


def _read(parse, path: Path, rel: str, log):
    try:
        return parse(path)
    except _READ_ERRORS as e:
        log(f"[model] {rel}: 읽지 못해 건너뛴다 ({e.__class__.__name__}: {e})")
        return None


def _take(hparams: dict[str, str], found: dict[str, str], rel: str, label: str, log) -> None:
    """먼저 읽은 파일의 값이 이긴다. 값이 다르면 알리고 버린다 (한 이름이 두 번 나오지 않는다)."""
    for name, value in found.items():
        if name not in hparams:
            hparams[name] = value
        elif hparams[name] != value:
            log(f"[model] {label}: hyperparameters[{name}] 에 이미 {hparams[name]!r} 가 있어 {rel} 의 {value!r} 를 버린다")


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
        path = _inside_file(root, root_resolved, location)
        if path is not None:
            found.add(path)
    return sorted(found, key=str)


def _inside_file(root: Path, root_resolved: Path, location: str) -> Path | None:
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

def parse_config(path: Path) -> dict[str, str]:
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
        n = _read(safetensors_parameters, path, _relative(path, root_resolved), log)
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


def safetensors_parameters(path: Path) -> int:
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

def parse_gguf(path: Path) -> tuple[dict[str, str], int | None]:
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

def internal_properties(hparams: dict[str, str], parameter_count: int | None) -> list[dict]:
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
