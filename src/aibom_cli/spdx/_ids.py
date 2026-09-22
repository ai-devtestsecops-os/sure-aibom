"""원소 식별자 체계 (spdx_spec element_id_scheme + critique 수정).

NS   = serialNumber (urn:uuid 형식일 때 그대로), 아니면 내용 해시의 uuid5. uuid4·시계는 쓰지 않는다.
IRI  = NS + "#SPDXRef-" + 조각. SpdxDocument 만 NS 자체.
enc  = NFKD 로 접어 악센트 라틴(café → cafe)은 살리고, [A-Za-z0-9._-] 밖의 구간을 '-' 하나로. 비면, 절반 넘게 잃으면,
       또는 비ASCII 글자를 하나라도 잃으면 sha256 앞 8자리를 붙인다 (한 글자 CJK 이름 '앱'·'웹'이 같은 조각이 되지 않게).
충돌 = 다른 원시 키가 같은 조각이면 '-' + sha8(원시 키); 그래도 겹치면 ValueError. 같은 원시 키는 같은 원소.
예약 = SBOM 과 Agent-aibom-cli 는 변환 시작 시 먼저 잡아 두므로 같은 bom-ref 의 컴포넌트가 접미를 받는다.
       License-*/LicenseText-*/Relationship-*/Organization-* 등은 첫 요청자가 조각을 갖는다 — 그런 bom-ref 를 쓴
       컴포넌트가 있으면 뒤에 오는 라이선스·관계 쪽이 해시 접미를 받는다 (문서는 여전히 유효·결정적).
BOM-Link = urn:cdx:<serial>/<ver>#<ref> 는 이 변환기 체계의 IRI urn:uuid:<serial>#SPDXRef-<enc(ref)> 로 옮긴다.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from ..merge import identity

_UUID_URN = re.compile(r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FRAGMENT_BAD = re.compile(r"[^A-Za-z0-9._-]+")
_LICENSEREF_BAD = re.compile(r"[^A-Za-z0-9.-]+")
BOM_LINK = re.compile(r"^urn:cdx:(?P<serial>[0-9a-fA-F-]{36})/(?P<version>\d+)#(?P<ref>.+)$")


def sha8(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def enc(raw: str) -> str:
    """IRI 조각 인코더. 비ASCII 를 잃으면 해시를 붙여 서로 다른 이름이 같은 조각이 되지 않게 한다."""
    nfkd = unicodedata.normalize("NFKD", raw)
    folded = "".join(c for c in nfkd if c.isascii())              # 결합 부호(é 의 ´)는 손실로 치지 않는다
    lost = any(not c.isascii() and not unicodedata.combining(c) for c in nfkd)
    out = _FRAGMENT_BAD.sub("-", folded).strip("-")
    if not out or len(out) * 2 < len(raw) or lost:
        return f"{out or 'x'}-{sha8(raw)}"
    return out


def bomlink_iri(link: "re.Match[str]") -> str:
    """다른 BOM 의 BOM-Link → 그 BOM 을 이 변환기로 바꿨을 때 원소가 갖게 될 IRI."""
    return f"urn:uuid:{link['serial'].lower()}#SPDXRef-{enc(link['ref'])}"


def license_ref(name: str) -> str:
    """LicenseRef- idstring 은 [A-Za-z0-9.-] 만 허용한다 ('_' 도 안 된다)."""
    out = _LICENSEREF_BAD.sub("-", name).strip("-")
    return "LicenseRef-" + (out or "x-" + sha8(name))


def namespace(cdx: dict) -> str:
    serial = cdx.get("serialNumber")
    if isinstance(serial, str) and _UUID_URN.match(serial):
        return serial
    body = {k: v for k, v in cdx.items() if k != "serialNumber"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "aibom-cli:" + digest))


def key_of(obj: dict) -> str:
    """컴포넌트·서비스·데이터의 원시 키: bom-ref, 없으면 merge.identity."""
    ref = obj.get("bom-ref")
    return ref if isinstance(ref, str) and ref else identity(obj)


def tool_key(tool: dict) -> str:
    """도구의 원시 키: bom-ref → purl → name@version (컴포넌트와 같은 우선순위)."""
    return tool.get("bom-ref") or tool.get("purl") or f"{tool.get('name', '')}@{tool.get('version') or '0'}"


def iso_z(value) -> str | None:
    """CycloneDX timestamp → "YYYY-MM-DDTHH:MM:SSZ". 소수·오프셋 제거, naive 는 UTC 로 본다. 못 읽으면 None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class IdRegistry:
    """조각 → 소유자(종류, 원시 키). 같은 소유자는 같은 IRI, 다른 소유자는 해시 접미."""

    def __init__(self, ns: str) -> None:
        self.ns = ns
        self._owner: dict[str, tuple[str, str]] = {}

    def iri(self, fragment: str, owner: tuple[str, str]) -> str:
        return f"{self.ns}#SPDXRef-{self._claim(fragment, owner)}"

    def _claim(self, fragment: str, owner: tuple[str, str]) -> str:
        for candidate in (fragment, f"{fragment}-{sha8(owner[1])}"):
            current = self._owner.get(candidate)
            if current is None:
                self._owner[candidate] = owner
                return candidate
            if current == owner:
                return candidate
        raise ValueError(f"spdxId 충돌: {owner} 와 {self._owner[fragment]} 가 모두 SPDXRef-{fragment} 를 요구한다")
