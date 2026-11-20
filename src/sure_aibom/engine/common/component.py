"""여러 단계 파일이 같이 쓰는, 컴포넌트를 알아보고 합치는 상수와 짧은 함수.

    identity           컴포넌트의 병합 키 (merge.py 가 같은 컴포넌트를 하나로 합칠 때, spdx.py 가 bom-ref 없는 컴포넌트의 id 를 정할 때 쓴다)
    fill_missing       없는 필드만 채운다 (merge.py 가 두 도구의 같은 컴포넌트를, dataset.py 가 같은 데이터셋을 합칠 때 쓴다)
    hub_model_id       허브 모델이면 그 id (model.py 가 보강할 모델을, dataset.py 가 모델 카드를 읽을 모델을, ai_service.py 가 서비스에서
                       떼어 낼 모델을 고를 때 쓴다)
    hf_dataset_id_of   허브 데이터셋이면 그 id (dataset.py 가 이미 있는 데이터셋 컴포넌트를 id 로 찾을 때 쓴다)
    is_dataset         D-BOM 으로 세는 컴포넌트인가 (spdx.py 가 데이터셋 요소로 바꿀 것을, service 가 요약에서 셀 것을 고를 때 쓴다)

상수는 CycloneDX 의 component.type 값, 허브 id 와 주소의 모양, 수집 단계와 form.py 가 주고받는 프로퍼티 이름이다.

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
DATA_TYPE = "data"
FILE_TYPE = "file"
DATASET_KIND = "dataset"       # data[].type 의 다섯 값 중 D-BOM 으로 치는 것

# ── 허브 id 와 주소의 모양 ─────────────────────────────────────────────────────
HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")
HF_DATASET_PURL = re.compile(r"^pkg:huggingface/datasets/(?P<id>[^@?#]+)")
HF_DATASET_URL = re.compile(r"^https?://huggingface\.co/datasets/(?P<id>[^?#]+?)/?$")
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


# ── 데이터셋 판정 ─────────────────────────────────────────────────────────────

def is_dataset(comp: dict) -> bool:
    """D-BOM 으로 세는 컴포넌트. type=data 만으로는 모자라다: cdxgen 이 이미지의 apt 저장소 설정도 data[] 없는
    type=data 로 낸다. data[] 에 dataset 항목이 있거나 허브 데이터셋 id 가 있으면 데이터셋이다."""
    if comp.get("type") != DATA_TYPE:
        return False
    return any(d.get("type") == DATASET_KIND for d in comp.get("data") or []) or hf_dataset_id_of(comp) is not None


def hf_dataset_id_of(comp: dict) -> str | None:
    """type=data 컴포넌트의 Hugging Face 데이터셋 id. purl → data[].name "datasets/<id>" → group "datasets" 의 name →
    data[].contents.url 이나 externalReferences 의 허브 데이터셋 주소. cdxgen 은 모델 카드의 이름만 있는 id 를 datasets/<id> 로,
    owner/name 은 group·name 으로 나누고 purl 없이 주소에만 남긴다. 코드의 huggingface.co/datasets 링크로 만든 것은 data[] 도 없이
    externalReferences 에만 주소가 있다."""
    if comp.get("type") != DATA_TYPE:
        return None
    m = HF_DATASET_PURL.match(comp.get("purl") or "")
    if m:
        return m["id"].strip("/")
    for d in comp.get("data") or []:
        name = d.get("name") or ""
        if name.startswith("datasets/") and HF_ID.match(name[len("datasets/"):]):
            return name[len("datasets/"):]
    if comp.get("group") == "datasets" and comp.get("name") and HF_ID.match(comp["name"]):
        return comp["name"]
    urls = [(d.get("contents") or {}).get("url") for d in comp.get("data") or []]
    urls += [r.get("url") for r in comp.get("externalReferences") or [] if isinstance(r, dict)]
    for url in urls:
        m = HF_DATASET_URL.match(url) if isinstance(url, str) else None
        if m and HF_ID.match(hf_id := m["id"].removeprefix("datasets/")):
            return hf_id
    return None
