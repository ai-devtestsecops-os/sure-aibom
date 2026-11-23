"""sure-aibom 이 만든 CycloneDX 문서(AI-BOM v0.6 형)를 SPDX 3.0.1 JSON-LD 로 바꾼다. 파이프라인 맨 끝, 출력 직전에 돈다.

값은 CycloneDX 로 다 만들고(병합, 보강, 규제 필드) 마지막에 모양만 바꾼다. 그래서 두 형식의 값이 어긋나지 않는다.
입력은 규제 필드를 v0.6 정규 필드로 넣은 문서(form "typed")다. 구조가 있는 쪽에서 옮기는 것이 쉽기 때문이다.

spec
    "3.0.1"  공식 SPDX 3.0.1 스키마에 맞는 문서. SPDX 에 자리가 있는 값은 그 자리에 적고(ai_hyperparameter, dataset_datasetSize …),
             자리가 없는 값은 SPDX 3.0.1 의 Extension 프로파일에 든 CdxPropertiesExtension 에 CycloneDX 경로를 이름으로 담는다.
    "v0.6"   AI-BOM v0.6 (SPDX) 스키마에 맞는 문서. 위에 더해 v0.6 이 더한 aibom_* 속성을 쓴다 (aibom_parameterCount, aibom_statistics …).

클래스
    패키지(library, application, operating-system …)  software_Package (software_primaryPurpose 는 CycloneDX type 에서)
    모델(machine-learning-model)                       ai_AIPackage
    데이터셋(type=data, data[] 에 dataset 항목)          dataset_DatasetPackage. dataset_datasetType 이 필수라 modality 가 없으면 noAssertion
    파일(file)                                          software_File
    서비스(services[])                                  software_Package (SPDX 에 서비스 클래스가 없다. primaryPurpose other, comment 에 service)
    루트(metadata.component)                            software_Package. SpdxDocument.rootElement 가 가리킨다
    pedigree 의 조상·변형                                같은 규칙으로 요소를 만든다 (문서에 같은 컴포넌트가 있으면 그것을 가리킨다)

관계 (Relationship)
    dependencies[]                       dependsOn. 모델 카드의 datasets ref 도 모델 → 데이터셋 dependsOn 에 더한다.
    facts.roles                          모델 → 데이터셋 trainedOn(모델 카드 datasets, GGUF general.datasets) · testedOn(model-index).
                                         CycloneDX 는 dependsOn 뿐이라 구분이 없고, dependsOn 은 그대로 둔 채 더한다
    pedigree.ancestors / variants / descendants   descendantOf / hasVariant / ancestorOf. pedigree.notes 는 그 관계의 comment
    licenses                             hasDeclaredLicense (acknowledgement 가 concluded 면 hasConcludedLicense) → simplelicensing_LicenseExpression 요소.
                                         SPDX id 와 식은 그대로, 이름뿐인 라이선스는 LicenseRef-<이름> 과 customIdToUri(url)

자리가 없는 값     CdxPropertiesExtension 에 담는다 (값은 문자열). 항목 이름은 두 가지다.
                   - v0.6 이 정의한 필드(3.0.1 에서 aibom_* 로 못 가는 값): 문서의 properties 키 그대로 (aibom:model:parameterCount,
                     aibom:dataset:statistics:<i>:type …). CycloneDX 1.7 출력의 properties 와 같은 이름이라 두 형식을 같은 키로 읽는다
                   - 그 밖의 값(bom-ref, group, tags, evidence, 로컬 데이터의 data[].name, 신뢰구간 …): CycloneDX 의 JSON 경로(배열 번호 없이)
작성 주체          CreationInfo.createdBy 가 필수라 sure-aibom 자신을 SoftwareAgent 로 적는다. metadata.tools 는 Tool 요소로 createdUsing 에.
부가 기록(facts)   CycloneDX 에 자리가 없어 수집 단계가 메모리로만 들고 온 값 (facts.py). 위의 학습·평가 관계와 요소의
                   builtTime(이미지 created 라벨)·releaseTime(허브 lastModified). CycloneDX 출력에는 없다. 주지 않으면 그냥 뺀다
식별자             문서 네임스페이스는 serialNumber(urn:uuid:…), 요소 id 는 "<네임스페이스>#<bom-ref>" (IRI 에 못 쓰는 글자만 퍼센트 인코딩).
                   그래서 같은 CycloneDX 문서를 두 번 바꾸면 같은 SPDX 가 나온다.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from urllib.parse import quote

from ..utils.dataset_component import is_dataset
from ..utils.facts import Facts
from ..utils.log import detail
from .common.component import MODEL_TYPE, identity

SPEC_VERSION = "3.0.1"
CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
SPECS = ("3.0.1", "v0.6")
PROFILES = ["core", "software", "ai", "dataset", "simpleLicensing", "extension"]

# CycloneDX component.type → software_primaryPurpose
PURPOSE_BY_TYPE = {
    "application": "application", "framework": "framework", "library": "library", "container": "container", "platform": "platform",
    "operating-system": "operatingSystem", "device": "device", "device-driver": "deviceDriver", "firmware": "firmware", "file": "file",
    "machine-learning-model": "model", "data": "data", "cryptographic-asset": "other",
}
HASH_ALGORITHM = {
    "MD5": "md5", "SHA-1": "sha1", "SHA-256": "sha256", "SHA-384": "sha384", "SHA-512": "sha512",
    "SHA3-256": "sha3_256", "SHA3-384": "sha3_384", "SHA3-512": "sha3_512",
    "BLAKE2b-256": "blake2b256", "BLAKE2b-384": "blake2b384", "BLAKE2b-512": "blake2b512", "BLAKE3": "blake3",
}
# CycloneDX externalReference.type → ExternalRefType. 없는 것은 other 에 원래 종류를 comment 로
EXTERNAL_REF_TYPE = {
    "vcs": "vcs", "issue-tracker": "issueTracker", "website": "altWebPage", "advisories": "securityAdvisory", "bom": "other",
    "mailing-list": "mailingList", "social": "socialMedia", "chat": "chat", "documentation": "documentation", "support": "support",
    "source-distribution": "sourceArtifact", "distribution": "altDownloadLocation", "distribution-intake": "other", "license": "license",
    "build-meta": "buildMeta", "build-system": "buildSystem", "release-notes": "releaseNotes", "security-contact": "securityOther",
    "model-card": "documentation", "log": "other", "configuration": "other", "evidence": "other", "formulation": "other",
    "attestation": "secureSoftwareAttestation", "threat-model": "securityThreatModel", "adversary-model": "securityAdversaryModel",
    "risk-assessment": "riskAssessment", "vulnerability-assertion": "vulnerabilityExploitabilityAssessment",
    "exploitability-statement": "vulnerabilityExploitabilityAssessment", "pentest-report": "securityPenTestReport",
    "static-analysis-report": "staticAnalysisReport", "dynamic-analysis-report": "dynamicAnalysisReport",
    "runtime-analysis-report": "runtimeAnalysisReport", "component-analysis-report": "componentAnalysisReport",
    "maturity-report": "other", "certification-report": "certificationReport", "codified-infrastructure": "other",
    "quality-metrics": "metrics", "poam": "other", "electronic-signature": "other", "digital-signature": "other",
    "rfc-9116": "securityPolicy", "export-control-assessment": "exportControlAssessment", "privacy-assessment": "privacyAssessment",
    "funding": "funding", "eol-notice": "eolNotice", "citation": "other", "other": "other",
}
AVAILABILITY = {"direct-download": "directDownload", "scraping-script": "scrapingScript"}       # 나머지 값은 두 형식이 같다
DATASET_TYPES = frozenset({"audio", "categorical", "graph", "image", "noAssertion", "numeric", "other", "sensor", "structured",
                           "syntactic", "text", "timeseries", "timestamp", "video"})
PRESENCE = {"yes": "yes", "no": "no", "unknown": "noAssertion"}
SAFE = ":/@!$&'()*+,;="                  # IRI 조각(fragment)에 그대로 둘 수 있는 글자. 나머지(공백, %, ?, # …)는 퍼센트 인코딩


def convert_spdx(doc: dict, spec: str = SPEC_VERSION, facts: Facts | None = None) -> dict:
    """CycloneDX 문서를 SPDX 3.0.1 JSON-LD 로 바꿔 돌려준다 (입력은 그대로 둔다). facts 는 수집 단계의 메모리 부가 기록."""
    if spec not in SPECS:
        raise ValueError(f"spec 은 {SPECS} 중 하나여야 한다: {spec!r}")
    return _Converter(doc, spec, facts).run()


class _Converter:
    def __init__(self, doc: dict, spec: str, facts: Facts | None = None) -> None:
        self.doc = doc
        self.facts = facts
        self.v06 = spec == "v0.6"
        self.ns = doc.get("serialNumber") or f"urn:uuid:{uuid.uuid4()}"
        self.ci = f"{self.ns}#creationinfo"
        self.elements: list[dict] = []                      # 요소 (문서 순서대로)
        self.relationships: list[dict] = []
        self.ref: dict[str, str] = {}                        # bom-ref(또는 병합 키) → spdxId
        self.extra_deps: dict[str, list[str]] = {}           # 모델 카드의 datasets ref → dependsOn 에 더할 것
        self.by_id: set[str] = set()

    # ── 문서 ────────────────────────────────────────────────────────────────
    def run(self) -> dict:
        meta = self.doc.get("metadata") or {}
        tools = ((meta.get("tools") or {}).get("components") if isinstance(meta.get("tools"), dict) else meta.get("tools")) or []
        agent = self._element({"type": "SoftwareAgent", "spdxId": f"{self.ns}#agent/sure-aibom", "creationInfo": self.ci, "name": "sure-aibom"})
        tool_ids = [self._tool(t) for t in tools if isinstance(t, dict) and t.get("name")]
        creation = {"type": "CreationInfo", "@id": self.ci, "specVersion": SPEC_VERSION,
                    "created": meta.get("timestamp") or "1970-01-01T00:00:00Z", "createdBy": [agent]}
        if tool_ids:
            creation["createdUsing"] = tool_ids

        components = [c for c in self.doc.get("components") or [] if isinstance(c, dict)]
        services = [s for s in self.doc.get("services") or [] if isinstance(s, dict)]
        for comp in components + services:                  # 먼저 id 를 다 매겨 두어야 관계와 조상이 서로를 가리킬 수 있다
            if comp.get("bom-ref"):
                self.ref[comp["bom-ref"]] = self._id(comp["bom-ref"])
        root = meta.get("component") if isinstance(meta.get("component"), dict) else None
        root_id = None
        if root:
            self.ref.setdefault(root.get("bom-ref") or identity(root), self._id(root.get("bom-ref") or identity(root)))
            root_id = self._component(root)
        for comp in components:
            self._component(comp)
        for service in services:
            self._service(service)
        self._dependencies()

        document = {"type": "SpdxDocument", "spdxId": f"{self.ns}#document", "creationInfo": self.ci,
                    "name": (root or {}).get("name") or "aibom", "profileConformance": list(PROFILES)}
        if root_id:
            document["rootElement"] = [root_id]
        document["element"] = [e["spdxId"] for e in self.elements] + [r["spdxId"] for r in self.relationships]
        self._extension(document, [("metadata.lifecycles.phase", lc.get("phase") or lc.get("name"))
                                   for lc in meta.get("lifecycles") or [] if isinstance(lc, dict)])
        return {"@context": CONTEXT, "@graph": [creation, document, *self.elements, *self.relationships]}

    # ── 요소 ────────────────────────────────────────────────────────────────
    def _id(self, local: str) -> str:
        return f"{self.ns}#{quote(local, safe=SAFE)}"

    def _element(self, element: dict) -> str:
        """요소를 문서에 넣고 id 를 돌려준다. 같은 id 는 한 번만."""
        if element["spdxId"] not in self.by_id:
            self.by_id.add(element["spdxId"])
            self.elements.append(element)
        return element["spdxId"]

    def _tool(self, tool: dict) -> str:
        local = f"tool/{tool['name']}" + (f"@{tool['version']}" if tool.get("version") else "")
        el = {"type": "Tool", "spdxId": self._id(local), "creationInfo": self.ci, "name": tool["name"]}
        if tool.get("version"):
            el["comment"] = f"version {tool['version']}"
        if tool.get("purl"):
            el["externalIdentifier"] = [{"type": "ExternalIdentifier", "externalIdentifierType": "packageUrl", "identifier": tool["purl"]}]
        return self._element(el)

    def _agent(self, name: str, kind: str = "Organization") -> str:
        prefix = "org" if kind == "Organization" else "agent"
        return self._element({"type": kind, "spdxId": self._id(f"{prefix}/{name}"), "creationInfo": self.ci, "name": name})

    def _license(self, entry: dict) -> str | None:
        """licenses[] 항목 하나 → simplelicensing_LicenseExpression 요소 id."""
        if entry.get("expression"):
            expression, name, url = entry["expression"], None, None
        else:
            lic = entry.get("license") or {}
            name, url = lic.get("name"), lic.get("url")
            if lic.get("id"):
                expression = lic["id"]
            elif name:
                expression = "LicenseRef-" + re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")
            else:
                return None
        el = {"type": "simplelicensing_LicenseExpression", "spdxId": self._id(f"license/{expression}"), "creationInfo": self.ci,
              "simplelicensing_licenseExpression": expression}
        if name and expression.startswith("LicenseRef-"):
            el["name"] = name
            if url:
                el["simplelicensing_customIdToUri"] = [_entry(expression, url)]
        return self._element(el)

    def _component(self, comp: dict) -> str:
        """컴포넌트(루트, 조상 포함) → 요소. 다룬 키는 지우고 남은 값은 확장에 담는다."""
        work = copy.deepcopy(comp)
        kind = work.pop("type", None)
        ref = work.pop("bom-ref", None) or identity(comp)
        spdx_id = self.ref.get(ref) or self._id(ref)
        if spdx_id in self.by_id:
            return spdx_id
        self.ref.setdefault(ref, spdx_id)
        dataset = kind == "data" and is_dataset(comp)
        cls = ("ai_AIPackage" if kind == MODEL_TYPE else "dataset_DatasetPackage" if dataset
               else "software_File" if kind == "file" else "software_Package")
        el: dict = {"type": cls, "spdxId": spdx_id, "creationInfo": self.ci}
        ext: list[tuple[str, object]] = [("bom-ref", ref)]
        _set(el, "name", work.pop("name", None))
        _set(el, "description", work.pop("description", None))
        self._times(el, ref)
        if cls == "software_File":
            el["software_fileKind"] = "file"
            work.pop("version", None)
            work.pop("purl", None)
        else:
            _set(el, "software_packageVersion", work.pop("version", None))
            _set(el, "software_packageUrl", work.pop("purl", None))
            if kind in PURPOSE_BY_TYPE:
                el["software_primaryPurpose"] = PURPOSE_BY_TYPE[kind]
        _set(el, "software_copyrightText", work.pop("copyright", None))
        ext.append(("group", work.pop("group", None)))
        self._external_references(el, work.pop("externalReferences", None) or [])
        self._identifiers(el, work.pop("cpe", None), work.pop("swid", None))
        self._hashes(el, work.pop("hashes", None) or [])
        self._parties(el, work)
        ext.extend(("tags", t) for t in work.pop("tags", None) or [])
        ext.extend(("evidence.occurrences.location", o.get("location"))
                   for o in (work.pop("evidence", None) or {}).get("occurrences") or [] if isinstance(o, dict))
        self._element(el)                                                    # 관계가 가리킬 수 있게 먼저 넣는다
        self._pedigree(spdx_id, work.pop("pedigree", None) or {}, ext)
        self._licenses(spdx_id, work.pop("licenses", None) or [])
        if kind == MODEL_TYPE:
            self._model_card(el, spdx_id, work.pop("modelCard", None) or {}, ext)
        if dataset:
            self._dataset(el, work.pop("data", None) or [], ext)
        work.pop("components", None)                                         # 병합이 평평하게 폈다
        ext.extend(_leaves(work))
        self._extension(el, ext)
        return spdx_id

    def _times(self, el: dict, ref: str) -> None:
        """facts 의 builtTime·releaseTime (bom-ref 로 찾는다)."""
        for key, value in ((self.facts.times.get(ref) if self.facts else None) or {}).items():
            el[key] = value

    def _service(self, service: dict) -> str:
        work = copy.deepcopy(service)
        ref = work.pop("bom-ref", None) or f"service:{work.get('name', '')}"
        spdx_id = self.ref.get(ref) or self._id(ref)
        el: dict = {"type": "software_Package", "spdxId": spdx_id, "creationInfo": self.ci}
        _set(el, "name", work.pop("name", None))
        _set(el, "description", work.pop("description", None))
        _set(el, "software_packageVersion", work.pop("version", None))
        el["software_primaryPurpose"] = "other"
        el["comment"] = "service: an external API the code calls"
        provider = work.pop("provider", None) or {}
        if isinstance(provider, dict) and provider.get("name"):
            el["suppliedBy"] = self._agent(provider["name"])
        self._external_references(el, work.pop("externalReferences", None) or [])
        ext: list[tuple[str, object]] = [("bom-ref", ref), ("group", work.pop("group", None))]
        ext.extend(("tags", t) for t in work.pop("tags", None) or [])
        ext.extend(("endpoints", e) for e in work.pop("endpoints", None) or [])
        self._element(el)
        self._licenses(spdx_id, work.pop("licenses", None) or [])
        work.pop("services", None)
        ext.extend(_leaves(work))
        self._extension(el, ext)
        return spdx_id

    # ── 컴포넌트 필드 ──────────────────────────────────────────────────────
    def _external_references(self, el: dict, refs: list) -> None:
        out = []
        for r in refs:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            kind, url = r.get("type") or "other", r["url"]
            if kind == "website":
                el.setdefault("software_homePage", url)
            elif kind == "distribution":
                el.setdefault("software_downloadLocation", url)
            entry = {"type": "ExternalRef", "externalRefType": EXTERNAL_REF_TYPE.get(kind, "other"), "locator": [url]}
            comment = r.get("comment")
            if EXTERNAL_REF_TYPE.get(kind, "other") == "other" and kind != "other":
                comment = f"{kind}" + (f": {comment}" if comment else "")
            _set(entry, "comment", comment)
            out.append(entry)
        if out:
            el["externalRef"] = out

    def _identifiers(self, el: dict, cpe, swid) -> None:
        out = []
        if cpe:
            out.append({"type": "ExternalIdentifier", "externalIdentifierType": "cpe23" if str(cpe).startswith("cpe:2.3") else "cpe22",
                        "identifier": cpe})
        if isinstance(swid, dict) and swid.get("tagId"):
            out.append({"type": "ExternalIdentifier", "externalIdentifierType": "swid", "identifier": swid["tagId"]})
        if out:
            el["externalIdentifier"] = out

    def _hashes(self, el: dict, hashes: list) -> None:
        out = []
        for h in hashes:
            if isinstance(h, dict) and h.get("content"):
                entry = {"type": "Hash", "algorithm": HASH_ALGORITHM.get(h.get("alg"), "other"), "hashValue": h["content"]}
                if entry["algorithm"] == "other":
                    entry["comment"] = str(h.get("alg"))
                out.append(entry)
        if out:
            el["verifiedUsing"] = out

    def _parties(self, el: dict, work: dict) -> None:
        """supplier → suppliedBy(Organization). publisher 는 supplier 가 없을 때 그 자리에. author·authors → originatedBy(Agent)."""
        supplier = work.pop("supplier", None)
        publisher = work.pop("publisher", None)
        name = supplier.get("name") if isinstance(supplier, dict) else None
        if name:
            el["suppliedBy"] = self._agent(name)
        elif isinstance(publisher, str) and publisher.strip():
            el["suppliedBy"] = self._agent(publisher.strip())
        elif publisher:
            work["publisher"] = publisher
        if isinstance(supplier, dict) and len([k for k in supplier if k != "name"]):
            work["supplier"] = {k: v for k, v in supplier.items() if k != "name"}
        origins = []
        author = work.pop("author", None)
        if isinstance(author, str) and author.strip():
            origins.append(self._agent(author.strip(), "Agent"))
        for a in work.pop("authors", None) or []:
            if isinstance(a, dict) and a.get("name"):
                origins.append(self._agent(a["name"], "Agent"))
        if origins:
            el["originatedBy"] = origins
        manufacturer = work.pop("manufacturer", None)
        if isinstance(manufacturer, dict) and manufacturer.get("name"):
            work["manufacturer"] = manufacturer                                  # SPDX 에 제조사 자리가 없다 → 확장으로

    def _pedigree(self, spdx_id: str, pedigree: dict, ext: list) -> None:
        notes = pedigree.get("notes")
        made = []
        for key, rel_type in (("ancestors", "descendantOf"), ("variants", "hasVariant"), ("descendants", "ancestorOf")):
            targets = [self._component(a) for a in pedigree.get(key) or [] if isinstance(a, dict)]
            if targets:
                made.append(self._rel(rel_type, spdx_id, targets))
        if notes:
            if made:
                made[0]["comment"] = notes
            else:
                ext.append(("pedigree.notes", notes))
        for key in ("commits", "patches"):
            ext.extend(_leaves({key: pedigree[key]}, "pedigree.") if pedigree.get(key) else [])

    def _licenses(self, spdx_id: str, licenses: list) -> None:
        declared, concluded = [], []
        for entry in licenses:
            if not isinstance(entry, dict):
                continue
            lic_id = self._license(entry)
            if not lic_id:
                continue
            ack = (entry.get("license") or {}).get("acknowledgement") if entry.get("license") else entry.get("acknowledgement")
            (concluded if ack == "concluded" else declared).append(lic_id)
        if declared:
            self._rel("hasDeclaredLicense", spdx_id, declared)
        if concluded:
            self._rel("hasConcludedLicense", spdx_id, concluded)

    def _model_card(self, el: dict, spdx_id: str, card: dict, ext: list) -> None:
        params = card.pop("modelParameters", None) or {}
        approach = params.pop("approach", None) or {}
        if isinstance(approach, dict) and approach.get("type"):
            el["ai_typeOfModel"] = [approach["type"]]
        self._put(el, ext, "aibom_task", params.pop("task", None), "aibom:model:task")
        self._put(el, ext, "aibom_architectureFamily", params.pop("architectureFamily", None), "aibom:model:architectureFamily")
        self._put(el, ext, "aibom_modelArchitecture", params.pop("modelArchitecture", None), "aibom:model:modelArchitecture")
        datasets = params.pop("datasets", None) or []
        for entry in datasets:
            if isinstance(entry, dict) and entry.get("ref"):
                self.extra_deps.setdefault(spdx_id, []).append(entry["ref"])
            else:
                ext.extend(_leaves(entry, "modelCard.modelParameters.datasets."))
        for side in ("inputs", "outputs"):
            formats, sizes = [], []
            for i, io in enumerate(params.pop(side, None) or []):
                if not isinstance(io, dict):
                    continue
                fmt = io.get("format")
                if fmt:
                    formats.append((i, fmt))
                if io.get("maxSize") is not None:
                    sizes.append((i, fmt or str(i), str(io["maxSize"])))
            if self.v06:
                _set(el, f"aibom_{side}", [f for _, f in formats])
            else:
                ext.extend((f"aibom:model:{side}:{i}:format", f) for i, f in formats)
            self._put_dict(el, ext, f"aibom_{side[:-1]}MaxSize", sizes, f"aibom:model:{side}", "maxSize")
        hyper = [_entry(h["name"], h.get("value")) for h in params.pop("hyperparameters", None) or []
                 if isinstance(h, dict) and h.get("name")]
        if hyper:
            el["ai_hyperparameter"] = hyper
        count = params.pop("parameterCount", None)
        if count is not None:
            if self.v06:
                el["aibom_parameterCount"] = int(count)
            else:
                ext.append(("aibom:model:parameterCount", count))
        _set(el, "ai_informationAboutTraining", ", ".join(_strings(params.pop("trainingTechniques", None))) or None)
        self._put(el, ext, "aibom_designChoices", _strings(params.pop("designChoices", None)), "aibom:model:designChoices")
        for key in ("optimizationTarget", "trainingCompute", "trainingTime"):
            self._put(el, ext, f"aibom_{key}", params.pop(key, None), f"aibom:model:{key}")
        ext.extend(_leaves(params, "modelCard.modelParameters."))

        analysis = card.pop("quantitativeAnalysis", None) or {}
        metrics, thresholds, slices = [], [], []
        for i, m in enumerate(analysis.pop("performanceMetrics", None) or []):
            if not isinstance(m, dict) or not m.get("type"):
                continue
            kind = m["type"]
            if m.get("value") is not None:
                metrics.append(_entry(kind, m["value"]))
            if m.get("decisionThreshold") is not None:
                thresholds.append(_entry(kind, m["decisionThreshold"]))
            if m.get("slice"):
                slices.append((i, kind, m["slice"]))
            rest = {k: v for k, v in m.items() if k not in ("type", "value", "decisionThreshold", "slice")}
            if rest:                                                          # 신뢰구간 등 두 형식 모두 자리가 없는 값: 지표 이름을 붙여 JSON 으로
                ext.append(("modelCard.quantitativeAnalysis.performanceMetrics", json.dumps({"type": kind, **rest}, ensure_ascii=False)))
        if metrics:
            el["ai_metric"] = metrics
        if thresholds:
            el["ai_metricDecisionThreshold"] = thresholds
        self._put_dict(el, ext, "aibom_metricSlice", slices, "aibom:model:performanceMetrics", "slice")
        ext.extend(_leaves(analysis, "modelCard.quantitativeAnalysis."))

        cons = card.pop("considerations", None) or {}
        self._put(el, ext, "aibom_users", _strings(cons.pop("users", None)), "aibom:model:users")
        self._put(el, ext, "aibom_useCases", _strings(cons.pop("useCases", None)), "aibom:model:useCases")
        _set(el, "ai_limitation", "; ".join(_strings(cons.pop("technicalLimitations", None))) or None)
        _set(el, "ai_informationAboutApplication", ", ".join(_strings(cons.pop("technicalRequirements", None))) or None)
        ethics = [(i, e) for i, e in enumerate(cons.pop("ethicalConsiderations", None) or []) if isinstance(e, dict) and e.get("name")]
        self._put_dict(el, ext, "aibom_ethicalConsiderations", [(i, e["name"], None) for i, e in ethics], "aibom:model:ethicalConsiderations", "name")
        self._put_dict(el, ext, "aibom_ethicalConsiderationsMitigationStrategy",
                       [(i, e["name"], e["mitigationStrategy"]) for i, e in ethics if e.get("mitigationStrategy")],
                       "aibom:model:ethicalConsiderations", "mitigationStrategy")
        fair = [(i, f) for i, f in enumerate(cons.pop("fairnessAssessments", None) or []) if isinstance(f, dict) and f.get("groupAtRisk")]
        self._put_dict(el, ext, "aibom_fairnessAssessments", [(i, f["groupAtRisk"], None) for i, f in fair], "aibom:model:fairnessAssessments", "groupAtRisk")
        self._put_dict(el, ext, "aibom_fairnessAssessmentBenefits", [(i, f["groupAtRisk"], f["benefits"]) for i, f in fair if f.get("benefits")],
                       "aibom:model:fairnessAssessments", "benefits")
        self._put_dict(el, ext, "aibom_fairnessAssessmentHarms", [(i, f["groupAtRisk"], f["harms"]) for i, f in fair if f.get("harms")],
                       "aibom:model:fairnessAssessments", "harms")
        ext.extend(("modelCard.considerations.fairnessAssessments", json.dumps({"groupAtRisk": f["groupAtRisk"], "mitigationStrategy": f["mitigationStrategy"]}, ensure_ascii=False))
                   for _, f in fair if f.get("mitigationStrategy"))              # v0.6 (SPDX) 에도 자리가 없다
        self._put(el, ext, "aibom_limitationIdentificationMethods", _strings(cons.pop("limitationIdentificationMethods", None)),
                  "aibom:model:limitationIdentificationMethods")
        explain = _strings(cons.pop("explainabilityMethods", None))
        if explain:
            el["ai_modelExplainability"] = explain
        sensitive = cons.pop("sensitivePersonalInformation", None)
        if sensitive in PRESENCE:
            el["ai_useSensitivePersonalInformation"] = PRESENCE[sensitive]
        safety = cons.pop("safetyRiskAssessment", None)
        if safety in ("serious", "high", "medium", "low"):
            el["ai_safetyRiskAssessment"] = safety
        ext.extend(_leaves(cons, "modelCard.considerations."))
        ext.extend(_leaves(card, "modelCard."))

    def _dataset(self, el: dict, entries: list, ext: list) -> None:
        entries = [copy.deepcopy(e) for e in entries if isinstance(e, dict)]
        primary = next((e for e in entries if e.get("type") == "dataset"), entries[0] if entries else {})
        for e in entries:
            e.pop("type", None)
            ext.append(("data.name", e.pop("name", None)))
        contents = primary.pop("contents", None) or {}
        if contents.get("url"):
            el.setdefault("software_downloadLocation", contents.pop("url"))
        availability = contents.pop("availability", None)
        if availability:
            el["dataset_datasetAvailability"] = AVAILABILITY.get(availability, availability)
        if contents:
            ext.extend(_leaves(contents, "data.contents."))
        modality = [m if m in DATASET_TYPES else "other" for m in _strings(primary.pop("modality", None))]
        el["dataset_datasetType"] = modality or ["noAssertion"]
        size = primary.pop("size", None)
        if size is not None:
            el["dataset_datasetSize"] = int(size)
        _set(el, "dataset_intendedUse", primary.pop("intendedUse", None))
        _set(el, "dataset_dataCollectionProcess", primary.pop("collectionProcess", None))
        _set(el, "software_sourceInfo", "; ".join(_strings(primary.pop("provenance", None))) or None)
        pre = _strings(primary.pop("preprocessing", None))
        if pre:
            el["dataset_dataPreprocessing"] = pre
        anon = _strings(primary.pop("anonymizationMethods", None))
        if anon:
            el["dataset_anonymizationMethodUsed"] = anon
        _set(el, "dataset_datasetNoise", primary.pop("noise", None))
        _set(el, "dataset_datasetUpdateMechanism", primary.pop("updateMechanism", None))
        bias = [(i, b) for i, b in enumerate(primary.pop("knownBias", None) or []) if isinstance(b, dict) and b.get("name")]
        if bias:
            el["dataset_knownBias"] = [b["name"] for _, b in bias]
        self._put_dict(el, ext, "aibom_knownBiasDetectionMethod", [(i, b["name"], b["detectionMethod"]) for i, b in bias if b.get("detectionMethod")],
                       "aibom:dataset:knownBias", "detectionMethod")
        self._put_dict(el, ext, "aibom_knownBiasMitigationStrategy", [(i, b["name"], b["mitigationStrategy"]) for i, b in bias if b.get("mitigationStrategy")],
                       "aibom:dataset:knownBias", "mitigationStrategy")
        gaps = [(i, g) for i, g in enumerate(primary.pop("knownGaps", None) or []) if isinstance(g, dict) and g.get("name")]
        self._put_dict(el, ext, "aibom_knownGaps", [(i, g["name"], None) for i, g in gaps], "aibom:dataset:knownGaps", "name")
        self._put_dict(el, ext, "aibom_knownGapsMitigationStrategy", [(i, g["name"], g["mitigationStrategy"]) for i, g in gaps if g.get("mitigationStrategy")],
                       "aibom:dataset:knownGaps", "mitigationStrategy")
        stats = [(i, s["type"], s.get("value")) for i, s in enumerate(primary.pop("statistics", None) or []) if isinstance(s, dict) and s.get("type")]
        if self.v06:
            self._put_dict(el, ext, "aibom_statistics", stats, "aibom:dataset:statistics", None)
        else:
            for i, kind, value in stats:
                ext.extend(((f"aibom:dataset:statistics:{i}:type", kind), (f"aibom:dataset:statistics:{i}:value", value)))
        self._put(el, ext, "aibom_originalCollectionPurpose", primary.pop("originalCollectionPurpose", None), "aibom:dataset:originalCollectionPurpose")
        self._put(el, ext, "aibom_designChoices", _strings(primary.pop("designChoices", None)), "aibom:dataset:designChoices")
        self._put(el, ext, "aibom_representationAssumptions", _strings(primary.pop("representationAssumptions", None)), "aibom:dataset:representationAssumptions")
        sensitive = _strings(primary.pop("sensitiveData", None))
        if sensitive:
            el["dataset_hasSensitivePersonalInformation"] = "yes"
            ext.extend(("data.sensitiveData", s) for s in sensitive)
        for e in entries:                                                     # 남은 값 (classification, governance, 다른 항목의 값 …)
            ext.extend(_leaves(e, "data."))

    # ── 관계 ────────────────────────────────────────────────────────────────
    def _dependencies(self) -> None:
        rows: dict[str, list[str]] = {}
        for row in self.doc.get("dependencies") or []:
            if not isinstance(row, dict) or not row.get("ref"):
                continue
            frm = self.ref.get(row["ref"])
            if not frm:
                detail(f"[spdx] dependency of unknown element skipped: {row['ref']}")
                continue
            for target in row.get("dependsOn") or []:
                to = self.ref.get(target)
                if to:
                    rows.setdefault(frm, []).append(to)
                else:
                    detail(f"[spdx] dependency on unknown element skipped: {row['ref']} -> {target}")
        for frm, refs in self.extra_deps.items():
            for target in refs:
                to = self.ref.get(target)
                if to:
                    rows.setdefault(frm, []).append(to)
        for frm, targets in rows.items():
            self._rel("dependsOn", frm, list(dict.fromkeys(targets)))
        self._dataset_roles()

    def _dataset_roles(self) -> None:
        """facts.roles → 모델 → 데이터셋 trainedOn(training) · testedOn(evaluation). dependsOn 은 그대로 둔다."""
        by_type: dict[str, dict[str, list[str]]] = {"trainedOn": {}, "testedOn": {}}
        for (model_ref, dataset_ref), roles in (self.facts.roles if self.facts else {}).items():
            frm, to = self.ref.get(model_ref), self.ref.get(dataset_ref)
            if not frm or not to:
                detail(f"[spdx] dataset role of unknown element skipped: {model_ref} -> {dataset_ref}")
                continue
            if "training" in roles:
                by_type["trainedOn"].setdefault(frm, []).append(to)
            if "evaluation" in roles:
                by_type["testedOn"].setdefault(frm, []).append(to)
        for rel_type, rows in by_type.items():
            for frm, targets in rows.items():
                self._rel(rel_type, frm, list(dict.fromkeys(targets)))

    def _rel(self, rel_type: str, frm: str, to: list[str], comment: str | None = None) -> dict:
        local = frm.split("#", 1)[1] if "#" in frm else frm
        base = f"{self.ns}#rel/{rel_type}/{local}"
        spdx_id, n = base, 2
        taken = {r["spdxId"] for r in self.relationships}
        while spdx_id in taken:
            spdx_id, n = f"{base}/{n}", n + 1
        rel = {"type": "Relationship", "spdxId": spdx_id, "creationInfo": self.ci, "from": frm, "relationshipType": rel_type, "to": to}
        _set(rel, "comment", comment)
        self.relationships.append(rel)
        return rel

    # ── 값 넣기 ─────────────────────────────────────────────────────────────
    def _put(self, el: dict, ext: list, prop: str, value, key: str) -> None:
        """v0.6 이 더한 속성: v0.6 이면 그 속성(prop)에, 3.0.1 이면 확장에 properties 키(key)로. 목록은 키 뒤에 0부터 인덱스."""
        if value in (None, "", [], {}):
            return
        if self.v06:
            el[prop] = value
        elif isinstance(value, list):
            ext.extend((f"{key}:{i}", v) for i, v in enumerate(value))
        else:
            ext.append((key, value))

    def _put_dict(self, el: dict, ext: list, prop: str, pairs: list[tuple], key: str, field: str | None) -> None:
        """(인덱스, 키, 값) 목록. v0.6 이면 DictionaryEntry 배열로, 3.0.1 이면 "<키>:<인덱스>[:<칸>]" 이름의 확장 항목으로."""
        if not pairs:
            return
        if self.v06:
            el[prop] = [k for _, k, _ in pairs] if all(v is None for _, _, v in pairs) else [_entry(k, v) for _, k, v in pairs]
        else:
            ext.extend((f"{key}:{i}" + (f":{field}" if field else ""), k if v is None else v) for i, k, v in pairs)

    def _extension(self, el: dict, entries: list) -> None:
        items = [{"type": "extension_CdxPropertyEntry", "extension_cdxPropName": name, "extension_cdxPropValue": _text(value)}
                 for name, value in entries if name and value not in (None, "", [], {})]
        if items:
            el["extension"] = [{"type": "extension_CdxPropertiesExtension", "extension_cdxProperty": items}]


def _entry(key, value) -> dict:
    out = {"type": "DictionaryEntry", "key": str(key)}
    if value is not None:
        out["value"] = _text(value)
    return out


def _set(target: dict, key: str, value) -> None:
    if value not in (None, "", [], {}):
        target[key] = value


def _strings(values) -> list[str]:
    if isinstance(values, str):
        return [values]
    return [str(v) for v in values or [] if v not in (None, "")]


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _leaves(value, prefix: str = "") -> list[tuple[str, object]]:
    """남은 값을 (CycloneDX 경로, 값) 으로 편다. 배열 번호는 뺀다. properties 는 그 안의 name 을 경로에 잇는다."""
    out: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "properties" and isinstance(v, list):
                out.extend((f"{prefix}properties.{p.get('name')}", p.get("value")) for p in v if isinstance(p, dict) and p.get("name"))
            else:
                out.extend(_leaves(v, f"{prefix}{k}."))
    elif isinstance(value, list):
        for v in value:
            out.extend(_leaves(v, prefix))
    elif value not in (None, ""):
        out.append((prefix[:-1] if prefix.endswith(".") else prefix, value))
    return out
