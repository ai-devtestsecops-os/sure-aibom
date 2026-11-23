"""여러 단계 파일이 같이 쓰는, 컴포넌트를 알아보고 합치는 상수와 짧은 함수.

    identity           컴포넌트의 병합 키 (merge.py 가 같은 컴포넌트를 하나로 합칠 때, spdx.py 가 bom-ref 없는 컴포넌트의 id 를 정할 때 쓴다)
    fill_missing       없는 필드만 채운다 (merge.py 가 두 도구의 같은 컴포넌트를, dataset.py 가 같은 데이터셋을 합칠 때 쓴다)
    hub_model_id       허브 모델이면 그 id (model.py 가 보강할 모델을, dataset.py 가 모델 카드를 읽을 모델을, ai_service.py 가 서비스에서
                       떼어 낼 모델을 고를 때 쓴다)

상수는 CycloneDX 의 component.type 값, 허브 모델 purl 과 로컬 모델 파일의 모양, 수집 단계와 form.py 가 주고받는 프로퍼티 이름이다.
데이터셋 컴포넌트를 알아보는 함수와 상수는 service 도 써서 utils/dataset_component.py 에 있다.

허브 모델: purl 이 pkg:huggingface/<ns>/<name> 인 모델 컴포넌트 가운데 로컬 모델 파일(README.md, config.json, adapter_config.json,
Modelfile, *.gguf, *.safetensors)에서 찾은 것이 아닌 것. 로컬 폴더는 그 파일들이 근거다 (config 의 _name_or_path 는 베이스 모델
이름일 수 있어 허브 값이 그 모델의 것이 아닐 수 있다).
매칭 키: purl 의 pkg:huggingface/<ns>/<name> (리비전 제외. 두 도구가 버전 표기를 달리 한다)
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

# ── component.type 값 ────────────────────────────────────────────────────────
MODEL_TYPE = "machine-learning-model"
FILE_TYPE = "file"

# ── 허브 모델 purl 과 로컬 모델 파일의 모양 ───────────────────────────────────────
_HF_PURL = re.compile(r"^pkg:huggingface/(?P<ns>[^/@]+)/(?P<name>[^/@]+)(?:@[^?#]+)?")
LOCAL_MODEL_FILES = frozenset({"readme.md", "config.json", "adapter_config.json", "modelfile"})
LOCAL_MODEL_SUFFIXES = (".gguf", ".safetensors")
AI_FILE_REF_PREFIX = "urn:file:ai:"       # cdxgen 이 AI 파일(gguf, Modelfile 등)에 붙이는 bom-ref

# ── 수집 단계가 두고 form.py 가 옮기는 프로퍼티 이름 ─────────────────────────────
INTERNAL_PREFIX = "aibom-internal:dataset:"                       # dataset.py 가 두는 원본 키 (정의서 키에서 접두어만 다르다)
INTERNAL_MODEL_PREFIX = "aibom-internal:model:"                   # model.py 가 두는 원본 키. form 이 읽어 가고 지운다
# 하이퍼파라미터: JSON 객체 문자열(키마다 한 항목) 다음에, 키가 아직 없을 때만 개별 프로퍼티
HYPERPARAMETER_JSON = "genai:aibom:modelcard:hyperparameter"
HYPERPARAMETER_BY_PROPERTY: dict[str, str] = {
    "genai:aibom:modelcard:vocabSize": "vocab_size",
    "genai:aibom:modelcard:embeddingLength": "embedding_length",
    "genai:aibom:modelcard:blockCount": "block_count",
    "genai:aibom:modelcard:attentionHeadCount": "attention_head_count",
    "genai:aibom:modelcard:attentionHeadCountKV": "attention_head_count_kv",
    "genai:aibom:modelcard:feedForwardLength": "feed_forward_length",
    "genai:aibom:modelcard:ropeDimensionCount": "rope_dimension_count",
}


# ── 병합 ─────────────────────────────────────────────────────────────────────

def identity(component: dict) -> str:
    """컴포넌트의 병합 키."""
    if component.get("type") == FILE_TYPE:
        path = _file_path_of(component)
        if path:
            return f"file:/{path.lstrip('/')}"
    purl = component.get("purl")
    if purl:
        return purl
    hashes = component.get("hashes") or []
    for h in hashes:
        if h.get("alg") in ("SHA-256", "SHA-512", "SHA-1") and h.get("content"):
            return f"hash:{h['alg']}:{h['content']}"
    return f"{component.get('type', 'component')}:{component.get('group', '')}/{component.get('name', '')}@{component.get('version', '')}"


def _file_path_of(component: dict) -> str | None:
    """파일 컴포넌트의 경로. cdxgen 이미지 스캔은 purl 의 `path=` 에, cdxgen AI 파일은 bom-ref `urn:file:ai:<path>` 에,
    syft 는 name 에 경로를 둔다 (디렉터리 스캔은 스캔 루트 기준, 이미지는 이미지 안 절대경로)."""
    purl = component.get("purl") or ""
    if "?" in purl:
        for pair in urlsplit(purl).query.split("&"):
            key, _, value = pair.partition("=")
            if key == "path" and value:
                return unquote(value)
    ref = component.get("bom-ref") or ""
    if ref.startswith(AI_FILE_REF_PREFIX) and len(ref) > len(AI_FILE_REF_PREFIX):
        return ref[len(AI_FILE_REF_PREFIX):]
    return component.get("name") or None


def fill_missing(base: dict, extra: dict) -> None:
    """base 에 없는 키만 extra 에서 채운다. properties/externalReferences 는 합친다."""
    for k, v in extra.items():
        if k not in base:
            base[k] = v
    for list_key, dedupe_key in (("properties", lambda p: (p.get("name"), p.get("value"))),
                                 ("externalReferences", lambda r: (r.get("type"), r.get("url")))):
        if list_key in extra:
            seen = {dedupe_key(x) for x in base.get(list_key, [])}
            merged = list(base.get(list_key, []))
            for x in extra[list_key]:
                if dedupe_key(x) not in seen:
                    merged.append(x)
                    seen.add(dedupe_key(x))
            if merged:
                base[list_key] = merged


# ── 허브 모델 ─────────────────────────────────────────────────────────────────

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
