"""CycloneDX 어휘 → SPDX 3.0.1 어휘 대응표. 코드가 아니라 데이터로 둔다.

출처: data/cdx_spdx_mapping.json 의 vocab 행 + spdx_spec mapping 행. 스키마 enum 에 없는 값은 넣지 않는다.
"""
from __future__ import annotations

CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"
SPEC_VERSION = "3.0.1"
CREATION_INFO_ID = "_:creationinfo"

# component.type → software_primaryPurpose. cryptographic-asset 는 enum 에 없어 other + aibom:cdx:type.
PURPOSE_BY_TYPE: dict[str, str] = {
    "application": "application",
    "framework": "framework",
    "library": "library",
    "container": "container",
    "platform": "platform",
    "operating-system": "operatingSystem",
    "device": "device",
    "device-driver": "deviceDriver",
    "firmware": "firmware",
    "file": "file",
    "machine-learning-model": "model",
    "data": "data",
    "cryptographic-asset": "other",
}

# component.type → SPDX 클래스. modelCard 가 있으면 타입과 무관하게 ai_AIPackage (mapping 60).
CLASS_BY_TYPE: dict[str, str] = {
    "machine-learning-model": "ai_AIPackage",
    "data": "dataset_DatasetPackage",
    "file": "software_File",
}
PACKAGE_CLASSES = frozenset({"software_Package", "ai_AIPackage", "dataset_DatasetPackage"})

# componentData.type → software_File 의 primaryPurpose (dataset 은 DatasetPackage 로 간다).
DATA_FILE_PURPOSE: dict[str, str] = {
    "source-code": "source",
    "configuration": "configuration",
    "definition": "specification",
    "other": "other",
}

# hash.alg → HashAlgorithm. 없는 값(Streebog 등)은 other + comment.
HASH_ALGORITHM: dict[str, str] = {
    "MD5": "md5",
    "SHA-1": "sha1",
    "SHA-256": "sha256",
    "SHA-384": "sha384",
    "SHA-512": "sha512",
    "SHA3-256": "sha3_256",
    "SHA3-384": "sha3_384",
    "SHA3-512": "sha3_512",
    "BLAKE2b-256": "blake2b256",
    "BLAKE2b-384": "blake2b384",
    "BLAKE2b-512": "blake2b512",
    "BLAKE3": "blake3",
}

# externalReference.type → ExternalRefType. 없는 값은 other + comment "aibom:cdx:externalReference:type=…".
EXTERNAL_REF_TYPE: dict[str, str] = {
    "website": "altWebPage",
    "distribution": "altDownloadLocation",
    "source-distribution": "sourceArtifact",
    "vcs": "vcs",
    "issue-tracker": "issueTracker",
    "documentation": "documentation",
    "mailing-list": "mailingList",
    "social": "socialMedia",
    "chat": "chat",
    "support": "support",
    "license": "license",
    "build-meta": "buildMeta",
    "build-system": "buildSystem",
    "release-notes": "releaseNotes",
    "advisories": "securityAdvisory",
    "attestation": "secureSoftwareAttestation",
    "threat-model": "securityThreatModel",
    "adversary-model": "securityAdversaryModel",
    "risk-assessment": "riskAssessment",
    "vulnerability-assertion": "vulnerabilityDisclosureReport",
    "exploitability-statement": "vulnerabilityExploitabilityAssessment",
    "pentest-report": "securityPenTestReport",
    "static-analysis-report": "staticAnalysisReport",
    "dynamic-analysis-report": "dynamicAnalysisReport",
    "runtime-analysis-report": "runtimeAnalysisReport",
    "component-analysis-report": "componentAnalysisReport",
    "maturity-report": "qualityAssessmentReport",
    "certification-report": "certificationReport",
    "quality-metrics": "metrics",
    "security-contact": "securityPolicy",
    "other": "other",
}

# metadata.lifecycles[].phase → software_sbomType. discovery/decommission 은 확장으로.
SBOM_TYPE_BY_PHASE: dict[str, str] = {
    "design": "design",
    "pre-build": "source",
    "build": "build",
    "post-build": "analyzed",
    "operations": "deployed",
}

# energyConsumption.activity → ai_EnergyConsumption 의 슬롯. 나머지 활동은 확장으로.
ENERGY_SLOT_BY_ACTIVITY: dict[str, str] = {
    "training": "ai_trainingEnergyConsumption",
    "fine-tuning": "ai_finetuningEnergyConsumption",
    "inference": "ai_inferenceEnergyConsumption",
}
ENERGY_UNIT: dict[str, str] = {"kWh": "kilowattHour"}

# 닫힌 enum — 라우터가 값을 검사할 때 쓴다.
DATASET_TYPES = frozenset({
    "audio", "categorical", "graph", "image", "noAssertion", "numeric", "other", "sensor",
    "structured", "syntactic", "text", "timeseries", "timestamp", "video",
})
CONFIDENTIALITY: dict[str, str] = {
    "amber": "amber", "clear": "clear", "green": "green", "red": "red",
    "white": "clear", "amber+strict": "amber", "amber_and_strict": "amber",
}
AVAILABILITY: dict[str, str] = {
    "direct-download": "directDownload", "directdownload": "directDownload",
    "scraping-script": "scrapingScript", "scrapingscript": "scrapingScript",
    "clickthrough": "clickthrough", "query": "query", "registration": "registration",
}
PRESENCE: dict[str, str] = {"yes": "yes", "no": "no", "unknown": "noAssertion", "noassertion": "noAssertion"}
SAFETY_RISK = frozenset({"serious", "high", "medium", "low"})
TESTED_ON_MARKERS = frozenset({"test", "testing", "evaluation", "validation"})

# 관계 종류의 @graph 출력 순서 (spec + critique 의 hasDynamicLink 슬롯).
RELATIONSHIP_ORDER: tuple[str, ...] = (
    "contains", "hasOptionalComponent", "hasDynamicLink",
    "dependsOn", "hasOptionalDependency", "hasSpecification",
    "trainedOn", "testedOn", "hasDataFile",
    "descendantOf", "ancestorOf", "hasVariant",
    "hasDeclaredLicense", "hasConcludedLicense", "publishedBy",
    "hasEvidence", "usesTool", "hasInput", "hasOutput",
)
# Sbom.rootElement 계산 시 "누군가의 to 에 등장하면 루트가 아니다" 로 보는 관계 종류.
NON_ROOT_RELATIONSHIPS = frozenset({
    "contains", "hasOptionalComponent", "hasDynamicLink", "dependsOn", "hasOptionalDependency",
    "hasDataFile", "trainedOn", "testedOn", "descendantOf",
})
PROFILE_ORDER: tuple[str, ...] = ("core", "software", "ai", "dataset", "build", "simpleLicensing", "expandedLicensing", "extension")

# 노드의 키 출력 순서. 여기 없는 키(aibom_* 등)는 뒤에 알파벳순, extension 은 항상 마지막 (결정적 직렬화).
KEY_ORDER: tuple[str, ...] = (
    "type", "@id", "spdxId", "creationInfo", "specVersion", "created", "createdBy", "createdUsing",
    "name", "summary", "description", "comment",
    "verifiedUsing", "externalRef", "externalIdentifier",
    "originatedBy", "suppliedBy", "releaseTime",
    "profileConformance", "rootElement", "element", "dataLicense", "import", "software_sbomType",
    "from", "relationshipType", "to", "completeness",
    "software_primaryPurpose", "software_copyrightText", "software_packageVersion",
    "software_downloadLocation", "software_homePage", "software_packageUrl",
    "contentType", "software_fileKind",
    "simplelicensing_licenseExpression", "simplelicensing_customIdToUri", "simplelicensing_licenseText",
    "ai_typeOfModel", "ai_hyperparameter", "ai_metric", "ai_metricDecisionThreshold", "ai_limitation",
    "ai_informationAboutApplication", "ai_informationAboutTraining", "ai_safetyRiskAssessment",
    "ai_useSensitivePersonalInformation", "ai_modelExplainability", "ai_energyConsumption",
    "dataset_datasetType", "dataset_datasetSize", "dataset_intendedUse", "dataset_knownBias",
    "dataset_hasSensitivePersonalInformation", "dataset_confidentialityLevel",
    "dataset_anonymizationMethodUsed", "dataset_dataCollectionProcess", "dataset_dataPreprocessing",
    "dataset_datasetAvailability", "dataset_datasetNoise", "dataset_datasetUpdateMechanism",
)

# aibom:cdx:* 확장 항목의 앞순서. 나머지는 경로 알파벳순(숫자 구간은 수치 비교).
FIXED_ENTRY_PRIORITY: tuple[str, ...] = ("bom-ref", "group", "scope", "version", "type", "kind", "tags")

# ---------------------------------------------------------------------------
# aibom:* (properties.md 어휘) → 타입 있는 속성.  properties_handling 의 TYPED ROUTER 를 표로 옮겼다.
# 스칼라: 이름 전체가 키. 종류: str | int | presence | risk | availability
AIBOM_SCALAR: dict[str, tuple[str, str]] = {
    "aibom:model:task": ("aibom_task", "str"),
    "aibom:model:architectureFamily": ("aibom_architectureFamily", "str"),
    "aibom:model:modelArchitecture": ("aibom_modelArchitecture", "str"),
    "aibom:model:parameterCount": ("aibom_parameterCount", "int"),
    "aibom:model:optimizationTarget": ("aibom_optimizationTarget", "str"),
    "aibom:model:trainingCompute": ("aibom_trainingCompute", "str"),
    "aibom:model:trainingTime": ("aibom_trainingTime", "str"),
    "aibom:model:sensitivePersonalInformation": ("ai_useSensitivePersonalInformation", "presence"),
    "aibom:model:safetyRiskAssessment": ("ai_safetyRiskAssessment", "risk"),
    "aibom:dataset:originalCollectionPurpose": ("aibom_originalCollectionPurpose", "str"),
    "aibom:dataset:availability": ("dataset_datasetAvailability", "availability"),
    "aibom:dataset:collectionProcess": ("dataset_dataCollectionProcess", "str"),
    "aibom:dataset:noise": ("dataset_datasetNoise", "str"),
    "aibom:dataset:size": ("dataset_datasetSize", "int"),
    "aibom:dataset:updateMechanism": ("dataset_datasetUpdateMechanism", "str"),
    "aibom:dataset:intendedUse": ("dataset_intendedUse", "str"),
    "aibom:dataset:sensitiveData": ("dataset_hasSensitivePersonalInformation", "presence"),
}
# 인덱스형: "<prefix>:<i>[:<leaf>]". leaf None 은 값 자체.
#   ("list", prop)              → 문자열 배열에 추가
#   ("enumlist", prop, allowed) → 허용값일 때만 추가
#   ("dict", prop, key_leaf)    → DictionaryEntry(key=같은 인덱스의 key_leaf 값, value=값)
#   ("key",)                    → dict 항목의 키로만 쓰이고 자체 슬롯은 없다
#   ("usage",)                  → trainedOn/testedOn 스위치 (관계 단계에서 소비)
AIBOM_INDEXED: dict[str, dict[str | None, tuple]] = {
    "aibom:model:inputs": {"format": ("list", "aibom_inputs"), "maxSize": ("dict", "aibom_inputMaxSize", "format")},
    "aibom:model:outputs": {"format": ("list", "aibom_outputs"), "maxSize": ("dict", "aibom_outputMaxSize", "format")},
    "aibom:model:designChoices": {None: ("list", "aibom_designChoices")},
    "aibom:model:hyperparameters": {"name": ("key",), "value": ("dict", "ai_hyperparameter", "name")},
    "aibom:model:performanceMetrics": {
        "type": ("key",),
        "value": ("dict", "ai_metric", "type"),
        "slice": ("dict", "aibom_metricSlice", "type"),
        "decisionThreshold": ("dict", "ai_metricDecisionThreshold", "type"),
    },
    "aibom:model:explainabilityMethods": {None: ("list", "ai_modelExplainability")},
    "aibom:model:users": {None: ("list", "aibom_users")},
    "aibom:model:useCases": {None: ("list", "aibom_useCases")},
    "aibom:model:ethicalConsiderations": {
        "name": ("list", "aibom_ethicalConsiderations"),
        "mitigationStrategy": ("dict", "aibom_ethicalConsiderationsMitigationStrategy", "name"),
    },
    "aibom:model:fairnessAssessments": {
        "groupAtRisk": ("list", "aibom_fairnessAssessments"),
        "benefits": ("dict", "aibom_fairnessAssessmentBenefits", "groupAtRisk"),
        "harms": ("dict", "aibom_fairnessAssessmentHarms", "groupAtRisk"),
    },
    "aibom:model:limitationIdentificationMethods": {None: ("list", "aibom_limitationIdentificationMethods")},
    "aibom:model:datasets": {"usage": ("usage",)},
    "aibom:dataset:designChoices": {None: ("list", "aibom_designChoices")},
    "aibom:dataset:representationAssumptions": {None: ("list", "aibom_representationAssumptions")},
    "aibom:dataset:knownBias": {
        "name": ("list", "dataset_knownBias"),
        "detectionMethod": ("dict", "aibom_knownBiasDetectionMethod", "name"),
        "mitigationStrategy": ("dict", "aibom_knownBiasMitigationStrategy", "name"),
    },
    "aibom:dataset:knownGaps": {
        "name": ("list", "aibom_knownGaps"),
        "mitigationStrategy": ("dict", "aibom_knownGapsMitigationStrategy", "name"),
    },
    "aibom:dataset:statistics": {"type": ("key",), "value": ("dict", "aibom_statistics", "type")},
    "aibom:dataset:preprocessing": {None: ("list", "dataset_dataPreprocessing")},
    "aibom:dataset:anonymizationMethods": {None: ("list", "dataset_anonymizationMethodUsed")},
    "aibom:dataset:modality": {None: ("enumlist", "dataset_datasetType", DATASET_TYPES)},
}

# aibom:<prefix>:* 항목이 타입 있는 슬롯으로 갈 수 있는 원소 종류. 다른 종류에서는 원문으로 남긴다
# (v0.6 스키마는 aibom_*/dataset_* 를 그 클래스에만 정의하므로 다른 클래스에 쓰면 두 스키마 모두 거부한다).
AIBOM_CLASS_BY_PREFIX: dict[str, str] = {"aibom:model": "ai_AIPackage", "aibom:dataset": "dataset_DatasetPackage"}

# ---------------------------------------------------------------------------
# aibom-v0.6 CycloneDX 의 타입 있는 JSON 필드 → SPDX 슬롯 (properties[] 철자가 아니라 필드 그대로 온 값).
# 스칼라: 필드 → (속성, 종류). 목록: 필드 → 속성 (enumlist 는 (속성, 허용값)).
# 사전형: 필드 → (키 leaf, 키 목록 속성 | None, {leaf: DictionaryEntry 속성}).
DATA_SCALAR: dict[str, tuple[str, str]] = {
    "size": ("dataset_datasetSize", "int"),
    "intendedUse": ("dataset_intendedUse", "str"),
    "collectionProcess": ("dataset_dataCollectionProcess", "str"),
    "noise": ("dataset_datasetNoise", "str"),
    "updateMechanism": ("dataset_datasetUpdateMechanism", "str"),
    "originalCollectionPurpose": ("aibom_originalCollectionPurpose", "str"),
}
DATA_LIST: dict[str, tuple] = {
    "modality": ("dataset_datasetType", DATASET_TYPES),
    "anonymizationMethods": ("dataset_anonymizationMethodUsed",),
    "preprocessing": ("dataset_dataPreprocessing",),
    "designChoices": ("aibom_designChoices",),
    "representationAssumptions": ("aibom_representationAssumptions",),
}
DATA_DICT: dict[str, tuple] = {
    "knownBias": ("name", "dataset_knownBias", {"detectionMethod": "aibom_knownBiasDetectionMethod",
                                                "mitigationStrategy": "aibom_knownBiasMitigationStrategy"}),
    "knownGaps": ("name", "aibom_knownGaps", {"mitigationStrategy": "aibom_knownGapsMitigationStrategy"}),
    "statistics": ("type", None, {"value": "aibom_statistics"}),
}
# provenance 는 SPDX 슬롯이 없어 aibom:cdx:data:<i>:provenance:<j> 로만 남는다.
DATA_EXT_ONLY: tuple[str, ...] = ("provenance",)

MODEL_PARAM_SCALAR: dict[str, tuple[str, str]] = {
    "task": ("aibom_task", "str"),
    "architectureFamily": ("aibom_architectureFamily", "str"),
    "modelArchitecture": ("aibom_modelArchitecture", "str"),
    "parameterCount": ("aibom_parameterCount", "int"),
    "trainingCompute": ("aibom_trainingCompute", "str"),
    "trainingTime": ("aibom_trainingTime", "str"),
    "optimizationTarget": ("aibom_optimizationTarget", "str"),
}
MODEL_PARAM_LIST: dict[str, tuple] = {"designChoices": ("aibom_designChoices",)}
MODEL_PARAM_EXT_ONLY: tuple[str, ...] = ("trainingTechniques",)
CONSIDERATION_SCALAR: dict[str, tuple[str, str]] = {
    "safetyRiskAssessment": ("ai_safetyRiskAssessment", "risk"),
    "sensitivePersonalInformation": ("ai_useSensitivePersonalInformation", "presence"),
}
CONSIDERATION_LIST: dict[str, tuple] = {
    "explainabilityMethods": ("ai_modelExplainability",),
    "limitationIdentificationMethods": ("aibom_limitationIdentificationMethods",),
}
CONSIDERATION_EXT_ONLY: tuple[str, ...] = ("technicalRequirements",)

# strict 모드: v0.6 전용 aibom_* 속성 → properties.md 키 (확장 항목 이름). {ns} 는 원소 종류로 정한다.
#   ("scalar", template) | ("list", template) | ("dict", template, list_prop) | ("kv", template)
STRICT_KEYS: dict[str, tuple] = {
    "aibom_task": ("scalar", "aibom:model:task"),
    "aibom_architectureFamily": ("scalar", "aibom:model:architectureFamily"),
    "aibom_modelArchitecture": ("scalar", "aibom:model:modelArchitecture"),
    "aibom_parameterCount": ("scalar", "aibom:model:parameterCount"),
    "aibom_optimizationTarget": ("scalar", "aibom:model:optimizationTarget"),
    "aibom_trainingCompute": ("scalar", "aibom:model:trainingCompute"),
    "aibom_trainingTime": ("scalar", "aibom:model:trainingTime"),
    "aibom_inputs": ("list", "aibom:model:inputs:{i}:format"),
    "aibom_inputMaxSize": ("dict", "aibom:model:inputs:{i}:maxSize", "aibom_inputs"),
    "aibom_outputs": ("list", "aibom:model:outputs:{i}:format"),
    "aibom_outputMaxSize": ("dict", "aibom:model:outputs:{i}:maxSize", "aibom_outputs"),
    "aibom_designChoices": ("list", "aibom:{ns}:designChoices:{i}"),
    "aibom_users": ("list", "aibom:model:users:{i}"),
    "aibom_useCases": ("list", "aibom:model:useCases:{i}"),
    "aibom_ethicalConsiderations": ("list", "aibom:model:ethicalConsiderations:{i}:name"),
    "aibom_ethicalConsiderationsMitigationStrategy": ("dict", "aibom:model:ethicalConsiderations:{i}:mitigationStrategy", "aibom_ethicalConsiderations"),
    "aibom_fairnessAssessments": ("list", "aibom:model:fairnessAssessments:{i}:groupAtRisk"),
    "aibom_fairnessAssessmentBenefits": ("dict", "aibom:model:fairnessAssessments:{i}:benefits", "aibom_fairnessAssessments"),
    "aibom_fairnessAssessmentHarms": ("dict", "aibom:model:fairnessAssessments:{i}:harms", "aibom_fairnessAssessments"),
    "aibom_limitationIdentificationMethods": ("list", "aibom:model:limitationIdentificationMethods:{i}"),
    "aibom_metricSlice": ("dict", "aibom:model:performanceMetrics:{i}:slice", "ai_metric"),
    "aibom_originalCollectionPurpose": ("scalar", "aibom:dataset:originalCollectionPurpose"),
    "aibom_representationAssumptions": ("list", "aibom:dataset:representationAssumptions:{i}"),
    "aibom_knownBiasDetectionMethod": ("dict", "aibom:dataset:knownBias:{i}:detectionMethod", "dataset_knownBias"),
    "aibom_knownBiasMitigationStrategy": ("dict", "aibom:dataset:knownBias:{i}:mitigationStrategy", "dataset_knownBias"),
    "aibom_knownGaps": ("list", "aibom:dataset:knownGaps:{i}:name"),
    "aibom_knownGapsMitigationStrategy": ("dict", "aibom:dataset:knownGaps:{i}:mitigationStrategy", "aibom_knownGaps"),
    "aibom_statistics": ("kv", "aibom:dataset:statistics:{i}"),
}
# dict 형 strict 항목의 키가 참조 목록에 없을 때 키 자체를 적는 leaf 이름.
STRICT_KEY_LEAF: dict[str, str] = {
    "aibom_inputs": "format", "aibom_outputs": "format", "ai_metric": "type",
    "aibom_ethicalConsiderations": "name", "aibom_fairnessAssessments": "groupAtRisk",
    "dataset_knownBias": "name", "aibom_knownGaps": "name",
}
STRICT_NS_BY_CLASS: dict[str, str] = {"ai_AIPackage": "model", "dataset_DatasetPackage": "dataset"}
