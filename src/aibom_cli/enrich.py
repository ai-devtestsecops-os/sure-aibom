"""허브 모델(코드가 부르는 Hugging Face 모델)을 보강한다. 두 단계다.

1) Hub API — 허브 모델마다 GET /api/models/<id> 응답을 받아 비어 있는 필드만 채운다. 받은 응답은 report["model_infos"] 로
   남겨, 뒤의 D-BOM 이 모델 카드의 데이터셋을 읽을 때 다시 쓴다 (같은 응답을 두 번 받지 않는다). 로컬 모델 카드에서 cdxgen 이
   읽는 것과 같은 키·같은 규칙이다.
       version                                     sha (조회 시점의 main 커밋. 허브 데이터셋과 같은 규칙)
       licenses                                    cardData.license (other 면 license_name · license_link)
       description                                 cardData.model_description, 없으면 cardData.description
       supplier.name                               author (저장소 소유 계정)
       externalReferences                          distribution https://huggingface.co/<id>, documentation arxiv:<번호> 태그의 논문
       pedigree.ancestors · notes                  cardData.base_model (+ base_model_relation 을 notes 앞에 "Hugging Face relation: …" 로)
       modelCard.modelParameters.task              pipeline_tag, 없으면 model-index 의 task
                                .architectureFamily  config.model_type, 없으면 gguf.architecture
                                .modelArchitecture   config.architectures[0]
                                .inputs/outputs[].format   task 를 cdxgen 과 같은 표로 바꾼 것, 표에 없으면 widget 예시로
       modelCard.quantitativeAnalysis.performanceMetrics   model-index 결과의 metrics (cdxgen 과 같은 모양: type, value, slice)
   규제 필드 원본 (aibom-internal:model:*, form 이 옮기고 지운다): parameterCount ← safetensors.total, 없으면 gguf.total;
   inputs maxSize ← gguf.context_length.
2) OWASP aibom-generator — 규제 필드 원본만 가져온다 (OWASP_SOURCES: modelCard.properties 의 하이퍼파라미터 묶음과 개별 키,
   contextLength, runtimeRequirement, safetensors_total_parameters). 나머지 출력은 버린다: 값이 없을 때 고정값(description
   "No description available", task text-generation, modelArchitecture transformer)을 채우고, README 를 정규식으로 잘라
   technicalLimitations·datasets 를 만들며, 허브에 없는 저장소에도 실패하지 않고 그런 BOM 을 낸다. 가져온 원본이 없으면 실패로 센다.

허브 모델: purl 이 pkg:huggingface/<ns>/<name> 인 모델 컴포넌트 가운데 로컬 모델 파일(README.md, config.json, adapter_config.json,
Modelfile, *.gguf, *.safetensors)에서 찾은 것이 아닌 것. 로컬 폴더는 그 파일들이 근거다 (config 의 _name_or_path 는 베이스 모델
이름일 수 있어 허브 값이 그 모델의 것이 아닐 수 있다).
매칭 키: purl 의 pkg:huggingface/<ns>/<name> (리비전 제외 — 두 도구가 버전 표기를 달리 한다)
"""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import urlparse

from .form import HYPERPARAMETER_BY_PROPERTY, HYPERPARAMETER_JSON, INTERNAL_MODEL_PREFIX
from .licenses import card_licenses
from .runners import run_aibom_generator
from .runners._proc import RunnerError

_HF_PURL = re.compile(r"^pkg:huggingface/(?P<ns>[^/@]+)/(?P<name>[^/@]+)(?:@[^?#]+)?")
_HF_ID = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)?$")
HUB = "https://huggingface.co"
LOCAL_MODEL_FILES = frozenset({"readme.md", "config.json", "adapter_config.json", "modelfile"})
LOCAL_MODEL_SUFFIXES = (".gguf", ".safetensors")
# OWASP 출력에서 가져오는 규제 필드 원본 (form 이 읽는 키 가운데 OWASP 가 내는 것)
OWASP_SOURCES = frozenset({HYPERPARAMETER_JSON, *HYPERPARAMETER_BY_PROPERTY, "genai:aibom:modelcard:contextLength",
                           "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"})
# cdxgen lib/parsers/huggingfaceManifest.js 의 HUGGING_FACE_TASK_IO_FORMATS
TASK_IO_FORMATS = {
    "automatic-speech-recognition": ("audio", "text"), "conversational": ("text", "text"),
    "feature-extraction": ("text", "vector"), "fill-mask": ("text", "text"), "image-classification": ("image", "text"),
    "image-segmentation": ("image", "image"), "image-text-to-text": ("image", "text"), "image-to-image": ("image", "image"),
    "image-to-text": ("image", "text"), "question-answering": ("text", "text"), "summarization": ("text", "text"),
    "translation": ("text", "text"), "text-generation": ("text", "text"), "text-to-audio": ("text", "audio"),
    "text-to-image": ("text", "image"), "text2text-generation": ("text", "text"), "token-classification": ("text", "text"),
}


def hf_id_of(component: dict) -> str | None:
    m = _HF_PURL.match(component.get("purl") or "")
    if not m or component.get("type") != "machine-learning-model":
        return None
    return f"{m['ns']}/{m['name']}"


def hub_model_id(component: dict) -> str | None:
    """허브 모델이면 그 id (머리 설명). 로컬 모델 파일에서 찾은 모델이면 None."""
    hf_id = hf_id_of(component)
    if hf_id is None:
        return None
    for occurrence in (component.get("evidence") or {}).get("occurrences") or []:
        location = occurrence.get("location") if isinstance(occurrence, dict) else None
        if isinstance(location, str):
            name = PurePosixPath(location.split("#", 1)[0].replace("\\", "/")).name.lower()
            if name in LOCAL_MODEL_FILES or name.endswith(LOCAL_MODEL_SUFFIXES):
                return None
    return hf_id


def hf_reachable(timeout: float = 3.0) -> bool:
    """huggingface.co(또는 HF_ENDPOINT 의 호스트) 443 포트에 TCP 로 닿는지만 본다."""
    host = urlparse(os.environ.get("HF_ENDPOINT") or HUB).hostname or "huggingface.co"
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_model_infos(hf_ids: Iterable[str], log=print) -> dict[str, dict | None]:
    """허브 모델 id 마다 GET /api/models/<id> 응답 (실패면 None)."""
    from .dataset import fetch_model_info          # dataset 이 이 모듈의 hub_model_id · hf_reachable 을 가져다 쓰므로 여기서 부른다
    return {hf_id: fetch_model_info(hf_id, log) for hf_id in hf_ids}


def skip_reason() -> str | None:
    """OWASP 보강을 건너뛰어야 하면 그 이유를, 해도 되면 None 을 돌려준다. 이유는 CLI 요약에 그대로 나가므로 영어다."""
    repo = os.environ.get("AIBOM_GENERATOR_DIR")
    if not repo:
        return "AIBOM_GENERATOR_DIR not set"
    if not Path(repo).is_dir():
        return f"AIBOM_GENERATOR_DIR not found: {repo}"
    if not (Path(repo) / "src" / "cli.py").is_file():
        return f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {repo}"
    if not hf_reachable():
        return "huggingface.co unreachable"
    return None


def enrich(merged: dict, workdir: Path, log=print, report: dict | None = None, model_infos: dict | None = None) -> dict:
    """model_infos 는 허브 모델 id → Hub API 응답 (실패면 None). 주지 않으면 허브에 닿는지 보고 허브 모델마다 받는다.
    report 를 주면 결과를 적는다: models(허브 모델 수) · hub(Hub API 로 채운 수) · hub_missing(응답이 없던 id) ·
    hub_skipped(Hub API 를 쓰지 못한 이유) · hub_reachable(허브에 닿는지 본 결과, 보지 않았으면 None) ·
    model_infos(쓴 응답, D-BOM 이 다시 쓴다) · enriched(OWASP 에서 원본을 가져온 수) · failed(실패한 id) ·
    errors(id → 이유 첫 줄) · skipped(OWASP 를 건너뛴 이유)."""
    report = {} if report is None else report
    targets = {hf: c for c in merged.get("components", []) if (hf := hub_model_id(c))}
    report.update(models=len(targets), hub=0, hub_missing=[], hub_skipped=None, hub_reachable=None, model_infos={},
                  enriched=0, failed=[], errors={}, skipped=None)
    if not targets:
        log("[enrich] no hub model components, nothing to enrich")
        report["skipped"] = report["hub_skipped"] = "no Hugging Face models"
        return merged

    if model_infos is None:
        report["hub_reachable"] = hf_reachable()
        if report["hub_reachable"]:
            model_infos = fetch_model_infos(targets, log)
    if model_infos is None:
        report["hub_skipped"] = "huggingface.co unreachable"
    else:
        report["model_infos"] = model_infos
        for hf_id, comp in targets.items():
            info = model_infos.get(hf_id)
            if isinstance(info, dict):
                apply_model_info(comp, hf_id, info)
                report["hub"] += 1
            else:
                report["hub_missing"].append(hf_id)
                log(f"[enrich] {hf_id}: no Hub API model info, fields left as cdxgen wrote them")

    reason = skip_reason()
    if reason:
        log(f"[enrich] aibom-generator skipped for {len(targets)} hub model{'s' if len(targets) != 1 else ''}: {reason}")
        report["skipped"] = reason
        return merged
    for hf_id, comp in targets.items():
        try:
            owasp = run_aibom_generator(hf_id, workdir)
        except RunnerError as e:
            log(f"[enrich] {hf_id}: {e}")
            report["failed"].append(hf_id)
            report["errors"][hf_id] = (str(e).splitlines() or ["failed"])[0]
            continue
        src = next((c for c in owasp.get("components", []) if c.get("type") == "machine-learning-model"), None)
        taken = _apply(comp, src) if src else 0
        if taken:
            report["enriched"] += 1
        else:
            report["failed"].append(hf_id)
            report["errors"][hf_id] = ("no regulation values in the aibom-generator output" if src
                                       else "no model component in the aibom-generator output")
    return merged


def _apply(dst: dict, src: dict) -> int:
    """OWASP 출력의 modelCard.properties 가운데 규제 필드 원본만 dst 의 modelCard.properties 에 더한다. 더한(또는 이미 있던) 수."""
    keep = [p for p in ((src.get("modelCard") or {}).get("properties") or [])
            if isinstance(p, dict) and p.get("name") in OWASP_SOURCES and isinstance(p.get("value"), str)]
    if keep:
        card = dst.setdefault("modelCard", {})
        seen = {(p.get("name"), p.get("value")) for p in card.get("properties") or []}
        card["properties"] = (card.get("properties") or []) + [p for p in keep if (p["name"], p["value"]) not in seen]
    return len(keep)


# ── Hub API 응답 → 필드 ────────────────────────────────────────────────────────

def apply_model_info(comp: dict, hf_id: str, info: dict) -> None:
    """머리 설명 1) 의 표대로 비어 있는 필드만 채운다."""
    cid = info.get("id") if isinstance(info.get("id"), str) and _HF_ID.match(info["id"].strip("/")) else hf_id
    hf_id = cid.strip("/")
    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    if not comp.get("version") and isinstance(info.get("sha"), str) and info["sha"]:
        comp["version"] = info["sha"]
    if not comp.get("licenses") and (licenses := card_licenses(card)):
        comp["licenses"] = licenses
    if not comp.get("description"):
        text = next((t for t in (card.get("model_description"), card.get("description")) if isinstance(t, str) and t.strip()), None)
        if text:
            comp["description"] = " ".join(text.split())
    if not comp.get("supplier") and isinstance(info.get("author"), str) and info["author"]:
        comp["supplier"] = {"name": info["author"]}
    refs = [{"type": "distribution", "url": f"{HUB}/{hf_id}"}]
    refs += [{"type": "documentation", "url": f"https://arxiv.org/abs/{t[len('arxiv:'):]}"}
             for t in _as_list(info.get("tags")) if isinstance(t, str) and t.startswith("arxiv:") and t[len("arxiv:"):]]
    existing = {(r.get("type"), r.get("url")) for r in comp.get("externalReferences") or []}
    new_refs = [r for r in refs if (r["type"], r["url"]) not in existing]
    if new_refs:
        comp["externalReferences"] = (comp.get("externalReferences") or []) + new_refs
    _pedigree(comp, card)
    _model_card(comp, info, card)
    _regulation_facts(comp, info)


def _pedigree(comp: dict, card: dict) -> None:
    pedigree = comp.get("pedigree") or {}
    if pedigree.get("ancestors"):
        return
    ancestors = []
    for base in _as_list(card.get("base_model")):
        base = base.strip() if isinstance(base, str) else ""
        if base and _HF_ID.match(base):
            group, _, name = base.rpartition("/")
            ancestors.append({"type": "machine-learning-model", **({"group": group} if group else {}), "name": name,
                              "purl": f"pkg:huggingface/{base}"})
    if not ancestors:
        return
    pedigree["ancestors"] = ancestors
    relation = card.get("base_model_relation")
    notes = pedigree.get("notes") if isinstance(pedigree.get("notes"), str) else ""
    if isinstance(relation, str) and relation.strip() and "Hugging Face relation:" not in notes:
        pedigree["notes"] = "; ".join(n for n in (f"Hugging Face relation: {relation.strip()}", notes) if n)   # cdxgen 의 로컬 카드와 같은 모양
    comp["pedigree"] = pedigree


def _model_card(comp: dict, info: dict, card: dict) -> None:
    config = info.get("config") if isinstance(info.get("config"), dict) else {}
    gguf = info.get("gguf") if isinstance(info.get("gguf"), dict) else {}
    task = next((t for t in (info.get("pipeline_tag"), card.get("pipeline_tag"), _model_index_task(card)) if isinstance(t, str) and t), None)
    architectures = config.get("architectures") if isinstance(config.get("architectures"), list) else []
    values = {
        "task": task,
        "architectureFamily": next((v for v in (config.get("model_type"), gguf.get("architecture")) if isinstance(v, str) and v), None),
        "modelArchitecture": architectures[0] if architectures and isinstance(architectures[0], str) else None,
    }
    io = TASK_IO_FORMATS.get(task.lower()) if task else None
    io = io or _widget_io(card.get("widget") or info.get("widgetData"))
    have = (comp.get("modelCard") or {}).get("modelParameters") or {}
    updates = {key: value for key, value in values.items() if value and not have.get(key)}
    if io and not have.get("inputs") and not have.get("outputs"):
        updates["inputs"], updates["outputs"] = [{"format": io[0]}], [{"format": io[1]}]
    if updates:
        comp.setdefault("modelCard", {}).setdefault("modelParameters", {}).update(updates)
    metrics = performance_metrics(card.get("model-index") or info.get("model-index"))
    if metrics and not ((comp.get("modelCard") or {}).get("quantitativeAnalysis") or {}).get("performanceMetrics"):
        comp.setdefault("modelCard", {}).setdefault("quantitativeAnalysis", {})["performanceMetrics"] = metrics


def _model_index_task(card: dict) -> str | None:
    for entry in _as_list(card.get("model-index")):
        for result in _as_list(entry.get("results")) if isinstance(entry, dict) else []:
            task = (result.get("task") or {}).get("type") if isinstance(result, dict) and isinstance(result.get("task"), dict) else None
            if isinstance(task, str) and task:
                return task
    return None


def _widget_io(widgets) -> tuple[str, str] | None:
    """cdxgen inferModelIoParameters 의 widget 규칙: 글(text·messages·sentences) → text/text, 그림(src) → image/(text|image), 표 → structured-data/text."""
    for widget in _as_list(widgets):
        if not isinstance(widget, dict):
            continue
        if widget.get("messages") or widget.get("text") or widget.get("sentences"):
            return ("text", "text")
        if widget.get("src"):
            return ("image", "text" if (widget.get("output") or {}).get("text") else "image")
        if widget.get("table") or widget.get("structured_data"):
            return ("structured-data", "text")
    return None


def performance_metrics(model_index) -> list[dict]:
    """cdxgen createPerformanceMetrics 와 같은 규칙: metric 마다 {type, value(문자열), slice "데이터셋 이름 / split"}. 값이 없으면 뺀다."""
    out = []
    for entry in _as_list(model_index):
        for result in _as_list(entry.get("results")) if isinstance(entry, dict) else []:
            if not isinstance(result, dict):
                continue
            dataset = result.get("dataset") if isinstance(result.get("dataset"), dict) else {}
            slice_ = " / ".join(str(x) for x in (dataset.get("name"), dataset.get("split")) if x)
            for metric in _as_list(result.get("metrics")):
                if not isinstance(metric, dict) or not (metric.get("type") or metric.get("name")):
                    continue
                value = metric.get("value")
                if value is None or str(value) == "":
                    continue
                out.append({"type": str(metric.get("type") or metric.get("name")), "value": str(value), **({"slice": slice_} if slice_ else {})})
    return out


def _regulation_facts(comp: dict, info: dict) -> None:
    safetensors = info.get("safetensors") if isinstance(info.get("safetensors"), dict) else {}
    gguf = info.get("gguf") if isinstance(info.get("gguf"), dict) else {}
    props = []
    count = next((v for v in (safetensors.get("total"), gguf.get("total")) if isinstance(v, int) and not isinstance(v, bool) and v >= 0), None)
    if count is not None:
        props.append({"name": INTERNAL_MODEL_PREFIX + "parameterCount", "value": str(count)})
    context = gguf.get("context_length")
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        props.append({"name": INTERNAL_MODEL_PREFIX + "maxSize", "value": str(context)})
    have = comp.get("properties") or []
    props = [p for p in props if p not in have]
    if props:
        comp["properties"] = have + props


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
