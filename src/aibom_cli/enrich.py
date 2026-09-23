"""OWASP aibom-generator 결과로 병합 문서의 HF 모델 컴포넌트를 보강한다.

가져오는 것: modelCard.properties[genai:aibom:* / owasp:aibom:* 와 접두어 없는 safetensors_total_parameters],
             modelCard.considerations, metadata.properties[] 의 완전성 점수.
유지하는 것: cdxgen 이 준 component.name / version / purl.
매칭 키:    purl 의 pkg:huggingface/<ns>/<name> (리비전 제외 — 두 도구가 버전 표기를 달리 한다)
"""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from .runners import run_aibom_generator
from .runners._proc import RunnerError

_HF_PURL = re.compile(r"^pkg:huggingface/(?P<ns>[^/@]+)/(?P<name>[^/@]+)(?:@[^?#]+)?")
_KEEP_PREFIXES = ("genai:aibom:", "owasp:aibom:")
_KEEP_UNPREFIXED = frozenset({"safetensors_total_parameters"})     # regulation 의 parameterCount 원본 — 접두어 없는 키는 이것만


def hf_id_of(component: dict) -> str | None:
    m = _HF_PURL.match(component.get("purl") or "")
    if not m or component.get("type") != "machine-learning-model":
        return None
    return f"{m['ns']}/{m['name']}"


def hf_reachable(timeout: float = 3.0) -> bool:
    """huggingface.co(또는 HF_ENDPOINT 의 호스트) 443 포트에 TCP 로 닿는지만 본다."""
    host = urlparse(os.environ.get("HF_ENDPOINT") or "https://huggingface.co").hostname or "huggingface.co"
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


def skip_reason() -> str | None:
    """보강을 건너뛰어야 하면 그 이유를, 해도 되면 None 을 돌려준다."""
    if not os.environ.get("AIBOM_GENERATOR_DIR"):
        return "AIBOM_GENERATOR_DIR 미설정"
    if not hf_reachable():
        return "huggingface.co 에 닿지 않음"
    return None


def enrich(merged: dict, workdir: Path, log=print) -> dict:
    targets = {hf: c for c in merged.get("components", []) if (hf := hf_id_of(c))}
    if not targets:
        log("[enrich] pkg:huggingface 모델 컴포넌트가 없어 보강을 건너뛴다")
        return merged
    reason = skip_reason()
    if reason:
        log(f"[enrich] {reason} — 보강을 건너뛴다 ({len(targets)}개 모델)")
        return merged

    for hf_id, comp in targets.items():
        try:
            owasp = run_aibom_generator(hf_id, workdir)
        except RunnerError as e:
            log(f"[enrich] {hf_id}: {e}")
            continue
        src = next((c for c in owasp.get("components", []) if c.get("type") == "machine-learning-model"), None)
        if not src:
            continue
        _apply(comp, src, owasp.get("metadata") or {})
        log(f"[enrich] {hf_id}: 보강 완료")
    return merged


def _keep_property(name: str) -> bool:
    return name.startswith(_KEEP_PREFIXES) or name in _KEEP_UNPREFIXED


def _apply(dst: dict, src: dict, src_metadata: dict) -> None:
    dst_card = dst.setdefault("modelCard", {})
    src_card = src.get("modelCard") or {}

    # properties: genai:aibom:* / owasp:aibom:* 와 safetensors_total_parameters 만 가져온다
    keep = [p for p in (src_card.get("properties") or []) if _keep_property(p.get("name", ""))]
    if keep:
        seen = {(p.get("name"), p.get("value")) for p in dst_card.get("properties", [])}
        dst_card["properties"] = dst_card.get("properties", []) + [p for p in keep if (p.get("name"), p.get("value")) not in seen]

    # considerations: 없는 하위 키만
    if src_card.get("considerations"):
        dst_c = dst_card.setdefault("considerations", {})
        for k, v in src_card["considerations"].items():
            dst_c.setdefault(k, v)

    # modelParameters: 없는 하위 키만 (task, modelArchitecture 는 cdxgen 것 유지)
    if src_card.get("modelParameters"):
        dst_p = dst_card.setdefault("modelParameters", {})
        for k, v in src_card["modelParameters"].items():
            dst_p.setdefault(k, v)

    # 완전성 점수 등 문서 단위 프로퍼티 → 컴포넌트 프로퍼티로 옮기며 접두어를 붙인다
    score_props = [p for p in (src_metadata.get("properties") or []) if "score" in p.get("name", "").lower()]
    if score_props:
        dst.setdefault("properties", []).extend(
            {"name": f"owasp:aibom:{p['name']}", "value": p.get("value")} for p in score_props
        )

    if not dst.get("description") and src.get("description"):
        dst["description"] = src["description"]
