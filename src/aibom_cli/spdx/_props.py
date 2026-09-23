"""properties[] 라우터. 타입 있는 슬롯이 받아 주면 소비하고, 나머지는 확장에 원문으로 남긴다.

- 컴포넌트 properties: syft:cpe23 → ExternalIdentifier, cdx:ai:modality → dataset_datasetType, aibom:* → 어휘 라우터
- modelCard.properties: genai:aibom:modelcard:* → ai_hyperparameter, genai:aibom:trainingData* → ai_informationAboutTraining,
  safetensors_total_parameters → aibom_parameterCount, safetyRiskAssessment → ai_safetyRiskAssessment(enum 일 때만)
- aibom:model:* 는 ai_AIPackage 에서만, aibom:dataset:* 는 dataset_DatasetPackage 에서만 슬롯으로 간다 (AIBOM_CLASS_BY_PREFIX).
  다른 클래스에는 그 속성이 정의돼 있지 않아 원문으로 남긴다.
- dict 형 항목(aibom:model:inputs:<i>:maxSize …)의 키는 같은 인덱스의 키 leaf 프로퍼티다. 그 프로퍼티가 없으면 타입 있는
  필드(modelParameters.inputs[i].format)를 키로 쓴다 — regulation 이 maxSize 만 프로퍼티로 승격하고 format 은 타입 필드에 두기 때문.
- v0.6 타입 있는 JSON 필드(componentData.size, modelParameters.parameterCount …)는 route_typed_fields 가 같은 규칙으로 옮긴다.
  스칼라 슬롯은 먼저 채운 쪽이 이기고 나중 값은 aibom:cdx:<경로> 로 남는다 (아무것도 조용히 버리지 않는다).
- strict 모드: aibom_* 를 properties.md 키 이름의 확장 항목으로 내린다 (공식 스키마는 aibom_* 를 거부한다).
"""
from __future__ import annotations

import json
import re

from ._ctx import Ctx, ExtBuffer, stringify
from ._tables import (
    AIBOM_CLASS_BY_PREFIX, AIBOM_INDEXED, AIBOM_SCALAR, AVAILABILITY, DATASET_TYPES, PRESENCE, SAFETY_RISK,
    STRICT_KEY_LEAF, STRICT_KEYS, STRICT_NS_BY_CLASS,
)

_INDEXED = re.compile(r"^(?P<prefix>aibom:(?:model|dataset):[A-Za-z]+):(?P<i>\d+)(?::(?P<leaf>[A-Za-z]+))?$")


def entry(key: str, value) -> dict:
    return {"type": "DictionaryEntry", "key": key, "value": stringify(value)}


def append_unique(node: dict, prop: str, value) -> None:
    lst = node.setdefault(prop, [])
    if value not in lst:
        lst.append(value)


def _non_negative_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except ValueError:
            return None
    return value if value >= 0 else None


def _coerce(kind: str, value) -> object | None:
    """슬롯 종류에 맞게 값을 검사·정규화한다. 실패하면 None (확장으로 보낸다)."""
    if kind == "str":
        return value if isinstance(value, str) else stringify(value)
    if kind == "int":
        return _non_negative_int(value)
    text = str(value).strip().lower()
    if kind == "presence":
        return PRESENCE.get(text)
    if kind == "risk":
        return text if text in SAFETY_RISK else None
    if kind == "availability":
        return AVAILABILITY.get(text)
    return None


def _scalar(node: dict, prop: str, kind: str, value) -> bool:
    """스칼라 슬롯에 넣는다. enum/정수 검사에 실패하거나 이미 다른 값이 있으면 False (확장으로 보낸다)."""
    v = _coerce(kind, value)
    if v is None or (prop in node and node[prop] != v):
        return False
    node[prop] = v
    return True


def set_scalar(node: dict, ext: ExtBuffer, prop: str, kind: str, value, ext_path: str) -> None:
    """타입 있는 필드용: 슬롯에 못 넣으면 aibom:cdx:<ext_path> 로 남긴다."""
    if not _scalar(node, prop, kind, value):
        ext.fix(ext_path, value)


def route_typed_fields(node: dict, ext: ExtBuffer, obj: dict, prefix: str, *, typed: bool,
                       scalars: dict, lists: dict, dicts: dict, ext_only: tuple[str, ...]) -> None:
    """v0.6 타입 있는 JSON 필드 → 슬롯. typed=False(클래스가 슬롯을 갖지 않음)면 전부 aibom:cdx:<prefix>:<필드> 로."""
    for field, (prop, kind) in scalars.items():
        if obj.get(field) is not None:
            if typed:
                set_scalar(node, ext, prop, kind, obj[field], f"{prefix}:{field}")
            else:
                ext.fix(f"{prefix}:{field}", obj[field])
    for field, rule in lists.items():
        for j, value in enumerate(obj.get(field) or []):
            if typed and (len(rule) == 1 or value in rule[1]):
                append_unique(node, rule[0], value)
            else:
                ext.fix(f"{prefix}:{field}:{j}", value)
    for field, (key_leaf, list_prop, leaves) in dicts.items():
        for j, item in enumerate(obj.get(field) or []):
            key = item.get(key_leaf)
            if typed and key is not None:
                if list_prop:
                    append_unique(node, list_prop, key)
                for leaf, prop in leaves.items():
                    if item.get(leaf) is not None:
                        node.setdefault(prop, []).append(entry(key, item[leaf]))
                continue
            for leaf, value in item.items():
                ext.fix(f"{prefix}:{field}:{j}:{leaf}", value)
    for field in ext_only:
        for j, value in enumerate(obj.get(field) or []):
            ext.fix(f"{prefix}:{field}:{j}", value)


def _typed_here(node: dict, name: str) -> bool:
    """이 원소 클래스가 aibom:<prefix>:* 의 슬롯을 갖는가."""
    prefix = ":".join(name.split(":", 2)[:2])
    return AIBOM_CLASS_BY_PREFIX.get(prefix) == node["type"]


KeyFallback = dict[tuple[str, str], dict[str, str]]                # (prefix, i) → {키 leaf: 타입 있는 필드의 값}


def typed_index_keys(card: dict | None) -> KeyFallback:
    """modelCard 의 타입 있는 inputs/outputs[i].format 을 dict 형 aibom:* 항목의 키 대체값으로."""
    params = (card or {}).get("modelParameters") or {}
    fallback: KeyFallback = {}
    for field in ("inputs", "outputs"):
        for i, io in enumerate(params.get(field) or []):
            if isinstance(io, dict) and isinstance(io.get("format"), str):
                fallback[(f"aibom:model:{field}", str(i))] = {"format": io["format"]}
    return fallback


def route_aibom(ctx: Ctx, node: dict, ext: ExtBuffer, props: list[tuple[str, str | None]], owner_key: str,
                key_fallback: KeyFallback | None = None) -> None:
    """aibom:model:* / aibom:dataset:* 항목을 타입 있는 슬롯으로. 검사에 실패한 값·슬롯 없는 클래스는 원문으로 남긴다."""
    groups: dict[tuple[str, str], dict[str | None, str]] = {}
    for name, value in props:
        if value is None or not _typed_here(node, name):
            ext.prop(name, value)
            continue
        if name in AIBOM_SCALAR:
            prop, kind = AIBOM_SCALAR[name]
            if not _scalar(node, prop, kind, value):
                ext.prop(name, value)
            continue
        m = _INDEXED.match(name)
        if m and m["prefix"] in AIBOM_INDEXED:
            groups.setdefault((m["prefix"], m["i"]), {})[m["leaf"]] = value
            continue
        ext.prop(name, value)

    for (prefix, i), leaves in groups.items():
        rules = AIBOM_INDEXED[prefix]
        used_keys: set[str] = set()
        for leaf, value in leaves.items():
            rule = rules.get(leaf)
            if rule is None:
                ext.prop(_name(prefix, i, leaf), value)
            elif rule[0] == "list":
                append_unique(node, rule[1], value)
            elif rule[0] == "enumlist":
                if value in rule[2]:
                    append_unique(node, rule[1], value)
                else:
                    ext.prop(_name(prefix, i, leaf), value)
            elif rule[0] == "dict":
                key_value = leaves.get(rule[2])
                if key_value is None:                            # 같은 인덱스의 키 프로퍼티가 없으면 타입 있는 필드의 키로
                    key_value = (key_fallback or {}).get((prefix, i), {}).get(rule[2])
                else:
                    used_keys.add(rule[2])
                if key_value is None:
                    ext.prop(_name(prefix, i, leaf), value)
                else:
                    node.setdefault(rule[1], []).append(entry(key_value, value))
            elif rule[0] == "usage":
                ctx.usage[(owner_key, int(i))] = value.strip().lower()
        for leaf, value in leaves.items():
            rule = rules.get(leaf)
            if rule is not None and rule[0] == "key" and leaf not in used_keys:
                ext.prop(_name(prefix, i, leaf), value)


def _name(prefix: str, i: str, leaf: str | None) -> str:
    return f"{prefix}:{i}" + (f":{leaf}" if leaf else "")


def route_component_properties(ctx: Ctx, node: dict, ext: ExtBuffer, props: list[dict], owner_key: str,
                               key_fallback: KeyFallback | None = None) -> None:
    aibom: list[tuple[str, str | None]] = []
    for p in props or []:
        name = p.get("name") or ""
        value = None if p.get("value") is None else stringify(p["value"])
        if name == "syft:cpe23" and value:
            add_external_identifier(node, "cpe23", value, comment="syft:cpe23 candidate")
        elif name == "cdx:ai:modality" and node["type"] == "dataset_DatasetPackage" and value in DATASET_TYPES:
            append_unique(node, "dataset_datasetType", value)
        elif name.startswith("aibom:"):
            aibom.append((name, value))
        else:
            ext.prop(name, value)
    route_aibom(ctx, node, ext, aibom, owner_key, key_fallback)


def route_modelcard_properties(ctx: Ctx, node: dict, ext: ExtBuffer, props: list[dict], owner_key: str,
                               key_fallback: KeyFallback | None = None) -> None:
    aibom: list[tuple[str, str | None]] = []
    training: list[str] = []
    for p in props or []:
        name = p.get("name") or ""
        value = None if p.get("value") is None else stringify(p["value"])
        if value is None:
            ext.prop(name, value)
        elif name == "genai:aibom:modelcard:hyperparameter":
            node.setdefault("ai_hyperparameter", []).extend(_hyperparameters(value))
        elif name.startswith("genai:aibom:modelcard:"):
            node.setdefault("ai_hyperparameter", []).append(entry(name.rsplit(":", 1)[1], value))
        elif name.startswith("genai:aibom:trainingData"):
            training.append(_training_line(name, value))
        elif name.rsplit(":", 1)[-1] == "safetensors_total_parameters" and _scalar(node, "aibom_parameterCount", "int", value):
            pass
        elif name.rsplit(":", 1)[-1] == "safetyRiskAssessment" and _scalar(node, "ai_safetyRiskAssessment", "risk", value):
            pass
        elif name.startswith("aibom:"):
            aibom.append((name, value))
        else:
            ext.prop(name, value)
    if training:
        node["ai_informationAboutTraining"] = "\n".join(training)
    route_aibom(ctx, node, ext, aibom, owner_key, key_fallback)


def _hyperparameters(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return [entry(k, v) for k, v in parsed.items()]
    return [entry("hyperparameter", raw)]


def _training_line(name: str, value: str) -> str:
    suffix = name.removeprefix("genai:aibom:")
    if suffix == "trainingDataAvailable":
        return f"Training data available: {value}"
    if suffix == "trainingDataStatus":
        return value
    return f"{suffix}: {value}"


def add_external_identifier(node: dict, id_type: str, identifier: str, *, comment: str | None = None,
                            locator: list[str] | None = None) -> None:
    """같은 (종류, 값) 은 한 번만. 주 식별자(cpe 필드)가 먼저 왔으면 후보 comment 는 붙지 않는다."""
    lst = node.setdefault("externalIdentifier", [])
    if any(x["externalIdentifierType"] == id_type and x["identifier"] == identifier for x in lst):
        return
    item = {"type": "ExternalIdentifier", "externalIdentifierType": id_type, "identifier": identifier}
    if locator:
        item["identifierLocator"] = list(locator)
    if comment:
        item["comment"] = comment
    lst.append(item)


# -- strict --------------------------------------------------------------------
def demote_aibom(node: dict, ext: ExtBuffer) -> None:
    """aibom_* 속성을 properties.md 키의 확장 항목으로 내리고 노드에서 지운다."""
    ns = STRICT_NS_BY_CLASS.get(node["type"], "model")
    for prop in [k for k in node if k.startswith("aibom_")]:
        value = node.pop(prop)
        rule = STRICT_KEYS.get(prop)
        if rule is None:
            ext.typed.append((f"aibom:{ns}:{prop.removeprefix('aibom_')}", stringify(value)))
            continue
        template = rule[1].replace("{ns}", ns)
        if rule[0] == "scalar":
            ext.typed.append((template, stringify(value)))
        elif rule[0] == "list":
            for i, v in enumerate(value):
                ext.typed.append((template.format(i=i), stringify(v)))
        elif rule[0] == "kv":
            for i, d in enumerate(value):
                ext.typed.append((f"{template.format(i=i)}:type", d["key"]))
                ext.typed.append((f"{template.format(i=i)}:value", d.get("value", "")))
        elif rule[0] == "dict":
            _demote_dict(node, ext, template, rule[2], value)


def _demote_dict(node: dict, ext: ExtBuffer, template: str, list_prop: str, entries: list[dict]) -> None:
    """DictionaryEntry 는 짝 목록(list_prop)에서 키의 인덱스를 찾아 같은 <i> 로 적는다. 없으면 뒤에 붙이고 키도 적는다."""
    keys = [x["key"] if isinstance(x, dict) else x for x in _demoted_list(node, ext, list_prop)]
    extra = 0
    for d in entries:
        if d["key"] in keys:
            i = keys.index(d["key"])
        else:
            i = len(keys) + extra
            extra += 1
            leaf = STRICT_KEY_LEAF.get(list_prop, "key")
            ext.typed.append((template.format(i=i).rsplit(":", 1)[0] + f":{leaf}", d["key"]))
        ext.typed.append((template.format(i=i), d.get("value", "")))


def _demoted_list(node: dict, ext: ExtBuffer, list_prop: str) -> list:
    """짝 목록이 아직 노드에 있으면 그것, 이미 확장으로 내려갔으면 확장 항목에서 복원한다."""
    if list_prop in node:
        return node[list_prop]
    rule = STRICT_KEYS.get(list_prop)
    if rule is None:
        return []
    prefix = rule[1].split("{i}")[0]
    return [v for name, v in ext.typed if name.startswith(prefix) and name.endswith(rule[1].split("{i}")[1])]
