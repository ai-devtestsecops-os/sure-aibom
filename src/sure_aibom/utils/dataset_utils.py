"""데이터셋 컴포넌트를 알아보는 함수와 상수. service 와 engine 이 같이 쓴다.

    is_dataset         D-BOM 으로 세는 컴포넌트인가 (service 가 단계 줄과 요약 줄에서 셀 것을, engine/spdx.py 가 데이터셋 요소로 바꿀
                       것을 고를 때 쓴다)
    hf_dataset_id_of   허브 데이터셋이면 그 id (engine/dataset.py 가 이미 있는 데이터셋 컴포넌트를 id 로 찾을 때 쓴다)

상수는 CycloneDX 의 데이터 컴포넌트 type 값과, 허브 id · 허브 데이터셋 주소의 모양이다. engine/dataset.py 가 데이터셋 컴포넌트를 만들고
고칠 때, engine/form.py 가 데이터 컴포넌트를 고를 때 쓴다. HF_ID 는 모델 id 도 같은 모양이라 engine/model.py 도 쓴다.
"""
from __future__ import annotations

import re

# ── component.type 과 data[].type 값 ─────────────────────────────────────────
DATA_TYPE = "data"
DATASET_KIND = "dataset"       # data[].type 의 다섯 값 중 D-BOM 으로 치는 것

# ── 허브 id 와 허브 데이터셋 주소의 모양 ────────────────────────────────────────
HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")
HF_DATASET_PURL = re.compile(r"^pkg:huggingface/datasets/(?P<id>[^@?#]+)")
HF_DATASET_URL = re.compile(r"^https?://huggingface\.co/datasets/(?P<id>[^?#]+?)/?$")


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
