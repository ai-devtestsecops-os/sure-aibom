"""image — 이미지 tar 를 디렉터리로 풀기와 이미지 이름 받기. 도구 없이 손으로 만든 tar 로 확인한다."""
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

import sure_aibom.engine.extract_image as im
import sure_aibom.external.pull_image as ip
from sure_aibom.exceptions import ImageExtractionError, RunnerError


# ── tar 만들기 ────────────────────────────────────────────────────────────────

def layer(*entries, gz: bool = False) -> bytes:
    """entries: ("file", 이름, 내용) · ("dir", 이름) · ("symlink", 이름, 대상) · ("hardlink", 이름, 대상) · ("dev", 이름)"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for kind, name, *rest in entries:
            ti = tarfile.TarInfo(name)
            data = None
            if kind == "file":
                data = rest[0].encode() if isinstance(rest[0], str) else rest[0]
                ti.size = len(data)
                ti.mode = 0o644
            elif kind == "dir":
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
            elif kind == "symlink":
                ti.type, ti.linkname = tarfile.SYMTYPE, rest[0]
            elif kind == "hardlink":
                ti.type, ti.linkname = tarfile.LNKTYPE, rest[0]
            elif kind == "dev":
                ti.type, ti.devmajor, ti.devminor = tarfile.CHRTYPE, 1, 3
            t.addfile(ti, io.BytesIO(data) if data is not None else None)
    raw = buf.getvalue()
    return gzip.compress(raw) if gz else raw


def _add(t: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    t.addfile(ti, io.BytesIO(data))


def docker_tar(path: Path, layers: list[bytes], tag: str | None = "img:test", arch: str = "amd64",
               labels: dict[str, str] | None = None) -> Path:
    """docker save · crane pull 모양: manifest.json (Config, RepoTags, Layers) + 설정 json + 레이어 tar 들. labels 는 설정의 config.Labels."""
    config = {"architecture": arch, "os": "linux", "rootfs": {"type": "layers",
              "diff_ids": ["sha256:" + hashlib.sha256(x).hexdigest() for x in layers]}}
    if labels:
        config["config"] = {"Labels": labels}
    config = json.dumps(config).encode()
    with tarfile.open(path, "w") as t:
        names = [f"layer{i}.tar" for i in range(len(layers))]
        _add(t, "manifest.json", json.dumps([{"Config": "config.json", "RepoTags": [tag] if tag else None, "Layers": names}]).encode())
        _add(t, "config.json", config)
        for name, data in zip(names, layers):
            _add(t, name, data)
    return path


def oci_tar(path: Path, images: dict[str, list[bytes]], nested: bool = False, name: str | None = "img:oci") -> Path:
    """OCI 레이아웃: index.json → (인덱스 →) 매니페스트 → blobs/sha256/<digest>. images: 아키텍처 → 레이어들."""
    blobs: dict[str, bytes] = {}

    def put(data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        return "sha256:" + digest

    descriptors = []
    for arch, layers in images.items():
        config = put(json.dumps({"architecture": arch, "os": "linux"}).encode())
        manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": config}, "layers": [{"digest": put(x)} for x in layers]}
        descriptors.append({"mediaType": manifest["mediaType"], "digest": put(json.dumps(manifest).encode()),
                            "platform": {"os": "linux", "architecture": arch}})
    if nested:
        inner = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": descriptors}
        descriptors = [{"mediaType": inner["mediaType"], "digest": put(json.dumps(inner).encode())}]
    if name:
        descriptors[0]["annotations"] = {"org.opencontainers.image.ref.name": name}
    with tarfile.open(path, "w") as t:
        _add(t, "oci-layout", b'{"imageLayoutVersion": "1.0.0"}')
        _add(t, "index.json", json.dumps({"schemaVersion": 2, "manifests": descriptors}).encode())
        for digest, data in blobs.items():
            _add(t, f"blobs/sha256/{digest}", data)
    return path


def tree(root: Path) -> dict[str, str]:
    """rootfs 안의 파일 → 내용 (심볼릭 링크는 "-> 대상")."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "-> " + os.readlink(p)
        elif p.is_file():
            out[rel] = p.read_text()
    return out


# ── 풀기 ──────────────────────────────────────────────────────────────────────

def test_layers_stack_in_order_and_whiteouts_hide_only_lower_layers(tmp_path):
    lower = layer(("dir", "app"), ("file", "app/a.txt", "A"), ("file", "app/old.txt", "old"), ("file", "app/same", "lower"),
                  ("dir", "etc/d"), ("file", "etc/d/x", "x"), ("file", "etc/d/keep", "keep"))
    upper = layer(("file", "app/new.txt", "new"), ("file", "app/.wh.old.txt", ""),
                  ("file", "app/.wh.same", ""), ("file", "app/same", "upper"),        # 같은 레이어의 것은 화이트아웃이 못 지운다
                  ("file", "etc/d/.wh..wh..opq", ""), ("file", "etc/d/y", "y"), gz=True)
    layers, name = im.extract_image(docker_tar(tmp_path / "img.tar", [lower, upper]), tmp_path / "rootfs")
    assert (layers, name) == (2, "img:test")
    assert tree(tmp_path / "rootfs") == {"app/a.txt": "A", "app/new.txt": "new", "app/same": "upper", "etc/d/y": "y"}


def test_links_are_kept_inside_the_unpacked_tree_and_escapes_are_skipped(tmp_path):
    one = layer(("dir", "app"), ("file", "app/a.txt", "A"),
                ("symlink", "app/abs", "/app/a.txt"),               # 이미지 안 절대경로 → 푼 디렉터리 안을 가리키게
                ("symlink", "bin", "usr/bin"),                      # 상대 링크는 그대로
                ("symlink", "app/esc", "../../../../etc/passwd"),   # 밖으로 나가는 링크는 건너뛴다
                ("file", "../evil", "evil"), ("file", "/rooted/file", "r"),
                ("hardlink", "app/hard", "app/a.txt"), ("dev", "dev/null"))
    im.extract_image(docker_tar(tmp_path / "img.tar", [one]), tmp_path / "rootfs")
    got = tree(tmp_path / "rootfs")
    assert got["app/abs"] == "-> a.txt" and (tmp_path / "rootfs" / "app" / "abs").read_text() == "A"
    assert got["bin"] == "-> usr/bin" and got["rooted/file"] == "r" and got["app/hard"] == "A"
    assert "app/esc" not in got and not (tmp_path / "evil").exists() and not (tmp_path / "rootfs" / "dev" / "null").exists()


def test_a_higher_layer_replaces_a_link_without_writing_through_it(tmp_path):
    lower = layer(("file", "real", "R"), ("symlink", "link", "real"), ("dir", "d"), ("file", "d/f", "f"), ("file", "plain", "p"))
    upper = layer(("file", "link", "L"), ("file", "d", "now a file"), ("dir", "plain"), ("file", "plain/inside", "i"))
    im.extract_image(docker_tar(tmp_path / "img.tar", [lower, upper]), tmp_path / "rootfs")
    assert tree(tmp_path / "rootfs") == {"real": "R", "link": "L", "d": "now a file", "plain/inside": "i"}


def test_hardlink_to_a_lower_layer_file_and_image_without_tags(tmp_path):
    lower = layer(("file", "a", "A"))
    upper = layer(("hardlink", "b", "a"))
    layers, name = im.extract_image(docker_tar(tmp_path / "img.tar", [lower, upper], tag=None), tmp_path / "rootfs")
    assert (layers, name) == (2, None) and tree(tmp_path / "rootfs") == {"a": "A", "b": "A"}


def test_oci_layout_picks_this_machines_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "host_arch", lambda: "arm64")
    images = {"amd64": [layer(("file", "arch", "amd64"))], "arm64": [layer(("file", "arch", "arm64"))]}
    for nested in (False, True):
        rootfs = tmp_path / f"rootfs{nested}"
        layers, name = im.extract_image(oci_tar(tmp_path / f"{nested}.tar", images, nested=nested), rootfs)
        assert (layers, name) == (1, "img:oci") and tree(rootfs) == {"arch": "arm64"}
    monkeypatch.setattr(im, "host_arch", lambda: "riscv64")           # 맞는 것이 없으면 첫 번째
    im.extract_image(oci_tar(tmp_path / "first.tar", images, name=None), tmp_path / "first")
    assert tree(tmp_path / "first") == {"arch": "amd64"}


def test_manifest_json_with_several_images_picks_this_machines_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "host_arch", lambda: "amd64")
    entries, blobs = [], {}
    for arch in ("arm64", "amd64"):
        data = layer(("file", "arch", arch))
        blobs[f"{arch}.tar"] = data
        blobs[f"{arch}.json"] = json.dumps({"architecture": arch, "os": "linux"}).encode()
        entries.append({"Config": f"{arch}.json", "RepoTags": [f"img:{arch}"], "Layers": [f"./{arch}.tar"]})
    with tarfile.open(tmp_path / "multi.tar", "w") as t:
        _add(t, "./manifest.json", json.dumps(entries).encode())
        for name, data in blobs.items():
            _add(t, "./" + name, data)
    assert im.extract_image(tmp_path / "multi.tar", tmp_path / "rootfs") == (1, "img:amd64")
    assert tree(tmp_path / "rootfs") == {"arch": "amd64"}


@pytest.mark.parametrize("make, message", [
    (lambda p: _plain_tar(p, {"README": b"x"}), "not an image tar"),
    (lambda p: _plain_tar(p, {"manifest.json": b"[]"}), "lists no image"),
    (lambda p: _plain_tar(p, {"manifest.json": json.dumps([{"Config": "c.json", "Layers": ["gone.tar"]}]).encode(), "c.json": b"{}"}), "layer gone.tar is missing"),
    (lambda p: _plain_tar(p, {"manifest.json": json.dumps([{"Config": "c.json", "Layers": ["z.tar"]}]).encode(), "c.json": b"{}",
                              "z.tar": im.ZSTD_MAGIC + b"\x00" * 16}), "zstd-compressed layers are not supported"),
    (lambda p: p.write_bytes(b"not a tar at all"), "cannot unpack"),
])
def test_bad_image_tars_are_image_extraction_errors(tmp_path, make, message):
    path = tmp_path / "bad.tar"
    make(path)
    with pytest.raises(ImageExtractionError, match=message):
        im.extract_image(path, tmp_path / "rootfs")


def _plain_tar(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as t:
        for name, data in files.items():
            _add(t, name, data)


def test_is_archive():
    assert im.is_archive("image.tar") and im.is_archive("IMG.TAR.GZ") and im.is_archive("x.tgz")
    assert not im.is_archive("alpine:3.20") and not im.is_archive("ghcr.io/org/img@sha256:abc") and not im.is_archive("./project")


# ── 이름 받기 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_tools(monkeypatch):
    """PATH 에 있는 도구(present)와 실패시킬 명령(fail, "docker image save" 꼴)을 정한다. 성공한 save 와 crane pull 은 tar 를 만든다."""
    state = {"present": set(), "fail": set(), "calls": []}
    monkeypatch.setattr(ip.shutil, "which", lambda name: f"/usr/bin/{name}" if name in state["present"] else None)

    def run(cmd, cwd=None, timeout=None):
        state["calls"].append(cmd)
        key = " ".join(cmd[:3] if cmd[1] == "image" else cmd[:2])
        if key in state["fail"]:
            state["fail"].discard(key + " once")
            return subprocess.CompletedProcess(cmd, 1, "", f"Error: {key} failed\n")
        if cmd[0] == "crane":
            Path(cmd[-1]).write_bytes(b"tar")
        elif cmd[1] == "image":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"tar")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(ip, "run", run)
    monkeypatch.setattr(ip, "host_arch", lambda: "amd64")
    return state


def test_pull_saves_from_the_daemon_first(tmp_path, fake_tools):
    fake_tools["present"] = {"docker", "crane"}
    tar, tool = ip.pull_image("alpine:3.20", tmp_path)
    assert (tar, tool) == (tmp_path / "image.tar", "docker")
    assert fake_tools["calls"] == [["docker", "image", "save", "-o", str(tar), "alpine:3.20"]]


def test_pull_fetches_when_the_daemon_does_not_have_the_image(tmp_path, fake_tools, monkeypatch):
    fake_tools["present"] = {"docker"}
    real = ip.run
    seen = {"save": 0}

    def run(cmd, cwd=None, timeout=None):                       # 첫 save 는 없다고 하고, pull 뒤의 save 는 된다
        if cmd[:3] == ["docker", "image", "save"]:
            seen["save"] += 1
            if seen["save"] == 1:
                fake_tools["calls"].append(cmd)
                return subprocess.CompletedProcess(cmd, 1, "", "Error: reference does not exist\n")
        return real(cmd, cwd, timeout)
    monkeypatch.setattr(ip, "run", run)
    tar, tool = ip.pull_image("alpine:3.20", tmp_path)
    assert tool == "docker" and [c[:2] for c in fake_tools["calls"]] == [["docker", "image"], ["docker", "pull"], ["docker", "image"]]


def test_pull_moves_on_to_the_next_tool_and_reports_every_failure(tmp_path, fake_tools):
    fake_tools["present"] = {"docker", "podman", "crane"}
    fake_tools["fail"] = {"docker image save", "docker pull", "podman image save", "podman pull"}     # 데몬이 둘 다 죽어 있다
    tar, tool = ip.pull_image("alpine:3.20", tmp_path)
    assert tool == "crane" and fake_tools["calls"][-1] == ["crane", "pull", "--platform", "linux/amd64", "alpine:3.20", str(tar)]

    fake_tools["fail"].add("crane pull")
    with pytest.raises(RunnerError) as e:
        ip.pull_image("alpine:3.20", tmp_path)
    lines = str(e.value).splitlines()
    assert lines[0] == "could not fetch alpine:3.20" and [line.split(":")[0] for line in lines[1:]] == ["docker", "podman", "crane"]
    assert lines[1] == "docker: docker pull exited with 1: Error: docker pull failed"


def test_pull_without_any_tool_says_which_are_needed(tmp_path, fake_tools):
    with pytest.raises(RunnerError, match=r"docker, podman or crane is needed to fetch alpine:3.20 \(or pass the image as a .tar\)"):
        ip.pull_image("alpine:3.20", tmp_path)
