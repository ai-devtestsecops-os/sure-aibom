"""tests/fixtures/mixed 를 실제 syft·cdxgen 으로 스캔해 병합 결과를 확인한다.
두 도구가 없으면 건너뛴다. owasp 보강은 네트워크가 필요해 --no-enrich 로 뺀다."""
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


def test_mixed_fixture_yields_all_three_domains(tmp_path):
    cdx = tmp_path / "bom.cdx.json"
    spdx = tmp_path / "bom.spdx.json"
    rc = main(["scan", str(FIXTURE), "--cdx", str(cdx), "--spdx", str(spdx), "--no-enrich", "--strict"])
    assert rc == 0

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
