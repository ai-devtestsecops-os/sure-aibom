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
