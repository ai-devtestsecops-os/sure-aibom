"""CycloneDX 1.7 → SPDX 3.0.1 JSON-LD.

세 도구 어느 것도 SPDX 3.0.1 의 AI·데이터셋 프로파일을 쓰지 않으므로 여기서 직접 만든다.

    component.type machine-learning-model → ai_AIPackage
    component.type data                   → dataset_DatasetPackage
    그 외                                  → software_Package
    dependencies[]                        → Relationship (dependsOn)
    pedigree.ancestors[]                  → Relationship (ancestorOf)
    properties[]                          → extension (3단계에서 결정)

3단계 골격이다. 지금은 원소 종류·이름·버전·purl·라이선스·관계만 옮기고,
modelCard → ai_* / dataset_* 세부 필드는 data/cdx_spdx_mapping.json 을 따라 채운다 (TODO).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
SPEC_VERSION = "3.0.1"

_TYPE = {
    "machine-learning-model": "ai_AIPackage",
    "data": "dataset_DatasetPackage",
    "file": "software_File",
}


def _ns(doc_id: str) -> str:
    return f"https://aibom-cli/{doc_id}"


def cdx_to_spdx(cdx: dict) -> dict:
    doc_id = cdx.get("serialNumber", f"urn:uuid:{uuid.uuid4()}").removeprefix("urn:uuid:")
    ns = _ns(doc_id)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    creation = {
        "type": "CreationInfo",
        "@id": "_:creationinfo",
        "specVersion": SPEC_VERSION,
        "created": now,
        "createdBy": [f"{ns}/agent/aibom-cli"],
    }
    agent = {"type": "Tool", "spdxId": f"{ns}/agent/aibom-cli", "name": "aibom-cli", "creationInfo": "_:creationinfo"}

    elements: list[dict] = []
    ref_to_spdxid: dict[str, str] = {}

    for comp in cdx.get("components", []):
        spdx_id = f"{ns}/package/{uuid.uuid5(uuid.NAMESPACE_URL, comp.get('bom-ref') or comp.get('name', ''))}"
        ref_to_spdxid[comp.get("bom-ref", "")] = spdx_id
        el = {
            "type": _TYPE.get(comp.get("type"), "software_Package"),
            "spdxId": spdx_id,
            "creationInfo": "_:creationinfo",
            "name": comp.get("name"),
        }
        if comp.get("version"):
            el["software_packageVersion"] = comp["version"]
        if comp.get("purl"):
            el["software_packageUrl"] = comp["purl"]
        if comp.get("description"):
            el["description"] = comp["description"]
        if comp.get("type") == "machine-learning-model":
            el["software_primaryPurpose"] = "model"
            _apply_ai_fields(el, comp)
        elif comp.get("type") == "data":
            el["software_primaryPurpose"] = "data"
        elements.append(el)

    relationships: list[dict] = []
    for dep in cdx.get("dependencies", []):
        frm = ref_to_spdxid.get(dep.get("ref"))
        tos = [ref_to_spdxid[t] for t in dep.get("dependsOn", []) if t in ref_to_spdxid]
        if frm and tos:
            relationships.append({
                "type": "Relationship",
                "spdxId": f"{ns}/rel/{uuid.uuid4()}",
                "creationInfo": "_:creationinfo",
                "from": frm,
                "relationshipType": "dependsOn",
                "to": tos,
            })

    sbom = {
        "type": "software_Sbom",
        "spdxId": f"{ns}/sbom",
        "creationInfo": "_:creationinfo",
        "software_sbomType": ["build"],
        "rootElement": [e["spdxId"] for e in elements],
        "element": [e["spdxId"] for e in elements] + [r["spdxId"] for r in relationships],
    }

    return {
        "@context": CONTEXT,
        "@graph": [creation, agent, sbom, *elements, *relationships],
    }


def _apply_ai_fields(el: dict, comp: dict) -> None:
    """modelCard → ai_* 필드. 3단계에서 data/cdx_spdx_mapping.json 을 따라 완성한다."""
    card = comp.get("modelCard") or {}
    params = card.get("modelParameters") or {}
    if params.get("modelArchitecture") or params.get("architectureFamily"):
        el["ai_typeOfModel"] = [v for v in (params.get("modelArchitecture"), params.get("architectureFamily")) if v]
    limits = (card.get("considerations") or {}).get("technicalLimitations")
    if limits:
        el["ai_limitation"] = "; ".join(limits)
    for p in card.get("properties") or []:
        if p.get("name") == "genai:aibom:modelcard:hyperparameter":
            el["ai_hyperparameter"] = [{"type": "DictionaryEntry", "key": "hyperparameter", "value": p.get("value")}]
    # TODO: ai_metric, ai_energyConsumption, ai_safetyRiskAssessment, ai_informationAboutTraining …
