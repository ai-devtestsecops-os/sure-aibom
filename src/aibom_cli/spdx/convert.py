"""CycloneDX 1.7 → SPDX 3.0.1 JSON-LD.

세 도구 어느 것도 SPDX 3.0.1 의 AI·데이터셋 프로파일을 쓰지 않으므로 여기서 직접 만든다.
설계 문서: spdx_spec(element_id_scheme·document_skeleton·mapping·relationships) + spdx_critique 의 수정 사항.

    metadata                        → CreationInfo(_:creationinfo) · SpdxDocument · software_Sbom · SoftwareAgent · Tool
    component.type                  → ai_AIPackage | dataset_DatasetPackage | software_File | software_Package
    modelCard                       → ai_* + aibom_*(v0.6)   modelCard.properties → 타입 승격 후 나머지는 Extension
    component.data[]                → DatasetPackage 접기/펼치기 (+hasDataFile)
    modelParameters.datasets[]      → trainedOn / testedOn      dependencies[] → dependsOn (+hasOptionalDependency)
    licenses[]                      → simplelicensing_LicenseExpression 풀 + hasDeclaredLicense/hasConcludedLicense
    pedigree                        → descendantOf / ancestorOf / hasVariant      nested components → contains 계열
    properties[]                    → extension_CdxPropertiesExtension (aibom:cdx:* 대체 항목 + 원문)

결정성: uuid4·시계를 쓰지 않는다. 모든 IRI 는 입력에서 유도되고 created 는 metadata.timestamp 다.
strict=True 는 v0.6 전용 aibom_* 속성을 확장 항목으로 내려 공식 SPDX 3.0.1 스키마에도 맞게 한다.

리뷰 뒤 spdx_spec 과 달라진 결정:
    - BOM-Link 는 그대로 쓰지 않고 urn:uuid:<serial>#SPDXRef-<enc(ref)> 로 옮긴다 (spec 의 "used verbatim" 대신).
      원본 BOM-Link 는 ExternalMap.locationHint 에 남긴다 — 다른 BOM 을 같은 변환기로 바꾸면 두 문서가 이어진다.
    - 같은 원시 키의 두 번째 등장은 라이선스 → 관계 대상, properties → 확장, 다른 필드 → aibom:cdx:duplicate:<n>:<필드>.
    - aibom:model:* / aibom:dataset:* 는 슬롯을 가진 클래스(ai_AIPackage / dataset_DatasetPackage)에서만 승격한다.
    - 스칼라 슬롯은 먼저 채운 쪽이 이긴다: 컴포넌트 properties → data[] 타입 필드 → modelCard 타입 필드 → modelCard.properties.
      밀린 값은 aibom:cdx:<경로> 로 남긴다.
    - SBOM·Agent-aibom-cli 조각은 Ctx 생성 시 예약한다. License-*/Relationship-* 는 첫 요청자가 갖는다 (_ids 참조).
    - Relationship 조각은 from 원소의 실제(접미 포함) 조각을 쓴다.
    - dataLicense 원소는 Sbom.element 와 SpdxDocument.element 양쪽에 든다.
    - 읽을 수 없는 metadata.timestamp 는 now 로 대신하고 원문을 SpdxDocument 확장 aibom:cdx:timestamp 에 남긴다.

TODO(보류 — 다음 단계에서 구현, 지금은 건수만 경고로 남기고 건너뛴다):
    - formulation[]      : workflows / tasks → build_Build, usesTool, formulation components
    - annotations[]      : Annotation (inline CreationInfo)
    - services[]         : software_Package 합성 (dependencies[].ref 가 서비스인 행은 해석 실패로 건너뛴다)
    - compositions[]     : Relationship.completeness
    - declarations[]     : ai_standardCompliance / standardName
    - evidence           : software_File 합성 + hasEvidence (위치는 aibom:cdx:evidence:* 로 잃지 않게 남긴다)
    - metadata.tools.services[] : Tool 합성 (지금은 건수 경고 + Sbom 확장 aibom:cdx:tools:services:<i>:* 로 이름·버전만 남긴다)
"""
from __future__ import annotations

import sys
from typing import Callable

from ..validate import spdx_integrity_findings
from ._ctx import Ctx, ExtBuffer, reorder
from ._datasets import apply_component_data, build_dataset_relationships, data_entry_element, ensure_dataset_type
from ._fields import (
    apply_evidence, apply_external_references, apply_hashes, apply_identifiers, apply_licenses, apply_mime_type,
    apply_parties, apply_patents, apply_pedigree_extras, apply_release_notes, license_expression, organization, person,
)
from ._ids import BOM_LINK, bomlink_iri, enc, iso_z, key_of, namespace, tool_key
from ._modelcard import apply_modelcard
from ._props import add_external_identifier, demote_aibom, route_component_properties, typed_index_keys
from ._tables import (
    CLASS_BY_TYPE, CONTEXT, CREATION_INFO_ID, NON_ROOT_RELATIONSHIPS, PACKAGE_CLASSES, PROFILE_ORDER, PURPOSE_BY_TYPE,
    RELATIONSHIP_ORDER, SBOM_TYPE_BY_PHASE, SPEC_VERSION,
)

_DEFERRED = ("formulation", "annotations", "services", "compositions", "declarations")


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def cdx_to_spdx(cdx: dict, strict: bool = False, *, log: Callable[[str], None] | None = None,
                now: str | None = None) -> dict:
    """CycloneDX 문서 → SPDX 3.0.1 JSON-LD 문서. 같은 입력이면 바이트 단위로 같은 출력."""
    ctx = Ctx(namespace(cdx), strict=strict, log=log or _stderr)
    meta = cdx.get("metadata") or {}
    _warn_deferred(ctx, cdx)

    created = iso_z(meta.get("timestamp"))
    if created is None and meta.get("timestamp"):
        ctx.warn(f"metadata.timestamp 를 읽을 수 없어 now 로 대신하고 원문은 aibom:cdx:timestamp 에 남긴다: {meta['timestamp']}")
        ctx.doc_ext.fix("timestamp", meta["timestamp"])
    created = created or iso_z(now)
    if created is None:
        raise ValueError("metadata.timestamp 가 없거나 읽을 수 없다 — 시계를 쓰지 않으므로 now 인자를 줘야 한다")

    agent_iri = _software_agent(ctx)
    tool_iris = _tools(ctx, meta)
    created_by = [agent_iri]
    created_by += [p for p in (person(ctx, a, in_sbom=False) for a in meta.get("authors") or []) if p]
    if meta.get("manufacturer"):
        org = organization(ctx, meta["manufacturer"], in_sbom=False)   # organizationalEntity 는 모든 필드가 선택 — 이름 없으면 None
        if org:
            created_by.append(org)

    root_iri = _root(ctx, cdx)
    for comp in cdx.get("components") or []:
        convert_component(ctx, comp, "artifacts")
    _second_pass(ctx, cdx)

    doc = _assemble(ctx, cdx, created, created_by, tool_iris, agent_iri, root_iri)
    findings = spdx_integrity_findings(doc)
    if findings:
        raise ValueError("SPDX 문서 불변식 위반:\n" + "\n".join(findings))
    return doc


# -- 골격 -------------------------------------------------------------------------
def _warn_deferred(ctx: Ctx, cdx: dict) -> None:
    for section in _DEFERRED:
        n = len(cdx.get(section) or [])
        if n:
            ctx.warn(f"{section}: {n}건 보류 — 이 단계에서는 변환하지 않는다")
    n = len(_tool_services(cdx))
    if n:
        ctx.warn(f"metadata.tools.services: {n}건 보류 — 이름·버전만 Sbom 확장 aibom:cdx:tools:services:* 에 남긴다")
    with_evidence = sum(1 for c in _walk(cdx.get("components") or []) if (c.get("evidence") or {}).get("occurrences"))
    if with_evidence:
        ctx.warn(f"evidence.occurrences: 컴포넌트 {with_evidence}개 — hasEvidence 보류, 위치는 aibom:cdx:evidence:* 로 남긴다")


def _tool_services(cdx: dict) -> list[dict]:
    tools = (cdx.get("metadata") or {}).get("tools")
    return (tools.get("services") or []) if isinstance(tools, dict) else []


def _walk(components: list[dict]):
    for c in components:
        yield c
        yield from _walk(c.get("components") or [])


def _software_agent(ctx: Ctx) -> str:
    iri, node, _ = ctx.element("Agent-aibom-cli", ("SoftwareAgent", "aibom-cli"), "SoftwareAgent", None)
    assert iri == ctx.agent_iri                                  # Ctx 가 먼저 예약한 조각
    node["name"] = "aibom-cli"
    return iri


def _tools(ctx: Ctx, meta: dict) -> list[str]:
    tools = meta.get("tools")
    entries = tools.get("components") or [] if isinstance(tools, dict) else tools or []
    iris: list[str] = []
    for tool in entries:
        key = tool_key(tool)
        iri, node, new = ctx.element(f"Tool-{enc(key)}", ("Tool", key), "Tool", "tools")
        if new:
            _fill_tool(ctx, node, ctx.ext_of(iri), tool)
        if iri not in iris:
            iris.append(iri)
    return iris


def _fill_tool(ctx: Ctx, node: dict, ext: ExtBuffer, tool: dict) -> None:
    node["name"] = tool.get("name") or tool.get("vendor") or "unnamed-tool"   # 조각은 tool_key, 이름은 읽을 수 있게
    if tool.get("description"):
        node["description"] = tool["description"]
    for field in ("bom-ref", "version", "group", "author", "publisher", "vendor"):
        ext.fix(field, tool.get(field))
    supplier = tool.get("supplier") or {}                        # Tool 에는 suppliedBy 가 없다
    ext.fix("supplier:name", supplier.get("name"))
    for i, url in enumerate(supplier.get("url") or []):
        ext.fix(f"supplier:url:{i}", url)
    if tool.get("type") and tool["type"] != "application":
        ext.fix("type", tool["type"])
    for i, a in enumerate(tool.get("authors") or []):
        ext.fix(f"authors:{i}:name", a.get("name"))
        ext.fix(f"authors:{i}:email", a.get("email"))
    if tool.get("purl"):
        add_external_identifier(node, "packageUrl", tool["purl"])
    apply_hashes(node, tool.get("hashes"))
    apply_external_references(node, ext, tool.get("externalReferences"), promote=False)
    for p in tool.get("properties") or []:
        ext.prop(p.get("name") or "", p.get("value"))


def _root(ctx: Ctx, cdx: dict) -> str | None:
    meta = cdx.get("metadata") or {}
    comp = meta.get("component")
    if not comp:
        return None
    iri = convert_component(ctx, comp, "root")
    node = ctx.nodes[iri]
    if meta.get("supplier") and "suppliedBy" not in node:
        org = organization(ctx, meta["supplier"], in_sbom=True)  # organizationalEntity 는 모든 필드가 선택 — 이름 없으면 None
        if org:
            node["suppliedBy"] = org
    if meta.get("manufacture"):
        org = organization(ctx, meta["manufacture"], in_sbom=True)
        if org and org not in node.setdefault("originatedBy", []):
            node["originatedBy"].append(org)
    apply_external_references(node, ctx.ext_of(iri), cdx.get("externalReferences"), promote=node["type"] in PACKAGE_CLASSES)
    return iri


# -- 컴포넌트 ---------------------------------------------------------------------
def convert_component(ctx: Ctx, comp: dict, category: str) -> str:
    """컴포넌트 하나 → 원소. 같은 원시 키는 첫 등장이 원소가 되고 이후는 관계 대상·확장 항목만 더한다."""
    key = key_of(comp)
    if key in ctx.key_iri:
        _merge_duplicate(ctx, comp, key, ctx.key_iri[key])
        return ctx.key_iri[key]
    cls = "ai_AIPackage" if comp.get("modelCard") else CLASS_BY_TYPE.get(comp.get("type"), "software_Package")
    iri, node, _ = ctx.element(enc(key), ("component", key), cls, category)
    ctx.bind_key(key, iri, comp)
    ctx.component_iris.append(iri)
    ext = ctx.ext_of(iri)

    _basics(node, ext, comp)
    apply_identifiers(node, ext, comp)
    apply_hashes(node, comp.get("hashes"))
    route_component_properties(ctx, node, ext, comp.get("properties") or [], key,       # 컴포넌트 값이 data[] 값보다 먼저
                               typed_index_keys(comp.get("modelCard")))
    _component_data(ctx, node, ext, comp, key, iri)                     # contents.url 이 distribution 승격보다 먼저
    apply_external_references(node, ext, comp.get("externalReferences"), promote=cls in PACKAGE_CLASSES)
    apply_parties(ctx, node, comp, iri)
    apply_licenses(ctx, iri, comp.get("licenses"))
    apply_mime_type(node, ext, comp.get("mime-type"))
    apply_release_notes(node, ext, comp.get("releaseNotes"))
    if comp.get("modelCard"):
        apply_modelcard(ctx, node, ext, comp["modelCard"], key)
        ctx.pending_datasets.append((comp["modelCard"], iri, key))
    ensure_dataset_type(node)
    apply_evidence(ext, comp.get("evidence"))
    apply_patents(ext, comp.get("patentAssertions"))
    apply_pedigree_extras(ext, comp.get("pedigree"))
    if comp.get("pedigree"):
        ctx.pending_pedigree.append((comp, iri, key))
    _nested(ctx, comp, iri)
    return iri


_DUPLICATE_SKIP = frozenset({"bom-ref", "licenses", "properties", "components"})


def _merge_duplicate(ctx: Ctx, comp: dict, key: str, iri: str) -> None:
    """같은 키의 두 번째 등장: 라이선스는 관계 대상으로, properties 는 확장으로, 다른 스칼라는 aibom:cdx:duplicate:<n>:* 로."""
    first = ctx.records.get(iri) or {}
    differing = [(f, v) for f, v in comp.items() if f not in _DUPLICATE_SKIP and first.get(f) != v]
    if not differing and not any(comp.get(f) for f in ("licenses", "properties", "components")):
        return                                                   # {"bom-ref": …} 만 있는 순수 참조(pedigree 등)는 조용히 지나간다
    ext = ctx.ext_of(iri)
    n = len({name.split(":")[3] for name, _ in ext.fixed if name.startswith("aibom:cdx:duplicate:")})
    ctx.warn(f"중복 키 {key}: 첫 등장이 원소가 되고 이후 항목은 관계·확장으로만 합친다")
    apply_licenses(ctx, iri, comp.get("licenses"))
    for p in comp.get("properties") or []:
        ext.prop(p.get("name") or "", p.get("value"))
    for field, value in differing:
        ext.fix(f"duplicate:{n}:{field}", value)
    _nested(ctx, comp, iri)


def _basics(node: dict, ext: ExtBuffer, comp: dict) -> None:
    node["name"] = comp.get("name") or "unnamed-component"
    if comp.get("description"):
        node["description"] = comp["description"]
    ext.fix("bom-ref", comp.get("bom-ref"))
    ext.fix("group", comp.get("group"))
    if comp.get("scope") in ("optional", "excluded"):
        ext.fix("scope", comp["scope"])
    if comp.get("version"):
        if node["type"] in PACKAGE_CLASSES:
            node["software_packageVersion"] = comp["version"]
        else:
            ext.fix("version", comp["version"])
    purpose = PURPOSE_BY_TYPE.get(comp.get("type"))
    if purpose:
        node["software_primaryPurpose"] = purpose
    if comp.get("type") == "cryptographic-asset":
        ext.fix("type", comp["type"])
    if node["type"] == "software_File":
        kind = _file_kind(comp)
        if kind:
            node["software_fileKind"] = kind
    if comp.get("copyright"):
        node["software_copyrightText"] = comp["copyright"]
    for i, tag in enumerate(comp.get("tags") or []):
        ext.fix(f"tags:{i}", tag)


def _file_kind(comp: dict) -> str | None:
    """CycloneDX file 은 파일/디렉터리를 구분하지 않는다. 아는 경우에만 software_fileKind 를 낸다."""
    for p in comp.get("properties") or []:
        if p.get("name") == "cdx:file:kind" and p.get("value") in ("file", "directory"):
            return p["value"]
    return "directory" if (comp.get("name") or "").endswith("/") else None


def _component_data(ctx: Ctx, node: dict, ext: ExtBuffer, comp: dict, key: str, iri: str) -> None:
    data = comp.get("data") or []
    fold = node["type"] == "dataset_DatasetPackage" and bool(data) and data[0].get("type") in (None, "dataset")
    children: list[str] = []
    for i, d in enumerate(data):
        if i == 0 and fold:
            apply_component_data(ctx, node, ext, d, 0, folded=True, owner_key=key)
        else:
            children.append(data_entry_element(ctx, d, i, owner_key=key, fallback_fragment=f"{enc(key)}-data-{i}"))
    ctx.rel(iri, "hasDataFile", children)


def _nested(ctx: Ctx, comp: dict, parent_iri: str) -> None:
    """components[].components[]: optional → hasOptionalComponent, excluded(런타임 동적 링크) → hasDynamicLink, 그 외 contains."""
    for child in comp.get("components") or []:
        child_iri = convert_component(ctx, child, "artifacts")
        scope = child.get("scope")
        rtype = "hasOptionalComponent" if scope == "optional" else "hasDynamicLink" if scope == "excluded" else "contains"
        ctx.rel(parent_iri, rtype, [child_iri])


# -- 2차: 모든 원소가 있어야 하는 관계 ----------------------------------------------------
def _second_pass(ctx: Ctx, cdx: dict) -> None:
    i = 0
    while i < len(ctx.pending_pedigree):                      # 조상 변환이 목록을 늘릴 수 있다
        _pedigree(ctx, *ctx.pending_pedigree[i])
        i += 1
    for card, iri, key in list(ctx.pending_datasets):
        build_dataset_relationships(ctx, card, iri, key)
    _dependencies(ctx, cdx)


def _pedigree(ctx: Ctx, comp: dict, iri: str, key: str) -> None:
    ped = comp.get("pedigree") or {}
    for field, rtype in (("ancestors", "descendantOf"), ("descendants", "ancestorOf"), ("variants", "hasVariant")):
        targets: list[str] = []
        for i, entry in enumerate(ped.get(field) or []):
            if key_of(entry) == key:                          # 자기 자신을 가리키면 관계 대신 원문만 남긴다
                ctx.ext_of(iri).fix(f"pedigree:{field}:{i}:bom-ref", entry.get("bom-ref") or key_of(entry))
                continue
            targets.append(convert_component(ctx, entry, "artifacts"))
        ctx.rel(iri, rtype, targets, comment=ped.get("notes"))


def _dependencies(ctx: Ctx, cdx: dict) -> None:
    seen: set[str] = set()
    for dep in cdx.get("dependencies") or []:
        ref = dep.get("ref")
        from_iri = ctx.key_iri.get(ref)
        if not from_iri:
            ctx.warn(f"dependencies[].ref 를 해석하지 못해 건너뛴다: {ref}")
            continue
        if ref in seen:                                          # merge() 는 ref 별로 접으므로 손으로 쓴 문서에서만 생긴다
            ctx.warn(f"dependencies[].ref 가 반복된다 — 대상을 한 관계로 합친다: {ref}")
        seen.add(ref)
        if dep.get("dependsOn") == []:
            ctx.rel(from_iri, "dependsOn", ["NoneElement"], completeness="complete")
        plain: list[str] = []
        optional: list[str] = []
        for target in dep.get("dependsOn") or []:
            iri = _resolve_target(ctx, target)
            if iri:
                (optional if (ctx.records.get(iri) or {}).get("scope") == "optional" else plain).append(iri)
        ctx.rel(from_iri, "dependsOn", plain)
        ctx.rel(from_iri, "hasOptionalDependency", optional)
        ctx.rel(from_iri, "hasSpecification", [p for p in (_resolve_target(ctx, x) for x in dep.get("provides") or []) if p])


def _resolve_target(ctx: Ctx, ref: str) -> str | None:
    if ref in ctx.key_iri:
        return ctx.key_iri[ref]
    link = BOM_LINK.match(ref or "")
    if link:
        if f"urn:uuid:{link['serial'].lower()}" == ctx.ns and link["ref"] in ctx.key_iri:
            return ctx.key_iri[link["ref"]]
        external = bomlink_iri(link)
        ctx.add_import(external, ref)
        return external
    ctx.warn(f"dependencies 대상을 해석하지 못해 버린다: {ref}")
    return None


# -- 조립 -------------------------------------------------------------------------
def _assemble(ctx: Ctx, cdx: dict, created: str, created_by: list[str], tool_iris: list[str],
              agent_iri: str, root_iri: str | None) -> dict:
    meta = cdx.get("metadata") or {}
    if ctx.strict:
        for iri, node in ctx.nodes.items():
            if any(k.startswith("aibom_") for k in node):
                demote_aibom(node, ctx.ext_of(iri))

    sbom_iri = ctx.sbom_iri
    sbom_ext = ExtBuffer()
    sbom: dict = {"type": "software_Sbom", "spdxId": sbom_iri, "creationInfo": CREATION_INFO_ID}
    doc_ext = ctx.doc_ext
    document: dict = {"type": "SpdxDocument", "spdxId": ctx.ns, "creationInfo": CREATION_INFO_ID}
    for choice in meta.get("licenses") or []:                  # dataLicense 원소도 Sbom.element 에 들어야 하므로 먼저
        lic = license_expression(ctx, choice)
        if lic:
            document["dataLicense"] = lic
            break

    rel_iris = _ordered_relationships(ctx)
    artifacts = ctx.order["root"] + ctx.order["artifacts"] + ctx.order["datasets"]
    sbom_elements = artifacts + ctx.sbom_agents + ctx.order["licenses"] + rel_iris

    name = (meta.get("component") or {}).get("name")
    if name:
        document["name"] = sbom["name"] = name
    sbom["rootElement"] = [root_iri] if root_iri else _graph_roots(ctx, artifacts)
    sbom["element"] = sbom_elements
    _sbom_type(sbom, sbom_ext, meta)
    if not meta.get("component"):
        apply_external_references(sbom, sbom_ext, cdx.get("externalReferences"), promote=False)
    for p in (meta.get("properties") or []) + (cdx.get("properties") or []):
        sbom_ext.prop(p.get("name") or "", p.get("value"))
    sbom_ext.fix("distributionConstraints:tlp", (meta.get("distributionConstraints") or {}).get("tlp"))
    for i, svc in enumerate(_tool_services(cdx)):               # 보류 — 이름·버전은 잃지 않게 남긴다
        for field in ("bom-ref", "name", "version", "description"):
            sbom_ext.fix(f"tools:services:{i}:{field}", svc.get(field))
        sbom_ext.fix(f"tools:services:{i}:provider:name", (svc.get("provider") or {}).get("name"))

    document["rootElement"] = [sbom_iri]
    if ctx.imports:                                            # 원본 BOM-Link 는 locationHint 로 남긴다
        document["import"] = [{"type": "ExternalMap", "externalSpdxId": x, "locationHint": link} for x, link in ctx.imports.items()]
    doc_ext.fix("bomFormat", cdx.get("bomFormat"))
    doc_ext.fix("specVersion", cdx.get("specVersion"))
    doc_ext.fix("bomVersion", cdx.get("version"))

    for iri, buf in ctx.ext.items():
        _attach_extension(ctx.nodes[iri], buf)
    _attach_extension(sbom, sbom_ext)
    _attach_extension(document, doc_ext)

    ordered = [sbom_iri, agent_iri] + tool_iris + ctx.order["agents"] + artifacts + ctx.order["licenses"] + rel_iris
    ctx.nodes[sbom_iri] = sbom
    document["element"] = ordered
    profiles = _profiles([document, sbom] + [ctx.nodes[i] for i in ordered])
    document["profileConformance"] = sbom["profileConformance"] = profiles

    creation = {"type": "CreationInfo", "@id": CREATION_INFO_ID, "specVersion": SPEC_VERSION,
                "created": created, "createdBy": created_by}
    if tool_iris:
        creation["createdUsing"] = tool_iris
    graph = [creation, document] + [ctx.nodes[i] for i in ordered]
    return {"@context": CONTEXT, "@graph": [reorder(n) for n in graph]}


def _ordered_relationships(ctx: Ctx) -> list[str]:
    known = [k for rtype in RELATIONSHIP_ORDER for k in ctx.rel_order if k[1] == rtype]
    rest = [k for k in ctx.rel_order if k[1] not in RELATIONSHIP_ORDER]
    return [ctx.rels[k]["spdxId"] for k in known + rest]


def _graph_roots(ctx: Ctx, artifacts: list[str]) -> list[str]:
    """metadata.component 가 없을 때: 포함·의존·학습 관계의 to 에 한 번도 등장하지 않는 아티팩트."""
    targets: set[str] = set()
    for (_, rtype), node in ctx.rels.items():
        if rtype in NON_ROOT_RELATIONSHIPS:
            targets.update(node["to"])
    return [a for a in artifacts if a not in targets]


def _sbom_type(sbom: dict, ext: ExtBuffer, meta: dict) -> None:
    for i, lc in enumerate(meta.get("lifecycles") or []):
        mapped = SBOM_TYPE_BY_PHASE.get(lc.get("phase"))
        if mapped:
            if mapped not in sbom.setdefault("software_sbomType", []):
                sbom["software_sbomType"].append(mapped)
        else:
            for field in ("phase", "name", "description"):
                ext.fix(f"lifecycles:{i}:{field}", lc.get(field))


def _attach_extension(node: dict, buf: ExtBuffer) -> None:
    entries = buf.entries()
    if entries:
        node["extension"] = [{"type": "extension_CdxPropertiesExtension", "extension_cdxProperty": entries}]


def _profiles(nodes: list[dict]) -> list[str]:
    types = {n["type"] for n in nodes}
    have = {"core", "software"}
    if "ai_AIPackage" in types:
        have.add("ai")
    if "dataset_DatasetPackage" in types:
        have.add("dataset")
    if "build_Build" in types:
        have.add("build")
    if any(t.startswith("simplelicensing_") for t in types):
        have.add("simpleLicensing")
    if any("extension" in n for n in nodes):
        have.add("extension")
    return [p for p in PROFILE_ORDER if p in have]
