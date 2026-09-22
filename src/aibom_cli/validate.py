"""aibom-v0.6 스키마로 출력을 검증한다. jsonschema 가 없으면 건너뛴다.

CycloneDX 는 draft-07, SPDX 는 draft 2020-12 (unevaluatedProperties 를 알아야 해서 Draft202012Validator 필수).
SPDX 는 스키마가 못 보는 참조 무결성(id 중복, 끊긴 참조, createdBy 가 Tool 인 경우 등)도 함께 본다.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
CDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-cyclonedx.schema.json"
SPDX_SCHEMA = SCHEMA_DIR / "aibom-v0.6-spdx.schema.json"
SPDX_OFFICIAL_SCHEMA = SCHEMA_DIR / "spdx-schema-3-0-1.json"

_IRI = re.compile(r"^(?!_:).+:.+")
_INDIVIDUALS = frozenset({"NoneElement", "NoAssertionElement", "SpdxOrganization",
                          "expandedlicensing_NoneLicense", "expandedlicensing_NoAssertionLicense"})
_AGENT_TYPES = frozenset({"Organization", "Person", "SoftwareAgent", "Agent"})
_REF_KEYS = ("creationInfo", "from", "to", "element", "rootElement", "createdBy", "createdUsing",
             "suppliedBy", "originatedBy", "dataLicense", "subject")
_FILE_FORBIDDEN = ("software_packageVersion", "software_packageUrl", "software_downloadLocation",
                   "software_homePage", "software_sourceInfo")


@lru_cache(maxsize=4)
def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=4)
def _spdx_validator(path: Path):
    """스키마가 200KB 라 컴파일이 비싸다 — 경로별로 한 번만 만든다."""
    import jsonschema
    return jsonschema.Draft202012Validator(_load(path))


@lru_cache(maxsize=None)
def _spdx_node_validator(path: Path, node_type: str):
    import jsonschema
    wrapper = {"$defs": _load(path)["$defs"], "type": "object", "allOf": [{"$ref": f"#/$defs/{node_type}"}],
               "unevaluatedProperties": False}
    return jsonschema.Draft202012Validator(wrapper)


def validate_cdx(doc: dict, log=print) -> bool:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        log("[validate] jsonschema/referencing 미설치 — 검증 생략 (pip install 'aibom-cli[validate]')")
        return True

    registry = Registry()
    for f in SCHEMA_DIR.glob("*.json"):
        schema = _load(f)
        uri = schema.get("$id") or f.name
        registry = registry.with_resource(uri, Resource.from_contents(schema))
        registry = registry.with_resource(f.name, Resource.from_contents(schema))

    validator = jsonschema.Draft7Validator(_load(CDX_SCHEMA), registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    _report([f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors], log)
    return not errors


def validate_spdx(doc: dict, strict: bool = False, log=print) -> bool:
    """@graph 문서 전체를 v0.6 SPDX 스키마(strict=True 면 공식 3.0.1 스키마)로 검증하고 참조 무결성을 본다."""
    try:
        import jsonschema
    except ImportError:
        log("[validate] jsonschema 미설치 — 검증 생략 (pip install 'aibom-cli[validate]')")
        return True
    path = SPDX_OFFICIAL_SCHEMA if strict else SPDX_SCHEMA
    messages: list[str] = []
    if next(_spdx_validator(path).iter_errors(doc), None) is not None:
        messages += _localize(path, doc)
    messages += spdx_integrity_findings(doc)
    _report(messages, log)
    return not messages


def _localize(path: Path, doc: dict) -> list[str]:
    """문서 전체 실패는 oneOf 탓에 쓸모없는 메시지만 나오므로 @graph 원소별로 다시 검증해 자리를 짚는다."""
    schema = _load(path)
    out: list[str] = []
    graph = doc.get("@graph")
    if doc.get("@context") != schema["properties"]["@context"]["const"]:
        out.append("@context 가 SPDX 3.0.1 컨텍스트가 아니다")
    if not isinstance(graph, list):
        return out + ["@graph 가 배열이 아니다"]
    for extra in sorted(set(doc) - {"@context", "@graph"}):
        out.append(f"루트에 허용되지 않는 키: {extra}")
    for i, node in enumerate(graph):
        ntype = node.get("type") if isinstance(node, dict) else None
        label = f"@graph[{i}] {ntype} {node.get('spdxId') or node.get('@id') or ''}".rstrip()
        if ntype not in schema["$defs"]:
            out.append(f"{label}: 알 수 없는 type")
            continue
        errors = list(_spdx_node_validator(path, ntype).iter_errors(node))
        specific = [e for e in errors if not e.message.startswith("Unevaluated properties are not allowed")]
        for e in specific or errors:
            where = "/".join(str(p) for p in e.path)
            out.append(f"{label}: {where + ': ' if where else ''}{e.message}")
    return out or ["문서가 스키마에 맞지 않지만 원소 단위로는 오류를 찾지 못했다"]


def spdx_integrity_findings(doc: dict) -> list[str]:
    """JSON 스키마가 못 보는 것: id 중복·형식, 끊긴 참조, createdBy/createdUsing 종류, rootElement ⊆ element,
    빈 extension, null 값 키, software_File 의 Package 속성, DatasetPackage 의 datasetType, CreationInfo·SpdxDocument 개수."""
    graph = doc.get("@graph") or []
    findings: list[str] = []
    nodes: dict[str, dict] = {}
    for i, node in enumerate(graph):
        nid = node.get("spdxId") or node.get("@id")
        if nid is None:
            findings.append(f"@graph[{i}] {node.get('type')}: spdxId/@id 가 없다")
            continue
        if nid in nodes:
            findings.append(f"@graph[{i}]: 중복 id {nid}")
        nodes[nid] = node
        if "spdxId" in node and not _IRI.match(nid):
            findings.append(f"@graph[{i}]: spdxId 가 IRI 형식이 아니다: {nid}")

    imports = {m.get("externalSpdxId") for n in graph if n.get("type") == "SpdxDocument" for m in n.get("import") or []}
    known = set(nodes) | _INDIVIDUALS | imports
    for node in graph:
        label = f"{node.get('type')} {node.get('spdxId') or node.get('@id')}"
        for key in sorted(k for k, v in node.items() if v is None):        # 어떤 스키마도 null 을 받지 않는다
            findings.append(f"{label}: {key} 가 null 이다")
        for key in _REF_KEYS:
            for ref in _as_list(node.get(key)):
                if not isinstance(ref, str):                     # 목록 안의 null 도 스키마가 거부한다 — 여기서 먼저 잡는다
                    findings.append(f"{label}: {key} 에 문자열이 아닌 항목 {ref!r}")
                elif ref not in known:
                    findings.append(f"{label}: {key} 가 문서에 없는 {ref} 를 가리킨다")
        for d in node.get("simplelicensing_customIdToUri") or []:
            if d.get("value") not in known:
                findings.append(f"{label}: customIdToUri 가 문서에 없는 {d.get('value')} 를 가리킨다")
        for ref in _as_list(node.get("createdBy")):
            if isinstance(ref, str) and ref in nodes and nodes[ref].get("type") not in _AGENT_TYPES:
                findings.append(f"{label}: createdBy 가 Agent 가 아닌 {nodes[ref].get('type')} 를 가리킨다")
        for ref in _as_list(node.get("createdUsing")):
            if isinstance(ref, str) and ref in nodes and nodes[ref].get("type") != "Tool":
                findings.append(f"{label}: createdUsing 이 Tool 이 아닌 {nodes[ref].get('type')} 를 가리킨다")
        if "rootElement" in node and not set(node["rootElement"]) <= set(node.get("element") or []):
            findings.append(f"{label}: rootElement 가 element 의 부분집합이 아니다")
        if "extension" in node and (not node["extension"] or any(not e.get("extension_cdxProperty") for e in node["extension"])):
            findings.append(f"{label}: 빈 extension")
        if node.get("type") == "software_File":
            for key in _FILE_FORBIDDEN:
                if key in node:
                    findings.append(f"{label}: software_File 에 {key}")
        if node.get("type") == "dataset_DatasetPackage" and not node.get("dataset_datasetType"):
            findings.append(f"{label}: dataset_datasetType 이 없다")
        if node.get("type") == "Relationship":
            if not isinstance(node.get("from"), str):
                findings.append(f"{label}: from 이 문자열이 아니다")
            if not node.get("to"):
                findings.append(f"{label}: to 가 비었다")
        ci = node.get("creationInfo")
        if isinstance(ci, str) and nodes.get(ci, {}).get("type") != "CreationInfo":
            findings.append(f"{label}: creationInfo 가 CreationInfo 노드를 가리키지 않는다")

    for ntype in ("CreationInfo", "SpdxDocument"):
        n = sum(1 for x in graph if x.get("type") == ntype)
        if n != 1:
            findings.append(f"최상위 {ntype} 가 {n}개 (정확히 1개여야 한다)")
    return findings


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _report(messages: list[str], log) -> None:
    for m in messages[:20]:
        log(f"[validate] {m}")
    if len(messages) > 20:
        log(f"[validate] … 외 {len(messages) - 20}건")
