import pytest

from aibom_cli.facts import Facts
from aibom_cli.merge import identity, merge


def _doc(components, dependencies=()):
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": components, "dependencies": list(dependencies)}


def test_identity_prefers_purl():
    assert identity({"purl": "pkg:npm/lodash@4.17.21", "name": "lodash"}) == "pkg:npm/lodash@4.17.21"


def test_identity_falls_back_to_hash_then_name():
    assert identity({"name": "m", "hashes": [{"alg": "SHA-256", "content": "abc"}]}) == "hash:SHA-256:abc"
    assert identity({"type": "library", "name": "m", "version": "1"}) == "library:/m@1"


@pytest.mark.parametrize("comp, expected", [
    # syft: name 이 경로 (디렉터리 스캔은 루트 기준 `/…`, 이미지는 이미지 안 절대경로), 해시가 있어도 경로가 키
    ({"type": "file", "name": "/requirements.txt", "hashes": [{"alg": "SHA-1", "content": "923c"}]}, "file:/requirements.txt"),
    # cdxgen 이미지 스캔: purl 의 path= (퍼센트 인코딩)
    ({"type": "file", "name": "apt", "purl": "pkg:generic/apt?path=%2Fusr%2Fbin%2Fapt", "hashes": [{"alg": "SHA-1", "content": "923c"}]}, "file:/usr/bin/apt"),
    ({"type": "file", "name": "g++", "purl": "pkg:generic/g%2B%2B?path=%2Fusr%2Fbin%2Fg%2B%2B"}, "file:/usr/bin/g++"),
    # cdxgen AI 파일: bom-ref urn:file:ai:<루트 기준 경로>, name 은 파일 이름뿐
    ({"type": "file", "name": "stories260K.gguf", "bom-ref": "urn:file:ai:models/stories260K.gguf", "group": "", "version": ""}, "file:/models/stories260K.gguf"),
    # 경로를 알 길이 없으면 종전 규칙
    ({"type": "file", "name": "", "hashes": [{"alg": "SHA-256", "content": "abc"}]}, "hash:SHA-256:abc"),
])
def test_file_components_are_keyed_by_path(comp, expected):
    assert identity(comp) == expected


def test_the_same_file_from_syft_and_cdxgen_is_one_component():
    """이미지 스캔에서 syft(해시)와 cdxgen(purl) 이 같은 파일을 각자 내면 하나로 합쳐지고, 해시와 프로퍼티가 모인다."""
    syft = _doc([{"bom-ref": "s", "type": "file", "name": "/usr/bin/apt",
                  "hashes": [{"alg": "SHA-1", "content": "2ffd"}, {"alg": "SHA-256", "content": "9a1b"}]}])
    cdx = _doc([{"bom-ref": "pkg:generic/apt?path=%2Fusr%2Fbin%2Fapt", "type": "file", "name": "apt",
                 "purl": "pkg:generic/apt?path=%2Fusr%2Fbin%2Fapt", "properties": [{"name": "internal:is_file", "value": "true"}]}],
                [{"ref": "pkg:generic/apt?path=%2Fusr%2Fbin%2Fapt", "dependsOn": []}])
    out = merge([syft, cdx])
    files = [c for c in out["components"] if c["type"] == "file"]
    assert len(files) == 1
    comp = files[0]
    assert comp["bom-ref"] == "file:/usr/bin/apt" and comp["name"] == "/usr/bin/apt"      # 먼저 온 syft 가 기준
    assert [h["alg"] for h in comp["hashes"]] == ["SHA-1", "SHA-256"]
    assert comp["purl"] == "pkg:generic/apt?path=%2Fusr%2Fbin%2Fapt" and comp["properties"] == [{"name": "internal:is_file", "value": "true"}]
    assert {d["ref"] for d in out["dependencies"]} >= {"file:/usr/bin/apt"}


def test_same_purl_from_two_tools_is_one_component():
    a = _doc([{"bom-ref": "a1", "type": "library", "name": "lodash", "version": "4.17.21", "purl": "pkg:npm/lodash@4.17.21"}])
    b = _doc([{"bom-ref": "b1", "type": "library", "name": "lodash", "version": "4.17.21", "purl": "pkg:npm/lodash@4.17.21",
               "licenses": [{"license": {"id": "MIT"}}]}])
    out = merge([a, b])
    assert len(out["components"]) == 1
    comp = out["components"][0]
    assert comp["bom-ref"] == "pkg:npm/lodash@4.17.21"
    assert comp["licenses"][0]["license"]["id"] == "MIT"       # 뒤 문서의 빠진 필드가 채워진다


def test_dependency_refs_are_remapped():
    a = _doc(
        [{"bom-ref": "app", "type": "application", "name": "app", "version": "1", "purl": "pkg:generic/app@1"},
         {"bom-ref": "x", "type": "library", "name": "x", "version": "2", "purl": "pkg:npm/x@2"}],
        [{"ref": "app", "dependsOn": ["x"]}],
    )
    out = merge([a])
    assert out["dependencies"] == [{"ref": "pkg:generic/app@1", "dependsOn": ["pkg:npm/x@2"]}]


def test_model_and_software_do_not_collide():
    sw = _doc([{"bom-ref": "s", "type": "library", "name": "numpy", "version": "2.0", "purl": "pkg:pypi/numpy@2.0"}])
    ai = _doc([{"bom-ref": "m", "type": "machine-learning-model", "name": "bert", "purl": "pkg:huggingface/google-bert/bert-base-uncased@abc"}])
    out = merge([sw, ai])
    assert {c["type"] for c in out["components"]} == {"library", "machine-learning-model"}


def test_modelcard_dataset_refs_follow_rekeyed_bom_refs():
    """데이터셋 컴포넌트의 bom-ref 가 병합 키로 바뀌면 모델카드의 ref 도 같이 바뀌어야 한다 (끊긴 참조 방지)."""
    ai = _doc([
        {"bom-ref": "pkg:huggingface/datasets/bookcorpus?x=1", "type": "data", "group": "datasets", "name": "bookcorpus"},
        {"bom-ref": "m", "type": "machine-learning-model", "name": "bert", "purl": "pkg:huggingface/google-bert/bert-base-uncased",
         "modelCard": {"modelParameters": {"datasets": [{"ref": "pkg:huggingface/datasets/bookcorpus?x=1"}]}}},
    ], [{"ref": "m", "dependsOn": ["pkg:huggingface/datasets/bookcorpus?x=1"]}])
    out = merge([ai])
    data = next(c for c in out["components"] if c["type"] == "data")
    model = next(c for c in out["components"] if c["type"] == "machine-learning-model")
    ref = model["modelCard"]["modelParameters"]["datasets"][0]["ref"]
    assert ref == data["bom-ref"] == "data:datasets/bookcorpus@"
    assert out["dependencies"] == [{"ref": model["bom-ref"], "dependsOn": [data["bom-ref"]]}]


def test_cdxgen_purl_style_dataset_ref_is_linked_to_the_data_component():
    """cdxgen 은 modelCard datasets[].ref 를 데이터셋 컴포넌트의 bom-ref 가 아닌 purl 로 쓴다 (원본부터 끊김).
    이름·URL 또는 의존성 엣지로 데이터셋 컴포넌트에 이어야 한다."""
    ai = _doc([
        {"bom-ref": "cdxgen:ai:dataset:huggingface:datasets-bookcorpus", "type": "data", "group": "datasets", "name": "bookcorpus",
         "data": [{"type": "dataset", "name": "datasets/bookcorpus", "contents": {"url": "https://huggingface.co/datasets/datasets/bookcorpus"}}]},
        {"bom-ref": "pkg:huggingface/google-bert/bert-base-uncased", "type": "machine-learning-model", "name": "bert-base-uncased",
         "purl": "pkg:huggingface/google-bert/bert-base-uncased",
         "modelCard": {"modelParameters": {"datasets": [{"ref": "pkg:huggingface/datasets/bookcorpus?repository_url=https%3A%2F%2Fhuggingface.co%2Fdatasets"}]}}},
    ], [{"ref": "pkg:huggingface/google-bert/bert-base-uncased", "dependsOn": ["cdxgen:ai:dataset:huggingface:datasets-bookcorpus"]}])
    out = merge([ai])
    data = next(c for c in out["components"] if c["type"] == "data")
    model = next(c for c in out["components"] if c["type"] == "machine-learning-model")
    assert model["modelCard"]["modelParameters"]["datasets"][0]["ref"] == data["bom-ref"]
    # 이름으로 못 맞춰도 의존성 엣지 하나면 잇는다
    ai["components"][0]["data"] = []; ai["components"][0]["name"] = "corpus-x"; ai["components"][0].pop("group")
    ai["components"][1]["modelCard"]["modelParameters"]["datasets"][0]["ref"] = "pkg:huggingface/datasets/something-else"
    out2 = merge([ai])
    m2 = next(c for c in out2["components"] if c["type"] == "machine-learning-model")
    d2 = next(c for c in out2["components"] if c["type"] == "data")
    assert m2["modelCard"]["modelParameters"]["datasets"][0]["ref"] == d2["bom-ref"]


# -- 이미지의 OCI 라벨 → 루트 ---------------------------------------------------------
OCI = "syft:image:labels:org.opencontainers.image."


def syft_image_doc(**labels) -> dict:
    """syft 가 이미지를 스캔하면 설정의 Labels 를 metadata.properties 에 syft:image:labels:<키> 로 둔다."""
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": [],
            "metadata": {"component": {"bom-ref": "x", "type": "container", "name": "img.tar"},
                         "properties": [{"name": f"{OCI}{k}", "value": v} for k, v in labels.items()]
                         + [{"name": "syft:image:labels:maintainer", "value": "a@b"}]}}


def test_oci_labels_fill_the_container_root():
    facts = Facts()
    out = merge([syft_image_doc(**{"version": "1.4.0", "description": "Acme app", "vendor": "Acme Corp", "authors": "ML Team <ml@acme.example>",
                                   "licenses": "Apache-2.0", "source": "https://github.com/acme/app", "revision": "0123abcd",
                                   "url": "https://acme.example/app", "documentation": "https://acme.example/docs", "title": "app",
                                   "created": "2026-10-01T00:00:00Z", "base.name": "docker.io/library/debian:12-slim",
                                   "base.digest": "sha256:" + "d1" * 32})], root=("acme-app:1.4.0", "image"), facts=facts)
    assert facts.times == {"container:/acme-app:1.4.0@": {"builtTime": "2026-10-01T00:00:00Z"}}   # created 라벨은 문서가 아니라 facts 에
    assert out["metadata"]["component"] == {
        "type": "container", "name": "acme-app:1.4.0", "bom-ref": "container:/acme-app:1.4.0@",       # bom-ref 는 이름으로만 (라벨과 무관)
        "version": "1.4.0", "description": "Acme app", "supplier": {"name": "Acme Corp"}, "authors": [{"name": "ML Team <ml@acme.example>"}],
        "licenses": [{"license": {"id": "Apache-2.0"}}],
        "externalReferences": [{"type": "vcs", "url": "https://github.com/acme/app", "comment": "revision: 0123abcd"},
                               {"type": "website", "url": "https://acme.example/app"}, {"type": "documentation", "url": "https://acme.example/docs"}],
        "pedigree": {"ancestors": [{"type": "container", "name": "docker.io/library/debian:12-slim",
                                    "hashes": [{"alg": "SHA-256", "content": "d1" * 32}]}]}}


def test_lifecycle_follows_the_target_kind_not_the_tools():
    """생성 맥락은 스캔 대상 종류로 정한다. cdxgen 이 대상과 상관없이 적는 pre-build 는 버린다."""
    cdxgen = {"metadata": {"lifecycles": [{"phase": "pre-build"}], "authors": [{"name": "OWASP Foundation"}]}, "components": []}
    assert merge([cdxgen], root=("acme-app:1.4.0", "image"))["metadata"]["lifecycles"] == [{"phase": "post-build"}]
    out = merge([cdxgen], root=("proj", "directory"))["metadata"]
    assert out["lifecycles"] == [{"phase": "pre-build"}] and "authors" not in out
    assert "lifecycles" not in merge([cdxgen])["metadata"]                          # 대상을 모르면 적지 않는다


def test_oci_license_expressions_and_partial_labels():
    out = merge([syft_image_doc(licenses="Apache-2.0 OR MIT", **{"base.name": "alpine:3.20", "base.digest": "sha256:short"})], root=("i", "image"))
    root = out["metadata"]["component"]
    assert root["licenses"] == [{"expression": "Apache-2.0 OR MIT"}] and root["pedigree"] == {"ancestors": [{"type": "container", "name": "alpine:3.20"}]}
    assert set(root) == {"type", "name", "bom-ref", "licenses", "pedigree"}
    plain = merge([syft_image_doc()], root=("proj", "directory"))["metadata"]["component"]
    assert plain == {"type": "application", "name": "proj", "bom-ref": "application:/proj@"}        # 라벨이 없으면 그대로 (maintainer 는 OCI 키가 아니다)
