"""fields 픽스처(tests/data/fields, make_fields.py 가 만든다)를 실제 syft·cdxgen 으로 두 번 스캔한다: project/ 디렉터리와,
rootfs/ 와 project/ 로 만든 이미지 tar (OCI 라벨 포함). 최종 BOM 의 값 하나하나가 어느 도구에서 왔는지 따라가(fieldtrace.py)
필드 탐색기의 도구 배지 데이터(docs/mapping-viewer/data/aibom_cli_sources.json, SPDX 트리는 aibom_cli_spdx_sources.json)와 맞춰 본다.
다르면 탐색기가 실제 출력과 어긋난 것이다 — AIBOM_UPDATE_SOURCES=1 로 이 테스트를 돌려 파일을 다시 쓰고 바뀐 자리를 확인한다.
허브 응답과 OWASP 출력은 tests/data/fields/{hf_api,owasp} 의 허구 녹화본으로 바꿔 끼운다. acme/acme-private 는 응답이 없는 비공개
저장소이고, 허브는 옛 이름 acmecorpus 를 acme/acmecorpus 로 돌려준다."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

import sure_aibom.external.hub as hub
import sure_aibom.engine.enrich as en
import fieldtrace
from sure_aibom.exceptions import RunnerError
from sure_aibom.engine.spdx import convert
from sure_aibom.engine.validate import validate_cdx, validate_spdx
from test_image import docker_tar

FIELDS = Path(__file__).parent / "data" / "fields"
PROJECT = FIELDS / "project"
SOURCES = Path(__file__).parents[1] / "docs" / "mapping-viewer" / "data" / "aibom_cli_sources.json"
SPDX_SOURCES = SOURCES.with_name("aibom_cli_spdx_sources.json")
OUT = Path(__file__).parents[1] / "out" / "test_fields"      # 스캔 결과를 남겨 둔다 (.gitignore 의 out/)
HUB_REDIRECTS = {"acmecorpus": "acme/acmecorpus"}
sys.path.insert(0, str(FIELDS))
import make_fields  # noqa: E402

pytestmark = pytest.mark.skipif(not (shutil.which("syft") and shutil.which("cdxgen")), reason="syft 와 cdxgen 이 모두 있어야 한다")


def recorded(kind: str, hf_id: str, *rest: str) -> dict | None:
    hf_id = HUB_REDIRECTS.get(hf_id, hf_id)
    path = FIELDS / "hf_api" / ("_".join(["hf", kind, hf_id.replace("/", "_"), *rest]) + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def recorded_owasp(hf_id: str, workdir) -> dict:
    path = FIELDS / "owasp" / (hf_id.rsplit("/", 1)[-1] + ".cdx.json")
    if not path.exists():
        raise RunnerError(f"no recorded aibom-generator output for {hf_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def tree_layer(src: Path, prefix: str) -> bytes:
    """폴더를 이미지 레이어 tar 로 (시각·소유자를 고정해 바이트가 늘 같다)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for path in sorted(src.rglob("*")):
            info = t.gettarinfo(str(path), arcname=prefix + path.relative_to(src).as_posix())
            info.mtime, info.uid, info.gid, info.uname, info.gname = 1700000000, 0, 0, "", ""
            info.mode = 0o755 if path.is_dir() or path.name == "busybox" else 0o644
            if path.is_file():
                with path.open("rb") as fh:
                    t.addfile(info, fh)
            else:
                t.addfile(info)
    return buf.getvalue()


@pytest.fixture(scope="module")
def scans(tmp_path_factory) -> dict:
    """{"directory" | "image" | "directory-1.7": (최종 문서, Tracker, 표준오류 줄)}. 앞의 둘은 --spec v0.6 (탐색기의 트리가 v0.6 이다),
    마지막은 기본 형태 --spec 1.7 로 v0.6 필드가 aibom:* properties 로 들어가는 자리를 본다. 로컬 데이터는 셋 다 project/data."""
    tar = docker_tar(tmp_path_factory.mktemp("image") / "acme-app.tar", [tree_layer(FIELDS / "rootfs", ""), tree_layer(PROJECT, "app/")],
                     tag=make_fields.IMAGE_TAG, labels=make_fields.IMAGE_LABELS)
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(en, "skip_reason", lambda: None)
        mp.setattr(en, "run_aibom_generator", recorded_owasp)
        mp.setattr(hub, "hf_reachable", lambda: True)                       # 허브 모델 응답은 M-BOM 보강이 받는다
        mp.setattr(hub, "fetch_model_info", lambda hf_id, log=print: recorded("model", hf_id))
        mp.setattr(hub, "fetch_dataset_info", lambda hf_id, log=print: recorded("dataset", hf_id))
        mp.setattr(hub, "fetch_dataset_size", lambda hf_id, log=print: recorded("size", hf_id))
        mp.setattr(hub, "fetch_dataset_statistics", lambda hf_id, config, split, log=print: recorded("statistics", hf_id, config, split))
        for name, target, spec in (("directory", PROJECT, "v0.6"), ("image", tar, "v0.6"), ("directory-1.7", PROJECT, "1.7")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                doc, tracker = fieldtrace.traced_scan(["scan", str(target), "-o", str(OUT / f"{name}.cdx.json"), "--spec", spec,
                                                       "--data", str(PROJECT / "data")])
            out[name] = (doc, tracker, err.getvalue().splitlines())
    return out


def explorer_rows(scans: dict) -> list[dict]:
    """v0.6 스캔 둘의 자리 전부와, 1.7 스캔의 properties 자리 (종류 뒤에 "· --spec 1.7")."""
    v06 = [fieldtrace.site_sources(scans[name][0], scans[name][1]) for name in ("directory", "image")]
    properties_form = {site: {(tool, f"{kind} · --spec 1.7") for tool, kind in pairs}
                       for site, pairs in fieldtrace.site_sources(*scans["directory-1.7"][:2]).items() if ".properties." in site}
    return fieldtrace.as_rows(*v06, properties_form)


def by_ref(doc: dict) -> dict[str, dict]:
    return {c["bom-ref"]: c for c in doc["components"]}


def test_field_explorer_sources_match_the_scans(scans):
    text = json.dumps(explorer_rows(scans), ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("AIBOM_UPDATE_SOURCES"):
        SOURCES.write_text(text, encoding="utf-8")
    assert SOURCES.read_text(encoding="utf-8") == text, "탐색기 데이터가 실제 출력과 다르다. AIBOM_UPDATE_SOURCES=1 로 다시 쓰고 바뀐 자리를 확인한다"


def test_field_explorer_spdx_sources_match_the_scans(scans):
    """SPDX 트리의 도구 배지: 두 v0.6 스캔을 SPDX 로 바꿔 요소의 값마다 CycloneDX 값의 출처를 잇는다 (fieldtrace.spdx_site_sources)."""
    rows = fieldtrace.as_rows(*(fieldtrace.spdx_site_sources(scans[name][0], scans[name][1]) for name in ("directory", "image")))
    text = json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("AIBOM_UPDATE_SOURCES"):
        SPDX_SOURCES.write_text(text, encoding="utf-8")
    assert SPDX_SOURCES.read_text(encoding="utf-8") == text, "탐색기의 SPDX 배지 데이터가 실제 출력과 다르다. AIBOM_UPDATE_SOURCES=1 로 다시 쓴다"


def test_the_fixture_is_what_the_builder_makes(tmp_path):
    """커밋한 픽스처가 make_fields.py 의 결과와 바이트 단위로 같다 (손으로 고친 파일이 없다)."""
    make_fields.build(tmp_path)
    for name in ("project", "rootfs", "hf_api", "owasp"):
        built = {p.relative_to(tmp_path / name): p.read_bytes() for p in (tmp_path / name).rglob("*") if p.is_file()}
        committed = {p.relative_to(FIELDS / name): p.read_bytes() for p in (FIELDS / name).rglob("*") if p.is_file()}
        assert built == committed, name


def test_the_scans_validate(scans):
    for name in scans:
        doc = json.loads((OUT / f"{name}.cdx.json").read_text())
        assert validate_cdx(doc, "v0.6", log=lambda m: None), name
    assert validate_cdx(json.loads((OUT / "directory-1.7.cdx.json").read_text()), "1.7", log=lambda m: None)


def test_the_spdx_conversion_of_the_scans_validates(scans):
    """두 v0.6 스캔(디렉터리, 이미지)을 SPDX 로 바꾸면 3.0.1 은 공식 스키마를, v0.6 은 aibom-v0.6 SPDX 스키마를 통과하고,
    컴포넌트와 서비스마다 요소가 하나씩 있다 (bom-ref 는 확장에 남는다)."""
    for name in ("directory", "image"):
        doc = json.loads((OUT / f"{name}.cdx.json").read_text())
        refs = {c["bom-ref"] for c in doc["components"]} | {s["bom-ref"] for s in doc["services"]} | {doc["metadata"]["component"]["bom-ref"]}
        for spec in ("3.0.1", "v0.6"):
            out = convert(doc, spec, log=lambda m: None)
            assert validate_spdx(out, spec, log=print), (name, spec)
            kept = {p["extension_cdxPropValue"] for e in out["@graph"] for x in e.get("extension") or []
                    for p in x["extension_cdxProperty"] if p["extension_cdxPropName"] == "bom-ref"}
            assert refs <= kept, (name, spec)


def test_only_aibom_properties_and_sdk_services_are_left(scans):
    for name, (doc, _, _) in scans.items():
        names = set()

        def walk(node):
            if isinstance(node, dict):
                names.update(p["name"] for p in node.get("properties") or [])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(doc)
        if name == "directory-1.7":
            assert names and all(n.startswith(("aibom:model:", "aibom:dataset:")) for n in names)
        else:
            assert not names                                                # typed 출력에는 aibom:* 프로퍼티도 없다 (규제 필드는 v0.6 필드로)
        # app.js 의 OpenAI SDK, agent.py 의 import anthropic (cdxgen 은 모델 이름으로만 짐작했다), langchain_groq (cdxgen 은 만들지 않았다)
        assert sorted(s["name"] for s in doc["services"]) == ["Anthropic API", "Groq API", "OpenAI API"]
        assert not any("version" in s for s in doc["services"])


def test_directory_scan_models(scans):
    doc, _, log = scans["directory"]
    models = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "machine-learning-model"}
    assert set(models) == {"pkg:generic/openai/gpt-4o-mini", "pkg:generic/anthropic/claude-sonnet-4-5", "pkg:generic/ollama/llama3.2:1b",
                           "pkg:generic/Acme/Acme%20Tiny%20Chat@v1.0",
                           "pkg:huggingface/acme/acme-chat-GGUF", "pkg:huggingface/acme/acme-bert", "pkg:huggingface/acme/acme-private",
                           "pkg:huggingface/acme/acme-local", "pkg:generic/huggingface/acme-lora"}      # Modelfile 의 가짜 허브 모델은 GGUF 모델로 합쳤다
    tiny = models["pkg:generic/Acme/Acme%20Tiny%20Chat@v1.0"]
    assert tiny["evidence"]["occurrences"] == [{"location": "models/acme-tiny-chat-Q4_K_M.gguf"}, {"location": "Modelfile"}]
    assert tiny["modelCard"]["considerations"]["technicalRequirements"] == ["llama.cpp", "ollama"]
    assert tiny["modelCard"]["modelParameters"]["datasets"] == [{"ref": "pkg:huggingface/datasets/acme/chat-sft"}]
    assert models["pkg:generic/ollama/llama3.2:1b"]["licenses"] == [{"license": {"name": "LLAMA 3.2 COMMUNITY LICENSE AGREEMENT"}}]
    bert = models["pkg:huggingface/acme/acme-bert"]                         # 코드가 부르는 허브 모델: Hub API 응답과 OWASP 의 규제 원본
    assert (bert["version"], bert["licenses"], bert["supplier"]) == ("a1" * 20, [{"license": {"id": "Apache-2.0"}}], {"name": "acme"})
    assert bert["pedigree"]["ancestors"][0]["purl"] == "pkg:huggingface/acme/acme-base"
    params = bert["modelCard"]["modelParameters"]
    assert (params["task"], params["architectureFamily"], params["modelArchitecture"], params["parameterCount"]) == ("fill-mask", "bert", "BertForMaskedLM", 4400000)
    assert bert["modelCard"]["quantitativeAnalysis"]["performanceMetrics"][0] == {"type": "accuracy", "value": "0.81", "slice": "Acme Eval / test"}
    assert "description" not in bert and "technicalLimitations" not in bert["modelCard"].get("considerations", {})   # OWASP 의 자리표시자·README 조각은 없다
    assert models["pkg:huggingface/acme/acme-chat-GGUF"]["description"] == "GGUF quantizations of Acme Tiny Chat."      # 카드의 model_description
    private = models["pkg:huggingface/acme/acme-private"]
    assert "modelCard" not in private or "modelParameters" not in private["modelCard"]                                # OWASP 기본값(task·구조)이 들어가지 않는다
    local = models["pkg:huggingface/acme/acme-local"]
    assert local["modelCard"]["modelParameters"]["datasets"] == [{"ref": f"pkg:huggingface/datasets/acme/{n}"} for n in ("acmecorpus", "reviews", "sentiment-eval")]
    assert "environmentalConsiderations" not in local["modelCard"]["considerations"]                                 # co2 는 properties 뿐이라 지워진다
    stages = [line.split(" .")[0] for line in log if " ..." in line]
    assert "[sure-aibom] Enriching M-BOM (Hub API)" in stages and "[sure-aibom]   acme/acme-private: no regulation values in the aibom-generator output" in log


def test_directory_scan_datasets(scans):
    doc, _, _ = scans["directory"]
    found = {c["bom-ref"]: c for c in doc["components"] if c["type"] == "data"}
    hub = {f"pkg:huggingface/datasets/acme/{n}" for n in ("reviews", "acmecorpus", "sentiment-eval", "eval-set", "notebook-set", "chat-sft")}
    assert set(found) == hub | {"data:local/data@"}                       # 코드 링크의 eval-set 이 허브 모델 카드의 것과 하나다
    assert "datasets/datasets" not in json.dumps(doc)
    assert found["pkg:huggingface/datasets/acme/acmecorpus"]["data"][0]["name"] == "acme/acmecorpus"
    assert found["pkg:huggingface/datasets/acme/sentiment-eval"]["licenses"] == [
        {"license": {"name": "acme-eval-license", "url": "https://acme.example/licenses/eval"}}]
    assert found["pkg:huggingface/datasets/acme/eval-set"]["evidence"]["occurrences"] == [{"location": "src/train.py#L8"}]


def test_directory_scan_packages(scans):
    doc, _, _ = scans["directory"]
    comps = by_ref(doc)
    slf4j = next(c for c in comps.values() if c["name"] == "slf4j-api")
    assert "version" not in slf4j and slf4j["purl"] == "pkg:maven/org.slf4j/slf4j-api"          # UNKNOWN 자리표시자 대신 비워 둔다
    util = comps["pkg:maven/com.acme.util/acme-util@2.0.0"]
    assert util["hashes"][0]["alg"] == "SHA-1" and "externalReferences" not in util
    assert comps["pkg:pypi/requests@2.31.0"]["evidence"]["occurrences"] == [{"location": "requirements.txt"}]
    assert doc["metadata"]["component"] == {"type": "application", "name": "project", "bom-ref": "application:/project@"}


def test_image_scan_root_and_packages(scans):
    doc, _, _ = scans["image"]
    root = doc["metadata"]["component"]
    assert (root["type"], root["name"], root["version"], root["supplier"]) == ("container", "acme-app:1.4.0", "1.4.0", {"name": "Acme Corp"})
    assert root["externalReferences"][0] == {"type": "vcs", "url": "https://github.com/acme/acme-app",
                                             "comment": "revision: 0123456789abcdef0123456789abcdef01234567"}
    assert root["pedigree"]["ancestors"][0]["name"] == "docker.io/library/debian:12-slim"
    comps = {c["name"]: c for c in doc["components"] if c["type"] != "file"}
    assert comps["left-pad"]["externalReferences"][0] == {"url": "git+https://github.com/stevemao/left-pad.git", "type": "vcs"}
    assert "licenses" not in comps["libc6"]                                 # sha256:<본문 해시> 자리표시자는 라이선스가 아니다
    assert "externalReferences" not in comps["localproj"]                   # file:// 설치 주소 (로컬 경로)
    assert comps["acme-sdk"]["evidence"]["occurrences"][0]["location"] == "usr/local/lib/python3.11/site-packages/acme_sdk-1.2.3.dist-info/METADATA"
    assert comps["debian"]["type"] == "operating-system" and "evidence" not in comps["debian"]
