"""앞 단계들이 모아 둔 값을 aibom-v0.6 필드로 옮긴다. 형태(properties·typed) 스위치는 여기 하나다.
값을 찾아내는 일은 dataset.py · model.py 가 하고, 여기서는 어느 자리에 어떤 모양으로 넣을지만 정한다.

모델(type=machine-learning-model): 가져오는 값은 전부 component.properties / component.modelCard.properties 에 있는
것이다 — 조회·추론·본문 해석은 하지 않는다. hyperparameters · parameterCount · inputs maxSize 는 model.py 가 대상 안의 모델
파일과 Hub API 응답에서 읽어 둔 aibom-internal:model:* 도 원본으로 쓴다 (도구가 준 값이 먼저이고, 내부 키는
이기든 지든 전부 지운다).

    v0.6 필드                 typed 형 (modelCard.…)                         properties 형 (modelCard.properties)
    hyperparameters           modelParameters.hyperparameters[]{name,value}  aibom:model:hyperparameters:<i>:name / :value
    parameterCount            modelParameters.parameterCount (integer)       aibom:model:parameterCount
    inputs maxSize            modelParameters.inputs[0].maxSize (string)     aibom:model:inputs:0:maxSize
    technicalRequirements     considerations.technicalRequirements[]         aibom:model:technicalRequirements:<i>

데이터셋(type=data): dataset.py 가 컴포넌트에 둔 aibom-internal:dataset:* 프로퍼티가 원본이다. 내부 키는 이기든 지든
전부 지운다 — 출력에 남지 않는다.

    v0.6 필드                 typed 형 (data[0].…)                           properties 형 (component.properties)
    size                      size (integer)                                 aibom:dataset:size
    modality                  modality[] (enum)                              aibom:dataset:modality:<i>
    availability              contents.availability (enum)                   aibom:dataset:availability
    intendedUse               intendedUse (string)                           aibom:dataset:intendedUse
    collectionProcess         collectionProcess (string)                     aibom:dataset:collectionProcess
    provenance                provenance[]                                   aibom:dataset:provenance:<i>
    statistics                statistics[]{type,value}                       aibom:dataset:statistics:<i>:type / :value

승격하면 소비한다: 값이 목표에 쓰인 원본 프로퍼티는 두 목록에서 모두 지운다 — 한 값이 출력에 두 번 나오지 않는다.
쓰지 않은 프로퍼티는 그대로 둔다. 원본끼리 값이 다르면 우선순위 앞의 것을 쓰고, 진 쪽은 남기고 로그에 적는다.
남은 도구 프로퍼티(syft:*, cdx:*, genai:*, owasp:* …)는 그 뒤 drop_tool_properties 가 출력 직전에 모두 지운다 — 출력의
properties 는 aibom:* 뿐이다.
목표에 이미 값이 있으면 그 값이 이긴다 (두 번 돌려도 결과가 같다 — 두 번째는 원본이 남아 있지 않다).

건드리는 범위는 승격한 값만이다: 목록 필드는 기존 항목 뒤에 덧붙이고(이름 없는 항목도 그대로 남긴다), 스칼라 필드는
비어 있을 때만 쓰며, 소비해서 비어 버린 목록·modelCard 만 없앤다. 원본이 하나도 없는 컴포넌트는 바이트 단위로 같다.

완성도: report 를 주면 컴포넌트마다 "채울 수 있는 규제 필드" 가운데 채운 수를 센다. 모델은 위 네 필드, 허브 데이터셋은
위 일곱 필드, 로컬 데이터는 파일만 보고 알 수 있는 size·modality·statistics 셋이 분모다. v0.6 의 나머지 필드(sure-aibom 이
아직 읽지 않는 것)는 세지 않는다.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from ..log import detail
from .common.component import (DATA_TYPE, HYPERPARAMETER_BY_PROPERTY, HYPERPARAMETER_JSON, INTERNAL_MODEL_PREFIX, INTERNAL_PREFIX,
                               MODEL_TYPE)

FORMS = ("properties", "typed")
OUTPUT_PREFIX = "aibom:"                                          # 출력에 남는 properties (정의서의 키)
PREFIX = "aibom:model:"
DATASET_PREFIX = "aibom:dataset:"
MODALITIES = frozenset({"image", "text", "audio", "video", "sensor", "timeseries", "timestamp", "structured", "categorical",
                        "graph", "syntactic", "numeric", "other"})
AVAILABILITIES = frozenset({"clickthrough", "direct-download", "query", "registration", "scraping-script"})

# 하이퍼파라미터의 원본 키(HYPERPARAMETER_JSON, HYPERPARAMETER_BY_PROPERTY)와 내부 키 접두어는 model.py 도 쓰므로 common/component.py 에 있다
# 단일 값 필드 — 우선순위 순
PARAMETER_COUNT_SOURCES = ("safetensors_total_parameters", "cdx:ai:parameterCount")
MAX_SIZE_SOURCES = ("genai:aibom:modelcard:contextLength", "cdx:ai:contextWindow")
# 목록 필드 — 있는 것을 모두 합친다 (중복 제거)
TECHNICAL_REQUIREMENT_SOURCES = ("owasp:aibom:distribution:runtimeRequirement", "cdx:ai:runtime")

_NON_NEGATIVE_INT = re.compile(r"^\+?\d+$")

# 완성도 — 컴포넌트 종류별로 채울 수 있는 규제 필드
MODEL_FIELDS = ("hyperparameters", "parameterCount", "inputs maxSize", "technicalRequirements")
DATASET_FIELDS = ("size", "modality", "availability", "provenance", "intendedUse", "collectionProcess", "statistics")
LOCAL_DATASET_FIELDS = ("size", "modality", "statistics")        # 나머지는 파일만 보고 알 수 없다
LOCAL_DATASET_REF = "data:local/"
HF_DATASETS_PURL = "pkg:huggingface/datasets/"


# ── 진입점 ──────────────────────────────────────────────────────────────────

def regulate(doc: dict, form: str = "properties", report: dict | None = None) -> dict:
    """문서를 제자리에서 고치고 돌려준다. form 은 "properties"(기본) 또는 "typed".
    report 를 주면 완성도를 적는다: {"models": {"filled", "total"}, "datasets": {…}, "filled", "total"}."""
    if form not in FORMS:
        raise ValueError(f"form 은 {FORMS} 중 하나여야 한다: {form!r}")
    for comp in _walk(doc.get("components") or []):
        if comp.get("type") == MODEL_TYPE:
            _apply_component(comp, form)
        elif comp.get("type") == DATA_TYPE:
            _apply_dataset(comp, form)
    if report is not None:
        report.update(_coverage_report(doc, form))
    return doc


def drop_tool_properties(doc: dict) -> dict:
    """문서 어디에 있든 properties 목록에서 aibom:* 가 아닌 항목을 지운다. 비어 버린 목록과, 그래서 비어 버린 객체(properties 만
    있던 environmentalConsiderations 등)는 없앤다. 원래 비어 있던 것은 그대로 둔다.
    도구가 낸 properties 가운데 믿을 만한 것은 앞 단계에서 정규 필드나 규제 필드로 옮겼다 (syft.py · cdxgen.py
    · merge.py · form). 나머지는 값과 뜻을 sure-aibom 이 관리하지 않으므로 내보내지 않는다."""
    def walk(node) -> bool:
        """node 가 이번에 지워서 빈 객체가 되었으면 True."""
        if isinstance(node, list):
            for value in node:
                walk(value)
            return False
        if not isinstance(node, dict):
            return False
        removed = False
        props = node.get("properties")
        if isinstance(props, list):
            kept = [p for p in props if isinstance(p, dict) and str(p.get("name") or "").startswith(OUTPUT_PREFIX)]
            if kept:
                node["properties"] = kept
            else:
                del node["properties"]
                removed = True
        for key in list(node):
            if walk(node[key]):
                del node[key]
                removed = True
        return removed and not node
    walk(doc)
    return doc


def _coverage(comp: dict, form: str) -> tuple[list[str], list[str]] | None:
    """컴포넌트의 규제 필드 가운데 (채운 것, 빈 것). 모델·데이터셋이 아니면 None."""
    if comp.get("type") == MODEL_TYPE:
        target = (_TypedTarget if form == "typed" else _PropertiesTarget)(comp)
        fields = MODEL_FIELDS
        filled = {"hyperparameters": bool(target.get_hyperparameters()),
                  "parameterCount": target.get_parameter_count() is not None,
                  "inputs maxSize": target.get_max_size() is not None,
                  "technicalRequirements": bool(target.get_technical_requirements())}
    elif comp.get("type") == DATA_TYPE and _is_dataset(comp):
        target = (_DatasetTypedTarget if form == "typed" else _DatasetPropertiesTarget)(comp)
        fields = LOCAL_DATASET_FIELDS if str(comp.get("bom-ref") or "").startswith(LOCAL_DATASET_REF) else DATASET_FIELDS
        filled = {f: (bool(target.get_statistics()) if f == "statistics"
                      else bool(target.get_list(f)) if f in ("modality", "provenance")
                      else target.get_scalar(f) is not None) for f in fields}
    else:
        return None
    return [f for f in fields if filled[f]], [f for f in fields if not filled[f]]


def _is_dataset(comp: dict) -> bool:
    """type=data 중 데이터셋 — data[] 에 dataset 항목이 있거나 허브 데이터셋 purl 이 있다 (cdxgen 의 apt 저장소 설정은 아니다)."""
    return any(isinstance(d, dict) and d.get("type") == "dataset" for d in comp.get("data") or []) \
        or str(comp.get("purl") or "").startswith(HF_DATASETS_PURL)


def _coverage_report(doc: dict, form: str) -> dict:
    report = {"models": {"filled": 0, "total": 0}, "datasets": {"filled": 0, "total": 0}}
    for comp in _walk(doc.get("components") or []):
        found = _coverage(comp, form)
        if found is None:
            continue
        filled, missing = found
        bucket = report["models" if comp.get("type") == MODEL_TYPE else "datasets"]
        bucket["filled"] += len(filled)
        bucket["total"] += len(filled) + len(missing)
        if missing:
            label = comp.get("bom-ref") or comp.get("name") or "?"
            detail(f"[form] {label}: {len(filled)}/{len(filled) + len(missing)} regulation fields filled, missing {', '.join(missing)}")
    report["filled"] = report["models"]["filled"] + report["datasets"]["filled"]
    report["total"] = report["models"]["total"] + report["datasets"]["total"]
    return report


def _walk(components: Iterable[dict]):
    for c in components:
        yield c
        yield from _walk(c.get("components") or [])


def _apply_component(comp: dict, form: str) -> None:
    label = comp.get("bom-ref") or comp.get("name") or "?"
    target = (_TypedTarget if form == "typed" else _PropertiesTarget)(comp)
    consumed: list[dict] = []
    consumed += _hyperparameters(comp, target, label)
    consumed += _parameter_count(comp, target, label)
    consumed += _max_size(comp, target, label)
    consumed += _technical_requirements(comp, target, label)
    consumed += _internal(comp)                                   # 내부 키는 이기든 지든 전부 지운다
    if consumed:                                                  # 아무것도 소비하지 않았으면 컴포넌트에 손대지 않는다
        _remove(comp, consumed)
        target.finish()


# ── 원본 프로퍼티 찾기·지우기 ────────────────────────────────────────────────

def _sources(comp: dict, name: str) -> list[dict]:
    """component.properties 와 modelCard.properties 양쪽에서 이름이 같은 프로퍼티(원본 객체)를 찾는다."""
    lists = (comp.get("properties") or [], (comp.get("modelCard") or {}).get("properties") or [])
    return [p for props in lists for p in props if p.get("name") == name and isinstance(p.get("value"), str)]


def _internal(comp: dict) -> list[dict]:
    """model.py 가 둔 aibom-internal:model:* 프로퍼티 (원본 객체)."""
    return [p for p in comp.get("properties") or []
            if isinstance(p.get("name"), str) and p["name"].startswith(INTERNAL_MODEL_PREFIX)
            and isinstance(p.get("value"), str)]


def _remove(comp: dict, consumed: list[dict]) -> None:
    ids = {id(p) for p in consumed}
    _remove_from(comp, ids)
    card = comp.get("modelCard")
    if card:
        _remove_from(card, ids)


def _remove_from(owner: dict, ids: set[int]) -> None:
    """owner.properties 에서 소비한 항목을 지운다. 그래서 비어 버린 목록만 없앤다 — 원래 비어 있던 목록은 그대로 둔다."""
    props = owner.get("properties")
    if not props:
        return
    owner["properties"] = [p for p in props if id(p) not in ids]
    if not owner["properties"]:
        del owner["properties"]


def _resolve(existing, candidates: list[tuple[object, dict]], field: str, label: str) -> tuple[object, list[dict]]:
    """단일 값: 목표에 있는 값, 없으면 우선순위 첫 후보가 이긴다. 이긴 값과 같은 후보만 소비하고 다른 후보는 남기며 로그에 적는다."""
    winner = existing if existing is not None else (candidates[0][0] if candidates else None)
    consumed: list[dict] = []
    for value, prop in candidates:
        if value == winner:
            consumed.append(prop)
        else:
            verb = "dropped" if prop["name"].startswith(INTERNAL_MODEL_PREFIX) else "left as is"
            detail(f"[form] {label}: {field}: {prop['name']}={prop['value']!r} differs from {winner!r}, {verb}")
    return winner, consumed


# ── 필드별 ───────────────────────────────────────────────────────────────────

def _hyperparameters(comp: dict, target: "_Target", label: str) -> list[dict]:
    by_name: dict[str, str] = {e["name"]: e["value"] for e in target.get_hyperparameters()}
    added: list[dict] = []                                        # 새로 붙이는 항목만 — 기존 항목은 손대지 않는다
    consumed: list[dict] = []

    def take(name: str, value: str) -> bool:
        """이름이 없으면 추가, 같은 값이면 이미 있는 것으로 침. 값이 다르면 False."""
        if name not in by_name:
            by_name[name] = value
            added.append({"name": name, "value": value})
        return by_name[name] == value

    # JSON 객체 문자열은 키 하나라도 어긋나면 통째로 남긴다 (일부만 지울 수 없고, 값이 두 곳에 나오면 안 된다)
    for prop in _sources(comp, HYPERPARAMETER_JSON):
        parsed = _json_object(prop["value"])
        if parsed is None:
            detail(f"[form] {label}: {HYPERPARAMETER_JSON} is not a JSON object, left as is")
            continue
        pairs = {k: _stringify(v) for k, v in parsed.items()}
        conflicts = {k: v for k, v in pairs.items() if k in by_name and by_name[k] != v}
        if conflicts:
            detail(f"[form] {label}: hyperparameters {sorted(conflicts)} differ from existing values, {HYPERPARAMETER_JSON} left as is")
            continue
        for k, v in pairs.items():
            take(k, v)
        consumed.append(prop)
    for source, name in HYPERPARAMETER_BY_PROPERTY.items():
        for prop in _sources(comp, source):
            if take(name, prop["value"]):
                consumed.append(prop)
            else:
                detail(f"[form] {label}: hyperparameters[{name}]={prop['value']!r} differs from {by_name[name]!r}, {source} left as is")
    for name, value in _Bag(_internal(comp), INTERNAL_MODEL_PREFIX).named_pairs("hyperparameters"):
        if not take(name, value):                                 # 내부 키는 뒤에 본다 — 도구가 준 값이 먼저다
            detail(f"[form] {label}: hyperparameters[{name}]={value!r} differs from {by_name[name]!r}, dropped")
    if added:
        target.add_hyperparameters(added)
    return consumed


def _parameter_count(comp: dict, target: "_Target", label: str) -> list[dict]:
    candidates: list[tuple[object, dict]] = []
    internal = [p for p in _internal(comp) if p["name"] == INTERNAL_MODEL_PREFIX + "parameterCount"]
    for prop in [p for source in PARAMETER_COUNT_SOURCES for p in _sources(comp, source)] + internal:
        n = _non_negative_int(prop["value"])
        if n is None:
            detail(f"[form] {label}: {prop['name']}={prop['value']!r} is not a non-negative integer, not promoted")
        else:
            candidates.append((n, prop))
    existing = target.get_parameter_count()
    if existing is not None and not isinstance(existing, int) and candidates:
        detail(f"[form] {label}: existing parameterCount={existing!r} is not a non-negative integer, kept as is and sources left")
    winner, consumed = _resolve(existing, candidates, "parameterCount", label)
    if consumed and existing is None:
        target.set_parameter_count(winner)
    return consumed


def _max_size(comp: dict, target: "_Target", label: str) -> list[dict]:
    candidates = [(prop["value"], prop) for source in MAX_SIZE_SOURCES for prop in _sources(comp, source)]
    candidates += [(p["value"], p) for p in _internal(comp) if p["name"] == INTERNAL_MODEL_PREFIX + "maxSize"]
    existing = target.get_max_size()
    winner, consumed = _resolve(existing, candidates, "inputs[0].maxSize", label)
    if consumed and existing is None:
        target.set_max_size(winner)
    return consumed


def _technical_requirements(comp: dict, target: "_Target", label: str) -> list[dict]:
    values = list(target.get_technical_requirements())
    added: list[str] = []
    consumed: list[dict] = []
    for source in TECHNICAL_REQUIREMENT_SOURCES:
        for prop in _sources(comp, source):
            if prop["value"] not in values:
                values.append(prop["value"])
                added.append(prop["value"])
            consumed.append(prop)
    if added:
        target.add_technical_requirements(added)
    return consumed


# ── 데이터셋 ─────────────────────────────────────────────────────────────────

def _apply_dataset(comp: dict, form: str) -> None:
    """aibom-internal:dataset:* 를 form 의 자리로 옮기고 지운다. 내부 키가 없는 컴포넌트는 손대지 않는다."""
    internal = [p for p in comp.get("properties") or [] if isinstance(p.get("name"), str) and p["name"].startswith(INTERNAL_PREFIX)
                and isinstance(p.get("value"), str)]
    if not internal:
        return
    label = comp.get("bom-ref") or comp.get("name") or "?"
    facts = _Bag(internal, INTERNAL_PREFIX)
    target = (_DatasetTypedTarget if form == "typed" else _DatasetPropertiesTarget)(comp)

    for field, valid in (("size", None), ("availability", AVAILABILITIES), ("intendedUse", None), ("collectionProcess", None)):
        value = facts.scalar(field)
        if value is None:
            continue
        if field == "size":
            value = _non_negative_int(value)
            if value is None:
                detail(f"[form] {label}: size={facts.scalar(field)!r} is not a non-negative integer, not promoted")
                continue
        elif valid and value not in valid:
            detail(f"[form] {label}: {field}={value!r} is not an allowed value, not promoted")
            continue
        existing = target.get_scalar(field)
        if existing is None:
            target.set_scalar(field, value)
        elif existing != value:
            detail(f"[form] {label}: {field} already has {existing!r}, {value!r} dropped")

    for field in ("modality", "provenance"):
        have = target.get_list(field)
        new: list[str] = []
        for value in facts.indexed(field):
            if field == "modality" and value not in MODALITIES:
                detail(f"[form] {label}: modality={value!r} is not an allowed value, not promoted")
            elif value not in have and value not in new:
                new.append(value)
        if new:
            target.add_list(field, new)

    have_stats = dict(target.get_statistics())
    new_stats: list[tuple[str, str]] = []
    for kind, value in facts.statistics():
        if kind in have_stats:
            if have_stats[kind] != value:
                detail(f"[form] {label}: statistics[{kind}] already has {have_stats[kind]!r}, {value!r} dropped")
        elif kind not in dict(new_stats):
            new_stats.append((kind, value))
    if new_stats:
        target.add_statistics(new_stats)

    _remove_from(comp, {id(p) for p in internal})                 # 내부 키는 이기든 지든 전부 지운다


class _Bag:
    """aibom-internal:* 프로퍼티 목록을 사실로 읽는다."""

    def __init__(self, props: list[dict], prefix: str) -> None:
        self.values = {p["name"][len(prefix):]: p["value"] for p in props}

    def scalar(self, field: str) -> str | None:
        return self.values.get(field)

    def indexed(self, field: str, leaf: str | None = None) -> list[str]:
        return [v for _, v in self._indexed_pairs(field, leaf)]

    def statistics(self) -> list[tuple[str, str]]:
        return self.named_pairs("statistics", "type")

    def named_pairs(self, field: str, key_leaf: str = "name") -> list[tuple[str, str]]:
        """field:<i>:<key_leaf> 와 field:<i>:value 를 짝지어 (키, 값) 목록으로. 인덱스 순, 짝이 없는 것은 버린다."""
        keys = dict(self._indexed_pairs(field, key_leaf))
        values = dict(self._indexed_pairs(field, "value"))
        return [(keys[i], values[i]) for i in sorted(keys) if i in values]

    def _indexed_pairs(self, field: str, leaf: str | None = None) -> list[tuple[int, str]]:
        """field:<i>[:leaf] → (i, value) 인덱스 순."""
        pattern = re.compile(rf"^{re.escape(field)}:(\d+){':' + re.escape(leaf) if leaf else ''}$")
        found = []
        for key, value in self.values.items():
            m = pattern.match(key)
            if m:
                found.append((int(m[1]), value))
        return sorted(found)


# ── 값 변환 ──────────────────────────────────────────────────────────────────

def _json_object(raw: str) -> dict | None:
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _stringify(value) -> str:
    """하이퍼파라미터 값은 문자열이다. 문자열이 아닌 JSON 값은 JSON 표기 그대로 (512 → "512", true → "true")."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _non_negative_int(raw: str) -> int | None:
    raw = raw.strip()
    return int(raw) if _NON_NEGATIVE_INT.match(raw) else None


# ── 목표 — 두 형태를 같은 인터페이스로 ────────────────────────────────────────

class _Target:
    """목표 필드 읽기·쓰기. 읽기는 이미 있는 값(승자), 목록은 뒤에 덧붙이기, 스칼라는 비어 있을 때만 쓰기."""

    def __init__(self, comp: dict) -> None:
        self.comp = comp

    def finish(self) -> None:
        """소비만 하고 아무것도 쓰지 않아 비어 버린 modelCard 는 남기지 않는다 (소비가 있었을 때만 불린다)."""
        card = self.comp.get("modelCard")
        if card is not None and not card:
            del self.comp["modelCard"]

    def get_hyperparameters(self) -> list[dict]:
        """이름이 문자열인 기존 항목만 {name, value} 로 (value 가 없으면 ""). 이름 없는 항목은 읽지도 지우지도 않는다."""
        ...

    def add_hyperparameters(self, entries: list[dict]) -> None: ...
    def get_parameter_count(self) -> object | None:
        """정수로 읽히면 int, 있지만 정수가 아니면 원문 그대로(그래도 이미 있는 값이 이긴다), 없으면 None."""
        ...

    def set_parameter_count(self, value: int) -> None: ...
    def get_max_size(self) -> object | None: ...
    def set_max_size(self, value: str) -> None: ...
    def get_technical_requirements(self) -> list[str]: ...
    def add_technical_requirements(self, values: list[str]) -> None: ...


class _TypedTarget(_Target):
    """CycloneDX v0.6 스키마의 타입 있는 필드."""

    def _params(self, create: bool) -> dict:
        card = self.comp.setdefault("modelCard", {}) if create else (self.comp.get("modelCard") or {})
        return card.setdefault("modelParameters", {}) if create else (card.get("modelParameters") or {})

    def _considerations(self, create: bool) -> dict:
        card = self.comp.setdefault("modelCard", {}) if create else (self.comp.get("modelCard") or {})
        return card.setdefault("considerations", {}) if create else (card.get("considerations") or {})

    def get_hyperparameters(self) -> list[dict]:
        return [{"name": h["name"], "value": h.get("value", "")}                    # 스키마상 name·value 모두 선택이다
                for h in self._params(False).get("hyperparameters") or [] if isinstance(h, dict) and isinstance(h.get("name"), str)]

    def add_hyperparameters(self, entries: list[dict]) -> None:
        self._params(True).setdefault("hyperparameters", []).extend(entries)

    def get_parameter_count(self) -> object | None:
        return self._params(False).get("parameterCount")

    def set_parameter_count(self, value: int) -> None:
        self._params(True)["parameterCount"] = value

    def get_max_size(self) -> object | None:
        inputs = self._params(False).get("inputs") or []
        return inputs[0].get("maxSize") if inputs and isinstance(inputs[0], dict) else None

    def set_max_size(self, value: str) -> None:
        inputs = self._params(True).setdefault("inputs", [])
        if not inputs:
            inputs.append({})                                     # format 은 스키마상 필수가 아니다
        inputs[0]["maxSize"] = value

    def get_technical_requirements(self) -> list[str]:
        return [v for v in self._considerations(False).get("technicalRequirements") or [] if isinstance(v, str)]

    def add_technical_requirements(self, values: list[str]) -> None:
        self._considerations(True).setdefault("technicalRequirements", []).extend(values)


class _PropertyBag:
    """properties 목록을 정의서 키로 읽고 쓰는 공통 코드. 목록의 자리(_props / _append)는 하위 클래스가 정한다."""

    def __init__(self, comp: dict) -> None:
        self.comp = comp

    def _props(self) -> list[dict]: ...
    def _append(self, new: list[dict]) -> None: ...

    def _value(self, name: str) -> object | None:
        return next((p.get("value") for p in self._props() if p.get("name") == name), None)

    def _indexed(self, prefix: str, leaf: str | None = None) -> list[tuple[int, str]]:
        """prefix:<i>[:leaf] 항목을 (i, value) 로 — 인덱스 순. 값이 문자열인 것만."""
        pattern = re.compile(rf"^{re.escape(prefix)}:(\d+){':' + re.escape(leaf) if leaf else ''}$")
        found = [(int(m[1]), p["value"]) for p in self._props()
                 if (m := pattern.match(p.get("name") or "")) and isinstance(p.get("value"), str)]
        return sorted(found)

    def _next_index(self, prefix: str) -> int:
        """prefix:<i>… 가 쓰는 인덱스 다음 — 기존 항목은 번호를 바꾸지 않고 뒤에 이어 붙인다."""
        pattern = re.compile(rf"^{re.escape(prefix)}:(\d+)(?::|$)")
        used = [int(m[1]) for p in self._props() if (m := pattern.match(p.get("name") or ""))]
        return max(used) + 1 if used else 0


class _PropertiesTarget(_PropertyBag, _Target):
    """정의서(aibom-v0.6-properties.md)의 aibom:model:* 키 — modelCard.properties 에 싣는다."""

    def _props(self) -> list[dict]:
        return (self.comp.get("modelCard") or {}).get("properties") or []

    def _append(self, new: list[dict]) -> None:
        self.comp.setdefault("modelCard", {}).setdefault("properties", []).extend(new)

    def get_hyperparameters(self) -> list[dict]:
        names = dict(self._indexed(PREFIX + "hyperparameters", "name"))
        values = dict(self._indexed(PREFIX + "hyperparameters", "value"))
        return [{"name": names[i], "value": values.get(i, "")} for i in sorted(names)]

    def add_hyperparameters(self, entries: list[dict]) -> None:
        start = self._next_index(PREFIX + "hyperparameters")
        new = []
        for i, e in enumerate(entries, start):
            new += [{"name": f"{PREFIX}hyperparameters:{i}:name", "value": e["name"]},
                    {"name": f"{PREFIX}hyperparameters:{i}:value", "value": e["value"]}]
        self._append(new)

    def get_parameter_count(self) -> object | None:
        v = self._value(PREFIX + "parameterCount")
        if isinstance(v, str):
            n = _non_negative_int(v)
            return v if n is None else n
        return v

    def set_parameter_count(self, value: int) -> None:
        self._append([{"name": PREFIX + "parameterCount", "value": str(value)}])

    def get_max_size(self) -> object | None:
        return self._value(PREFIX + "inputs:0:maxSize")

    def set_max_size(self, value: str) -> None:
        self._append([{"name": PREFIX + "inputs:0:maxSize", "value": value}])

    def get_technical_requirements(self) -> list[str]:
        return [v for _, v in self._indexed(PREFIX + "technicalRequirements")]

    def add_technical_requirements(self, values: list[str]) -> None:
        start = self._next_index(PREFIX + "technicalRequirements")
        self._append([{"name": f"{PREFIX}technicalRequirements:{i}", "value": v} for i, v in enumerate(values, start)])


# ── 데이터셋 목표 — 두 형태를 같은 인터페이스로 ───────────────────────────────

class _DatasetTarget:
    """스칼라(size, availability, intendedUse, collectionProcess)는 비어 있을 때만, 목록(modality, provenance, statistics)은 뒤에 덧붙인다."""

    def get_scalar(self, field: str) -> object | None: ...
    def set_scalar(self, field: str, value) -> None: ...
    def get_list(self, field: str) -> list[str]: ...
    def add_list(self, field: str, values: list[str]) -> None: ...
    def get_statistics(self) -> list[tuple[str, str]]: ...
    def add_statistics(self, entries: list[tuple[str, str]]) -> None: ...


class _DatasetTypedTarget(_DatasetTarget):
    """v0.6 componentData 필드 — data[0] 에 싣는다. data[] 가 없으면 만든다."""

    def __init__(self, comp: dict) -> None:
        self.comp = comp

    def _entry(self, create: bool) -> dict:
        data = self.comp.get("data") or []
        if not data:
            if not create:
                return {}
            data = self.comp["data"] = [{"type": "dataset", "name": self.comp.get("name", "")}]
        return data[0]

    def get_scalar(self, field: str) -> object | None:
        entry = self._entry(False)
        return (entry.get("contents") or {}).get("availability") if field == "availability" else entry.get(field)

    def set_scalar(self, field: str, value) -> None:
        entry = self._entry(True)
        if field == "availability":
            entry.setdefault("contents", {})["availability"] = value
        else:
            entry[field] = value

    def get_list(self, field: str) -> list[str]:
        return [v for v in self._entry(False).get(field) or [] if isinstance(v, str)]

    def add_list(self, field: str, values: list[str]) -> None:
        self._entry(True).setdefault(field, []).extend(values)

    def get_statistics(self) -> list[tuple[str, str]]:
        return [(s["type"], s.get("value", "")) for s in self._entry(False).get("statistics") or []
                if isinstance(s, dict) and isinstance(s.get("type"), str)]

    def add_statistics(self, entries: list[tuple[str, str]]) -> None:
        self._entry(True).setdefault("statistics", []).extend({"type": t, "value": v} for t, v in entries)


class _DatasetPropertiesTarget(_PropertyBag, _DatasetTarget):
    """정의서의 aibom:dataset:* 키 — component.properties 에 싣는다 (componentData 에는 properties 슬롯이 없다)."""

    def _props(self) -> list[dict]:
        return self.comp.get("properties") or []

    def _append(self, new: list[dict]) -> None:
        self.comp.setdefault("properties", []).extend(new)

    def get_scalar(self, field: str) -> object | None:
        v = self._value(DATASET_PREFIX + field)
        if field == "size" and isinstance(v, str):
            n = _non_negative_int(v)
            return v if n is None else n
        return v

    def set_scalar(self, field: str, value) -> None:
        self._append([{"name": DATASET_PREFIX + field, "value": str(value)}])

    def get_list(self, field: str) -> list[str]:
        return [v for _, v in self._indexed(DATASET_PREFIX + field)]

    def add_list(self, field: str, values: list[str]) -> None:
        start = self._next_index(DATASET_PREFIX + field)
        self._append([{"name": f"{DATASET_PREFIX}{field}:{i}", "value": v} for i, v in enumerate(values, start)])

    def get_statistics(self) -> list[tuple[str, str]]:
        types = dict(self._indexed(DATASET_PREFIX + "statistics", "type"))
        values = dict(self._indexed(DATASET_PREFIX + "statistics", "value"))
        return [(types[i], values.get(i, "")) for i in sorted(types)]

    def add_statistics(self, entries: list[tuple[str, str]]) -> None:
        start = self._next_index(DATASET_PREFIX + "statistics")
        new = []
        for i, (t, v) in enumerate(entries, start):
            new += [{"name": f"{DATASET_PREFIX}statistics:{i}:type", "value": t}, {"name": f"{DATASET_PREFIX}statistics:{i}:value", "value": v}]
        self._append(new)
