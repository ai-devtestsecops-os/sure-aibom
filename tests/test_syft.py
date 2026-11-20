"""syft — syft 출력의 정리 (값을 더하지 않고 빼기·종류 고치기·인코딩 고치기·자리 옮기기만 한다).
도구 없이 출력 모양을 손으로 만들어 확인한다. 모양은 syft 1.52.0 을 실제로 돌린 결과를 따른다."""
import copy

import pytest

import sure_aibom.engine.syft as syft


def props(**kv) -> list[dict]:
    return [{"name": k, "value": v} for k, v in kv.items()]


def syft_package(metadata_type: str, **extra) -> dict:
    comp = {"bom-ref": "pkg:x/y@1?package-id=1", "type": "library", "name": "y", "version": "1", "purl": "pkg:x/y@1",
            "properties": [{"name": "syft:package:foundBy", "value": "c"}, {"name": "syft:package:metadataType", "value": metadata_type},
                           {"name": "syft:location:1:path", "value": "/b/RECORD"}, {"name": "syft:location:0:path", "value": "/a/METADATA"}]}
    comp.update(extra)
    return comp


def test_syft_runs_with_missing_versions_kept_empty(tmp_path, monkeypatch):
    """syft 기본값은 버전을 못 찾은 패키지에 UNKNOWN 을 적는다. keep 이면 version 을 비워 둔다 (실측: purl 은 같다)."""
    seen = {}

    def run(cmd, env=None, **kw):
        seen.update(cmd=cmd, env=env)
        (tmp_path / "syft.cdx.json").write_text('{"bomFormat": "CycloneDX", "components": []}', encoding="utf-8")
        return type("P", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(syft, "run", run)
    syft.run_syft(str(tmp_path), tmp_path)
    assert seen["env"] == {"SYFT_COMPLIANCE_MISSING_VERSION": "keep"} and seen["cmd"][2:4] == ["--select-catalogers", "-ai"]


def test_package_locations_become_evidence_occurrences():
    comp = syft_package("python-package", evidence={"occurrences": [{"location": "a/METADATA"}]})
    syft._tidy(comp)
    assert comp["evidence"]["occurrences"] == [{"location": "a/METADATA"}, {"location": "b/RECORD"}]   # 번호 순, 앞의 / 는 뺀다, 겹치면 한 번
    plain = {"type": "operating-system", "name": "debian", "properties": props(**{"syft:distro:id": "debian"})}
    syft._tidy(plain)
    assert "evidence" not in plain


def test_unidentified_license_text_hash_is_not_a_license():
    """syft 는 알아보지 못한 라이선스 본문(DEP-5 가 아닌 Debian copyright)의 sha256 을 이름으로 적는다."""
    placeholder = {"license": {"name": "sha256:" + "0a" * 32}}
    comp = syft_package("dpkg-db-entry", licenses=[placeholder, {"license": {"id": "MIT"}}, {"expression": "MIT OR Apache-2.0"}])
    syft._tidy(comp)
    assert comp["licenses"] == [{"license": {"id": "MIT"}}, {"expression": "MIT OR Apache-2.0"}]
    only = syft_package("dpkg-db-entry", licenses=[copy.deepcopy(placeholder)])
    syft._tidy(only)
    assert "licenses" not in only
    named = syft_package("python-package", licenses=[{"license": {"name": "sha256 is not a hash"}}])
    syft._tidy(named)
    assert named["licenses"] == [{"license": {"name": "sha256 is not a hash"}}]


@pytest.mark.parametrize("metadata_type, refs, expected", [
    # npm package.json: repository.url 을 distribution 으로, homepage 를 website 로 낸다
    ("javascript-npm-package", [{"type": "distribution", "url": "git+https://github.com/a/b.git"}, {"type": "website", "url": "https://a.example"}],
     [{"type": "vcs", "url": "git+https://github.com/a/b.git"}, {"type": "website", "url": "https://a.example"}]),
    # apk: U:(upstream 프로젝트 주소)를 distribution 으로 낸다
    ("apk-db-entry", [{"type": "distribution", "url": "https://musl.libc.org/"}], [{"type": "website", "url": "https://musl.libc.org/"}]),
    # Cargo.lock 의 source(레지스트리)는 그대로
    ("rust-cargo-lock-entry", [{"type": "distribution", "url": "registry+https://github.com/rust-lang/crates.io-index"}],
     [{"type": "distribution", "url": "registry+https://github.com/rust-lang/crates.io-index"}]),
    # pip direct_url: git 주소는 그대로, file:// (로컬 경로, pip install -e) 는 vcs 가 아니라 뺀다
    ("python-package", [{"type": "vcs", "url": "https://github.com/a/b.git", "comment": "commit: 0123"}, {"type": "vcs", "url": "file:///home/dev/src/b"}],
     [{"type": "vcs", "url": "https://github.com/a/b.git", "comment": "commit: 0123"}]),
])
def test_external_reference_types_are_corrected(metadata_type, refs, expected):
    comp = syft_package(metadata_type, externalReferences=copy.deepcopy(refs))
    syft._tidy(comp)
    assert comp["externalReferences"] == expected


def test_jar_digest_moves_from_an_empty_build_meta_reference_to_hashes():
    comp = syft_package("java-archive", hashes=[{"alg": "SHA-1", "content": "aa"}],
                        externalReferences=[{"type": "build-meta", "url": "", "hashes": [{"alg": "SHA-1", "content": "aa"}, {"alg": "SHA-256", "content": "bb"}]}])
    syft._tidy(comp)
    assert comp["hashes"] == [{"alg": "SHA-1", "content": "aa"}, {"alg": "SHA-256", "content": "bb"}] and "externalReferences" not in comp
    file_only = syft_package("python-package", externalReferences=[{"type": "vcs", "url": "file:///x"}])
    syft._tidy(file_only)
    assert "externalReferences" not in file_only and "hashes" not in file_only
