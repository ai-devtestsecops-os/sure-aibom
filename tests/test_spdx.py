"""CycloneDX 1.7 → SPDX 3.0.1 변환기. 정적 샘플(tests/fixtures/merged_sample.cdx.json)은 실제 syft+cdxgen+owasp 병합 결과다."""
import base64
import copy
import json
import re
from pathlib import Path

import pytest

from aibom_cli.cli import scan_root
from aibom_cli.merge import merge
from aibom_cli.spdx import cdx_to_spdx
from aibom_cli.spdx._ids import IdRegistry, enc, iso_z, license_ref
from aibom_cli.validate import spdx_integrity_findings, validate_cdx, validate_spdx

SAMPLE = Path(__file__).parent / "fixtures" / "merged_sample.cdx.json"
NS = "urn:uuid:4cdb0fa1-98df-46de-aec5-e2f5de6c392e"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def iri(fragment: str) -> str:
    return f"{NS}#SPDXRef-{fragment}"


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def by_id(doc: dict) -> dict:
    return {n.get("spdxId") or n.get("@id"): n for n in doc["@graph"]}


def rels(doc: dict, rtype: str) -> list[dict]:
    return [n for n in doc["@graph"] if n["type"] == "Relationship" and n["relationshipType"] == rtype]


def ext(node: dict) -> dict:
    out = {}
    for e in (node.get("extension") or [{}])[0].get("extension_cdxProperty", []):
        out.setdefault(e["extension_cdxPropName"], e.get("extension_cdxPropValue"))
    return out


def convert(cdx: dict, **kw) -> tuple[dict, list[str]]:
    logs: list[str] = []
    return cdx_to_spdx(copy.deepcopy(cdx), log=logs.append, **kw), logs


def synthetic(components, dependencies=(), metadata_extra=None, **root_extra) -> dict:
    doc = {
        "bomFormat": "CycloneDX", "specVersion": "1.7", "serialNumber": NS, "version": 1,
        "metadata": {"timestamp": "2026-09-21T06:51:20Z", "tools": {"components": [{"type": "application", "name": "aibom-cli", "version": "0.1.0"}]}},
        "components": components, "dependencies": list(dependencies),
    }
    doc["metadata"].update(metadata_extra or {})
    doc.update(root_extra)
    return doc


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def out(sample) -> dict:
    return cdx_to_spdx(copy.deepcopy(sample), log=lambda m: None)


@pytest.fixture(scope="module")
def nodes(out) -> dict:
    return by_id(out)


# -- 골격 -------------------------------------------------------------------------
def test_document_skeleton(out, nodes):
    assert set(out) == {"@context", "@graph"}
    creation = out["@graph"][0]
    assert creation["type"] == "CreationInfo" and creation["@id"] == "_:creationinfo"
    assert creation["created"] == "2026-09-21T06:51:20Z"                      # metadata.timestamp, 시계 아님
    assert creation["createdBy"] == [iri("Agent-aibom-cli")]
    assert nodes[iri("Agent-aibom-cli")]["type"] == "SoftwareAgent"
    tools = [nodes[t] for t in creation["createdUsing"]]
    assert [t["name"] for t in tools] == ["syft", "cdxgen", "aibom-cli"] and all(t["type"] == "Tool" for t in tools)
    assert creation["createdUsing"][1] == iri("Tool-pkg-npm-cyclonedx-cdxgen-12.8.3")
    assert sum(1 for n in out["@graph"] if n["type"] == "CreationInfo") == 1
    assert sum(1 for n in out["@graph"] if n["type"] == "SpdxDocument") == 1

    document, sbom = nodes[NS], nodes[iri("SBOM")]
    assert document["rootElement"] == [iri("SBOM")]
    assert set(document["element"]) == set(nodes) - {NS, "_:creationinfo"}
    assert document["profileConformance"] == sbom["profileConformance"] == ["core", "software", "ai", "dataset", "simpleLicensing", "extension"]
    assert set(sbom["rootElement"]) <= set(sbom["element"])
    assert not any(nodes[e]["type"] in ("Tool", "SoftwareAgent", "SpdxDocument") for e in sbom["element"])
    assert "software_sbomType" not in sbom and "name" not in sbom                   # lifecycles·metadata.component 없음
    assert ext(document) == {"aibom:cdx:bomFormat": "CycloneDX", "aibom:cdx:bomVersion": "1", "aibom:cdx:specVersion": "1.7"}


def test_tool_fields(nodes):
    cdxgen = nodes[iri("Tool-pkg-npm-cyclonedx-cdxgen-12.8.3")]
    assert cdxgen["externalIdentifier"] == [{"type": "ExternalIdentifier", "externalIdentifierType": "packageUrl", "identifier": "pkg:npm/%40cyclonedx/cdxgen@12.8.3"}]
    assert ext(cdxgen) == {"aibom:cdx:bom-ref": "pkg:npm/@cyclonedx/cdxgen@12.8.3", "aibom:cdx:group": "@cyclonedx", "aibom:cdx:version": "12.8.3",
                           "aibom:cdx:authors:0:name": "OWASP Foundation", "aibom:cdx:publisher": "OWASP Foundation"}
    assert ext(nodes[iri("Tool-syft-1.52.0")]) == {"aibom:cdx:version": "1.52.0", "aibom:cdx:author": "anchore"}
    assert all("software_packageVersion" not in n for n in nodes.values() if n["type"] == "Tool")


# -- 컴포넌트 종류 ------------------------------------------------------------------
def test_element_types_per_component_type(nodes):
    numpy = nodes[iri("pkg-pypi-numpy-2.5.1")]
    assert numpy["type"] == "software_Package" and numpy["software_primaryPurpose"] == "library"
    assert numpy["software_packageVersion"] == "2.5.1" and numpy["software_packageUrl"] == "pkg:pypi/numpy@2.5.1"
    cpes = [e for e in numpy["externalIdentifier"] if e["externalIdentifierType"] == "cpe23"]
    assert len(cpes) == 12 and len({e["identifier"] for e in cpes}) == 12
    assert "comment" not in cpes[0] and all(e["comment"] == "syft:cpe23 candidate" for e in cpes[1:])
    assert "syft:cpe23" not in ext(numpy) and ext(numpy)["syft:package:foundBy"] == "python-package-cataloger"

    req = nodes[iri("hash-SHA-1-923ca73ff01cf8895691e71833605bac717e6670")]
    assert req["type"] == "software_File" and req["name"] == "/requirements.txt"
    assert req["verifiedUsing"] == [{"type": "Hash", "algorithm": "sha1", "hashValue": "923ca73ff01cf8895691e71833605bac717e6670"},
                                    {"type": "Hash", "algorithm": "sha256", "hashValue": "2e975904a12d15cfbe6a2436b4971f1d112c7cc5a742abc2b58430d5a7443160"}]
    modelfile = nodes[iri("file-Modelfile")]
    assert modelfile["type"] == "software_File"
    for f in (req, modelfile):
        assert "software_fileKind" not in f and "software_packageVersion" not in f and "software_packageUrl" not in f
    assert [ext(modelfile)[f"aibom:cdx:tags:{i}"] for i in range(4)] == ["ai", "model-config-file", "modelfile", "ollama"]

    llama = nodes[iri("pkg-generic-ollama-llama3.2-1b")]
    assert llama["type"] == "ai_AIPackage" and llama["software_primaryPurpose"] == "model"
    assert "software_packageVersion" not in llama and ext(llama)["aibom:cdx:group"] == "ollama"

    book = nodes[iri("data-datasets-bookcorpus")]
    assert book["type"] == "dataset_DatasetPackage" and book["software_primaryPurpose"] == "data"
    assert book["dataset_datasetType"] == ["noAssertion"]
    assert book["software_downloadLocation"] == "https://huggingface.co/datasets/datasets/bookcorpus"      # data[0] 접힘
    assert ext(book)["aibom:cdx:data:0:name"] == "datasets/bookcorpus" and ext(book)["aibom:cdx:data:0:type"] == "dataset"
    assert sum(1 for n in nodes.values() if n["type"] == "dataset_DatasetPackage") == 1 and not rels_from(nodes, "hasDataFile")

    bert = nodes[iri("pkg-huggingface-google-bert-bert-base-uncased")]
    assert bert["type"] == "ai_AIPackage" and bert["aibom_task"] == "fill-mask"
    assert bert["aibom_architectureFamily"] == "bert" and bert["aibom_modelArchitecture"] == "BertForMaskedLM"
    assert bert["ai_typeOfModel"] == ["BertForMaskedLM", "bert"] and bert["aibom_inputs"] == bert["aibom_outputs"] == ["text"]
    assert bert["aibom_useCases"] == ["fill-mask"] and bert["ai_informationAboutApplication"] == "fill-mask"
    assert bert["ai_limitation"].startswith("You can use the raw model")
    assert bert["software_downloadLocation"] == "https://huggingface.co/google-bert/bert-base-uncased"
    assert ext(bert)["aibom:cdx:pedigree:ancestors:0:bom-ref"] == bert["software_packageUrl"]           # 자기 참조 조상
    assert not rels_from(nodes, "descendantOf")


def rels_from(nodes: dict, rtype: str) -> list[dict]:
    return [n for n in nodes.values() if n.get("relationshipType") == rtype]


# -- 관계 -------------------------------------------------------------------------
def test_trained_on_bert_bookcorpus(out):
    trained = rels(out, "trainedOn")
    assert len(trained) == 1
    assert trained[0]["spdxId"] == iri("Relationship-trainedOn-pkg-huggingface-google-bert-bert-base-uncased")
    assert trained[0]["from"] == iri("pkg-huggingface-google-bert-bert-base-uncased")
    assert trained[0]["to"] == [iri("data-datasets-bookcorpus")]                 # HF id 정규화로 해석, 스텁 없음
    assert not [n for n in out["@graph"] if n.get("spdxId", "").startswith(f"{NS}#SPDXRef-Dataset-")]


def test_depends_on_remap(sample):
    out, logs = convert(sample)
    deps = {r["from"]: r for r in rels(out, "dependsOn")}
    assert set(deps) == {iri("file-Modelfile"), iri("pkg-huggingface-google-bert-bert-base-uncased")}
    assert deps[iri("file-Modelfile")]["to"] == [iri("pkg-generic-ollama-llama3.2-1b")]
    assert deps[iri("file-Modelfile")]["spdxId"] == iri("Relationship-dependsOn-file-Modelfile")
    assert deps[iri("pkg-huggingface-google-bert-bert-base-uncased")]["to"] == [iri("data-datasets-bookcorpus")]
    assert any("urn:service:ai:ollama:ollama-service" in m for m in logs)          # 서비스는 보류 → 경고
    assert any("services: 1건 보류" in m for m in logs) and any("formulation: 1건 보류" in m for m in logs)


def test_declared_license_pooling(out, nodes):
    mit, apache = nodes[iri("License-MIT")], nodes[iri("License-Apache-2.0")]
    assert mit["type"] == "simplelicensing_LicenseExpression" and mit["simplelicensing_licenseExpression"] == "MIT"
    assert mit["externalRef"] == [{"type": "ExternalRef", "externalRefType": "license", "locator": ["https://opensource.org/licenses/MIT"]}]
    assert ext(mit)["cdx:license:category"] == "Permissive" and len(ext(mit)) == 5
    declared = {r["from"]: r["to"] for r in rels(out, "hasDeclaredLicense")}
    assert declared == {iri("pkg-generic-ollama-llama3.2-1b"): [mit["spdxId"]], iri("pkg-huggingface-google-bert-bert-base-uncased"): [apache["spdxId"]]}

    two_mit = synthetic([
        {"bom-ref": "a", "type": "library", "name": "a", "licenses": [{"license": {"id": "MIT", "url": "https://a", "bom-ref": "lic-1"}}]},
        {"bom-ref": "b", "type": "library", "name": "b", "licenses": [{"license": {"id": "MIT", "url": "https://b", "bom-ref": "lic-2"}}]},
        {"bom-ref": "c", "type": "library", "name": "c", "licenses": [{"expression": "MIT OR Apache-2.0"},
                                                                       {"license": {"name": "Acme_Proprietary", "acknowledgement": "concluded"}}]},   # license 객체 형
        {"bom-ref": "d", "type": "library", "name": "d", "licenses": [{"expression": "MIT", "acknowledgement": "concluded"}]},                        # expression 형
        {"bom-ref": "e", "type": "library", "name": "e", "licenses": [{"license": {"id": "MIT", "acknowledgement": "declared"}}]},
    ])
    assert validate_cdx(two_mit, log=lambda m: None)                                # 스키마에 맞는 CycloneDX 로 검사한다
    doc, _ = convert(two_mit)
    licenses = [n for n in doc["@graph"] if n["type"] == "simplelicensing_LicenseExpression"]
    assert [n["simplelicensing_licenseExpression"] for n in licenses] == ["MIT", "MIT OR Apache-2.0", "LicenseRef-Acme-Proprietary"]
    pooled = by_id(doc)[iri("License-MIT")]
    assert pooled["externalRef"][0]["locator"] == ["https://a"]                    # 첫 등장이 이긴다
    assert ext(pooled) == {"aibom:cdx:licenseRefs:0": "lic-1", "aibom:cdx:licenseRefs:1": "lic-2"}
    assert {r["from"] for r in rels(doc, "hasDeclaredLicense")} == {iri("a"), iri("b"), iri("c"), iri("e")}
    assert {r["from"] for r in rels(doc, "hasConcludedLicense")} == {iri("c"), iri("d")}
    assert by_id(doc)[iri("License-LicenseRef-Acme-Proprietary")]["name"] == "Acme_Proprietary"
    assert license_ref("Acme_Proprietary") == "LicenseRef-Acme-Proprietary"


def test_license_text_and_data_license():
    text = base64.b64encode(b"All rights reserved.").decode()
    doc, _ = convert(synthetic(
        [{"bom-ref": "a", "type": "library", "name": "a", "licenses": [{"license": {"name": "Acme Proprietary", "text": {"content": text, "encoding": "base64"}}}]}],
        metadata_extra={"licenses": [{"license": {"id": "CC0-1.0"}}]}))
    nodes = by_id(doc)
    expr = nodes[iri("License-LicenseRef-Acme-Proprietary")]
    assert expr["simplelicensing_customIdToUri"] == [{"type": "DictionaryEntry", "key": "LicenseRef-Acme-Proprietary", "value": iri("LicenseText-LicenseRef-Acme-Proprietary")}]
    assert nodes[iri("LicenseText-LicenseRef-Acme-Proprietary")]["simplelicensing_licenseText"] == "All rights reserved."
    assert nodes[NS]["dataLicense"] == iri("License-CC0-1.0")
    assert validate_spdx(doc, log=lambda m: None)


def test_nested_components_and_scope():
    doc, _ = convert(synthetic(
        [{"bom-ref": "node", "type": "platform", "name": "Node.js", "version": "20", "components": [
            {"bom-ref": "libc", "type": "library", "name": "libc.so.6", "scope": "excluded", "purl": "pkg:generic/libc.so.6"},
            {"bom-ref": "opt", "type": "library", "name": "opt", "scope": "optional"},
            {"bom-ref": "inner", "type": "library", "name": "inner"}]},
         {"bom-ref": "app", "type": "application", "name": "app"}],
        [{"ref": "app", "dependsOn": ["node", "opt"]}, {"ref": "inner", "dependsOn": []}, {"ref": "ghost", "dependsOn": ["app"]}]))
    nodes = by_id(doc)
    assert rels(doc, "hasDynamicLink")[0]["to"] == [iri("libc")] and ext(nodes[iri("libc")])["aibom:cdx:scope"] == "excluded"
    assert rels(doc, "hasOptionalComponent")[0]["to"] == [iri("opt")]
    assert rels(doc, "contains")[0]["to"] == [iri("inner")]
    assert rels(doc, "dependsOn")[0]["to"] == [iri("node")] and rels(doc, "hasOptionalDependency")[0]["to"] == [iri("opt")]
    none = [r for r in rels(doc, "dependsOn") if r["from"] == iri("inner")][0]
    assert none["to"] == ["NoneElement"] and none["completeness"] == "complete"
    graph_order = [n["spdxId"] for n in doc["@graph"] if n["type"] in ("software_Package",)]
    assert graph_order[:4] == [iri("node"), iri("libc"), iri("opt"), iri("inner")]           # 자식은 부모 바로 뒤
    assert nodes[iri("SBOM")]["rootElement"] == [iri("app")]                                 # 그래프 루트
    assert validate_spdx(doc, log=lambda m: None)


# -- 결정성 · 식별자 -----------------------------------------------------------------
def test_deterministic_ids(sample):
    a, _ = convert(sample)
    b, _ = convert(sample)
    text = dumps(a)
    assert text == dumps(b)
    assert set(UUID_RE.findall(text)) == {"4cdb0fa1-98df-46de-aec5-e2f5de6c392e"}         # serialNumber 외 uuid 없음
    assert all(n["spdxId"].startswith(NS) for n in a["@graph"] if "spdxId" in n)

    no_serial = {k: v for k, v in sample.items() if k != "serialNumber"}
    c, _ = convert(no_serial)
    d, _ = convert(no_serial)
    assert dumps(c) == dumps(d) and c["@graph"][1]["spdxId"].startswith("urn:uuid:") and c["@graph"][1]["spdxId"] != NS
    assert convert(dict(sample, serialNumber="not-a-urn"))[0]["@graph"][1]["spdxId"] == c["@graph"][1]["spdxId"]

    assert enc("pkg:pypi/numpy@2.5.1") == "pkg-pypi-numpy-2.5.1" and enc("file:/Modelfile@") == "file-Modelfile"
    assert enc("!!!").startswith("x-") and re.fullmatch(r"x-[0-9a-f]{8}", enc("!!!"))
    assert re.fullmatch(r"x-[0-9a-f]{8}", enc("한국전자")) and enc("한국전자") != enc("일본전자")             # 비ASCII 이름 충돌 방지
    reg = IdRegistry(NS)
    assert reg.iri("a-b", ("component", "a/b")) == iri("a-b")
    assert reg.iri("a-b", ("component", "a/b")) == iri("a-b")                              # 같은 원시 키 → 같은 IRI
    assert re.fullmatch(re.escape(iri("a-b-")) + r"[0-9a-f]{8}", reg.iri("a-b", ("component", "a-b")))
    with pytest.raises(ValueError):
        reg2 = IdRegistry(NS)
        reg2._owner["x"] = ("component", "p")
        reg2._owner["x-" + __import__("aibom_cli.spdx._ids", fromlist=["sha8"]).sha8("q")] = ("component", "r")
        reg2.iri("x", ("component", "q"))
    assert iso_z("2026-09-21T06:51:25.951477+00:00") == "2026-09-21T06:51:25Z"
    assert iso_z("2026-09-21T15:51:20+09:00") == "2026-09-21T06:51:20Z" and iso_z("2026-09-21T06:51:20") == "2026-09-21T06:51:20Z"


def test_same_raw_key_is_one_element():
    comp = {"bom-ref": "dup", "type": "library", "name": "dup", "version": "1"}
    doc, _ = convert(synthetic([comp, dict(comp, description="second")], metadata_extra={"component": dict(comp)}))
    nodes = by_id(doc)
    assert sum(1 for n in nodes.values() if n["type"] == "software_Package") == 1 and "description" not in nodes[iri("dup")]
    assert nodes[iri("SBOM")]["rootElement"] == [iri("dup")]


def test_missing_timestamp_raises_without_now(sample):
    doc = copy.deepcopy(sample)
    del doc["metadata"]["timestamp"]
    with pytest.raises(ValueError):
        cdx_to_spdx(doc, log=lambda m: None)
    assert cdx_to_spdx(doc, log=lambda m: None, now="2026-01-01T00:00:00+09:00")["@graph"][0]["created"] == "2025-12-31T15:00:00Z"


def test_no_absolute_paths(out):
    text = dumps(out)
    assert "/mnt/yhchoe" not in text and "/tmp/claude" not in text and "environmentVars" not in text
    assert by_id(out)[iri("hash-SHA-1-923ca73ff01cf8895691e71833605bac717e6670")]["name"] == "/requirements.txt"


# -- 스키마 -----------------------------------------------------------------------
def test_validates_against_both_schemas(sample, out):
    assert validate_spdx(out, strict=False, log=lambda m: None)
    assert not validate_spdx(out, strict=True, log=lambda m: None)                        # aibom_* 는 공식 스키마가 거부
    strict, _ = convert(sample, strict=True)
    assert validate_spdx(strict, strict=True, log=lambda m: None)
    assert validate_spdx(strict, strict=False, log=lambda m: None)
    assert spdx_integrity_findings(out) == [] and spdx_integrity_findings(strict) == []


def test_strict_mode_drops_aibom(sample):
    strict, _ = convert(sample, strict=True)
    assert not [k for n in strict["@graph"] for k in n if k.startswith("aibom_")]
    bert = by_id(strict)[iri("pkg-huggingface-google-bert-bert-base-uncased")]
    e = ext(bert)
    assert e["aibom:model:task"] == "fill-mask" and e["aibom:model:inputs:0:format"] == "text" and e["aibom:model:outputs:0:format"] == "text"
    assert e["aibom:model:architectureFamily"] == "bert" and e["aibom:model:useCases:0"] == "fill-mask"
    assert bert["ai_typeOfModel"] == ["BertForMaskedLM", "bert"]                             # 네이티브 ai_* 는 남는다


def test_hyperparameter_from_owasp_property(nodes):
    bert = nodes[iri("pkg-huggingface-google-bert-bert-base-uncased")]
    assert [(h["key"], h["value"]) for h in bert["ai_hyperparameter"]] == [
        ("context_length", "512"), ("embedding_length", "768"), ("block_count", "12"), ("attention_head_count", "12"),
        ("feed_forward_length", "3072"), ("vocabSize", "30522"), ("contextLength", "512")]
    assert all(h["type"] == "DictionaryEntry" and isinstance(h["value"], str) for h in bert["ai_hyperparameter"])
    assert bert["ai_informationAboutTraining"] == "Training data available: true\nTraining datasets verified: Dataset(s) exist and are accessible on Hugging Face Hub."
    e = ext(bert)
    assert not [k for k in e if k.startswith("genai:")]                                       # 승격된 항목은 확장에 없다
    assert e["owasp:aibom:distribution:modelFileSize"] == "2918975670" and e["cdx:ai:contextWindow"] == "512"


def test_extension_round_trip_of_cdx_property(out, nodes):
    llama = nodes[iri("pkg-generic-ollama-llama3.2-1b")]
    assert ext(llama)["cdx:ai:provider"] == "ollama" and ext(llama)["cdx:ai:reviewNeeded"] == "true"
    assert ext(llama)["aibom:cdx:evidence:occurrences:0:location"] == "Modelfile"
    for n in out["@graph"]:
        if "extension" in n:
            assert len(n["extension"]) == 1 and n["extension"][0]["type"] == "extension_CdxPropertiesExtension"
            entries = n["extension"][0]["extension_cdxProperty"]
            assert entries and all(e["type"] == "extension_CdxPropertyEntry" and isinstance(e["extension_cdxPropName"], str)
                                   and isinstance(e["extension_cdxPropValue"], str) for e in entries)
            assert not any(e["extension_cdxPropName"].startswith("cdx:bom-ref") for e in entries)
    assert "extension" not in nodes[iri("Agent-aibom-cli")]


def test_validate_spdx_reports_and_localizes(out):
    bad = copy.deepcopy(out)
    by_id(bad)[iri("file-Modelfile")]["software_packageVersion"] = "1"
    logs: list[str] = []
    assert not validate_spdx(bad, log=logs.append)
    assert any("software_File" in m and "SPDXRef-file-Modelfile" in m for m in logs)
    assert not any("@graph was unexpected" in m for m in logs)

    bad = copy.deepcopy(out)
    bad["@graph"][0]["created"] = "2026-09-21T06:51:20.123Z"
    assert not validate_spdx(bad, log=lambda m: None)
    bad = copy.deepcopy(out)
    bad["@graph"][0]["createdBy"] = [iri("Tool-syft-1.52.0")]
    assert any("createdBy" in f for f in spdx_integrity_findings(bad))
    bad = copy.deepcopy(out)
    by_id(bad)[iri("pkg-pypi-numpy-2.5.1")]["foo_bar"] = 1
    assert not validate_spdx(bad, log=lambda m: None)                                        # Draft 2020-12 (unevaluatedProperties)
    bad = copy.deepcopy(out)
    del by_id(bad)[iri("data-datasets-bookcorpus")]["dataset_datasetType"]
    logs = []
    assert not validate_spdx(bad, log=logs.append) and any("dataset_datasetType" in m for m in logs)


# -- 합성 케이스 -------------------------------------------------------------------
def test_root_component_from_merge():
    src = synthetic([{"bom-ref": "x", "type": "library", "name": "x", "version": "1", "purl": "pkg:npm/x@1"},
                     {"bom-ref": "y", "type": "library", "name": "y", "version": "2", "purl": "pkg:npm/y@2"}],
                    [{"ref": "x", "dependsOn": ["y"]}])
    merged = merge([src], root=("fixture", "directory"))
    assert merged["metadata"]["component"] == {"type": "application", "name": "fixture", "bom-ref": "application:/fixture@"}
    assert merged["dependencies"][0] == {"ref": "application:/fixture@", "dependsOn": ["pkg:npm/x@1"]}
    merged["metadata"].update({"lifecycles": [{"phase": "pre-build"}, {"phase": "discovery"}], "supplier": {"name": "ACME", "url": ["https://acme.example"]},
                               "properties": [{"name": "cdx:bom:componentTypes", "value": "generic"}]})
    assert merge([src], root=("alpine:latest", "image"))["metadata"]["component"]["type"] == "container"
    assert merge([src])["metadata"].get("component") is None

    doc, _ = convert(merged)
    nodes = by_id(doc)
    ns = merged["serialNumber"]                                                               # merge 가 새 serialNumber 를 준다
    root = nodes[f"{ns}#SPDXRef-application-fixture"]
    assert root["type"] == "software_Package" and root["software_primaryPurpose"] == "application"
    assert root["suppliedBy"] == f"{ns}#SPDXRef-Organization-ACME" and nodes[root["suppliedBy"]]["externalRef"][0]["externalRefType"] == "altWebPage"
    sbom = nodes[f"{ns}#SPDXRef-SBOM"]
    assert sbom["rootElement"] == [root["spdxId"]] and sbom["name"] == nodes[ns]["name"] == "fixture"
    assert sbom["software_sbomType"] == ["source"] and ext(sbom) == {"aibom:cdx:lifecycles:1:phase": "discovery", "cdx:bom:componentTypes": "generic"}
    assert root["suppliedBy"] in sbom["element"]
    assert rels(doc, "dependsOn")[0]["from"] == root["spdxId"] and rels(doc, "dependsOn")[0]["to"] == [f"{ns}#SPDXRef-pkg-npm-x-1"]
    assert validate_spdx(doc, log=lambda m: None)


def test_scan_root(tmp_path):
    assert scan_root(str(tmp_path)) == (tmp_path.resolve().name, "directory")
    assert scan_root("alpine:latest") == ("alpine:latest", "image")


def test_datasets_synthetic():
    model = {"bom-ref": "m", "type": "machine-learning-model", "name": "m",
             "properties": [{"name": "aibom:model:datasets:3:usage", "value": "testing"}],
             "modelCard": {"modelParameters": {"datasets": [
                 {"type": "dataset", "name": "wikipedia", "contents": {"url": "https://huggingface.co/datasets/wikipedia"}},
                 {"ref": "pkg:huggingface/datasets/nonexistent"},
                 {"ref": "opaque"},
                 {"ref": "d"},
                 {"ref": "urn:cdx:4cdb0fa1-98df-46de-aec5-e2f5de6c392e/1#d"},
                 {"ref": "urn:cdx:11111111-1111-1111-1111-111111111111/1#other"}]}}}
    data = {"bom-ref": "d", "type": "data", "name": "d", "properties": [{"name": "aibom:dataset:modality:0", "value": "text"}, {"name": "aibom:dataset:modality:1", "value": "image"},
                                                                          {"name": "aibom:dataset:size", "value": "1000"}, {"name": "aibom:dataset:availability", "value": "direct-download"},
                                                                          {"name": "aibom:dataset:knownBias:0:name", "value": "gender"}, {"name": "aibom:dataset:knownBias:0:mitigationStrategy", "value": "reweigh"}],
            "data": [{"type": "dataset", "name": "d-main", "classification": "TLP:AMBER", "sensitiveData": ["PII"], "contents": {"url": "https://x/d"}},
                     {"type": "dataset", "bom-ref": "d2", "name": "d-second", "classification": "internal"},
                     {"type": "source-code", "name": "loader.py", "contents": {"url": "https://x/loader.py"}}]}
    doc, logs = convert(synthetic([model, data]))
    nodes = by_id(doc)
    d = nodes[iri("d")]
    assert d["dataset_datasetType"] == ["text", "image"] and d["dataset_confidentialityLevel"] == "amber"
    assert d["dataset_hasSensitivePersonalInformation"] == "yes" and ext(d)["aibom:cdx:data:0:sensitiveData:0"] == "PII"
    assert d["dataset_datasetSize"] == 1000 and d["dataset_datasetAvailability"] == "directDownload"
    assert d["dataset_knownBias"] == ["gender"] and d["aibom_knownBiasMitigationStrategy"] == [{"type": "DictionaryEntry", "key": "gender", "value": "reweigh"}]
    assert d["software_downloadLocation"] == "https://x/d"
    d2, loader = nodes[iri("d2")], nodes[iri("d-data-2")]
    assert d2["type"] == "dataset_DatasetPackage" and ext(d2)["aibom:cdx:data:1:classification"] == "internal" and "dataset_confidentialityLevel" not in d2
    assert loader["type"] == "software_File" and loader["software_primaryPurpose"] == "source" and loader["externalRef"][0]["externalRefType"] == "altDownloadLocation"
    assert rels(doc, "hasDataFile")[0]["to"] == [iri("d2"), iri("d-data-2")]

    trained = rels(doc, "trainedOn")[0]
    wiki = nodes[iri("m-dataset-0")]
    assert wiki["name"] == "wikipedia" and wiki["software_downloadLocation"] == "https://huggingface.co/datasets/wikipedia" and wiki["dataset_datasetType"] == ["noAssertion"]
    stub = nodes[iri("Dataset-pkg-huggingface-datasets-nonexistent")]
    assert stub["software_packageUrl"] == "pkg:huggingface/datasets/nonexistent" and stub["name"] == "datasets/nonexistent" and "unresolved" in stub["comment"]
    other = "urn:uuid:11111111-1111-1111-1111-111111111111#SPDXRef-other"                    # BOM-Link → 이 체계의 IRI
    assert trained["to"] == [wiki["spdxId"], stub["spdxId"], iri("d"), other]
    assert rels(doc, "testedOn")[0]["to"] == [iri("d")]                                        # usage 마커
    assert ext(nodes[iri("m")])["aibom:cdx:modelCard:datasets:2:ref"] == "opaque"
    assert nodes[NS]["import"] == [{"type": "ExternalMap", "externalSpdxId": other, "locationHint": "urn:cdx:11111111-1111-1111-1111-111111111111/1#other"}]
    assert any("nonexistent" in m for m in logs)
    assert validate_spdx(doc, log=lambda m: None)
    strict, _ = convert(synthetic([model, data]), strict=True)
    assert validate_spdx(strict, strict=True, log=lambda m: None)
    assert ext(by_id(strict)[iri("d")])["aibom:dataset:knownBias:0:mitigationStrategy"] == "reweigh"


def test_modelcard_extras_and_edge_cases():
    comp = {
        "bom-ref": "m", "type": "machine-learning-model", "name": "m", "version": "1", "publisher": "ACME", "author": "jane",
        "supplier": {"name": "Sup", "url": ["https://sup"]}, "manufacturer": {"name": "Manu"}, "authors": [{"name": "Kim", "email": "kim@example.com"}],
        "cpe": "cpe:/a:vendor:prod:1", "hashes": [{"alg": "Streebog-256", "content": "aa"}, {"alg": "SHA3-256", "content": "bb"}],
        "externalReferences": [{"type": "model-card", "url": "https://mc", "comment": "c"}, {"type": "website", "url": "https://home"}, {"type": "security-contact", "url": "https://sec"}],
        "copyright": "(c) ACME", "releaseNotes": {"type": "major", "timestamp": "2026-01-02T03:04:05.6+00:00", "title": "T"},
        "modelCard": {
            "bom-ref": "mc-1",
            "modelParameters": {"approach": {"type": "supervised"}, "architectureFamily": "bert", "modelArchitecture": "BertForMaskedLM", "inputs": [{"format": "text"}]},
            "quantitativeAnalysis": {"performanceMetrics": [{"type": "accuracy", "value": "0.91", "slice": "en", "confidenceInterval": {"lowerBound": "0.9", "upperBound": "0.92"}}]},
            "considerations": {
                "users": ["devs"], "technicalLimitations": ["a; b", "c"], "performanceTradeoffs": ["speed"],
                "ethicalConsiderations": [{"name": "bias", "mitigationStrategy": "audit"}],
                "fairnessAssessments": [{"groupAtRisk": "g", "benefits": "b", "harms": "h", "mitigationStrategy": "ms"}],
                "environmentalConsiderations": {"energyConsumptions": [
                    {"activity": "training", "activityEnergyCost": {"value": 12.5, "unit": "kWh"}, "co2CostEquivalent": {"value": 3, "unit": "tCO2eq"}},
                    {"activity": "inference", "activityEnergyCost": {"value": 1, "unit": "kWh"}},
                    {"activity": "design", "activityEnergyCost": {"value": 2, "unit": "kWh"}}]}},
            "properties": [{"name": "genai:aibom:modelcard:hyperparameter", "value": "x"}, {"name": "aibom:model:parameterCount", "value": "110106428"},
                           {"name": "aibom:model:sensitivePersonalInformation", "value": "unknown"}, {"name": "aibom:model:safetyRiskAssessment", "value": "Medium"},
                           {"name": "aibom:model:performanceMetrics:0:type", "value": "f1"}, {"name": "aibom:model:performanceMetrics:0:value", "value": "0.8"},
                           {"name": "aibom:model:performanceMetrics:0:decisionThreshold", "value": "0.5"}, {"name": "aibom:model:hyperparameters:0:name", "value": "lr"},
                           {"name": "aibom:model:hyperparameters:0:value", "value": "0.01"}, {"name": "aibom:model:explainabilityMethods:0", "value": "SHAP"},
                           {"name": "aibom:model:trainingTechniques:0", "value": "RLHF"}, {"name": "safetyRiskAssessment", "value": "a long paragraph"}],
        },
    }
    crypto = {"bom-ref": "k", "type": "cryptographic-asset", "name": "key"}
    afile = {"bom-ref": "f", "type": "file", "name": "a.txt", "version": "1.0", "mime-type": "text/plain", "purl": "pkg:generic/a.txt",
             "properties": [{"name": "cdx:file:kind", "value": "file"}, {"name": "aibom:model:parameterCount", "value": "abc"}]}
    link = "urn:cdx:11111111-1111-1111-1111-111111111111/1#x"
    doc, logs = convert(synthetic([comp, crypto, afile], [{"ref": "m", "dependsOn": [link, "k", "urn:cdx:abc/1#x"]}]))
    nodes = by_id(doc)
    m = nodes[iri("m")]
    assert m["ai_typeOfModel"] == ["BertForMaskedLM", "bert", "supervised"]
    assert m["ai_metric"] == [{"type": "DictionaryEntry", "key": "accuracy", "value": "0.91"}, {"type": "DictionaryEntry", "key": "f1", "value": "0.8"}]
    assert m["aibom_metricSlice"] == [{"type": "DictionaryEntry", "key": "accuracy", "value": "en"}]
    assert m["ai_metricDecisionThreshold"] == [{"type": "DictionaryEntry", "key": "f1", "value": "0.5"}]
    assert m["ai_hyperparameter"] == [{"type": "DictionaryEntry", "key": "hyperparameter", "value": "x"}, {"type": "DictionaryEntry", "key": "lr", "value": "0.01"}]
    assert m["ai_limitation"] == "a; b\nc" and m["aibom_users"] == ["devs"] and m["ai_modelExplainability"] == ["SHAP"]
    assert m["aibom_ethicalConsiderations"] == ["bias"] and m["aibom_ethicalConsiderationsMitigationStrategy"] == [{"type": "DictionaryEntry", "key": "bias", "value": "audit"}]
    assert m["aibom_fairnessAssessments"] == ["g"] and m["aibom_fairnessAssessmentHarms"][0]["value"] == "h"
    energy = m["ai_energyConsumption"]
    assert energy["ai_trainingEnergyConsumption"] == [{"type": "ai_EnergyConsumptionDescription", "ai_energyQuantity": 12.5, "ai_energyUnit": "kilowattHour"}]
    assert energy["ai_inferenceEnergyConsumption"][0]["ai_energyQuantity"] == 1 and "ai_finetuningEnergyConsumption" not in energy
    assert m["aibom_parameterCount"] == 110106428 and m["ai_useSensitivePersonalInformation"] == "noAssertion" and m["ai_safetyRiskAssessment"] == "medium"
    e = ext(m)
    assert e["aibom:cdx:modelCard:energyConsumptions:2:activity"] == "design" and e["aibom:cdx:modelCard:energyConsumptions:0:co2CostEquivalent:value"] == "3"
    assert e["aibom:cdx:modelCard:performanceMetrics:0:confidenceInterval:lowerBound"] == "0.9"
    assert e["aibom:cdx:modelCard:considerations:fairnessAssessments:0:mitigationStrategy"] == "ms"
    assert e["aibom:cdx:modelCard:considerations:performanceTradeoffs:0"] == "speed"
    assert e["aibom:model:trainingTechniques:0"] == "RLHF" and e["safetyRiskAssessment"] == "a long paragraph"
    assert e["aibom:cdx:releaseNotes:type"] == "major" and m["releaseTime"] == "2026-01-02T03:04:05Z"
    assert {"type": "ExternalIdentifier", "externalIdentifierType": "other", "identifier": "mc-1", "comment": "aibom:cdx:modelCard:bom-ref"} in m["externalIdentifier"]
    assert {"type": "ExternalIdentifier", "externalIdentifierType": "cpe22", "identifier": "cpe:/a:vendor:prod:1"} in m["externalIdentifier"]
    assert m["verifiedUsing"] == [{"type": "Hash", "algorithm": "other", "hashValue": "aa", "comment": "CycloneDX alg: Streebog-256"}, {"type": "Hash", "algorithm": "sha3_256", "hashValue": "bb"}]
    refs = {r["locator"][0]: r for r in m["externalRef"]}
    assert refs["https://mc"]["externalRefType"] == "other" and refs["https://mc"]["comment"] == "aibom:cdx:externalReference:type=model-card; c"
    assert refs["https://sec"]["externalRefType"] == "securityPolicy" and m["software_homePage"] == "https://home"
    assert m["software_copyrightText"] == "(c) ACME" and m["software_packageVersion"] == "1"
    assert m["suppliedBy"] == iri("Organization-Sup") and m["originatedBy"] == [iri("Organization-Manu"), iri("Person-Kim"), iri("Agent-jane")]
    assert nodes[iri("Person-Kim")]["externalIdentifier"][0]["externalIdentifierType"] == "email" and nodes[iri("Agent-jane")]["type"] == "Agent"
    assert rels(doc, "publishedBy")[0]["to"] == [iri("Organization-ACME")]
    dep = rels(doc, "dependsOn")[0]
    external = "urn:uuid:11111111-1111-1111-1111-111111111111#SPDXRef-x"
    assert dep["to"] == [external, iri("k")] and nodes[NS]["import"] == [{"type": "ExternalMap", "externalSpdxId": external, "locationHint": link}]
    assert any("urn:cdx:abc/1#x" in m for m in logs)                                           # UUID 아닌 serial 은 BOM-Link 가 아니다
    k = nodes[iri("k")]
    assert k["software_primaryPurpose"] == "other" and ext(k)["aibom:cdx:type"] == "cryptographic-asset"
    f = nodes[iri("f")]
    assert f["type"] == "software_File" and "software_packageVersion" not in f and ext(f)["aibom:cdx:version"] == "1.0"
    assert f["contentType"] == "text/plain" and f["software_fileKind"] == "file"
    assert f["externalIdentifier"] == [{"type": "ExternalIdentifier", "externalIdentifierType": "packageUrl", "identifier": "pkg:generic/a.txt"}]
    assert ext(f)["aibom:model:parameterCount"] == "abc"                                          # 정수 검사 실패 → 원문 유지
    assert validate_spdx(doc, log=lambda m: None)
    strict, _ = convert(synthetic([comp, crypto, afile]), strict=True)
    assert validate_spdx(strict, strict=True, log=lambda m: None)
    se = ext(by_id(strict)[iri("m")])
    assert se["aibom:model:parameterCount"] == "110106428" and se["aibom:model:performanceMetrics:0:slice"] == "en"
    assert se["aibom:model:ethicalConsiderations:0:name"] == "bias" and se["aibom:model:ethicalConsiderations:0:mitigationStrategy"] == "audit"
    assert se["aibom:model:fairnessAssessments:0:groupAtRisk"] == "g" and se["aibom:model:fairnessAssessments:0:harms"] == "h"


def test_non_ascii_organization_names_do_not_collide():
    doc, _ = convert(synthetic([{"bom-ref": "a", "type": "library", "name": "a", "supplier": {"name": "한국전자"}},
                                {"bom-ref": "b", "type": "library", "name": "b", "supplier": {"name": "일본전자"}}]))
    orgs = [n for n in doc["@graph"] if n["type"] == "Organization"]
    assert [o["name"] for o in orgs] == ["한국전자", "일본전자"] and len({o["spdxId"] for o in orgs}) == 2
    assert validate_spdx(doc, log=lambda m: None)


# -- 리뷰 지적 사항 회귀 -----------------------------------------------------------
def test_nameless_metadata_supplier_omits_supplied_by():
    for supplier in ({"url": ["https://x"]}, {"name": ""}):
        doc, _ = convert(synthetic([{"bom-ref": "a", "type": "library", "name": "a"}],
                                   metadata_extra={"component": {"bom-ref": "root", "type": "application", "name": "root"}, "supplier": supplier}))
        root = by_id(doc)[iri("root")]
        assert "suppliedBy" not in root and validate_spdx(doc, log=lambda m: None) and validate_spdx(convert(synthetic([]))[0], strict=True, log=lambda m: None)
    bad = copy.deepcopy(doc)
    by_id(bad)[iri("root")]["suppliedBy"] = None
    assert any("suppliedBy 가 null" in f for f in spdx_integrity_findings(bad))


def test_invalid_base64_license_text_is_kept_raw():
    doc, logs = convert(synthetic([{"bom-ref": "a", "type": "library", "name": "a",
                                    "licenses": [{"license": {"name": "X", "text": {"content": "not base64 !!!", "encoding": "base64"}}}]}]))
    assert by_id(doc)[iri("LicenseText-LicenseRef-X")]["simplelicensing_licenseText"] == "not base64 !!!"
    assert any("base64" in m for m in logs) and validate_spdx(doc, log=lambda m: None)


def test_duplicate_key_merges_relationships_and_extension():
    doc, logs = convert(synthetic([
        {"bom-ref": "dup", "type": "library", "name": "first", "version": "1", "properties": [{"name": "p", "value": "1"}]},
        {"bom-ref": "dup", "type": "machine-learning-model", "name": "second", "version": "2", "description": "SECOND",
         "licenses": [{"license": {"id": "MIT"}}], "properties": [{"name": "p", "value": "2"}], "modelCard": {"modelParameters": {"task": "fill-mask"}},
         "components": [{"bom-ref": "child", "type": "library", "name": "child"}]}]))
    nodes = by_id(doc)
    dup = nodes[iri("dup")]
    assert dup["type"] == "software_Package" and dup["name"] == "first" and "description" not in dup
    assert rels(doc, "hasDeclaredLicense")[0]["from"] == iri("dup") and rels(doc, "contains")[0]["to"] == [iri("child")]
    e = ext(dup)
    assert e["p"] == "1" and [x["extension_cdxPropValue"] for x in dup["extension"][0]["extension_cdxProperty"] if x["extension_cdxPropName"] == "p"] == ["1", "2"]
    assert e["aibom:cdx:duplicate:0:description"] == "SECOND" and e["aibom:cdx:duplicate:0:name"] == "second" and "fill-mask" in e["aibom:cdx:duplicate:0:modelCard"]
    assert any("중복 키 dup" in m for m in logs) and validate_spdx(doc, log=lambda m: None)
    same = {"bom-ref": "s", "type": "library", "name": "s"}
    assert not [m for m in convert(synthetic([same, dict(same)]))[1] if "중복" in m]         # 내용까지 같으면 조용히 합친다


def test_null_values_never_leak_as_python_none():
    model = {"bom-ref": "m", "type": "machine-learning-model", "name": "m", "modelCard": {
        "properties": [{"name": "genai:aibom:modelcard:hyperparameter", "value": "{\"lr\": null, \"flag\": true, \"n\": 1.0}"}],
        "considerations": {"ethicalConsiderations": [{"mitigationStrategy": "ONLY-MITIGATION"}],
                           "environmentalConsiderations": {"energyConsumptions": [
                               {"activity": "training", "activityEnergyCost": {"value": "abc", "unit": "kWh"}, "properties": [{"name": "p-novalue"}]},
                               {"activity": "inference", "activityEnergyCost": {"value": "12.5", "unit": "kWh"}}]}}}}
    doc, _ = convert(synthetic([model]))
    m = by_id(doc)[iri("m")]
    assert [(h["key"], h["value"]) for h in m["ai_hyperparameter"]] == [("lr", "null"), ("flag", "true"), ("n", "1.0")]
    e = ext(m)
    assert "None" not in dumps(doc) and not [k for k in e if k.endswith("p-novalue")]
    assert e["aibom:cdx:modelCard:considerations:ethicalConsiderations:0:mitigationStrategy"] == "ONLY-MITIGATION"
    assert e["aibom:cdx:modelCard:energyConsumptions:0:activityEnergyCost:value"] == "abc"       # 숫자 아닌 값은 슬롯에 넣지 않는다
    assert m["ai_energyConsumption"] == {"type": "ai_EnergyConsumption", "ai_inferenceEnergyConsumption": [
        {"type": "ai_EnergyConsumptionDescription", "ai_energyQuantity": "12.5", "ai_energyUnit": "kilowattHour"}]}
    assert validate_spdx(doc, log=lambda m: None) and validate_spdx(convert(synthetic([model]), strict=True)[0], strict=True, log=lambda m: None)


def test_reserved_fragments_win_over_components():
    doc, _ = convert(synthetic([{"bom-ref": "SBOM", "type": "library", "name": "x", "licenses": [{"license": {"id": "MIT"}}]},
                                {"bom-ref": "Agent-aibom-cli", "type": "library", "name": "y"}, {"bom-ref": "a/b", "type": "library", "name": "ab1"},
                                {"bom-ref": "a-b", "type": "library", "name": "ab2", "licenses": [{"license": {"id": "MIT"}}]}]))
    nodes = by_id(doc)
    assert nodes[iri("SBOM")]["type"] == "software_Sbom" and nodes[NS]["rootElement"] == [iri("SBOM")]
    assert nodes[iri("Agent-aibom-cli")]["type"] == "SoftwareAgent"
    packages = {n["name"]: n["spdxId"] for n in doc["@graph"] if n["type"] == "software_Package"}
    assert re.fullmatch(re.escape(iri("SBOM-")) + r"[0-9a-f]{8}", packages["x"]) and packages["y"] != iri("Agent-aibom-cli")
    sbom_rel = [r for r in rels(doc, "hasDeclaredLicense") if r["from"] == packages["x"]][0]
    assert sbom_rel["spdxId"] == packages["x"].replace("#SPDXRef-", "#SPDXRef-Relationship-hasDeclaredLicense-")   # 접미까지 실제 조각
    ab2_rel = [r for r in rels(doc, "hasDeclaredLicense") if r["from"] == packages["ab2"]][0]
    assert packages["ab1"] == iri("a-b") and ab2_rel["spdxId"].endswith(packages["ab2"].rsplit("#SPDXRef-", 1)[1])
    assert validate_spdx(doc, log=lambda m: None)


def test_unparseable_timestamp_is_kept():
    doc = synthetic([{"bom-ref": "a", "type": "library", "name": "a"}])
    doc["metadata"]["timestamp"] = "21/09/2026 06:51"
    with pytest.raises(ValueError, match="읽을 수 없다"):
        cdx_to_spdx(copy.deepcopy(doc), log=lambda m: None)
    out, logs = convert(doc, now="2026-01-01T00:00:00Z")
    assert out["@graph"][0]["created"] == "2026-01-01T00:00:00Z" and ext(by_id(out)[NS])["aibom:cdx:timestamp"] == "21/09/2026 06:51"
    assert any("timestamp" in m for m in logs) and validate_spdx(out, log=lambda m: None)


def test_validate_cli_reports_cyclonedx_level(tmp_path):
    from aibom_cli.cli import main
    assert main(["validate", "tests/fixtures/merged_sample.cdx.json"]) == 0      # 공식 1.7 적합
    assert main(["validate", str(tmp_path / "none.json")]) == 2                  # 없는 파일
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.7", "components": [{"type": "nope", "name": 1}]}))
    assert main(["validate", str(bad)]) == 3                                      # 둘 다 실패
    doc = json.loads(Path("tests/fixtures/merged_sample.cdx.json").read_text())
    strict = cdx_to_spdx(doc, strict=True, log=lambda m: None)
    assert not any(k.startswith("aibom_") for e in strict["@graph"] for k in e)  # 변환기 strict 모드는 함수로 계속 확인


def test_cjk_component_names_get_hash_suffix():
    doc, _ = convert(synthetic([{"type": "library", "name": "일본라이브러리", "version": "1.0"}, {"type": "library", "name": "한국라이브러리", "version": "1.0"}]))
    ids = [n["spdxId"] for n in doc["@graph"] if n["type"] == "software_Package"]
    assert all(re.fullmatch(re.escape(iri("library-1.0-")) + r"[0-9a-f]{8}", x) for x in ids) and len(set(ids)) == 2
    assert enc("café@1") == "cafe-1"                                                         # 악센트 라틴은 NFKD 로 접어 해시 없이
    assert enc("application:/앱@") != enc("application:/웹@")                                  # 한 글자 CJK 이름도 해시를 받는다
    assert enc("application:/앱@").startswith("application-") and len(enc("application:/앱@")) == len("application-") + 8
    doc, _ = convert(synthetic([{"type": "application", "name": "앱"}, {"type": "application", "name": "웹"}]))
    assert len({n["spdxId"] for n in doc["@graph"] if n["type"] == "software_Package"}) == 2


def test_aibom_properties_are_gated_by_element_class():
    cdx = synthetic([
        {"bom-ref": "d", "type": "data", "name": "d", "data": [
            {"type": "dataset", "name": "d0"},
            {"type": "source-code", "name": "loader.py", "contents": {"properties": [{"name": "aibom:dataset:size", "value": "5"}, {"name": "aibom:dataset:knownBias:0:name", "value": "x"}]}}]},
        {"bom-ref": "lib", "type": "library", "name": "lib", "properties": [{"name": "aibom:model:task", "value": "x"}, {"name": "aibom:dataset:size", "value": "3"}]}])
    doc, _ = convert(cdx)
    nodes = by_id(doc)
    lib, loader = nodes[iri("lib")], nodes[iri("d-data-1")]
    assert ext(lib) == {"aibom:cdx:bom-ref": "lib", "aibom:model:task": "x", "aibom:dataset:size": "3"} and not [k for k in lib if k.startswith(("aibom_", "ai_"))]
    assert ext(loader)["aibom:dataset:size"] == "5" and ext(loader)["aibom:dataset:knownBias:0:name"] == "x" and not [k for k in loader if k.startswith("dataset_")]
    assert validate_spdx(doc, log=lambda m: None) and validate_spdx(convert(cdx, strict=True)[0], strict=True, log=lambda m: None)


def test_inline_dataset_does_not_fold_into_library_with_same_name():
    doc, _ = convert(synthetic([
        {"bom-ref": "pkg:pypi/wikipedia@1.4.0", "type": "library", "name": "wikipedia", "version": "1.4.0", "purl": "pkg:pypi/wikipedia@1.4.0"},
        {"bom-ref": "ds", "type": "data", "name": "corpus", "data": [{"type": "dataset", "name": "datasets/bookcorpus", "contents": {"url": "https://hf.co/datasets/bookcorpus"}}]},
        {"bom-ref": "m", "type": "machine-learning-model", "name": "m", "modelCard": {"modelParameters": {"datasets": [
            {"type": "dataset", "name": "wikipedia", "contents": {"url": "https://huggingface.co/datasets/wikipedia"}},
            {"type": "dataset", "name": "datasets/bookcorpus"},                                  # 접힌 data[0] 이름으로 기존 DatasetPackage 에 접힘
            {"type": "dataset", "name": "other", "contents": {"url": "https://hf.co/datasets/bookcorpus"}}]}}}]))
    nodes = by_id(doc)
    trained = rels(doc, "trainedOn")[0]["to"]
    assert trained == [iri("m-dataset-0"), iri("ds")] and nodes[iri("m-dataset-0")]["type"] == "dataset_DatasetPackage"
    assert all(nodes[t]["type"] == "dataset_DatasetPackage" for t in trained)


def test_data_license_is_in_sbom_element_and_tool_fields_survive():
    doc, _ = convert(synthetic([{"bom-ref": "a", "type": "library", "name": "a"}], metadata_extra={
        "licenses": [{"license": {"id": "CC0-1.0"}}],
        "tools": {"components": [{"type": "application", "name": "t", "version": "1", "description": "a tool description", "supplier": {"name": "ToolCorp", "url": ["https://tool"]}}]}}))
    nodes = by_id(doc)
    document, sbom = nodes[NS], nodes[iri("SBOM")]
    assert document["dataLicense"] == iri("License-CC0-1.0") and document["dataLicense"] in sbom["element"] and document["dataLicense"] in document["element"]
    tool = nodes[iri("Tool-t-1")]
    assert tool["description"] == "a tool description" and ext(tool)["aibom:cdx:supplier:name"] == "ToolCorp" and ext(tool)["aibom:cdx:supplier:url:0"] == "https://tool"
    assert validate_spdx(doc, log=lambda m: None)


V06_TYPED = [
    {"bom-ref": "ds", "type": "data", "name": "corpus", "properties": [{"name": "aibom:dataset:size", "value": "999"}], "data": [
        {"type": "dataset", "bom-ref": "ds-data0", "name": "corpus", "contents": {"url": "https://example.org/corpus"},
         "modality": ["text"], "size": 12345, "intendedUse": "LM pretraining", "collectionProcess": "crawl",
         "knownBias": [{"name": "english-heavy", "detectionMethod": "audit"}, {"detectionMethod": "no-name"}], "knownGaps": [{"name": "no-korean", "mitigationStrategy": "add"}],
         "noise": "some", "updateMechanism": "yearly", "anonymizationMethods": ["hashing"], "preprocessing": ["dedupe"], "provenance": ["web"],
         "originalCollectionPurpose": "research", "designChoices": ["utf8"], "representationAssumptions": ["web=world"], "statistics": [{"type": "rows", "value": "1e9"}]}]},
    {"bom-ref": "model", "type": "machine-learning-model", "name": "m", "modelCard": {
        "modelParameters": {"task": "fill-mask", "parameterCount": 110000000, "trainingCompute": "8xA100", "trainingTime": "3d", "optimizationTarget": "loss",
                            "designChoices": ["wordpiece"], "trainingTechniques": ["mlm"], "hyperparameters": [{"name": "epochs", "value": "3"}, {"value": "orphan"}],
                            "datasets": [{"ref": "ds-data0"}]},
        "considerations": {"explainabilityMethods": ["SHAP"], "limitationIdentificationMethods": ["red-team"], "safetyRiskAssessment": "low",
                           "sensitivePersonalInformation": "no", "technicalRequirements": ["gpu"]}}},
]


def test_v06_typed_fields_are_not_lost():
    cdx = synthetic(copy.deepcopy(V06_TYPED), [{"ref": "model", "dependsOn": ["ds-data0"]}])
    assert validate_cdx(cdx, log=lambda m: None)
    doc, logs = convert(cdx)
    nodes = by_id(doc)
    ds, model = nodes[iri("ds")], nodes[iri("model")]
    assert ds["dataset_datasetType"] == ["text"]
    assert ds["dataset_datasetSize"] == 999 and ext(ds)["aibom:cdx:data:0:size"] == "12345"                        # 컴포넌트 값이 먼저, 데이터 값은 남긴다
    assert ds["dataset_intendedUse"] == "LM pretraining" and ds["dataset_dataCollectionProcess"] == "crawl" and ds["dataset_datasetNoise"] == "some"
    assert ds["dataset_datasetUpdateMechanism"] == "yearly" and ds["dataset_anonymizationMethodUsed"] == ["hashing"] and ds["dataset_dataPreprocessing"] == ["dedupe"]
    assert ds["dataset_knownBias"] == ["english-heavy"] and ds["aibom_knownBiasDetectionMethod"] == [{"type": "DictionaryEntry", "key": "english-heavy", "value": "audit"}]
    assert ext(ds)["aibom:cdx:data:0:knownBias:1:detectionMethod"] == "no-name"
    assert ds["aibom_knownGaps"] == ["no-korean"] and ds["aibom_knownGapsMitigationStrategy"][0]["value"] == "add"
    assert ds["aibom_originalCollectionPurpose"] == "research" and ds["aibom_designChoices"] == ["utf8"] and ds["aibom_representationAssumptions"] == ["web=world"]
    assert ds["aibom_statistics"] == [{"type": "DictionaryEntry", "key": "rows", "value": "1e9"}] and ext(ds)["aibom:cdx:data:0:provenance:0"] == "web"
    assert model["aibom_parameterCount"] == 110000000 and model["aibom_trainingCompute"] == "8xA100" and model["aibom_trainingTime"] == "3d"
    assert model["aibom_optimizationTarget"] == "loss" and model["aibom_designChoices"] == ["wordpiece"]
    assert model["ai_hyperparameter"] == [{"type": "DictionaryEntry", "key": "epochs", "value": "3"}]
    assert ext(model)["aibom:cdx:modelCard:modelParameters:hyperparameters:1:value"] == "orphan"
    assert ext(model)["aibom:cdx:modelCard:modelParameters:trainingTechniques:0"] == "mlm" and ext(model)["aibom:cdx:modelCard:considerations:technicalRequirements:0"] == "gpu"
    assert model["ai_modelExplainability"] == ["SHAP"] and model["aibom_limitationIdentificationMethods"] == ["red-team"]
    assert model["ai_safetyRiskAssessment"] == "low" and model["ai_useSensitivePersonalInformation"] == "no"
    text = dumps(doc)
    for needle in ("12345", "LM pretraining", "crawl", "english-heavy", "no-korean", "yearly", "hashing", "dedupe", "8xA100", "3d", "wordpiece", "mlm",
                   "epochs", "SHAP", "red-team", "gpu", "research", "web=world", "1e9", "utf8", "no-name", "orphan", "add"):
        assert needle in text, needle
    # 접힌 data[0] 의 bom-ref 는 소유 원소의 별칭 — trainedOn/dependsOn 이 풀린다
    assert rels(doc, "trainedOn")[0]["to"] == [iri("ds")] and rels(doc, "dependsOn")[0]["to"] == [iri("ds")]
    assert not [m for m in logs if "해석하지 못해" in m]
    assert validate_spdx(doc, log=lambda m: None)
    strict, _ = convert(cdx, strict=True)
    assert validate_spdx(strict, strict=True, log=lambda m: None) and validate_spdx(strict, strict=False, log=lambda m: None)
    se = ext(by_id(strict)[iri("ds")])
    assert se["aibom:dataset:knownGaps:0:name"] == "no-korean" and se["aibom:dataset:statistics:0:value"] == "1e9"
    assert ext(by_id(strict)[iri("model")])["aibom:model:parameterCount"] == "110000000"
    loose = copy.deepcopy(V06_TYPED)                                                            # 스키마 밖 값(enum 아닌 modality)은 확장으로
    loose[0]["data"][0]["modality"] = ["text", "hologram"]
    ds = by_id(convert(synthetic(loose))[0])[iri("ds")]
    assert ds["dataset_datasetType"] == ["text"] and ext(ds)["aibom:cdx:data:0:modality:1"] == "hologram"


# -- 2차 리뷰 지적 사항 회귀 ---------------------------------------------------------
def test_nameless_metadata_manufacturer_is_omitted_from_created_by():
    for manufacturer in ({"url": ["https://example.org"]}, {"name": ""}):
        cdx = synthetic([{"bom-ref": "a", "type": "library", "name": "a"}], metadata_extra={"manufacturer": manufacturer})
        assert validate_cdx(copy.deepcopy(cdx), log=lambda m: None)
        doc, _ = convert(cdx)
        assert doc["@graph"][0]["createdBy"] == [iri("Agent-aibom-cli")] and validate_spdx(doc, log=lambda m: None)
        assert validate_spdx(convert(cdx, strict=True)[0], strict=True, log=lambda m: None)
    named, _ = convert(synthetic([{"bom-ref": "a", "type": "library", "name": "a"}], metadata_extra={"manufacturer": {"name": "ACME"}}))
    assert named["@graph"][0]["createdBy"] == [iri("Agent-aibom-cli"), iri("Organization-ACME")]


def test_integrity_check_flags_null_items_inside_reference_lists():
    doc = {"@graph": [{"type": "CreationInfo", "@id": "_:c", "createdBy": [None]},
                      {"type": "SpdxDocument", "spdxId": "urn:x:y", "creationInfo": "_:c", "rootElement": [None], "element": [None]}]}
    findings = spdx_integrity_findings(doc)
    assert [f for f in findings if "createdBy 에 문자열이 아닌 항목 None" in f]
    assert [f for f in findings if "rootElement 에 문자열이 아닌 항목 None" in f] and [f for f in findings if "element 에 문자열이 아닌 항목 None" in f]


def test_tools_services_are_warned_and_kept_in_sbom_extension():
    cdx = synthetic([{"bom-ref": "a", "type": "library", "name": "a"}])
    cdx["metadata"]["tools"]["services"] = [{"bom-ref": "svc", "name": "scan-svc", "version": "2", "provider": {"name": "P"}}]
    doc, logs = convert(cdx)
    assert any("metadata.tools.services: 1건 보류" in m for m in logs)
    e = ext(by_id(doc)[iri("SBOM")])
    assert e["aibom:cdx:tools:services:0:name"] == "scan-svc" and e["aibom:cdx:tools:services:0:version"] == "2"
    assert e["aibom:cdx:tools:services:0:provider:name"] == "P" and e["aibom:cdx:tools:services:0:bom-ref"] == "svc"
    assert validate_spdx(doc, log=lambda m: None)


def test_pedigree_commit_and_patch_leaves_are_not_dropped():
    comp = {"bom-ref": "a", "type": "library", "name": "a", "pedigree": {
        "commits": [{"uid": "c1", "author": {"name": "au", "email": "au@x", "timestamp": "2026-01-01T00:00:00Z"},
                     "committer": {"name": "co", "email": "co@x"}}],
        "patches": [{"type": "backport", "resolves": [{"id": "CVE-1", "type": "security", "name": "nm", "description": "dd",
                                                       "source": {"name": "NVD", "url": "https://nvd"}}]}]}}
    doc, _ = convert(synthetic([comp]))
    e = ext(by_id(doc)[iri("a")])
    assert e["aibom:cdx:pedigree:commits:0:author:email"] == "au@x" and e["aibom:cdx:pedigree:commits:0:author:timestamp"] == "2026-01-01T00:00:00Z"
    assert e["aibom:cdx:pedigree:commits:0:committer:email"] == "co@x" and e["aibom:cdx:pedigree:commits:0:committer:name"] == "co"
    assert e["aibom:cdx:pedigree:patches:0:resolves:0:type"] == "security" and e["aibom:cdx:pedigree:patches:0:resolves:0:name"] == "nm"
    assert e["aibom:cdx:pedigree:patches:0:resolves:0:description"] == "dd"
    assert e["aibom:cdx:pedigree:patches:0:resolves:0:source:name"] == "NVD" and e["aibom:cdx:pedigree:patches:0:resolves:0:source:url"] == "https://nvd"
    assert validate_spdx(doc, log=lambda m: None)


def test_legacy_tool_without_name_gets_readable_fallback():
    cdx = synthetic([{"bom-ref": "a", "type": "library", "name": "a"}])
    cdx["metadata"]["tools"] = [{"vendor": "V", "name": "oldtool", "version": "1"}, {"vendor": "V2"}]
    doc, _ = convert(cdx)
    tools = [(n["name"], n["spdxId"].split("#")[-1]) for n in doc["@graph"] if n["type"] == "Tool"]
    assert tools == [("oldtool", "SPDXRef-Tool-oldtool-1"), ("V2", "SPDXRef-Tool-0")]
    assert validate_spdx(doc, log=lambda m: None)
    cdx["metadata"]["tools"] = [{}, {"description": "d"}]                                     # 같은 원시 키 "@0" → 원소 하나
    doc, _ = convert(cdx)
    assert [n["name"] for n in doc["@graph"] if n["type"] == "Tool"] == ["unnamed-tool"]


def test_model_parameters_do_not_overwrite_component_property_slots():
    model = {"bom-ref": "m", "type": "machine-learning-model", "name": "m",
             "properties": [{"name": "aibom:model:task", "value": "FROM-PROP"}, {"name": "aibom:model:architectureFamily", "value": "FAM-PROP"}],
             "modelCard": {"modelParameters": {"task": "FROM-CARD", "architectureFamily": "FAM-CARD", "modelArchitecture": "ARCH-CARD"}}}
    doc, _ = convert(synthetic([model]))
    m = by_id(doc)[iri("m")]
    e = ext(m)
    assert m["aibom_task"] == "FROM-PROP" and m["aibom_architectureFamily"] == "FAM-PROP" and m["aibom_modelArchitecture"] == "ARCH-CARD"
    assert e["aibom:cdx:modelCard:modelParameters:task"] == "FROM-CARD" and e["aibom:cdx:modelCard:modelParameters:architectureFamily"] == "FAM-CARD"
    assert m["ai_typeOfModel"] == ["ARCH-CARD", "FAM-CARD"]                              # typeOfModel 은 카드 값 그대로
    assert validate_spdx(doc, log=lambda m: None)
    only_card, _ = convert(synthetic([{**model, "properties": []}]))
    assert by_id(only_card)[iri("m")]["aibom_task"] == "FROM-CARD"


def test_pedigree_bare_reference_to_existing_component_is_not_a_duplicate():
    doc, logs = convert(synthetic([{"bom-ref": "m", "type": "machine-learning-model", "name": "m"},
                                   {"bom-ref": "v", "type": "machine-learning-model", "name": "v", "pedigree": {"ancestors": [{"bom-ref": "m"}]}}]))
    assert not [m for m in logs if "중복" in m]
    assert rels(doc, "descendantOf")[0]["from"] == iri("v") and rels(doc, "descendantOf")[0]["to"] == [iri("m")]
    assert "aibom:cdx:duplicate" not in dumps(doc)


def test_repeated_dependency_ref_replaces_none_element_marker():
    comps = [{"bom-ref": "a", "type": "library", "name": "a"}, {"bom-ref": "b", "type": "library", "name": "b"}]
    doc, logs = convert(synthetic(comps, [{"ref": "a", "dependsOn": []}, {"ref": "a", "dependsOn": ["b"]}]))
    dep = rels(doc, "dependsOn")
    assert len(dep) == 1 and dep[0]["to"] == [iri("b")] and "completeness" not in dep[0]
    assert any("dependencies[].ref 가 반복된다" in m for m in logs)
    doc, _ = convert(synthetic(comps, [{"ref": "a", "dependsOn": ["b"]}, {"ref": "a", "dependsOn": []}]))
    assert rels(doc, "dependsOn")[0]["to"] == [iri("b")]                                          # 뒤에 오는 빈 행도 마커를 만들지 않는다
    doc, _ = convert(synthetic(comps, [{"ref": "a", "dependsOn": []}]))
    assert rels(doc, "dependsOn")[0]["to"] == ["NoneElement"] and rels(doc, "dependsOn")[0]["completeness"] == "complete"


def test_merge_remaps_producer_root_dependency_row_to_new_root():
    syft = {"bomFormat": "CycloneDX", "specVersion": "1.6", "metadata": {"component": {"type": "file", "name": "/mixed", "bom-ref": "root-dir"}},
            "components": [{"bom-ref": "s1", "type": "library", "name": "numpy", "version": "1", "purl": "pkg:pypi/numpy@1"},
                           {"bom-ref": "s2", "type": "library", "name": "requests", "version": "2", "purl": "pkg:pypi/requests@2"},
                           {"bom-ref": "s3", "type": "library", "name": "urllib3", "version": "3", "purl": "pkg:pypi/urllib3@3"}],
            "dependencies": [{"ref": "root-dir", "dependsOn": ["s1", "s2"]}, {"ref": "s2", "dependsOn": ["s3"]},
                             {"ref": "svc", "dependsOn": ["s1"]}]}
    merged = merge([syft], root=("mixed", "directory"))
    assert merged["dependencies"][0] == {"ref": "application:/mixed@", "dependsOn": ["pkg:pypi/numpy@1", "pkg:pypi/requests@2"]}
    assert {"ref": "pkg:pypi/requests@2", "dependsOn": ["pkg:pypi/urllib3@3"]} in merged["dependencies"]
    assert {"ref": "svc", "dependsOn": ["pkg:pypi/numpy@1"]} in merged["dependencies"]            # 서비스 행은 남기고 변환기가 경고한다
    merged["metadata"]["timestamp"] = "2026-09-21T06:51:20Z"
    doc, logs = convert(merged)
    ns = merged["serialNumber"]
    root_dep = [r for r in rels(doc, "dependsOn") if r["from"] == f"{ns}#SPDXRef-application-mixed"][0]
    assert root_dep["to"] == [f"{ns}#SPDXRef-pkg-pypi-numpy-1", f"{ns}#SPDXRef-pkg-pypi-requests-2"]
    assert any("건너뛴다: svc" in m for m in logs) and validate_spdx(doc, log=lambda m: None)
    # 도구 루트 행의 대상만 '의존받음'으로 치던 결함: 서비스 행의 대상은 루트가 직접 의존한다
    only_svc = {**syft, "metadata": {}, "dependencies": [{"ref": "svc", "dependsOn": ["s1", "s2", "s3"]}]}
    assert merge([only_svc], root=("mixed", "directory"))["dependencies"][0]["dependsOn"] == ["pkg:pypi/numpy@1", "pkg:pypi/requests@2", "pkg:pypi/urllib3@3"]
