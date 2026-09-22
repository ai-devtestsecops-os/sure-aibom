"""변환 문맥: 노드 저장소, 원소 순서, 확장 버퍼, 관계 빌더. 모든 모듈이 공유한다."""
from __future__ import annotations

import json
import re
from typing import Callable

from ._ids import IdRegistry, enc
from ._tables import CREATION_INFO_ID, FIXED_ENTRY_PRIORITY, KEY_ORDER

# @graph 의 카테고리 순서. 관계는 따로 종류별로 정렬한다.
CATEGORIES: tuple[str, ...] = ("tools", "agents", "root", "artifacts", "datasets", "licenses")
_NUM = re.compile(r"(\d+)")


def stringify(value) -> str:
    """확장 항목 값은 항상 문자열. bool/None 은 JSON 표기(true/false/null), 구조체는 정렬 JSON."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _natural(path: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in _NUM.split(path))


class ExtBuffer:
    """원소 하나의 extension_CdxPropertiesExtension 항목. 고정(aibom:cdx:*) → strict 승격분 → properties[] 원문."""

    def __init__(self) -> None:
        self.fixed: list[tuple[str, str]] = []
        self.typed: list[tuple[str, str]] = []
        self.props: list[tuple[str, str | None]] = []

    def fix(self, path: str, value) -> None:
        if value is None or value == "" or value == [] or value == {}:
            return
        self.fixed.append((f"aibom:cdx:{path}", stringify(value)))

    def prop(self, name: str, value) -> None:
        self.props.append((name, None if value is None else stringify(value)))

    def entries(self) -> list[dict]:
        def fixed_key(item: tuple[str, str]) -> tuple:
            path = item[0].removeprefix("aibom:cdx:")
            head = path.split(":", 1)[0]
            rank = FIXED_ENTRY_PRIORITY.index(head) if head in FIXED_ENTRY_PRIORITY else len(FIXED_ENTRY_PRIORITY)
            return (rank, _natural(path))

        ordered = sorted(self.fixed, key=fixed_key) + self.typed + self.props
        out: list[dict] = []
        seen: set[tuple] = set()
        for name, value in ordered:
            if (name, value) in seen:
                continue
            seen.add((name, value))
            entry = {"type": "extension_CdxPropertyEntry", "extension_cdxPropName": name}
            if value is not None:
                entry["extension_cdxPropValue"] = value
            out.append(entry)
        return out


class Ctx:
    def __init__(self, ns: str, *, strict: bool, log: Callable[[str], None]) -> None:
        self.ns = ns
        self.strict = strict
        self.log = log
        self.ids = IdRegistry(ns)
        self.nodes: dict[str, dict] = {}                       # spdxId → 노드
        self.order: dict[str, list[str]] = {c: [] for c in CATEGORIES}
        self.ext: dict[str, ExtBuffer] = {}
        self.key_iri: dict[str, str] = {}                      # 원시 키 → IRI (컴포넌트·서비스·데이터)
        self.iri_key: dict[str, str] = {}
        self.records: dict[str, dict] = {}                     # IRI → 원본 CycloneDX 객체
        self.component_iris: list[str] = []                    # 문서 순서의 컴포넌트 IRI (데이터셋 참조 해석용)
        self.rels: dict[tuple[str, str], dict] = {}            # (from IRI, 종류) → Relationship
        self.rel_order: list[tuple[str, str]] = []
        self.imports: dict[str, str] = {}                      # 외부 원소 IRI → 원본 BOM-Link (ExternalMap)
        self.sbom_agents: list[str] = []                       # 아티팩트가 참조한 Agent (Sbom.element 에 든다)
        self.usage: dict[tuple[str, int], str] = {}            # (모델 키, 데이터셋 인덱스) → usage 마커
        self.pending_pedigree: list[tuple[dict, str, str]] = []  # 2차 처리: (컴포넌트, IRI, 키)
        self.pending_datasets: list[tuple[dict, str, str]] = []
        self.doc_ext = ExtBuffer()                             # SpdxDocument 의 확장 (읽지 못한 timestamp 등)
        # 골격 조각은 컴포넌트보다 먼저 잡아 둔다 — bom-ref "SBOM" 인 컴포넌트가 있어도 Sbom 이 SPDXRef-SBOM 을 갖는다.
        self.sbom_iri = self.ids.iri("SBOM", ("Sbom", "SBOM"))
        self.agent_iri = self.ids.iri("Agent-aibom-cli", ("SoftwareAgent", "aibom-cli"))

    # -- 노드 ----------------------------------------------------------------
    def element(self, fragment: str, owner: tuple[str, str], node_type: str, category: str | None) -> tuple[str, dict, bool]:
        """IRI 를 정하고 노드를 만든다. 이미 있으면 (IRI, 노드, False)."""
        iri = self.ids.iri(fragment, owner)
        if iri in self.nodes:
            return iri, self.nodes[iri], False
        node = {"type": node_type, "spdxId": iri, "creationInfo": CREATION_INFO_ID}
        self.nodes[iri] = node
        if category:
            self.order[category].append(iri)
        return iri, node, True

    def ext_of(self, iri: str) -> ExtBuffer:
        return self.ext.setdefault(iri, ExtBuffer())

    def bind_key(self, key: str, iri: str, record: dict) -> None:
        self.key_iri[key] = iri
        self.iri_key[iri] = key
        self.records[iri] = record

    # -- 관계 ----------------------------------------------------------------
    def rel(self, from_iri: str, rtype: str, targets: list[str], *, comment: str | None = None,
            completeness: str | None = None) -> dict | None:
        """(from, 종류) 당 하나. 대상은 등장 순서로 합치고 중복은 버린다."""
        targets = [t for t in targets if t]
        if not targets:
            return None
        key = (from_iri, rtype)
        node = self.rels.get(key)
        if node is None:
            from_frag = fragment_of(from_iri)                  # 충돌 접미까지 포함한 실제 조각
            iri = self.ids.iri(f"Relationship-{rtype}-{from_frag}", ("Relationship", f"{rtype}:{from_iri}"))
            node = {"type": "Relationship", "spdxId": iri, "creationInfo": CREATION_INFO_ID,
                    "from": from_iri, "relationshipType": rtype, "to": []}
            self.rels[key] = node
            self.rel_order.append(key)
            self.nodes[iri] = node
        real = [t for t in targets if t != "NoneElement"]
        if real and node["to"] == ["NoneElement"]:              # 빈 dependsOn 마커 뒤에 실제 대상이 오면 마커를 거둔다
            node["to"] = []
            node.pop("completeness", None)
        if node["to"] and not real:                              # 실제 대상이 있는 관계에 NoneElement 는 넣지 않는다
            return node
        for t in real or targets:
            if t not in node["to"]:
                node["to"].append(t)
        if comment and "comment" not in node:
            node["comment"] = comment
        if completeness and real == []:
            node["completeness"] = completeness
        return node

    def add_import(self, external_iri: str, bomlink: str) -> None:
        self.imports.setdefault(external_iri, bomlink)

    def warn(self, msg: str) -> None:
        self.log(f"[spdx] {msg}")


def fragment_of(iri: str) -> str:
    """IRI 의 SPDXRef- 뒤 조각. 조각이 없는 IRI(SpdxDocument 등)는 enc 한 전체."""
    head, sep, frag = iri.rpartition("#SPDXRef-")
    return frag if sep else enc(iri)


def reorder(node: dict) -> dict:
    """키를 고정 순서로 다시 배열한다. 모르는 키는 뒤에 알파벳순, extension 은 항상 마지막."""
    known = [k for k in KEY_ORDER if k in node]
    rest = sorted(k for k in node if k not in KEY_ORDER and k != "extension")
    tail = ["extension"] if "extension" in node else []
    return {k: node[k] for k in known + rest + tail}
