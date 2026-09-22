"""데이터셋: componentData 접기/펼치기, modelCard.modelParameters.datasets[] → trainedOn/testedOn (spdx_spec dataset_handling).

접기: type:data 컴포넌트의 data[0](type dataset) 은 그 컴포넌트의 DatasetPackage 에 합친다.
펼치기: 나머지 data[] 항목은 각자 원소(dataset → DatasetPackage, 그 외 → software_File) + hasDataFile.
참조 해석: 키 일치 → 쿼리 뗀 purl → Hugging Face id 정규화 → BOM-Link(import) → pkg: 스텁 → 확장 항목.
접힌 data[0] 의 bom-ref 는 소유 원소의 별칭으로 등록해 datasets[].ref / dependencies 가 그것을 가리켜도 풀린다.
인라인 datasets[] 항목은 기존 DatasetPackage 에만 접는다 — 이름이 같은 라이브러리 패키지에 붙이지 않는다.
BOM-Link 는 이 변환기 체계의 IRI 로 옮기고 원본은 ExternalMap.locationHint 에 남긴다.
"""
from __future__ import annotations

import re

from ._ctx import Ctx, ExtBuffer
from ._ids import BOM_LINK, bomlink_iri, enc, key_of
from ._props import route_component_properties, route_typed_fields
from ._tables import (
    CONFIDENTIALITY, DATA_DICT, DATA_EXT_ONLY, DATA_FILE_PURPOSE, DATA_LIST, DATA_SCALAR, TESTED_ON_MARKERS,
)

_HF_PURL = re.compile(r"^pkg:huggingface/(?P<ns>[^/@?#]+)/(?P<name>[^/@?#]+)")
_USAGE_PROPS = ("aibom:dataset:usage", "cdx:ai:datasetUsage")


def ensure_dataset_type(node: dict) -> None:
    if node["type"] == "dataset_DatasetPackage" and not node.get("dataset_datasetType"):
        node["dataset_datasetType"] = ["noAssertion"]


def apply_component_data(ctx: Ctx, node: dict, ext: ExtBuffer, data: dict, i: int, *, folded: bool, owner_key: str) -> None:
    """componentData 의 필드를 노드에 옮긴다. 접힌 경우 컴포넌트 값이 우선하고 데이터 값은 aibom:cdx:data:<i>:* 로 남는다."""
    prefix = f"data:{i}"
    contents = data.get("contents") or {}
    if contents.get("url"):
        if node["type"] == "dataset_DatasetPackage":
            node["software_downloadLocation"] = contents["url"]
        else:
            node.setdefault("externalRef", []).append({"type": "ExternalRef", "externalRefType": "altDownloadLocation", "locator": [contents["url"]]})
    if data.get("classification") is not None:
        level = CONFIDENTIALITY.get(str(data["classification"]).strip().lower().removeprefix("tlp:").strip())
        if level and node["type"] == "dataset_DatasetPackage":
            node["dataset_confidentialityLevel"] = level
        else:
            ext.fix(f"{prefix}:classification", data["classification"])
    if "sensitiveData" in data and node["type"] == "dataset_DatasetPackage":
        node["dataset_hasSensitivePersonalInformation"] = "yes" if data["sensitiveData"] else "no"
    for j, s in enumerate(data.get("sensitiveData") or []):
        ext.fix(f"{prefix}:sensitiveData:{j}", s)
    if data.get("description"):
        if node.get("description"):
            ext.fix(f"{prefix}:description", data["description"])
        else:
            node["description"] = data["description"]
    if folded:
        if data.get("name") and data["name"] != node.get("name"):
            ext.fix(f"{prefix}:name", data["name"])
        ext.fix(f"{prefix}:bom-ref", data.get("bom-ref"))
        if data.get("bom-ref") and data["bom-ref"] not in ctx.key_iri:
            ctx.key_iri[data["bom-ref"]] = node["spdxId"]           # 별칭만 — iri_key/records 는 소유 컴포넌트 것
    ext.fix(f"{prefix}:type", data.get("type"))
    route_typed_fields(node, ext, data, prefix, typed=node["type"] == "dataset_DatasetPackage",
                       scalars=DATA_SCALAR, lists=DATA_LIST, dicts=DATA_DICT, ext_only=DATA_EXT_ONLY)
    route_component_properties(ctx, node, ext, contents.get("properties") or [], owner_key)
    ext.fix(f"{prefix}:contents:attachment:contentType", (contents.get("attachment") or {}).get("contentType"))
    for role, parties in (data.get("governance") or {}).items():
        for j, party in enumerate(parties or []):
            ext.fix(f"{prefix}:governance:{role}:{j}:organization:name", (party.get("organization") or {}).get("name"))
            ext.fix(f"{prefix}:governance:{role}:{j}:contact:name", (party.get("contact") or {}).get("name"))
            ext.fix(f"{prefix}:governance:{role}:{j}:contact:email", (party.get("contact") or {}).get("email"))
    ext.fix(f"{prefix}:graphics:description", (data.get("graphics") or {}).get("description"))


def data_entry_element(ctx: Ctx, data: dict, i: int, *, owner_key: str, fallback_fragment: str) -> str:
    """접히지 않은 componentData 하나 → 자체 원소. bom-ref 가 있으면 그 키, 없으면 부모 기준 조각."""
    key = data.get("bom-ref")
    if key and key in ctx.key_iri:
        return ctx.key_iri[key]
    dtype = data.get("type")
    if dtype in (None, "dataset"):
        cls, purpose = "dataset_DatasetPackage", "data"
    else:
        cls, purpose = "software_File", DATA_FILE_PURPOSE.get(dtype, "other")
    fragment, owner = (enc(key), ("component", key)) if key else (fallback_fragment, ("data", f"{owner_key}#{fallback_fragment}"))
    iri, node, new = ctx.element(fragment, owner, cls, "datasets")
    if not new:
        return iri
    ext = ctx.ext_of(iri)
    node["name"] = data.get("name") or "unnamed-data"
    node["software_primaryPurpose"] = purpose
    if key:
        ctx.bind_key(key, iri, data)
        ext.fix("bom-ref", key)
    apply_component_data(ctx, node, ext, data, i, folded=False, owner_key=key or owner_key)
    ensure_dataset_type(node)
    return iri


# -- modelCard.modelParameters.datasets[] ----------------------------------------------
def build_dataset_relationships(ctx: Ctx, card: dict, model_iri: str, model_key: str) -> None:
    ext = ctx.ext_of(model_iri)
    trained: list[str] = []
    tested: list[str] = []
    for i, ds in enumerate((card.get("modelParameters") or {}).get("datasets") or []):
        usage = ctx.usage.get((model_key, i))
        if "ref" in ds:
            target = _resolve_reference(ctx, ext, ds["ref"], i)
        else:
            target = _resolve_inline(ctx, ds) or data_entry_element(
                ctx, ds, i, owner_key=model_key, fallback_fragment=f"{enc(model_key)}-dataset-{i}")
            usage = usage or _inline_usage(ds)
        if target:
            (tested if usage in TESTED_ON_MARKERS else trained).append(target)
    ctx.rel(model_iri, "trainedOn", trained)
    ctx.rel(model_iri, "testedOn", tested)


def _inline_usage(data: dict) -> str | None:
    for p in (data.get("contents") or {}).get("properties") or []:
        if p.get("name") in _USAGE_PROPS and p.get("value"):
            return str(p["value"]).strip().lower()
    return None


def _resolve_reference(ctx: Ctx, ext: ExtBuffer, ref: str, i: int) -> str | None:
    target = resolve_dataset_ref(ctx, ref)
    if target:
        return target
    link = BOM_LINK.match(ref)
    if link:
        if f"urn:uuid:{link['serial'].lower()}" == ctx.ns and link["ref"] in ctx.key_iri:
            return ctx.key_iri[link["ref"]]
        external = bomlink_iri(link)
        ctx.add_import(external, ref)
        return external
    if ref.startswith("pkg:"):
        return _stub(ctx, ref, i)
    ext.fix(f"modelCard:datasets:{i}:ref", ref)
    ctx.warn(f"modelCard 데이터셋 참조를 해석하지 못해 확장에 남긴다: {ref}")
    return None


def _stub(ctx: Ctx, ref: str, i: int) -> str:
    iri, node, new = ctx.element(f"Dataset-{enc(ref)}", ("Dataset", ref), "dataset_DatasetPackage", "datasets")
    if new:
        hf = _HF_PURL.match(ref)
        node["name"] = f"{hf['ns']}/{hf['name']}" if hf else ref.split("?", 1)[0].rsplit("/", 1)[-1]
        node["comment"] = "unresolved CycloneDX modelCard dataset reference"
        node["software_primaryPurpose"] = "data"
        node["software_packageUrl"] = ref
        node["dataset_datasetType"] = ["noAssertion"]
        ctx.warn(f"modelCard 데이터셋 참조가 문서 안에 없어 스텁을 만든다: {ref}")
    ctx.ext_of(iri).fix(f"modelCard:datasets:{i}:ref", ref)
    return iri


def resolve_dataset_ref(ctx: Ctx, ref: str) -> str | None:
    if ref in ctx.key_iri:
        return ctx.key_iri[ref]
    base = ref.split("?", 1)[0]
    if base in ctx.key_iri:
        return ctx.key_iri[base]
    for iri in ctx.component_iris:
        purl = ctx.records[iri].get("purl") or ""
        if purl and purl.split("?", 1)[0] == base:
            return iri
    hf = _HF_PURL.match(ref)
    if not hf:
        return None
    hf_id = f"{hf['ns']}/{hf['name']}"
    ordered = sorted(ctx.component_iris, key=lambda x: ctx.nodes[x]["type"] != "dataset_DatasetPackage")
    for iri in ordered:
        if _matches_hf(ctx.records[iri], ctx.iri_key.get(iri, ""), hf_id):
            return iri
    return None


def _matches_hf(comp: dict, key: str, hf_id: str) -> bool:
    short = hf_id.split("/", 1)[1]
    if f"{comp.get('group', '')}/{comp.get('name', '')}" == hf_id or key == f"data:{hf_id}@":
        return True
    if (comp.get("purl") or "").startswith(f"pkg:huggingface/{hf_id}"):
        return True
    urls = [(d.get("contents") or {}).get("url") for d in comp.get("data") or []]
    urls += [r.get("url") for r in comp.get("externalReferences") or []]
    if any(d.get("name") == hf_id for d in comp.get("data") or []):
        return True
    return any(u and (u.rstrip("/").endswith(f"/{hf_id}") or u.rstrip("/").endswith(f"/datasets/{short}")) for u in urls)


def _resolve_inline(ctx: Ctx, data: dict) -> str | None:
    """인라인 Data Information → 이미 있는 DatasetPackage (bom-ref, url, 이름). 다른 클래스에는 절대 접지 않는다."""
    key = data.get("bom-ref")
    if key and key in ctx.key_iri:
        return ctx.key_iri[key]
    url = (data.get("contents") or {}).get("url")
    name = data.get("name")
    for iri, node in ctx.nodes.items():
        if node["type"] != "dataset_DatasetPackage":
            continue
        rec = ctx.records.get(iri) or {}
        names = {node.get("name"), f"{rec.get('group', '')}/{rec.get('name', '')}"}
        folded = (rec.get("data") or [{}])[0]
        if folded.get("type") in (None, "dataset"):
            names.add(folded.get("name"))
        urls = {node.get("software_downloadLocation"), (folded.get("contents") or {}).get("url")}
        urls.update(r.get("url") for r in rec.get("externalReferences") or [])
        if (url and url in urls) or (name and name in names):
            return iri
    return None


__all__ = ["apply_component_data", "build_dataset_relationships", "data_entry_element", "ensure_dataset_type", "key_of"]
