"""aibom-cli scan 을 단계마다 가로채, 최종 BOM 의 값 하나하나가 어느 도구에서 왔는지 따라간다 (tests/test_fields.py 가 쓴다).

단계와 출처:
    run_syft · run_cdxgen    도구 출력 (runners/*.py 의 정리까지 끝난 것)을 원본으로 둔다
    merge                    값마다, 병합 키가 같은 원본 컴포넌트의 같은 자리에 같은 값이 있으면 그 도구, 없으면 aibom-cli.
                             컴포넌트 bom-ref 는 병합 키라 aibom-cli. 문서 머리·metadata.component 는 aibom-cli 가 쓰고, 그 가운데
                             이미지 OCI 라벨에서 옮긴 자리는 syft. metadata.tools · services 는 같은 자리에 같은 값을 낸 도구,
                             dependencies 는 그 관계를 낸 도구 (병합 키로 바꿔 비교)
    discover_services · discover_datasets · discover_models    새 값은 aibom-cli
    enrich                   modelCard.properties 에 새로 든 값은 OWASP aibom-generator, 나머지(Hub API 로 채운 필드) 는 aibom-cli
    regulate (form)          새 값은 그 자리를 채우는 원본 키 가운데 같은 값을 가진, 소비된 프로퍼티의 도구 (같으면 OWASP > cdxgen > aibom-cli)
값 단위 규칙: 단계 뒤의 값이 단계 앞에도 있던 값이면 앞의 출처를 잇고, 새 값이면 그 단계의 도구가 출처다.
컴포넌트는 단계 사이에서 같은 dict 가 제자리에서 바뀌므로 숨은 표지(MARK)로 단계 전후를 맞춘다. 표지는 출력 직전에 뗀다.

자리 경로는 인스턴스 JSON 경로에서 배열 번호를 뺀 것이다 (components.modelCard.modelParameters.task). 필드 탐색기의
CycloneDX 트리 경로(docs/mapping-viewer/app.js 의 sitePath)와 같은 모양이다.
"""
from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import PurePosixPath

import aibom_cli.cli as cli
from aibom_cli.enrich import LOCAL_MODEL_FILES, LOCAL_MODEL_SUFFIXES
from aibom_cli.form import HYPERPARAMETER_BY_PROPERTY, INTERNAL_MODEL_PREFIX, INTERNAL_PREFIX
from aibom_cli.merge import _walk_components, identity

MARK = "\x00mark"
SYFT, CDXGEN, OWASP, CLI = "syft", "cdxgen", "OWASP aibom-generator", "aibom-cli"
TOOL_ORDER = (SYFT, CDXGEN, OWASP, CLI)
PRIORITY = (OWASP, CDXGEN, CLI)
ROOT_FROM_CLI = ("metadata.component.type", "metadata.component.name", "metadata.component.bom-ref")
# typed 자리 → 그 자리를 채우는 원본 키 (form.py 와 같은 규칙). 목록에 없는 자리는 모든 원본과 맞춰 본다
SOURCES_BY_TARGET = (
    ("hyperparameters", ("genai:aibom:modelcard:hyperparameter", *HYPERPARAMETER_BY_PROPERTY, INTERNAL_MODEL_PREFIX + "hyperparameters:")),
    ("parameterCount", ("safetensors_total_parameters", "cdx:ai:parameterCount", INTERNAL_MODEL_PREFIX + "parameterCount")),
    ("maxSize", ("genai:aibom:modelcard:contextLength", "cdx:ai:contextWindow", INTERNAL_MODEL_PREFIX + "maxSize")),
    ("technicalRequirements", ("owasp:aibom:distribution:runtimeRequirement", "cdx:ai:runtime")),
    ("data.", (INTERNAL_PREFIX,)),
)


def leaves(value, path: str = "") -> list[tuple[str, str]]:
    """(자리 경로, 값의 JSON) 목록. 빈 문자열과 null 은 값이 아니다."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k != MARK:
                out += leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for v in value:
            out += leaves(v, path)
    elif value is not None and value != "":
        out.append((path, json.dumps(value, sort_keys=True, ensure_ascii=False)))
    return out


def grouped(pairs) -> dict[str, list[str]]:
    out = defaultdict(list)
    for path, value in pairs:
        out[path].append(value)
    return out


def doc_part(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "components"}


def props_of(comp: dict) -> list[tuple]:
    return [(p.get("name"), p.get("value")) for p in (comp.get("properties") or []) + ((comp.get("modelCard") or {}).get("properties") or [])]


class Tracker:
    def __init__(self) -> None:
        self.n = 0
        self.attr: dict = {}         # 표지 → {자리: {값: {도구}}}, "doc" → 문서 자리
        self.raw: dict[str, dict] = {}

    def mark_all(self, doc: dict) -> None:
        for comp in doc.get("components") or []:
            if MARK not in comp:
                self.n += 1
                comp[MARK] = self.n

    def snapshot(self, doc: dict) -> dict:
        snap = {"doc": grouped(leaves(doc_part(doc)))}
        for comp in doc.get("components") or []:
            snap[comp[MARK]] = grouped(leaves(comp))
        return snap

    def after_merge(self, merged: dict) -> None:
        by_key = defaultdict(list)
        for tool, raw in self.raw.items():
            for c in _walk_components(raw.get("components") or []):
                by_key[identity(c)].append((tool, grouped(leaves(c))))
        self.mark_all(merged)
        for comp in merged["components"]:
            sources = by_key.get(comp["bom-ref"], [])
            self.attr[comp[MARK]] = {
                path: {v: ({CLI} if path == "bom-ref" else ({t for t, g in sources if v in g.get(path, ())} or {CLI})) for v in values}
                for path, values in grouped(leaves(comp)).items()}
        raw_docs = {t: grouped(leaves(doc_part(r))) for t, r in self.raw.items()}
        tool_entries: dict[tuple[str, str], set[str]] = defaultdict(set)      # 도구 목록은 항목 단위로 (aibom-cli 항목의 type 이 도구 항목과 값이 같다)
        for entry in ((merged.get("metadata") or {}).get("tools") or {}).get("components") or []:
            owners = {t for t, r in self.raw.items() if entry in (((r.get("metadata") or {}).get("tools") or {}).get("components") or [])} or {CLI}
            for pair in leaves(entry, "metadata.tools.components"):
                tool_entries[pair] |= owners
        doc_attr = {}
        for path, values in grouped(leaves(doc_part(merged))).items():
            doc_attr[path] = {}
            for v in values:
                if path.startswith("dependencies."):
                    tools = self._dependency_tools(v)
                elif path.startswith("metadata.tools."):
                    tools = tool_entries.get((path, v), set())
                elif path.startswith("services."):
                    tools = {t for t, g in raw_docs.items() if v in g.get(path, ())}
                elif path.startswith("metadata.component.") and path not in ROOT_FROM_CLI:
                    tools = {SYFT}                                               # merge._apply_image_labels 가 syft 의 OCI 라벨에서 옮긴 자리
                else:
                    tools = set()
                doc_attr[path][v] = tools or {CLI}
        self.attr["doc"] = doc_attr

    def _dependency_tools(self, value: str) -> set[str]:
        tools = set()
        for tool, raw in self.raw.items():
            remap = {c.get("bom-ref"): identity(c) for c in _walk_components(raw.get("components") or [])}
            root = ((raw.get("metadata") or {}).get("component") or {}).get("bom-ref")
            for row in raw.get("dependencies") or []:
                for ref in [row.get("ref"), *(row.get("dependsOn") or [])]:
                    if ref != root and json.dumps(remap.get(ref, ref)) == value:
                        tools.add(tool)
        return tools

    def stage(self, doc: dict, run, tool_of):
        self.mark_all(doc)
        before_props = {c[MARK]: props_of(c) for c in doc.get("components") or []}
        out = run()
        self.mark_all(out)
        now = self.snapshot(out)
        consumed = {}
        for c in out.get("components") or []:
            after = set(props_of(c))
            consumed[c[MARK]] = [p for p in before_props.get(c[MARK], []) if p not in after]
        new = {}
        for mark, paths in now.items():
            old = self.attr.get(mark, {})
            new[mark] = {path: {v: (old.get(path, {}).get(v) or tool_of(path, v, consumed.get(mark, []))) for v in values}
                         for path, values in paths.items()}
        self.attr = new
        return out


def tool_entries(doc: dict) -> list[dict]:
    """문서의 도구 목록 항목 (사본)."""
    return copy.deepcopy(((doc.get("metadata") or {}).get("tools") or {}).get("components") or [])


def enrich_tool(path: str, value: str, consumed) -> set[str]:
    """보강 단계에서 새로 생긴 값. 규제 필드 원본과, 원본을 가져다 쓴 aibom-generator 가 자기를 적은 도구 항목은 OWASP 의 값이다."""
    return {OWASP} if path.startswith(("modelCard.properties", "metadata.tools")) else {CLI}


def form_tool(path: str, value: str, consumed) -> set[str]:
    plain = str(json.loads(value))
    allowed = next((keys for target, keys in SOURCES_BY_TARGET if target in path), None)
    found = set()
    for name, raw in consumed:
        if not isinstance(name, str) or (allowed is not None and not name.startswith(allowed)):
            continue
        tool = (OWASP if name.startswith(("genai:aibom:", "owasp:aibom:")) or name == "safetensors_total_parameters"
                else CDXGEN if name.startswith("cdx:ai:") else CLI if name.startswith("aibom-internal:") else None)
        if tool is None:
            continue
        texts = {str(raw)}
        if name in HYPERPARAMETER_BY_PROPERTY:
            texts.add(HYPERPARAMETER_BY_PROPERTY[name])
        try:
            obj = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else None
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            texts |= {str(k) for k in obj} | {str(v) for v in obj.values()}
        if plain in texts:
            found.add(tool)
    return {next((t for t in PRIORITY if t in found), CLI)}


def traced_scan(argv: list[str]) -> tuple[dict, Tracker]:
    """cli.main(argv) 를 단계마다 가로채 돌린다. (최종 문서, Tracker) — 최종 문서의 컴포넌트에는 표지가 붙어 있다."""
    tracker = Tracker()
    real = {n: getattr(cli, n) for n in ("run_syft", "run_cdxgen", "merge", "discover_services", "discover_datasets", "discover_models",
                                         "enrich", "regulate", "_emit")}
    final: dict = {}

    def raw_of(name, tool):
        def run(target, workdir):
            doc = real[name](target, workdir)
            tracker.raw[tool] = copy.deepcopy(doc)
            return doc
        return run

    def merge(docs, root=None, **k):
        out = real["merge"](docs, root=root, **k)
        tracker.after_merge(out)
        return out

    def staged(name, tool_of):
        return lambda doc, *a, **k: tracker.stage(doc, lambda: real[name](doc, *a, **k), tool_of)

    def enrich(doc, *a, **k):
        before = tool_entries(doc)
        out = tracker.stage(doc, lambda: real["enrich"](doc, *a, **k), enrich_tool)
        # 도구 목록은 항목 단위로 본다 (merge 와 같다): 새로 더해진 항목의 칸은 값이 다른 항목과 같아도(type) 그 항목을 낸 도구의 것이다
        for entry in tool_entries(out):
            if entry not in before:
                for path, v in leaves(entry, "metadata.tools.components"):
                    tracker.attr["doc"].setdefault(path, {}).setdefault(v, set()).update(enrich_tool(path, v, []))
        return out

    def emit(doc, output):
        final["doc"] = doc
        clean = copy.deepcopy(doc)
        for c in clean.get("components") or []:
            c.pop(MARK, None)
        return real["_emit"](clean, output)

    patched = dict(run_syft=raw_of("run_syft", SYFT), run_cdxgen=raw_of("run_cdxgen", CDXGEN), merge=merge,
                   discover_services=staged("discover_services", lambda *_: {CLI}),
                   discover_datasets=staged("discover_datasets", lambda *_: {CLI}), discover_models=staged("discover_models", lambda *_: {CLI}),
                   enrich=enrich, regulate=staged("regulate", form_tool), _emit=emit)
    try:
        for name, fn in patched.items():
            setattr(cli, name, fn)
        code = cli.main(argv)
    finally:
        for name, fn in real.items():
            setattr(cli, name, fn)
    assert code == 0, f"scan exited {code}"
    return final["doc"], tracker


def component_kind(comp: dict, tools: set[str]) -> str:
    kind = comp.get("type")
    if kind == "machine-learning-model":
        locations = [o.get("location") for o in (comp.get("evidence") or {}).get("occurrences") or [] if isinstance(o, dict)]
        names = [PurePosixPath(str(loc).split("#", 1)[0]).name.lower() for loc in locations if loc]
        return "모델(로컬 파일)" if any(n in LOCAL_MODEL_FILES or n.endswith(LOCAL_MODEL_SUFFIXES) for n in names) else "모델(코드 참조)"
    if kind == "data":
        return "데이터셋(로컬)" if str(comp.get("bom-ref") or "").startswith("data:local/") else "데이터셋(허브)"
    if kind == "file":
        return "파일"
    if kind == "operating-system":
        return "운영체제"
    if SYFT in tools:
        return "패키지"
    if any("huggingface.co/spaces/" in str(r.get("url")) for r in comp.get("externalReferences") or []):
        return "Space"
    return kind or "?"


def site_sources(doc: dict, tracker: Tracker) -> dict[str, set[tuple[str, str]]]:
    """최종 문서의 자리마다 {(도구, 대상 종류)}. 출처는 최종 문서에 남은 값만 본다 (출력 직전에 지운 properties 는 빠진다)."""
    out: dict[str, set] = defaultdict(set)
    doc_attr = tracker.attr.get("doc", {})
    for path, value in leaves(doc_part(doc)):
        kind = ("스캔 대상 (이미지 라벨)" if path.startswith("metadata.component.") and path not in ROOT_FROM_CLI
                else "스캔 대상" if path.startswith("metadata.component") else "도구 목록" if path.startswith("metadata.tools")
                else "서비스" if path.startswith("services") else "관계" if path.startswith("dependencies") else "문서")
        for tool in doc_attr.get(path, {}).get(value) or {CLI}:
            out[path].add((tool, kind))
    for comp in doc.get("components") or []:
        attr = tracker.attr.get(comp.get(MARK), {})
        pairs = leaves(comp)
        tools = {t for path, value in pairs for t in attr.get(path, {}).get(value) or ()}
        kind = component_kind(comp, tools)
        for path, value in pairs:
            for tool in attr.get(path, {}).get(value) or {CLI}:
                out[f"components.{path}"].add((tool, kind))
    return out


def as_rows(*site_maps: dict) -> list[dict]:
    """필드 탐색기 데이터: [{site, sources: [{tool, kinds}]}]. 자리 경로 순, 도구는 TOOL_ORDER 순, 종류는 가나다 순. 여러 스캔은 합친다."""
    merged: dict[str, set] = defaultdict(set)
    for sites in site_maps:
        for site, pairs in sites.items():
            merged[site] |= pairs
    rows = []
    for site in sorted(merged):
        by_tool = defaultdict(set)
        for tool, kind in merged[site]:
            by_tool[tool].add(kind)
        rows.append({"site": site, "sources": [{"tool": t, "kinds": sorted(by_tool[t])} for t in TOOL_ORDER if t in by_tool]})
    return rows
