"""modelCard → ai_AIPackage 의 ai_* / aibom_* 속성 (spdx_spec mapping 60-75).

datasets[] 는 관계라서 여기서 다루지 않는다 (_datasets.build_dataset_relationships).
"""
from __future__ import annotations

import re

from ._ctx import Ctx, ExtBuffer
from ._props import add_external_identifier, append_unique, entry, route_modelcard_properties, route_typed_fields, typed_index_keys
from ._tables import (
    CONSIDERATION_EXT_ONLY, CONSIDERATION_LIST, CONSIDERATION_SCALAR, ENERGY_SLOT_BY_ACTIVITY, ENERGY_UNIT,
    MODEL_PARAM_EXT_ONLY, MODEL_PARAM_LIST, MODEL_PARAM_SCALAR,
)

_ENERGY_NUMBER = re.compile(r"^-?[0-9]+(\.[0-9]*)?$")             # 스키마의 ai_energyQuantity 문자열 패턴


def apply_modelcard(ctx: Ctx, node: dict, ext: ExtBuffer, card: dict, owner_key: str) -> None:
    if card.get("bom-ref"):
        add_external_identifier(node, "other", card["bom-ref"], comment="aibom:cdx:modelCard:bom-ref")
    _parameters(node, ext, card.get("modelParameters") or {})
    _quantitative(node, ext, card.get("quantitativeAnalysis") or {})
    _considerations(node, ext, card.get("considerations") or {})
    route_modelcard_properties(ctx, node, ext, card.get("properties") or [], owner_key, typed_index_keys(card))


def _parameters(node: dict, ext: ExtBuffer, params: dict) -> None:
    """task/architectureFamily/modelArchitecture 도 MODEL_PARAM_SCALAR 를 거친다 — 컴포넌트 properties 가 먼저 채웠으면 확장으로."""
    approach = (params.get("approach") or {}).get("type")
    for value in (params.get("modelArchitecture"), params.get("architectureFamily"), approach):
        if value:
            append_unique(node, "ai_typeOfModel", value)
    for field, prop, max_prop in (("inputs", "aibom_inputs", "aibom_inputMaxSize"), ("outputs", "aibom_outputs", "aibom_outputMaxSize")):
        for i, io in enumerate(params.get(field) or []):
            for key, value in io.items():
                if key == "format":
                    append_unique(node, prop, value)
                elif key == "maxSize" and isinstance(io.get("format"), str):        # format 을 키로 하는 DictionaryEntry
                    node.setdefault(max_prop, []).append(entry(io["format"], value))
                else:
                    ext.fix(f"modelCard:{field}:{i}:{key}", value)
    route_typed_fields(node, ext, params, "modelCard:modelParameters", typed=True, scalars=MODEL_PARAM_SCALAR,
                       lists=MODEL_PARAM_LIST, dicts={}, ext_only=MODEL_PARAM_EXT_ONLY)
    for i, h in enumerate(params.get("hyperparameters") or []):
        if h.get("name") and h.get("value") is not None:
            node.setdefault("ai_hyperparameter", []).append(entry(h["name"], h["value"]))
        else:
            for key, value in h.items():
                ext.fix(f"modelCard:modelParameters:hyperparameters:{i}:{key}", value)


def _quantitative(node: dict, ext: ExtBuffer, qa: dict) -> None:
    for i, m in enumerate(qa.get("performanceMetrics") or []):
        mtype = m.get("type")
        if mtype is None:
            for key, value in m.items():
                ext.fix(f"modelCard:performanceMetrics:{i}:{key}", value)
            continue
        if m.get("value") is not None:
            node.setdefault("ai_metric", []).append(entry(mtype, m["value"]))
        if m.get("slice") is not None:
            node.setdefault("aibom_metricSlice", []).append(entry(mtype, m["slice"]))
        for bound in ("lowerBound", "upperBound"):
            ext.fix(f"modelCard:performanceMetrics:{i}:confidenceInterval:{bound}", (m.get("confidenceInterval") or {}).get(bound))
    ext.fix("modelCard:graphics:description", (qa.get("graphics") or {}).get("description"))


def _considerations(node: dict, ext: ExtBuffer, cons: dict) -> None:
    for user in cons.get("users") or []:
        append_unique(node, "aibom_users", user)
    for case in cons.get("useCases") or []:
        append_unique(node, "aibom_useCases", case)
    if cons.get("useCases"):
        node["ai_informationAboutApplication"] = "\n".join(cons["useCases"])
    if cons.get("technicalLimitations"):
        node["ai_limitation"] = "\n".join(cons["technicalLimitations"])
    for i, t in enumerate(cons.get("performanceTradeoffs") or []):
        ext.fix(f"modelCard:considerations:performanceTradeoffs:{i}", t)
    for i, e in enumerate(cons.get("ethicalConsiderations") or []):
        if e.get("name"):
            append_unique(node, "aibom_ethicalConsiderations", e["name"])
            if e.get("mitigationStrategy"):
                node.setdefault("aibom_ethicalConsiderationsMitigationStrategy", []).append(entry(e["name"], e["mitigationStrategy"]))
        else:                                                    # name 없는 risk — 완화 전략만이라도 남긴다
            ext.fix(f"modelCard:considerations:ethicalConsiderations:{i}:mitigationStrategy", e.get("mitigationStrategy"))
    for i, f in enumerate(cons.get("fairnessAssessments") or []):
        group = f.get("groupAtRisk")
        if group:
            append_unique(node, "aibom_fairnessAssessments", group)
            if f.get("benefits"):
                node.setdefault("aibom_fairnessAssessmentBenefits", []).append(entry(group, f["benefits"]))
            if f.get("harms"):
                node.setdefault("aibom_fairnessAssessmentHarms", []).append(entry(group, f["harms"]))
        else:
            ext.fix(f"modelCard:considerations:fairnessAssessments:{i}:benefits", f.get("benefits"))
            ext.fix(f"modelCard:considerations:fairnessAssessments:{i}:harms", f.get("harms"))
        ext.fix(f"modelCard:considerations:fairnessAssessments:{i}:mitigationStrategy", f.get("mitigationStrategy"))
    route_typed_fields(node, ext, cons, "modelCard:considerations", typed=True, scalars=CONSIDERATION_SCALAR,
                       lists=CONSIDERATION_LIST, dicts={}, ext_only=CONSIDERATION_EXT_ONLY)
    env = cons.get("environmentalConsiderations") or {}
    _energy(node, ext, env.get("energyConsumptions") or [])
    for p in env.get("properties") or []:
        ext.fix(f"modelCard:environmentalConsiderations:properties:{p.get('name')}", p.get("value"))


def _energy(node: dict, ext: ExtBuffer, consumptions: list[dict]) -> None:
    energy: dict = {"type": "ai_EnergyConsumption"}
    for i, ec in enumerate(consumptions):
        prefix = f"modelCard:energyConsumptions:{i}"
        cost = ec.get("activityEnergyCost") or {}
        slot = ENERGY_SLOT_BY_ACTIVITY.get(ec.get("activity"))
        if slot and _energy_number(cost.get("value")):
            unit = ENERGY_UNIT.get(cost.get("unit"), "other")
            energy.setdefault(slot, []).append({"type": "ai_EnergyConsumptionDescription",
                                                "ai_energyQuantity": cost["value"], "ai_energyUnit": unit})
            if unit == "other":
                ext.fix(f"{prefix}:activityEnergyCost:unit", cost.get("unit"))
        else:
            ext.fix(f"{prefix}:activity", ec.get("activity"))
            ext.fix(f"{prefix}:activityEnergyCost:value", cost.get("value"))
            ext.fix(f"{prefix}:activityEnergyCost:unit", cost.get("unit"))
        for field in ("co2CostEquivalent", "co2CostOffset"):
            ext.fix(f"{prefix}:{field}:value", (ec.get(field) or {}).get("value"))
            ext.fix(f"{prefix}:{field}:unit", (ec.get(field) or {}).get("unit"))
        for j, p in enumerate(ec.get("energyProviders") or []):
            ext.fix(f"{prefix}:energyProviders:{j}:organization:name", (p.get("organization") or {}).get("name"))
            ext.fix(f"{prefix}:energyProviders:{j}:energySource", p.get("energySource"))
            ext.fix(f"{prefix}:energyProviders:{j}:energyProvided:value", (p.get("energyProvided") or {}).get("value"))
        for p in ec.get("properties") or []:
            ext.fix(f"{prefix}:properties:{p.get('name')}", p.get("value"))
    if len(energy) > 1:
        node["ai_energyConsumption"] = energy


def _energy_number(value) -> bool:
    """ai_energyQuantity 는 number 또는 숫자 문자열만 받는다. 아니면 확장 분기로 보낸다."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) or (isinstance(value, str) and bool(_ENERGY_NUMBER.match(value)))
