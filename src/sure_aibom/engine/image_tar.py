"""컨테이너 이미지를 디렉터리로 푼다 (M-BOM·D-BOM 단계용).

cdxgen 은 대상이 이미지면 컨테이너 모드로 바뀌어 프로젝트 타입을 oci 로 강제하고 AI 수집을 건너뛴다. 그래서 이미지의
M-BOM·D-BOM 단계(cdxgen -t ai, model.py, dataset.py)는 이미지를 푼 디렉터리에 대해 돌린다. syft 는 이미지를 그대로 스캔한다.

    이미지 .tar (docker save, crane pull)        바로 푼다. 데몬도 네트워크도 필요 없다
    이미지 이름 (alpine:3.20, ghcr.io/org/img)   external/container_tools.py 가 .tar 로 받은 뒤 푼다

tar 의 안쪽 모양은 둘이다. docker save·crane 의 manifest.json (Config, Layers) 과 OCI 레이아웃 (index.json, blobs/).
레이어는 순서대로 겹쳐 쓰고 화이트아웃(.wh.<이름>, .wh..wh..opq)은 아래 레이어의 것을 지운다. 항목마다 tarfile 의
data 필터를 거쳐 경로 탈출·장치 파일을 막고, 이미지 안 절대 경로를 가리키는 심볼릭 링크는 푼 디렉터리 안을 가리키게 고친다.
"""
from __future__ import annotations

import json
import os
import shutil
import tarfile
from pathlib import Path

from ..exceptions import ImageExtractionError
from ..utils.host import host_arch

ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz")
WHITEOUT = ".wh."
OPAQUE = ".wh..wh..opq"
INDEX_MEDIA_TYPES = {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}
NAME_ANNOTATIONS = ("org.opencontainers.image.ref.name", "io.containerd.image.name")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def is_archive(target: str) -> bool:
    return target.lower().endswith(ARCHIVE_SUFFIXES)


# ── .tar → 디렉터리 ───────────────────────────────────────────────────────────

def extract_image(tar_path: Path, rootfs: Path) -> tuple[int, str | None]:
    """이미지 tar 의 레이어를 rootfs 에 순서대로 푼다. (레이어 수, 이미지 이름). 이름은 tar 에 적힌 것(RepoTags 등)이 없으면 None."""
    rootfs.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tar_path) as outer:
            members = {m.name.removeprefix("./"): m for m in outer.getmembers()}
            layers, name = _layers_of(outer, members)
            for layer_name in layers:
                if layer_name not in members:
                    raise ImageExtractionError(f"layer {layer_name} is missing")
                with outer.extractfile(members[layer_name]) as raw:
                    if raw.read(4) == ZSTD_MAGIC:
                        raise ImageExtractionError("zstd-compressed layers are not supported")
                    raw.seek(0)
                    with tarfile.open(fileobj=raw, mode="r:*") as layer:
                        _apply_layer(layer, rootfs)
    except (tarfile.TarError, OSError, ValueError, KeyError, TypeError) as e:
        raise ImageExtractionError(f"cannot unpack {tar_path.name}: {e}") from e
    return len(layers), name


def _layers_of(outer: tarfile.TarFile, members: dict[str, tarfile.TarInfo]) -> tuple[list[str], str | None]:
    """레이어 항목 이름들(순서대로)과 이미지 이름. manifest.json 이 있으면 그것(docker save, crane), 없으면 OCI index.json."""
    if "manifest.json" in members:
        entries = _json(outer, members, "manifest.json")
        if not isinstance(entries, list) or not entries:
            raise ImageExtractionError("manifest.json lists no image")
        entry = _for_this_machine(entries, lambda e: _platform_of(_json(outer, members, e.get("Config", ""))))
        tags = entry.get("RepoTags") or []
        return [layer.removeprefix("./") for layer in entry.get("Layers") or []], (tags[0] if tags else None)
    if "index.json" in members:
        manifest, name = _resolve_index(outer, members, _json(outer, members, "index.json"), None)
        return [_blob(layer["digest"]) for layer in manifest.get("layers") or []], name
    raise ImageExtractionError("not an image tar (no manifest.json or index.json)")


def _resolve_index(outer, members, index: dict, name: str | None) -> tuple[dict, str | None]:
    """OCI index → (이미지 매니페스트, 이름). 다중 플랫폼이면 이 머신의 것, 인덱스가 인덱스를 가리키면 따라 들어간다."""
    descriptors = index.get("manifests") or []
    if not descriptors:
        raise ImageExtractionError("index.json lists no image")
    chosen = _for_this_machine(descriptors, lambda d: _platform_of(d.get("platform") or {}))
    name = name or _name_of(chosen) or next((n for n in map(_name_of, descriptors) if n), None)
    manifest = _json(outer, members, _blob(chosen["digest"]))
    if chosen.get("mediaType") in INDEX_MEDIA_TYPES or "manifests" in manifest:
        return _resolve_index(outer, members, manifest, name)
    return manifest, name


def _name_of(descriptor: dict) -> str | None:
    annotations = descriptor.get("annotations") or {}
    return next((annotations[k] for k in NAME_ANNOTATIONS if annotations.get(k)), None)


def _for_this_machine(candidates: list[dict], platform_of) -> dict:
    """이 머신의 (os, arch) 와 맞는 것, 없으면 첫 번째."""
    wanted = ("linux", host_arch())
    for candidate in candidates:
        try:
            if platform_of(candidate) == wanted:
                return candidate
        except ImageExtractionError:
            continue
    return candidates[0]


def _platform_of(obj: dict) -> tuple[str, str]:
    return (str(obj.get("os", "")), str(obj.get("architecture", "")))


def _blob(digest: str) -> str:
    algorithm, _, hex_digest = digest.partition(":")
    return f"blobs/{algorithm}/{hex_digest}"


def _json(outer: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str):
    if name not in members:
        raise ImageExtractionError(f"{name} is missing")
    with outer.extractfile(members[name]) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ImageExtractionError(f"{name} is not JSON") from e


def _apply_layer(layer: tarfile.TarFile, rootfs: Path) -> None:
    """레이어 하나를 rootfs 위에 겹친다. 화이트아웃은 아래 레이어의 것만 지우므로 이 레이어의 항목보다 먼저 처리한다."""
    members = layer.getmembers()
    for m in members:
        directory, base = os.path.split(m.name)
        if base == OPAQUE:
            _remove_children(_inside(rootfs, directory))
        elif base.startswith(WHITEOUT):
            _remove(_inside(rootfs, os.path.join(directory, base[len(WHITEOUT):])))
    link_filter = _filter_for(rootfs)
    for m in members:
        if os.path.basename(m.name).startswith(WHITEOUT):
            continue
        target = _inside(rootfs, m.name)
        if target is None:
            continue
        _clear(target, m)
        try:
            layer.extract(m, path=rootfs, filter=link_filter)
        except (tarfile.FilterError, tarfile.ExtractError, OSError):
            continue            # 장치 파일, 밖을 가리키는 링크, 권한 문제는 건너뛴다


def _filter_for(rootfs: Path):
    root = str(rootfs)

    def _filter(member: tarfile.TarInfo, dest: str) -> tarfile.TarInfo | None:
        if member.issym() and member.linkname.startswith("/"):       # 이미지 안 절대경로 → 푼 디렉터리 안
            here = os.path.dirname(os.path.join(root, member.name.lstrip("/")))
            member = member.replace(linkname=os.path.relpath(os.path.join(root, member.linkname.lstrip("/")), here))
        return tarfile.data_filter(member, dest)

    return _filter


def _inside(rootfs: Path, name: str) -> str | None:
    """rootfs 안의 경로. 밖으로 나가면 None."""
    root = str(rootfs)
    path = os.path.normpath(os.path.join(root, name.lstrip("/")))
    return path if path == root or path.startswith(root + os.sep) else None


def _clear(target: str, member: tarfile.TarInfo) -> None:
    """아래 레이어의 항목과 종류가 다르면(파일 자리에 디렉터리, 링크 자리에 파일 등) 먼저 치운다. 링크를 통해 쓰지 않게."""
    if not os.path.lexists(target):
        return
    if member.isdir():
        if os.path.islink(target) or not os.path.isdir(target):
            os.unlink(target)
    else:
        _remove(target)


def _remove(path: str | None) -> None:
    if path is None or not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        os.unlink(path)


def _remove_children(path: str | None) -> None:
    if path is None or not os.path.isdir(path) or os.path.islink(path):
        return
    for child in os.listdir(path):
        _remove(os.path.join(path, child))
