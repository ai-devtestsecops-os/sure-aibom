"""컴포넌트 필드 단위 변환기: 식별자, 해시, 외부 참조, 주체(Agent), 라이선스, 릴리스 노트, 증거."""
from __future__ import annotations

import base64
import binascii
import re

from ._ctx import Ctx, ExtBuffer, stringify
from ._ids import enc, iso_z, license_ref
from ._props import add_external_identifier
from ._tables import CREATION_INFO_ID, EXTERNAL_REF_TYPE, HASH_ALGORITHM, PACKAGE_CLASSES

_MEDIA_TYPE = re.compile(r"^[^/]+/[^/]+$")


# -- 식별자 -----------------------------------------------------------------------
def apply_identifiers(node: dict, ext: ExtBuffer, comp: dict) -> None:
    purl = comp.get("purl")
    if purl:
        if node["type"] in PACKAGE_CLASSES:
            node["software_packageUrl"] = purl
        else:
            add_external_identifier(node, "packageUrl", purl)
    cpe = comp.get("cpe")
    if cpe:
        kind = "cpe23" if cpe.startswith("cpe:2.3:") else "cpe22" if cpe.startswith("cpe:/") else "other"
        add_external_identifier(node, kind, cpe)
    for gitoid in comp.get("omniborId") or []:
        add_external_identifier(node, "gitoid", gitoid)
    for swhid in comp.get("swhid") or []:
        add_external_identifier(node, "swhid", swhid)
    swid = comp.get("swid")
    if swid and swid.get("tagId"):
        add_external_identifier(node, "swid", swid["tagId"], locator=[swid["url"]] if swid.get("url") else None)
        for field in ("name", "version", "tagVersion", "patch"):
            if swid.get(field) is not None:
                ext.fix(f"swid:{field}", swid[field])


def apply_hashes(node: dict, hashes: list[dict] | None) -> None:
    for h in hashes or []:
        alg, content = h.get("alg"), h.get("content")
        if not content:
            continue
        item = {"type": "Hash", "algorithm": HASH_ALGORITHM.get(alg, "other"), "hashValue": content}
        if alg not in HASH_ALGORITHM:
            item["comment"] = f"CycloneDX alg: {alg}"
        node.setdefault("verifiedUsing", []).append(item)


# -- 외부 참조 ---------------------------------------------------------------------
def apply_external_references(node: dict, ext: ExtBuffer, refs: list[dict] | None, *, promote: bool) -> None:
    """externalRef 로 옮기고, Package 계열이면 첫 distribution/website 를 downloadLocation/homePage 로 올린다."""
    for i, ref in enumerate(refs or []):
        url, cdx_type = ref.get("url"), ref.get("type")
        if not url:
            continue
        item = {"type": "ExternalRef", "externalRefType": EXTERNAL_REF_TYPE.get(cdx_type, "other"), "locator": [url]}
        comment = ref.get("comment")
        if cdx_type not in EXTERNAL_REF_TYPE:
            comment = f"aibom:cdx:externalReference:type={cdx_type}" + (f"; {comment}" if comment else "")
        if comment:
            item["comment"] = comment
        node.setdefault("externalRef", []).append(item)
        if promote and cdx_type == "distribution" and "software_downloadLocation" not in node:
            node["software_downloadLocation"] = url
        if promote and cdx_type == "website" and "software_homePage" not in node:
            node["software_homePage"] = url
        for j, h in enumerate(ref.get("hashes") or []):
            ext.fix(f"externalReferences:{i}:hashes:{j}:alg", h.get("alg"))
            ext.fix(f"externalReferences:{i}:hashes:{j}:content", h.get("content"))
        for p in ref.get("properties") or []:
            ext.fix(f"externalReferences:{i}:properties:{p.get('name')}", p.get("value"))


def apply_mime_type(node: dict, ext: ExtBuffer, mime: str | None) -> None:
    if not mime:
        return
    if node["type"] == "software_File" and _MEDIA_TYPE.match(mime):
        node["contentType"] = mime
    else:
        ext.fix("mime-type", mime)


# -- 주체 -------------------------------------------------------------------------
def organization(ctx: Ctx, org: dict, *, in_sbom: bool) -> str | None:
    name = org.get("name")
    key = org.get("bom-ref") or name
    if not key:
        return None
    iri, node, new = ctx.element(f"Organization-{enc(key)}", ("Organization", key), "Organization", "agents")
    if new:
        node["name"] = name or key
        ext = ctx.ext_of(iri)
        if org.get("bom-ref"):
            ext.fix("bom-ref", org["bom-ref"])
        for url in org.get("url") or []:
            node.setdefault("externalRef", []).append({"type": "ExternalRef", "externalRefType": "altWebPage", "locator": [url]})
        for field, value in (org.get("address") or {}).items():
            ext.fix(f"address:{field}", value)
        for i, c in enumerate(org.get("contact") or []):
            ext.fix(f"contact:{i}:name", c.get("name"))
            ext.fix(f"contact:{i}:email", c.get("email"))
    if in_sbom and iri not in ctx.sbom_agents:
        ctx.sbom_agents.append(iri)
    return iri


def person(ctx: Ctx, contact: dict, *, in_sbom: bool) -> str | None:
    key = contact.get("bom-ref") or contact.get("name") or contact.get("email")
    if not key:
        return None
    iri, node, new = ctx.element(f"Person-{enc(key)}", ("Person", key), "Person", "agents")
    if new:
        node["name"] = contact.get("name") or key
        if contact.get("email"):
            add_external_identifier(node, "email", contact["email"])
        ext = ctx.ext_of(iri)
        if contact.get("bom-ref"):
            ext.fix("bom-ref", contact["bom-ref"])
        ext.fix("phone", contact.get("phone"))
    if in_sbom and iri not in ctx.sbom_agents:
        ctx.sbom_agents.append(iri)
    return iri


def plain_agent(ctx: Ctx, name: str) -> str:
    """component.author (문자열) — 개인인지 조직인지 모르므로 일반 Agent."""
    iri, node, new = ctx.element(f"Agent-{enc(name)}", ("Agent", name), "Agent", "agents")
    if new:
        node["name"] = name
    if iri not in ctx.sbom_agents:
        ctx.sbom_agents.append(iri)
    return iri


def apply_parties(ctx: Ctx, node: dict, comp: dict, iri: str) -> None:
    """supplier → suppliedBy, manufacturer/authors/author → originatedBy, publisher → publishedBy 관계."""
    if comp.get("supplier"):
        org = organization(ctx, comp["supplier"], in_sbom=True)
        if org:
            node["suppliedBy"] = org
    originated: list[str] = []
    if comp.get("manufacturer"):
        originated.append(organization(ctx, comp["manufacturer"], in_sbom=True))
    for c in comp.get("authors") or []:
        originated.append(person(ctx, c, in_sbom=True))
    if comp.get("author"):
        originated.append(plain_agent(ctx, comp["author"]))
    for agent in originated:
        if agent and agent not in node.setdefault("originatedBy", []):
            node["originatedBy"].append(agent)
    if not node.get("originatedBy"):
        node.pop("originatedBy", None)
    if comp.get("publisher"):
        ctx.rel(iri, "publishedBy", [organization(ctx, {"name": comp["publisher"]}, in_sbom=True)])


# -- 라이선스 ---------------------------------------------------------------------
def license_expression(ctx: Ctx, choice: dict) -> str | None:
    """licenseChoice 하나 → 공유 simplelicensing_LicenseExpression (expr 로만 풀링). 첫 등장이 url/properties 를 정한다."""
    lic = choice.get("license")
    if lic is not None:
        if lic.get("id"):
            expr, name = lic["id"], lic["id"]
        elif lic.get("name"):
            expr, name = license_ref(lic["name"]), lic["name"]
        else:
            return None
    elif choice.get("expression"):
        expr = name = choice["expression"]
        lic = choice
    else:
        return None

    iri, node, new = ctx.element(f"License-{enc(expr)}", ("License", expr), "simplelicensing_LicenseExpression", "licenses")
    ext = ctx.ext_of(iri)
    if new:
        node["name"] = name
        node["simplelicensing_licenseExpression"] = expr
        if lic.get("url"):
            node["externalRef"] = [{"type": "ExternalRef", "externalRefType": "license", "locator": [lic["url"]]}]
        for p in lic.get("properties") or []:
            ext.prop(p.get("name") or "", p.get("value"))
        for i, d in enumerate(lic.get("expressionDetails") or []):
            ext.fix(f"license:expressionDetails:{i}:licenseIdentifier", d.get("licenseIdentifier"))
            ext.fix(f"license:expressionDetails:{i}:url", d.get("url"))
        _license_text(ctx, node, expr, lic.get("text"))
    if lic.get("bom-ref"):
        refs = [v for n, v in ext.fixed if n.startswith("aibom:cdx:licenseRefs:")]
        if lic["bom-ref"] not in refs:
            ext.fix(f"licenseRefs:{len(refs)}", lic["bom-ref"])
    return iri


def _license_text(ctx: Ctx, expression_node: dict, expr: str, text: dict | None) -> None:
    if not text or text.get("content") is None:
        return
    content = text["content"]
    if text.get("encoding") == "base64":
        try:                                                     # encoding 은 생산자의 힌트일 뿐 — 틀려도 문서를 버리지 않는다
            content = base64.b64decode(content, validate=True).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            ctx.warn(f"license text ({expr}): base64 해독 실패, 원문을 그대로 둔다")
    iri, node, new = ctx.element(f"LicenseText-{enc(expr)}", ("LicenseText", expr), "simplelicensing_SimpleLicensingText", "licenses")
    if new:
        node["name"] = expr
        node["simplelicensing_licenseText"] = content
    if expr.startswith("LicenseRef-"):
        expression_node["simplelicensing_customIdToUri"] = [{"type": "DictionaryEntry", "key": expr, "value": iri}]
    else:
        expression_node["comment"] = f"license text: {iri}"


def apply_licenses(ctx: Ctx, iri: str, licenses: list[dict] | None) -> None:
    """acknowledgement 는 license 객체 형은 license 안에, expression 형은 choice 에 있다. concluded 만 따로 간다."""
    declared: list[str] = []
    concluded: list[str] = []
    for choice in licenses or []:
        target = license_expression(ctx, choice)
        if not target:
            continue
        ack = (choice.get("license") or {}).get("acknowledgement") or choice.get("acknowledgement")
        (concluded if ack == "concluded" else declared).append(target)
    ctx.rel(iri, "hasDeclaredLicense", declared)
    ctx.rel(iri, "hasConcludedLicense", concluded)


# -- 릴리스 노트 · 증거 · 특허 --------------------------------------------------------
def apply_release_notes(node: dict, ext: ExtBuffer, notes: dict | None) -> None:
    if not notes:
        return
    stamp = iso_z(notes.get("timestamp"))
    if stamp:
        node["releaseTime"] = stamp
    elif notes.get("timestamp"):
        ext.fix("releaseNotes:timestamp", notes["timestamp"])
    for field in ("type", "title", "description"):
        ext.fix(f"releaseNotes:{field}", notes.get(field))
    for field in ("aliases", "tags"):
        for i, v in enumerate(notes.get(field) or []):
            ext.fix(f"releaseNotes:{field}:{i}", v)
    for i, n in enumerate(notes.get("notes") or []):
        ext.fix(f"releaseNotes:notes:{i}:locale", n.get("locale"))
        ext.fix(f"releaseNotes:notes:{i}:text", (n.get("text") or {}).get("content"))
    for p in notes.get("properties") or []:
        ext.fix(f"releaseNotes:properties:{p.get('name')}", p.get("value"))


def apply_evidence(ext: ExtBuffer, evidence: dict | None) -> None:
    """hasEvidence/software_File 합성은 보류 — 잃지 않도록 확장에 원문을 남긴다."""
    if not evidence:
        return
    for field in ("identity", "callstack", "licenses"):
        if evidence.get(field) is not None:
            ext.fix(f"evidence:{field}", stringify(evidence[field]))
    for i, c in enumerate(evidence.get("copyright") or []):
        ext.fix(f"evidence:copyright:{i}:text", c.get("text"))
    for i, occ in enumerate(evidence.get("occurrences") or []):
        for field in ("bom-ref", "location", "line", "offset", "symbol", "additionalContext"):
            ext.fix(f"evidence:occurrences:{i}:{field}", occ.get(field))


def apply_patents(ext: ExtBuffer, assertions: list[dict] | None) -> None:
    for i, a in enumerate(assertions or []):
        ext.fix(f"patentAssertions:{i}:assertionType", a.get("assertionType"))
        ext.fix(f"patentAssertions:{i}:notes", a.get("notes"))
        ext.fix(f"patentAssertions:{i}:asserter:name", (a.get("asserter") or {}).get("name"))
        for j, ref in enumerate(a.get("patentRefs") or []):
            ext.fix(f"patentAssertions:{i}:patentRefs:{j}", ref)


def apply_pedigree_extras(ext: ExtBuffer, pedigree: dict | None) -> None:
    for i, patch in enumerate((pedigree or {}).get("patches") or []):
        ext.fix(f"pedigree:patches:{i}:type", patch.get("type"))
        ext.fix(f"pedigree:patches:{i}:diff:url", (patch.get("diff") or {}).get("url"))
        for j, r in enumerate(patch.get("resolves") or []):
            for field in ("id", "type", "name", "description"):
                ext.fix(f"pedigree:patches:{i}:resolves:{j}:{field}", r.get(field))
            for field in ("name", "url"):
                ext.fix(f"pedigree:patches:{i}:resolves:{j}:source:{field}", (r.get("source") or {}).get(field))
    for i, commit in enumerate((pedigree or {}).get("commits") or []):
        for field in ("uid", "url", "message"):
            ext.fix(f"pedigree:commits:{i}:{field}", commit.get(field))
        for who in ("author", "committer"):                      # identifiableAction: timestamp/name/email
            for field in ("name", "email", "timestamp"):
                ext.fix(f"pedigree:commits:{i}:{who}:{field}", (commit.get(who) or {}).get(field))


__all__ = [
    "CREATION_INFO_ID", "apply_identifiers", "apply_hashes", "apply_external_references", "apply_mime_type",
    "organization", "person", "plain_agent", "apply_parties", "license_expression", "apply_licenses",
    "apply_release_notes", "apply_evidence", "apply_patents", "apply_pedigree_extras",
]
