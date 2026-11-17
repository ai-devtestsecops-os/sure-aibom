"""cdxgen — cdxgen 출력의 정리 (값을 더하지 않고 빼기·종류 고치기·인코딩 고치기·자리 옮기기만 한다).
도구 없이 출력 모양을 손으로 만들어 확인한다. 모양은 cdxgen 12.8.4 를 실제로 돌린 결과를 따른다."""
import copy
from pathlib import Path

import pytest

import sure_aibom.external.cdxgen as cdxgen


def props(**kv) -> list[dict]:
    return [{"name": k, "value": v} for k, v in kv.items()]


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_cdxgen_gets_an_absolute_target(tmp_path, monkeypatch):
    """owner/name 모양의 상대 경로를 cdxgen 이 허브 id 로 읽지 않게 절대경로로 넘긴다."""
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        (tmp_path / "cdxgen.cdx.json").write_text('{"bomFormat": "CycloneDX", "components": []}', encoding="utf-8")
        return type("P", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(cdxgen, "run", run)
    (tmp_path / "acme" / "project").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    cdxgen.run_cdxgen("acme/project", tmp_path)
    assert seen["cmd"][1] == str(tmp_path / "acme" / "project")


@pytest.mark.parametrize("comp, purl", [
    # GGUF general.name 의 공백: cdxgen 은 %20 을 한 번 더 인코딩한다
    ({"group": "Acme", "name": "Acme Tiny Chat", "purl": "pkg:generic/Acme/Acme%2520Tiny%2520Chat@v1.0"}, "pkg:generic/Acme/Acme%20Tiny%20Chat@v1.0"),
    ({"group": "My Org", "name": "m", "purl": "pkg:generic/My%2520Org/m?x=%2520"}, "pkg:generic/My%20Org/m?x=%2520"),   # 한정자는 건드리지 않는다
    # 이름에 진짜 % 가 들어 있으면 %25 가 맞다
    ({"group": "", "name": "50%AB", "purl": "pkg:generic/50%25AB"}, "pkg:generic/50%25AB"),
    ({"name": "x", "purl": "pkg:generic/x"}, "pkg:generic/x"),
])
def test_double_encoded_purls_are_decoded_once(comp, purl):
    comp = {"type": "machine-learning-model", **comp}
    cdxgen._fix_purl(comp)
    assert comp["purl"] == purl


def test_pedigree_entries_lose_their_bom_ref():
    """로컬 어댑터의 베이스 모델이 스캔 대상에도 있으면 cdxgen 이 pedigree 에 적은 bom-ref 가 최상위 컴포넌트와 겹친다."""
    doc = {"components": [{"type": "machine-learning-model", "name": "lora", "bom-ref": "l",
                           "pedigree": {"ancestors": [{"bom-ref": "pkg:huggingface/a/base", "name": "base", "purl": "pkg:huggingface/a/base"}],
                                        "notes": "Hugging Face relation: adapter"}}]}
    cdxgen.tidy(doc, Path("/nonexistent"))
    assert doc["components"][0]["pedigree"] == {"ancestors": [{"name": "base", "purl": "pkg:huggingface/a/base"}],
                                                "notes": "Hugging Face relation: adapter"}


@pytest.mark.parametrize("text, expected", [
    ('FROM ./m.gguf\nLICENSE """MIT License\n\nCopyright\n"""\n', ("./m.gguf", "MIT License")),
    ('FROM llama3.2:1b\nLICENSE """\n\nLLAMA 3.2 COMMUNITY LICENSE\nmore\n"""\n', ("llama3.2:1b", "LLAMA 3.2 COMMUNITY LICENSE")),
    ("from base\nlicense Apache-2.0\nFROM other\n", ("other", "Apache-2.0")),                      # 마지막 지시문이 이긴다 (cdxgen 과 같다)
    ('FROM x\nLICENSE """one line"""\n', ("x", "one line")),
    ('FROM x\nLICENSE """\nnever closed\n', ("x", "never closed")),
    ("# FROM commented\nPARAMETER num_ctx 4096\n", (None, None)),
])
def test_parse_modelfile(text, expected):
    assert cdxgen.parse_modelfile(text) == expected


def modelfile_model(location: str, name: str, group: str, licenses=None) -> dict:
    """cdxgen 이 Modelfile 에서 만드는 모델 (FROM 의 로컬 경로를 owner/name 으로 읽은 purl)."""
    comp = {"bom-ref": f"pkg:huggingface/{group}/{name}", "type": "machine-learning-model", "group": group, "name": name,
            "purl": f"pkg:huggingface/{group}/{name}", "evidence": {"occurrences": [{"location": location}]},
            "properties": props(**{"cdx:ai:artifactFormat": "modelfile", "cdx:ai:runtime": "ollama", "cdx:ai:source": "local-config"})}
    if licenses:
        comp["licenses"] = licenses
    return comp


def test_a_modelfile_from_a_local_gguf_merges_into_that_gguf_model(tmp_path):
    write(tmp_path, "Modelfile", 'FROM ./models/x.gguf\nLICENSE """MIT License\n"""\n')
    write(tmp_path, "models/x.gguf", "GGUF")
    gguf = {"bom-ref": "cdxgen:ai:model:Acme:X", "type": "machine-learning-model", "group": "Acme", "name": "X", "purl": "pkg:generic/Acme/X",
            "evidence": {"occurrences": [{"location": "models/x.gguf"}]}, "properties": props(**{"cdx:ai:runtime": "llama.cpp"})}
    fake = modelfile_model("Modelfile", "x.gguf", "models", licenses=[{"license": {"id": "MIT"}}])
    doc = {"components": [fake, gguf], "services": [],
           "dependencies": [{"ref": "urn:file:ai:Modelfile", "dependsOn": [fake["bom-ref"]]},
                            {"ref": "urn:file:ai:models/x.gguf", "dependsOn": [gguf["bom-ref"]]}]}
    cdxgen.tidy(doc, tmp_path)
    assert [c["bom-ref"] for c in doc["components"]] == [gguf["bom-ref"]]
    merged = doc["components"][0]
    assert merged["evidence"]["occurrences"] == [{"location": "models/x.gguf"}, {"location": "Modelfile"}]
    assert [p["value"] for p in merged["properties"] if p["name"] == "cdx:ai:runtime"] == ["llama.cpp", "ollama"]
    assert merged["licenses"] == [{"license": {"id": "MIT"}}]                     # GGUF 모델에 없던 라이선스는 넘긴다
    assert doc["dependencies"] == [{"ref": "urn:file:ai:Modelfile", "dependsOn": [gguf["bom-ref"]]},
                                   {"ref": "urn:file:ai:models/x.gguf", "dependsOn": [gguf["bom-ref"]]}]


def test_a_modelfile_from_a_local_path_without_a_gguf_model_gets_a_generic_purl(tmp_path):
    write(tmp_path, "deploy/Modelfile", "FROM ../weights/big.gguf\n")
    fake = modelfile_model("deploy/Modelfile", "big.gguf", "weights")
    doc = {"components": [fake]}
    cdxgen.tidy(doc, tmp_path)                                                     # 큰 어휘라 cdxgen 이 GGUF 를 놓친 경우 등
    assert (fake["purl"], fake["name"], "group" in fake) == ("pkg:generic/big.gguf", "big.gguf", False)


def test_a_modelfile_from_a_library_model_keeps_its_purl_and_gets_its_license_line(tmp_path):
    write(tmp_path, "Modelfile", 'FROM llama3.2:1b\nLICENSE """\nLLAMA 3.2 COMMUNITY LICENSE AGREEMENT\n"""\n')
    comp = modelfile_model("Modelfile", "llama3.2:1b", "ollama", licenses=[{"license": {"name": '"""'}}])
    comp["purl"] = comp["bom-ref"] = "pkg:generic/ollama/llama3.2:1b"
    doc = {"components": [comp]}
    cdxgen.tidy(doc, tmp_path)
    assert comp["purl"] == "pkg:generic/ollama/llama3.2:1b"
    assert comp["licenses"] == [{"license": {"name": "LLAMA 3.2 COMMUNITY LICENSE AGREEMENT"}}]
    write(tmp_path, "b/Modelfile", 'FROM llama3.2:1b\nLICENSE """\n"""\n')
    empty = modelfile_model("b/Modelfile", "llama3.2:1b", "ollama", licenses=[{"license": {"name": '"""'}}])
    cdxgen.tidy({"components": [empty]}, tmp_path)
    assert "licenses" not in empty                                                  # 본문이 비면 이름 없는 라이선스는 뺀다


def test_a_modelfile_outside_the_target_is_not_read(tmp_path):
    outside = tmp_path / "outside"
    write(outside, "Modelfile", "FROM ./x.gguf\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "Modelfile").symlink_to(outside / "Modelfile")
    fake = modelfile_model("Modelfile", "x.gguf", "models")
    before = copy.deepcopy(fake)
    cdxgen.tidy({"components": [fake]}, root)
    assert fake == before
