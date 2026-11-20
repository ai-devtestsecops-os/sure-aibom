"""syft — 소프트웨어 생산자.

모델 카탈로거(ai 태그: gguf, safetensors)는 끈다. 모델은 cdxgen 이 맡는다.
    SYFT_COMPLIANCE_MISSING_VERSION=keep syft <target> --select-catalogers -ai -o cyclonedx-json@1.7=<out>

버전을 못 찾은 패키지(pom 의 버전 없는 의존성 등)에 syft 는 기본값으로 `UNKNOWN` 을 적는다. keep 이면 version 을 비워 둔다
(purl 은 어느 쪽이든 버전 없이 같다).

출력은 값을 더하지 않고 다음만 고친다 (도구 값의 정리라 출처는 syft 그대로다).
    파일 컴포넌트 이름        스캔에 넘긴 절대경로 → 스캔 루트 기준 (디렉터리 스캔만)
    evidence.occurrences     패키지를 찾은 파일 경로. syft 는 properties 의 syft:location:<i>:path 에만 둔다 (앞의 / 를 뺀다)
    licenses                 알아보지 못한 라이선스 본문의 sha256 을 이름으로 적은 자리표시자(sha256:<64자>)는 뺀다
    externalReferences       종류를 바로잡는다. npm package.json 의 repository.url 은 distribution → vcs,
                             apk 의 U:(프로젝트 주소)는 distribution → website. pip 의 file:// 설치 주소(로컬 경로)는 vcs 가 아니라 뺀다.
                             jar 의 해시를 url "" 인 build-meta 에 두는 것은 컴포넌트 hashes 로 옮긴다
나머지 syft:* properties 는 출력 직전에 지운다 (form.drop_tool_properties).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..utils.exceptions import RunnerError
from .common.proc import load_json_file, run

SPEC_VERSION = "1.7"
ENV = {"SYFT_COMPLIANCE_MISSING_VERSION": "keep"}

_LOCATION = re.compile(r"^syft:location:(\d+):path$")
_LICENSE_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
METADATA_TYPE = "syft:package:metadataType"
# 메타데이터 종류 → (syft 가 붙인 종류, 바른 종류)
REFERENCE_TYPE_FIXES = {
    "javascript-npm-package": ("distribution", "vcs"),       # package.json 의 repository.url
    "apk-db-entry": ("distribution", "website"),             # APKINDEX 의 U: (upstream 프로젝트 주소)
}


def run_syft(target: str, workdir: Path) -> dict:
    out = workdir / "syft.cdx.json"
    cmd = [
        "syft",
        target,
        "--select-catalogers", "-ai",
        "-o", f"cyclonedx-json@{SPEC_VERSION}={out}",
        "-q",
    ]
    proc = run(cmd, env=ENV)
    if proc.returncode != 0:
        raise RunnerError(f"syft exited with {proc.returncode}\n{proc.stderr[-2000:]}")
    doc = _relativize_file_components(load_json_file(out, "syft"), target)
    for comp in doc.get("components") or []:
        _tidy(comp)
    return doc


def _relativize_file_components(doc: dict, target: str) -> dict:
    """syft 는 패키지가 발견된 파일을 `type: file` 컴포넌트(해시 포함)로 내는데, 이름이 스캔 시
    넘긴 절대경로다. 패키지 쪽 `syft:location:N:path` 는 스캔 루트 기준(`/requirements.txt`)이라
    둘을 맞추고 스캔 머신의 경로가 BOM 에 새지 않게 한다. 디렉터리 스캔에만 해당한다."""
    root = str(Path(target).resolve())
    if not Path(root).is_dir():
        return doc
    for comp in doc.get("components") or []:
        name = comp.get("name") or ""
        if comp.get("type") == "file" and name.startswith(root):
            comp["name"] = "/" + name[len(root):].lstrip("/")
    return doc


def _tidy(comp: dict) -> None:
    """패키지 컴포넌트 하나를 제자리에서 고친다 (머리 설명의 표)."""
    props = {p.get("name"): p.get("value") for p in comp.get("properties") or [] if isinstance(p, dict)}
    _evidence_from_locations(comp)
    licenses = [entry for entry in comp.get("licenses") or []
                if not _LICENSE_HASH.match(str(((entry or {}).get("license") or {}).get("name") or ""))]
    if "licenses" in comp:
        if licenses:
            comp["licenses"] = licenses
        else:
            del comp["licenses"]
    refs = []
    for ref in comp.get("externalReferences") or []:
        fix = REFERENCE_TYPE_FIXES.get(props.get(METADATA_TYPE))
        if fix and ref.get("type") == fix[0]:
            ref = {**ref, "type": fix[1]}
        if ref.get("type") == "vcs" and str(ref.get("url") or "").startswith("file:"):
            continue
        if ref.get("type") == "build-meta" and not ref.get("url"):
            _add_hashes(comp, ref.get("hashes") or [])
            continue
        refs.append(ref)
    if "externalReferences" in comp:
        if refs:
            comp["externalReferences"] = refs
        else:
            del comp["externalReferences"]


def _evidence_from_locations(comp: dict) -> None:
    found = []
    for p in comp.get("properties") or []:
        m = _LOCATION.match(str(p.get("name") or "")) if isinstance(p, dict) else None
        if m and isinstance(p.get("value"), str) and p["value"].strip("/"):
            found.append((int(m[1]), p["value"].lstrip("/")))
    if not found:
        return
    occurrences = comp.setdefault("evidence", {}).setdefault("occurrences", [])
    known = {o.get("location") for o in occurrences}
    for _, location in sorted(found):
        if location not in known:
            occurrences.append({"location": location})
            known.add(location)


def _add_hashes(comp: dict, hashes: list[dict]) -> None:
    have = {(h.get("alg"), h.get("content")) for h in comp.get("hashes") or []}
    new = [h for h in hashes if isinstance(h, dict) and h.get("alg") and h.get("content") and (h["alg"], h["content"]) not in have]
    if new:
        comp["hashes"] = (comp.get("hashes") or []) + new
