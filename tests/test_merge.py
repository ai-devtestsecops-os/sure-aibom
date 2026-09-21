from aibom_cli.merge import identity, merge


def _doc(components, dependencies=()):
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", "components": components, "dependencies": list(dependencies)}


def test_identity_prefers_purl():
    assert identity({"purl": "pkg:npm/lodash@4.17.21", "name": "lodash"}) == "pkg:npm/lodash@4.17.21"


def test_identity_falls_back_to_hash_then_name():
    assert identity({"name": "m", "hashes": [{"alg": "SHA-256", "content": "abc"}]}) == "hash:SHA-256:abc"
    assert identity({"type": "library", "name": "m", "version": "1"}) == "library:/m@1"


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
