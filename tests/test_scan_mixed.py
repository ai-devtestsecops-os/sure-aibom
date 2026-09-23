"""tests/fixtures/mixed 를 실제 syft·cdxgen 으로 스캔해 병합 결과를 확인한다.
두 도구가 없으면 건너뛴다. owasp 보강은 네트워크가 필요해 AIBOM_OFFLINE=1 로 뺀다 — regulation 은 cdxgen 의
cdx:ai:runtime / cdx:ai:contextWindow 만으로 technicalRequirements 와 inputs[0].maxSize 를 채운다."""
import json
import os
import shutil
from pathlib import Path

import pytest

from aibom_cli.cli import main
from aibom_cli.spdx import cdx_to_spdx
from aibom_cli.validate import validate_spdx

FIXTURE = Path(__file__).parent / "fixtures" / "mixed"


def _cdxgen_available() -> bool:
    b = os.environ.get("CDXGEN_BIN")
    return bool(shutil.which("cdxgen") or (b and Path(b).exists()))


pytestmark = pytest.mark.skipif(
    not (shutil.which(os.environ.get("SYFT_BIN", "syft")) and _cdxgen_available()),
    reason="syft 와 cdxgen 이 모두 있어야 한다",
)


def test_mixed_fixture_yields_all_three_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("AIBOM_OFFLINE", "1")                                # 보강은 네트워크가 필요해 강제 생략
    cdx = tmp_path / "bom.cdx.json"
    spdx = tmp_path / "bom.spdx.json"
    assert main(["scan", str(FIXTURE), "-o", str(cdx)]) == 0                       # 기본 --form properties
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 0
    # 변환기는 CLI 에 아직 노출하지 않으므로 함수를 직접 부른다
    doc0 = json.loads(cdx.read_text())
    spdx.write_text(json.dumps(cdx_to_spdx(doc0, log=lambda m: None), ensure_ascii=False, indent=2) + "\n")
    assert validate_spdx(json.loads(spdx.read_text()), log=print)      # SPDX 검증은 CLI 미노출, 함수로

    doc = json.loads(cdx.read_text())
    by_type = {}
    for c in doc["components"]:
        by_type.setdefault(c["type"], set()).add(c["name"])

    assert {"numpy", "requests"} <= by_type["library"]                      # syft → 소프트웨어
    assert "bert-base-uncased" in by_type["machine-learning-model"]         # cdxgen → HF 모델
    assert "llama3.2:1b" in by_type["machine-learning-model"]               # cdxgen → Modelfile
    assert "bookcorpus" in by_type["data"]                                  # cdxgen → 데이터셋
    assert "fixture" not in by_type.get("application", set())               # package.json 은 -t ai 가 막는다

    # 파일 컴포넌트 이름에 스캔 머신 경로가 새지 않는다
    assert all(not n.startswith(str(FIXTURE)) for n in by_type.get("file", set()))

    bert = next(c for c in doc["components"] if c["name"] == "bert-base-uncased")
    card = {p["name"]: p["value"] for p in bert["modelCard"]["properties"]}
    assert card["aibom:model:technicalRequirements:0"] == "transformers" and card["aibom:model:inputs:0:maxSize"] == "512"
    assert "cdx:ai:runtime" not in {p["name"] for p in bert["properties"]}       # 승격한 원본은 소비된다

    refs = {c["bom-ref"] for c in doc["components"]}
    assert len(refs) == len(doc["components"])                              # bom-ref 중복 없음
    assert {t["name"] for t in doc["metadata"]["tools"]["components"]} >= {"syft", "cdxgen", "aibom-cli"}

    assert doc["metadata"]["component"] == {"type": "application", "name": "mixed", "bom-ref": "application:/mixed@"}

    spdx_doc = json.loads(spdx.read_text())
    types = {e["type"] for e in spdx_doc["@graph"]}
    assert {"SpdxDocument", "software_Sbom", "CreationInfo", "SoftwareAgent", "Tool", "software_Package", "software_File",
            "ai_AIPackage", "dataset_DatasetPackage", "simplelicensing_LicenseExpression", "Relationship"} <= types
    assert {r["relationshipType"] for r in spdx_doc["@graph"] if r["type"] == "Relationship"} >= {"trainedOn", "hasDeclaredLicense", "dependsOn"}
    assert validate_spdx(spdx_doc, log=print)
    root = next(n for n in spdx_doc["@graph"] if n["type"] == "software_Sbom")["rootElement"]
    assert root == [f"{doc['serialNumber']}#SPDXRef-application-mixed"]
    # 같은 CycloneDX 를 다시 변환하면 바이트 단위로 같다
    again = json.dumps(cdx_to_spdx(doc, log=lambda m: None), ensure_ascii=False, indent=2) + "\n"
    assert again == spdx.read_text()


def test_typed_form_scan_validates_against_v06_only(tmp_path, monkeypatch):
    monkeypatch.setenv("AIBOM_OFFLINE", "1")
    cdx = tmp_path / "typed.cdx.json"
    assert main(["scan", str(FIXTURE), "--form", "typed", "-o", str(cdx)]) == 0
    assert main(["validate", str(cdx), "--spec", "v0.6"]) == 0
    assert main(["validate", str(cdx), "--spec", "1.7"]) == 3                      # maxSize·technicalRequirements 는 공식 1.7 에 없다
    doc = json.loads(cdx.read_text())
    bert = next(c for c in doc["components"] if c["name"] == "bert-base-uncased")
    assert bert["modelCard"]["considerations"]["technicalRequirements"] == ["transformers"]
    assert bert["modelCard"]["modelParameters"]["inputs"][0]["maxSize"] == "512"
    assert not any(p["name"].startswith("aibom:model:") for p in bert["modelCard"].get("properties", []))
