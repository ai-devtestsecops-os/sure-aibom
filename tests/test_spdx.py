"""spdx — CycloneDX(v0.6 형) 문서를 SPDX 3.0.1 JSON-LD 로 바꾼다. 네트워크도 도구도 쓰지 않는다.
결과는 공식 SPDX 3.0.1 스키마(spec 3.0.1)와 aibom-v0.6 SPDX 스키마(spec v0.6)로 검증한다."""
import copy
import json

import pytest

from sure_aibom.engine.facts import Facts
from sure_aibom.engine.spdx import convert_spdx
from sure_aibom.engine.validation import _validate_spdx, detect_format, schema_for, validate_doc

NS = "urn:uuid:3b1f6c2e-8a4d-4c1e-9f7a-0d2b5e6a7c91"
ROOT, BERT, REVIEWS, LOCAL, LIB, FILE, OS_REF = ("container:/acme-app:1.4.0@", "pkg:huggingface/acme/acme-bert", "pkg:huggingface/datasets/acme/reviews",
                                                "data:local/data@", "pkg:pypi/requests@2.31.0", "file:/requirements.txt", "operating-system:/debian@12")
SERVICE, APT = "urn:service:ai:openai:OpenAI-API", "pkg:generic/os-repository/deb.debian.org"


def doc_of() -> dict:
    """sure-aibom 이 --spec v0.6 으로 내는 모양을 본뜬 문서. 변환기가 다루는 자리를 모두 한 번씩 담는다."""
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.7", "serialNumber": NS, "version": 1,
        "metadata": {
            "timestamp": "2026-10-20T00:00:00Z", "lifecycles": [{"phase": "post-build"}],
            "tools": {"components": [{"type": "application", "author": "anchore", "name": "syft", "version": "1.52.0"},
                                     {"type": "application", "name": "cdxgen", "version": "12.8.4", "purl": "pkg:npm/%40cyclonedx/cdxgen@12.8.4"},
                                     {"type": "application", "name": "sure-aibom", "version": "0.2.0"}]},
            "component": {"type": "container", "name": "acme-app:1.4.0", "bom-ref": ROOT, "version": "1.4.0", "description": "Acme review assistant",
                          "supplier": {"name": "Acme Corp"}, "authors": [{"name": "Acme ML Team"}], "licenses": [{"expression": "Apache-2.0 OR MIT"}],
                          "externalReferences": [{"type": "vcs", "url": "https://github.com/acme/acme-app", "comment": "revision: 0123abcd"},
                                                 {"type": "website", "url": "https://acme.example/app"}],
                          "pedigree": {"ancestors": [{"type": "container", "name": "docker.io/library/debian:12-slim",
                                                      "hashes": [{"alg": "SHA-256", "content": "d1" * 32}]}]}}},
        "components": [
            {"type": "library", "bom-ref": LIB, "name": "requests", "version": "2.31.0", "purl": LIB, "author": "Kenneth Reitz", "publisher": "PyPI",
             "cpe": "cpe:2.3:a:python-requests:requests:2.31.0:*:*:*:*:*:*:*", "licenses": [{"license": {"id": "Apache-2.0"}}],
             "hashes": [{"alg": "SHA-256", "content": "ab" * 32}], "evidence": {"occurrences": [{"location": "requirements.txt"}]},
             "externalReferences": [{"type": "distribution", "url": "https://pypi.org/project/requests/"}, {"type": "citation", "url": "https://doi.org/10.1/x"}]},
            {"type": "file", "bom-ref": FILE, "name": "/requirements.txt", "hashes": [{"alg": "SHA-1", "content": "cd" * 20}, {"alg": "MD6", "content": "ef" * 8}]},
            {"type": "operating-system", "bom-ref": OS_REF, "name": "debian", "version": "12", "swid": {"tagId": "debian-12", "name": "debian"}},
            {"type": "machine-learning-model", "bom-ref": BERT, "group": "acme", "name": "acme-bert", "version": "a1" * 20, "purl": BERT,
             "description": "Intent classifier", "tags": ["ai", "machine-learning-model"], "supplier": {"name": "acme"},
             "licenses": [{"license": {"name": "Acme Model License", "url": "https://acme.example/licenses/model", "acknowledgement": "concluded"}}],
             "evidence": {"occurrences": [{"location": "src/train.py#L4"}]},
             "pedigree": {"ancestors": [{"type": "machine-learning-model", "group": "acme", "name": "acme-base", "purl": "pkg:huggingface/acme/acme-base"}],
                          "variants": [{"type": "machine-learning-model", "name": "acme-bert-int8", "purl": "pkg:huggingface/acme/acme-bert-int8"}],
                          "notes": "Hugging Face relation: finetune"},
             "modelCard": {
                 "modelParameters": {"approach": {"type": "supervised"}, "task": "text-classification", "architectureFamily": "bert",
                                     "modelArchitecture": "BertForSequenceClassification", "datasets": [{"ref": REVIEWS}, {"type": "dataset", "name": "inline-only"}],
                                     "inputs": [{"format": "text", "maxSize": "512"}], "outputs": [{"format": "label"}],
                                     "hyperparameters": [{"name": "learning_rate", "value": "2e-5"}, {"name": "block_count", "value": "12"}],
                                     "parameterCount": 110000000, "trainingTechniques": ["fine-tuning", "transfer learning"],
                                     "designChoices": ["Single classification head"], "optimizationTarget": "macro F1", "trainingCompute": "3.2e17 FLOPs",
                                     "trainingTime": "6 hours"},
                 "quantitativeAnalysis": {"performanceMetrics": [{"type": "accuracy", "value": "0.81", "slice": "test", "decisionThreshold": "0.5",
                                                                  "confidenceInterval": {"lowerBound": "0.79", "upperBound": "0.83"}},
                                                                 {"type": "f1", "value": "0.77", "slice": "elderly-speakers"}]},
                 "considerations": {"users": ["Call center operators"], "useCases": ["Voice intent classification"],
                                    "technicalLimitations": ["Lower accuracy in noisy environments"],
                                    "ethicalConsiderations": [{"name": "Misclassification", "mitigationStrategy": "Route to an agent"}],
                                    "fairnessAssessments": [{"groupAtRisk": "Elderly users", "benefits": "Hands-free access",
                                                             "harms": "Recognition errors", "mitigationStrategy": "Add elderly speaker data"}],
                                    "limitationIdentificationMethods": ["Error analysis by age group"], "explainabilityMethods": ["SHAP"],
                                    "sensitivePersonalInformation": "unknown", "safetyRiskAssessment": "low",
                                    "technicalRequirements": ["python 3.12", "transformers"]}}},
            {"type": "data", "bom-ref": REVIEWS, "group": "acme", "name": "reviews", "version": "c3" * 20, "purl": REVIEWS,
             "licenses": [{"license": {"id": "CC-BY-4.0"}}],
             "externalReferences": [{"type": "distribution", "url": "https://huggingface.co/datasets/acme/reviews"}],
             "data": [{"type": "dataset", "name": "acme/reviews", "contents": {"url": "https://huggingface.co/datasets/acme/reviews", "availability": "direct-download"},
                       "classification": "internal", "sensitiveData": ["Speaker voice recordings"], "size": 750000, "modality": ["text"],
                       "intendedUse": "text-classification", "collectionProcess": "annotations crowdsourced", "preprocessing": ["Deduplication"],
                       "originalCollectionPurpose": "Service quality review", "designChoices": ["Excluded calls shorter than 2 seconds"],
                       "representationAssumptions": ["Transcripts reflect speaker intent"],
                       "knownBias": [{"name": "Few elderly speakers", "detectionMethod": "Sample count by age group", "mitigationStrategy": "Collect more"}],
                       "knownGaps": [{"name": "Few dialect samples", "mitigationStrategy": "Collect regional call data"}], "noise": "About 3% transcription errors",
                       "anonymizationMethods": ["Name and phone number masking"], "updateMechanism": "Quarterly additions",
                       "provenance": ["https://huggingface.co/datasets/acme/reviews", "https://huggingface.co/datasets/acme/raw-reviews"],
                       "statistics": [{"type": "train:label:n_unique", "value": "2"}, {"type": "train:text:length:mean", "value": "140.5"}]}]},
            {"type": "data", "bom-ref": LOCAL, "name": "data",
             "data": [{"type": "dataset", "name": "data/train.csv", "size": 8404, "statistics": [{"type": "train:label:n_unique", "value": "2"}]},
                      {"type": "dataset", "name": "data/images/train/*.png"}]},
            {"type": "data", "bom-ref": APT, "name": "deb.debian.org/debian", "purl": APT,
             "data": [{"type": "configuration", "name": "apt-source", "contents": {"url": "https://deb.debian.org/debian"}}]},
        ],
        "services": [{"bom-ref": SERVICE, "group": "openai", "name": "OpenAI API", "provider": {"name": "openai"}, "endpoints": [], "tags": ["ai", "openai"]}],
        "dependencies": [
            {"ref": ROOT, "dependsOn": [LIB, FILE, OS_REF, BERT, LOCAL, APT, "pkg:pypi/gone@1.0"]},
            {"ref": BERT, "dependsOn": [REVIEWS]},
            {"ref": SERVICE, "dependsOn": [BERT]},
            {"ref": "urn:nowhere", "dependsOn": [LIB]},
        ],
    }


def graph_of(out: dict) -> dict[str, dict]:
    return {e.get("spdxId") or e.get("@id"): e for e in out["@graph"]}


def by_type(out: dict, cls: str) -> list[dict]:
    return [e for e in out["@graph"] if e["type"] == cls]


def ext_of(el: dict) -> list[tuple[str, str]]:
    return [(p["extension_cdxPropName"], p.get("extension_cdxPropValue")) for x in el.get("extension") or [] for p in x["extension_cdxProperty"]]


def rels(out: dict, kind: str) -> dict[str, list[str]]:
    return {r["from"]: r["to"] for r in by_type(out, "Relationship") if r["relationshipType"] == kind}


def sid(local: str) -> str:
    return f"{NS}#{local}"


@pytest.mark.parametrize("spec", ["3.0.1", "v0.6"])
def test_both_specs_validate_against_their_schema(spec):
    out = convert_spdx(doc_of(), spec, log=lambda m: None)
    assert _validate_spdx(out, spec, log=print)
    has_aibom = any(k.startswith("aibom_") for e in out["@graph"] for k in e)
    assert has_aibom == (spec == "v0.6")                                      # 3.0.1 문서에는 v0.6 속성이 없다


def test_a_v06_document_is_not_plain_spdx_and_a_plain_one_is_also_v06():
    v06 = convert_spdx(doc_of(), "v0.6", log=lambda m: None)
    assert not _validate_spdx(v06, "3.0.1", log=lambda m: None)                  # aibom_* 는 공식 스키마에 없는 속성이다
    assert _validate_spdx(convert_spdx(doc_of(), "3.0.1", log=lambda m: None), "v0.6", log=lambda m: None)   # 3.0.1 문서는 v0.6 의 부분집합


def test_classes_follow_the_component_type():
    g = graph_of(convert_spdx(doc_of(), "3.0.1", log=lambda m: None))
    kinds = {local: g[sid(local)]["type"] for local in (ROOT, LIB, FILE, OS_REF, BERT, REVIEWS, LOCAL, APT, SERVICE)}
    assert kinds == {ROOT: "software_Package", LIB: "software_Package", FILE: "software_File", OS_REF: "software_Package", BERT: "ai_AIPackage",
                     REVIEWS: "dataset_DatasetPackage", LOCAL: "dataset_DatasetPackage", APT: "software_Package", SERVICE: "software_Package"}
    assert g[sid(ROOT)]["software_primaryPurpose"] == "container" and g[sid(OS_REF)]["software_primaryPurpose"] == "operatingSystem"
    assert g[sid(APT)]["software_primaryPurpose"] == "data" and "dataset_datasetType" not in g[sid(APT)]   # dataset 항목이 없는 type=data 는 데이터셋이 아니다
    assert g[sid(SERVICE)]["software_primaryPurpose"] == "other" and g[sid(SERVICE)]["comment"].startswith("service")
    assert g[sid(FILE)]["software_fileKind"] == "file" and "software_packageVersion" not in g[sid(FILE)]


def test_package_fields_land_in_standard_spdx_properties():
    g = graph_of(convert_spdx(doc_of(), "3.0.1", log=lambda m: None))
    lib, root, file = g[sid(LIB)], g[sid(ROOT)], g[sid(FILE)]
    assert (lib["software_packageVersion"], lib["software_packageUrl"]) == ("2.31.0", LIB)
    assert lib["externalIdentifier"] == [{"type": "ExternalIdentifier", "externalIdentifierType": "cpe23", "identifier": lib_cpe()}]
    assert lib["verifiedUsing"] == [{"type": "Hash", "algorithm": "sha256", "hashValue": "ab" * 32}]
    assert file["verifiedUsing"] == [{"type": "Hash", "algorithm": "sha1", "hashValue": "cd" * 20},
                                     {"type": "Hash", "algorithm": "other", "hashValue": "ef" * 8, "comment": "MD6"}]
    assert lib["software_downloadLocation"] == "https://pypi.org/project/requests/"
    assert lib["externalRef"] == [{"type": "ExternalRef", "externalRefType": "altDownloadLocation", "locator": ["https://pypi.org/project/requests/"]},
                                  {"type": "ExternalRef", "externalRefType": "other", "locator": ["https://doi.org/10.1/x"], "comment": "citation"}]
    assert g[lib["suppliedBy"]] == {"type": "Organization", "spdxId": sid("org/PyPI"), "creationInfo": sid("creationinfo"), "name": "PyPI"}   # publisher
    assert [g[a]["type"] for a in lib["originatedBy"]] == ["Agent"] and g[lib["originatedBy"][0]]["name"] == "Kenneth Reitz"
    assert g[root["suppliedBy"]]["name"] == "Acme Corp" and g[root["originatedBy"][0]]["name"] == "Acme ML Team"
    assert root["software_homePage"] == "https://acme.example/app" and root["externalRef"][0]["comment"] == "revision: 0123abcd"
    assert g[sid(OS_REF)]["externalIdentifier"][0] == {"type": "ExternalIdentifier", "externalIdentifierType": "swid", "identifier": "debian-12"}


def lib_cpe() -> str:
    return "cpe:2.3:a:python-requests:requests:2.31.0:*:*:*:*:*:*:*"


def test_model_fields_split_between_standard_properties_and_the_spec():
    plain = graph_of(convert_spdx(doc_of(), "3.0.1", log=lambda m: None))[sid(BERT)]
    rich = graph_of(convert_spdx(doc_of(), "v0.6", log=lambda m: None))[sid(BERT)]
    for el in (plain, rich):                                                   # SPDX 3.0.1 에 자리가 있는 값은 두 spec 에서 같다
        assert el["ai_typeOfModel"] == ["supervised"]
        assert el["ai_hyperparameter"] == [{"type": "DictionaryEntry", "key": "learning_rate", "value": "2e-5"},
                                           {"type": "DictionaryEntry", "key": "block_count", "value": "12"}]
        assert el["ai_metric"] == [{"type": "DictionaryEntry", "key": "accuracy", "value": "0.81"}, {"type": "DictionaryEntry", "key": "f1", "value": "0.77"}]
        assert el["ai_metricDecisionThreshold"] == [{"type": "DictionaryEntry", "key": "accuracy", "value": "0.5"}]
        assert el["ai_informationAboutTraining"] == "fine-tuning, transfer learning"
        assert el["ai_informationAboutApplication"] == "python 3.12, transformers"
        assert el["ai_limitation"] == "Lower accuracy in noisy environments" and el["ai_modelExplainability"] == ["SHAP"]
        assert (el["ai_useSensitivePersonalInformation"], el["ai_safetyRiskAssessment"]) == ("noAssertion", "low")
    # v0.6: 더한 속성으로
    assert (rich["aibom_task"], rich["aibom_architectureFamily"], rich["aibom_modelArchitecture"]) == ("text-classification", "bert", "BertForSequenceClassification")
    assert rich["aibom_inputs"] == ["text"] and rich["aibom_inputMaxSize"] == [{"type": "DictionaryEntry", "key": "text", "value": "512"}]
    assert rich["aibom_outputs"] == ["label"] and "aibom_outputMaxSize" not in rich
    assert rich["aibom_parameterCount"] == 110000000 and rich["aibom_trainingTime"] == "6 hours"
    assert rich["aibom_metricSlice"] == [{"type": "DictionaryEntry", "key": "accuracy", "value": "test"}, {"type": "DictionaryEntry", "key": "f1", "value": "elderly-speakers"}]
    assert rich["aibom_fairnessAssessments"] == ["Elderly users"]
    assert rich["aibom_fairnessAssessmentHarms"] == [{"type": "DictionaryEntry", "key": "Elderly users", "value": "Recognition errors"}]
    assert rich["aibom_ethicalConsiderationsMitigationStrategy"] == [{"type": "DictionaryEntry", "key": "Misclassification", "value": "Route to an agent"}]
    # 3.0.1: 같은 값이 확장에 CycloneDX 경로 이름으로
    ext = dict(ext_of(plain))                                                  # properties 키 페이지의 키 그대로
    assert ext["aibom:model:task"] == "text-classification" and ext["aibom:model:parameterCount"] == "110000000"
    assert ext["aibom:model:inputs:0:format"] == "text" and ext["aibom:model:inputs:0:maxSize"] == "512" and ext["aibom:model:outputs:0:format"] == "label"
    assert ext["aibom:model:performanceMetrics:1:slice"] == "elderly-speakers" and ext["aibom:model:designChoices:0"] == "Single classification head"
    assert ext["aibom:model:fairnessAssessments:0:groupAtRisk"] == "Elderly users" and ext["aibom:model:fairnessAssessments:0:harms"] == "Recognition errors"
    assert ext["aibom:model:ethicalConsiderations:0:name"] == "Misclassification" and ext["aibom:model:ethicalConsiderations:0:mitigationStrategy"] == "Route to an agent"
    assert "aibom_task" not in plain and "modelCard.modelParameters.task" not in ext and "modelCard.modelParameters.parameterCount" not in ext
    # 두 spec 모두 자리가 없는 값: 공정성 완화 전략, 신뢰구간, 이름뿐인 데이터셋 항목
    for el in (plain, rich):
        ext = ext_of(el)
        assert ("modelCard.considerations.fairnessAssessments", json.dumps({"groupAtRisk": "Elderly users", "mitigationStrategy": "Add elderly speaker data"})) in ext
        assert ("modelCard.quantitativeAnalysis.performanceMetrics", json.dumps({"type": "accuracy", "confidenceInterval": {"lowerBound": "0.79", "upperBound": "0.83"}})) in ext
        assert ("modelCard.modelParameters.datasets.name", "inline-only") in ext
        assert ("bom-ref", BERT) in ext and ("group", "acme") in ext and ("tags", "ai") in ext and ("evidence.occurrences.location", "src/train.py#L4") in ext


def test_dataset_fields_split_between_standard_properties_and_the_spec():
    plain = graph_of(convert_spdx(doc_of(), "3.0.1", log=lambda m: None))
    rich = graph_of(convert_spdx(doc_of(), "v0.6", log=lambda m: None))
    for g in (plain, rich):
        el = g[sid(REVIEWS)]
        assert (el["dataset_datasetType"], el["dataset_datasetSize"], el["dataset_datasetAvailability"]) == (["text"], 750000, "directDownload")
        assert (el["dataset_intendedUse"], el["dataset_dataCollectionProcess"]) == ("text-classification", "annotations crowdsourced")
        assert el["software_sourceInfo"] == "https://huggingface.co/datasets/acme/reviews; https://huggingface.co/datasets/acme/raw-reviews"
        assert el["software_downloadLocation"] == "https://huggingface.co/datasets/acme/reviews"
        assert el["dataset_dataPreprocessing"] == ["Deduplication"] and el["dataset_knownBias"] == ["Few elderly speakers"]
        assert el["dataset_datasetNoise"].startswith("About 3%") and el["dataset_anonymizationMethodUsed"] == ["Name and phone number masking"]
        assert el["dataset_datasetUpdateMechanism"] == "Quarterly additions" and el["dataset_hasSensitivePersonalInformation"] == "yes"
        ext = ext_of(el)
        assert ("data.classification", "internal") in ext and ("data.sensitiveData", "Speaker voice recordings") in ext and ("data.name", "acme/reviews") in ext
        local = g[sid(LOCAL)]
        assert local["dataset_datasetType"] == ["noAssertion"] and local["dataset_datasetSize"] == 8404          # modality 가 없으면 noAssertion (필수 속성)
        assert [v for k, v in ext_of(local) if k == "data.name"] == ["data/train.csv", "data/images/train/*.png"]
    rich_el = rich[sid(REVIEWS)]
    assert rich_el["aibom_statistics"] == [{"type": "DictionaryEntry", "key": "train:label:n_unique", "value": "2"},
                                           {"type": "DictionaryEntry", "key": "train:text:length:mean", "value": "140.5"}]
    assert rich_el["aibom_knownBiasDetectionMethod"] == [{"type": "DictionaryEntry", "key": "Few elderly speakers", "value": "Sample count by age group"}]
    assert rich_el["aibom_knownGaps"] == ["Few dialect samples"] and rich_el["aibom_originalCollectionPurpose"] == "Service quality review"
    plain_ext = dict(ext_of(plain[sid(REVIEWS)]))
    assert (plain_ext["aibom:dataset:statistics:0:type"], plain_ext["aibom:dataset:statistics:0:value"]) == ("train:label:n_unique", "2")
    assert plain_ext["aibom:dataset:knownBias:0:detectionMethod"] == "Sample count by age group" and plain_ext["aibom:dataset:knownGaps:0:name"] == "Few dialect samples"
    assert plain_ext["aibom:dataset:originalCollectionPurpose"] == "Service quality review" and "aibom_statistics" not in plain[sid(REVIEWS)]


def test_relationships_cover_dependencies_lineage_and_licenses():
    logs: list[str] = []
    out = convert_spdx(doc_of(), "3.0.1", log=logs.append)
    g = graph_of(out)
    depends = rels(out, "dependsOn")
    assert set(depends[sid(ROOT)]) == {sid(x) for x in (LIB, FILE, OS_REF, BERT, LOCAL, APT)}            # 없는 대상은 뺀다
    assert depends[sid(BERT)] == [sid(REVIEWS)] and depends[sid(SERVICE)] == [sid(BERT)]
    assert sorted(logs) == ["[spdx] dependency of unknown element skipped: urn:nowhere",
                            f"[spdx] dependency on unknown element skipped: {ROOT} -> pkg:pypi/gone@1.0"]
    # 계보: 조상·변형은 요소가 되고 관계로 잇는다. notes 는 그 관계의 comment
    base = g[sid("pkg:huggingface/acme/acme-base")]
    assert base["type"] == "ai_AIPackage" and base["name"] == "acme-base" and base["software_packageUrl"] == "pkg:huggingface/acme/acme-base"
    descendant = next(r for r in by_type(out, "Relationship") if r["relationshipType"] == "descendantOf" and r["from"] == sid(BERT))
    assert (descendant["to"], descendant["comment"]) == ([base["spdxId"]], "Hugging Face relation: finetune")
    assert rels(out, "hasVariant")[sid(BERT)] == [sid("pkg:huggingface/acme/acme-bert-int8")]
    image = g[rels(out, "descendantOf")[sid(ROOT)][0]]
    assert image["type"] == "software_Package" and image["name"] == "docker.io/library/debian:12-slim" and image["verifiedUsing"][0]["algorithm"] == "sha256"
    # 라이선스: 식과 SPDX id 는 그대로, 이름뿐인 것은 LicenseRef 와 url. acknowledgement concluded 는 hasConcludedLicense
    declared, concluded = rels(out, "hasDeclaredLicense"), rels(out, "hasConcludedLicense")
    assert g[declared[sid(ROOT)][0]]["simplelicensing_licenseExpression"] == "Apache-2.0 OR MIT"
    assert g[declared[sid(LIB)][0]]["simplelicensing_licenseExpression"] == "Apache-2.0" and g[declared[sid(REVIEWS)][0]]["simplelicensing_licenseExpression"] == "CC-BY-4.0"
    custom = g[concluded[sid(BERT)][0]]
    assert custom["simplelicensing_licenseExpression"] == "LicenseRef-Acme-Model-License" and custom["name"] == "Acme Model License"
    assert custom["simplelicensing_customIdToUri"] == [{"type": "DictionaryEntry", "key": "LicenseRef-Acme-Model-License", "value": "https://acme.example/licenses/model"}]
    # 문서: 루트와 요소 목록
    document = by_type(out, "SpdxDocument")[0]
    assert document["rootElement"] == [sid(ROOT)] and document["name"] == "acme-app:1.4.0"
    assert set(document["element"]) == {e["spdxId"] for e in out["@graph"] if "spdxId" in e and e["type"] != "SpdxDocument"}
    assert ("metadata.lifecycles.phase", "post-build") in ext_of(document)
    creation = next(e for e in out["@graph"] if e["type"] == "CreationInfo")
    assert creation["created"] == "2026-10-20T00:00:00Z" and g[creation["createdBy"][0]] == {
        "type": "SoftwareAgent", "spdxId": sid("agent/sure-aibom"), "creationInfo": sid("creationinfo"), "name": "sure-aibom"}
    tools = [g[t] for t in creation["createdUsing"]]
    assert [(t["name"], t.get("comment")) for t in tools] == [("syft", "version 1.52.0"), ("cdxgen", "version 12.8.4"), ("sure-aibom", "version 0.2.0")]
    assert tools[1]["externalIdentifier"][0]["identifier"] == "pkg:npm/%40cyclonedx/cdxgen@12.8.4"


def test_facts_add_training_and_evaluation_relationships_and_times():
    """수집 단계의 메모리 부가 기록(facts): 데이터셋 역할은 trainedOn·testedOn 관계가 되고 dependsOn 은 그대로 남으며, 시각은
    builtTime·releaseTime 이 된다. 문서에 없는 요소의 역할은 알리고 건너뛴다. 결과는 두 스키마를 통과한다."""
    facts = Facts()
    facts.add_role(BERT, REVIEWS, "training")
    facts.add_role(BERT, REVIEWS, "evaluation")
    facts.add_role(BERT, LOCAL, "evaluation")
    facts.add_role("pkg:huggingface/acme/gone", REVIEWS, "training")
    facts.set_time(ROOT, "builtTime", "2026-10-01T00:00:00Z")
    facts.set_time(BERT, "releaseTime", "2024-02-19T11:06:12.000Z")
    facts.set_time(REVIEWS, "releaseTime", "2024-01-04T21:09:45+09:00")
    logs: list[str] = []
    out = convert_spdx(doc_of(), "3.0.1", log=logs.append, facts=facts)
    g = graph_of(out)
    assert rels(out, "trainedOn") == {sid(BERT): [sid(REVIEWS)]} and rels(out, "testedOn") == {sid(BERT): [sid(REVIEWS), sid(LOCAL)]}
    assert rels(out, "dependsOn")[sid(BERT)] == [sid(REVIEWS)]                      # dependsOn 은 그대로 (CycloneDX 와 같게)
    assert g[sid(ROOT)]["builtTime"] == "2026-10-01T00:00:00Z" and g[sid(BERT)]["releaseTime"] == "2024-02-19T11:06:12Z"
    assert g[sid(REVIEWS)]["releaseTime"] == "2024-01-04T12:09:45Z" and not any("Time" in k for k in g[sid(LIB)])
    assert f"[spdx] dataset role of unknown element skipped: pkg:huggingface/acme/gone -> {REVIEWS}" in logs
    assert _validate_spdx(out, "3.0.1", log=print) and _validate_spdx(convert_spdx(doc_of(), "v0.6", log=lambda m: None, facts=facts), "v0.6", log=print)
    plain = convert_spdx(doc_of(), "3.0.1", log=lambda m: None)                             # facts 가 없으면 아무것도 더하지 않는다
    assert not rels(plain, "trainedOn") and not rels(plain, "testedOn") and "builtTime" not in graph_of(plain)[sid(ROOT)]


def test_ids_come_from_the_serial_number_and_bom_refs_and_the_output_is_deterministic():
    doc = doc_of()
    doc["components"].append({"type": "machine-learning-model", "bom-ref": "pkg:generic/Acme/Acme%20Tiny%20Chat@v1.0", "name": "Acme Tiny Chat"})
    once, twice = convert_spdx(doc, "v0.6", log=lambda m: None), convert_spdx(copy.deepcopy(doc), "v0.6", log=lambda m: None)
    assert once == twice
    ids = {e["spdxId"] for e in once["@graph"] if "spdxId" in e}
    assert sid("pkg:generic/Acme/Acme%2520Tiny%2520Chat@v1.0") in ids                 # % 는 퍼센트 인코딩, : / @ 는 그대로
    assert sid("rel/dependsOn/" + ROOT) in ids and all(e.startswith(NS + "#") for e in ids)
    without_serial = convert_spdx({k: v for k, v in doc.items() if k != "serialNumber"}, "v0.6", log=lambda m: None)
    assert all(e["spdxId"].startswith("urn:uuid:") for e in without_serial["@graph"] if "spdxId" in e)
    assert _validate_spdx(once, "v0.6", log=print)


def test_the_input_document_is_left_untouched():
    doc = doc_of()
    before = json.dumps(doc, sort_keys=True)
    convert_spdx(doc, "3.0.1", log=lambda m: None)
    convert_spdx(doc, "v0.6", log=lambda m: None)
    assert json.dumps(doc, sort_keys=True) == before


def test_convert_rejects_an_unknown_spec():
    with pytest.raises(ValueError):
        convert_spdx(doc_of(), "2.3")


def test_validate_detects_the_format_and_refuses_a_spec_of_the_other_format():
    cdx, spdx = doc_of(), convert_spdx(doc_of(), "3.0.1", log=lambda m: None)
    assert (detect_format(cdx), detect_format(spdx), detect_format({"x": 1})) == ("cyclonedx", "spdx", None)
    assert schema_for("cyclonedx", "3.0.1") is None and schema_for("spdx", "1.7") is None
    assert schema_for("cyclonedx", "v0.6") is not None and schema_for("spdx", "v0.6") is not None
    assert validate_doc(spdx, "spdx", "3.0.1", log=print)
    with pytest.raises(ValueError):
        validate_doc(spdx, "spdx", "1.7")
    broken = copy.deepcopy(spdx)
    broken["@graph"][2]["bogus"] = 1
    broken["@graph"].append({"type": "Nope", "spdxId": "x:y"})
    messages: list[str] = []
    assert not _validate_spdx(broken, "3.0.1", log=messages.append)
    assert any("bogus" in m for m in messages) and any("'Nope' is not an SPDX class" in m for m in messages)
