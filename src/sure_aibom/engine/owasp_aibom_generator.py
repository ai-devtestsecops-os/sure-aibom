"""M-BOM 보강 (OWASP aibom-generator). 코드가 부르는 허브 모델마다 OWASP aibom-generator 를 돌려 규제 필드 원본만 가져온다.

service 가 engine/model.py 의 허브 모델 보강(Hub API) 다음에 부른다. cdxgen 이 낸 문서에 대고, 병합 앞에서 돈다.

    enrich_with_owasp_aibom_generator   허브 모델마다 도구를 돌리고, 그 출력의 규제 필드 원본을 모델 컴포넌트에 더한다

가져오는 것은 규제 필드 원본뿐이다 (OWASP_SOURCES: modelCard.properties 의 하이퍼파라미터 묶음과 개별 키, contextLength,
runtimeRequirement, safetensors_total_parameters). 나머지 출력은 버린다: 값이 없을 때 고정값(description
"No description available", task text-generation, modelArchitecture transformer)을 채우고, README 를 정규식으로 잘라
technicalLimitations·datasets 를 만들며, 허브에 없는 저장소에도 실패하지 않고 그런 BOM 을 낸다. 가져온 원본이 없으면 실패로 센다.
원본을 가져온 출력이 metadata.tools 에 자기를 적은 도구 항목은 문서의 도구 목록에 더한다 (한 번만).

도구는 디렉터리를 못 받고 Hugging Face 모델 id 만 받는다. 그래서 허브 모델마다 한 번씩 돌린다. 허브 모델인지는
common/component.py 의 hub_model_id 가 정한다 (purl 이 pkg:huggingface/<ns>/<name> 이고 로컬 모델 파일에서 찾은 것이 아닌 모델).
콘솔 스크립트 이름 `aibom` 이 cdxgen 의 `aibom` 과 겹치므로 모듈 경로로 부른다.

    AIBOM_GENERATOR_DIR=/path/to/aibom-generator
    python -m src.cli <owner/model> -o <out>
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

from ..utils.exceptions import RunnerError
from ..utils.log import detail
from .common import hub
from .common.component import HYPERPARAMETER_BY_PROPERTY, HYPERPARAMETER_JSON, hub_model_id
from .common.proc import load_json_file, run

# OWASP 출력에서 가져오는 규제 필드 원본 (form 이 읽는 키 가운데 OWASP 가 내는 것)
OWASP_SOURCES = frozenset({HYPERPARAMETER_JSON, *HYPERPARAMETER_BY_PROPERTY, "genai:aibom:modelcard:contextLength",
                           "owasp:aibom:distribution:runtimeRequirement", "safetensors_total_parameters"})


def enrich_with_owasp_aibom_generator(merged: dict, workdir: Path, report: dict | None = None) -> dict:
    """허브 모델마다 aibom-generator 를 돌려, 그 출력의 규제 필드 원본을 모델 컴포넌트의 modelCard.properties 에 더한다.
    돌릴 수 없으면(클론이 없거나 허브에 닿지 않으면) 문서를 그대로 돌려준다. 한 모델에서 실패해도 나머지 모델은 돌린다.
    report 를 주면 결과를 적는다: models(허브 모델 수) · enriched(원본을 가져온 수) · failed(실패한 id) ·
    errors(id → 이유 첫 줄) · skipped(건너뛴 이유)."""
    report = {} if report is None else report
    targets = {hf: c for c in merged.get("components", []) if (hf := hub_model_id(c))}
    report.update(models=len(targets), enriched=0, failed=[], errors={}, skipped=None)
    if not targets:
        report["skipped"] = "no Hugging Face models"
        return merged
    reason = _skip_reason()
    if reason:
        detail(f"[enrich] aibom-generator skipped for {len(targets)} hub model{'s' if len(targets) != 1 else ''}: {reason}")
        report["skipped"] = reason
        return merged
    used_tools: list[dict] = []
    for hf_id, comp in targets.items():
        try:
            owasp = _run_owasp_aibom_generator(hf_id, workdir)
        except RunnerError as e:
            detail(f"[enrich] {hf_id}: {e}")
            report["failed"].append(hf_id)
            report["errors"][hf_id] = (str(e).splitlines() or ["failed"])[0]
            continue
        src = next((c for c in owasp.get("components", []) if c.get("type") == "machine-learning-model"), None)
        taken = _apply_owasp(comp, src) if src else 0
        if taken:
            report["enriched"] += 1
            used_tools += _tools_of(owasp)
        else:
            report["failed"].append(hf_id)
            report["errors"][hf_id] = ("no regulation values in the aibom-generator output" if src
                                       else "no model component in the aibom-generator output")
    _add_tools(merged, used_tools)
    return merged


def _skip_reason() -> str | None:
    """aibom-generator 를 건너뛰어야 하면 그 이유를, 돌려도 되면 None 을 돌려준다. 클론을 먼저 보고 네트워크는 마지막에 본다.
    이유는 CLI 요약에 그대로 나가므로 영어다."""
    repo = os.environ.get("AIBOM_GENERATOR_DIR")
    if not repo:
        return "AIBOM_GENERATOR_DIR not set"
    if not Path(repo).is_dir():
        return f"AIBOM_GENERATOR_DIR not found: {repo}"
    if not (Path(repo) / "src" / "cli.py").is_file():
        return f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {repo}"
    if not hub.hf_reachable():
        return "huggingface.co unreachable"
    return None


def _run_owasp_aibom_generator(hf_id: str, workdir: Path) -> dict:
    """허브 모델 하나에 도구를 돌려 그 출력 BOM 을 돌려준다. 도구가 실패하거나 출력이 없으면 RunnerError."""
    repo = os.environ.get("AIBOM_GENERATOR_DIR")
    if not repo:
        raise RunnerError("AIBOM_GENERATOR_DIR not set")
    python = sys.executable
    safe = hf_id.replace("/", "__")
    out = workdir / f"owasp.{safe}.cdx.json"
    cmd = [python, "-m", "src.cli", hf_id, "-o", str(out)]
    proc = run(cmd, cwd=repo)
    if proc.returncode != 0:
        raise RunnerError(f"aibom-generator exited with {proc.returncode} for {hf_id}\n{proc.stderr[-2000:]}")
    return load_json_file(out, "aibom-generator")


def _apply_owasp(dst: dict, src: dict) -> int:
    """OWASP 출력의 modelCard.properties 가운데 규제 필드 원본만 dst 의 modelCard.properties 에 더한다. 더한(또는 이미 있던) 수."""
    keep = [p for p in ((src.get("modelCard") or {}).get("properties") or [])
            if isinstance(p, dict) and p.get("name") in OWASP_SOURCES and isinstance(p.get("value"), str)]
    if keep:
        card = dst.setdefault("modelCard", {})
        seen = {(p.get("name"), p.get("value")) for p in card.get("properties") or []}
        card["properties"] = (card.get("properties") or []) + [p for p in keep if (p["name"], p["value"]) not in seen]
    return len(keep)


def _tools_of(doc: dict) -> list[dict]:
    """문서가 metadata.tools 에 적은 도구 항목 (1.5 이후의 components 꼴, 그 전의 배열 꼴 모두)."""
    tools = (doc.get("metadata") or {}).get("tools")
    items = tools.get("components") if isinstance(tools, dict) else tools
    return [t for t in items or [] if isinstance(t, dict) and t.get("name")]


def _add_tools(merged: dict, tools: list[dict]) -> None:
    """값을 가져다 쓴 aibom-generator 의 도구 항목(그 출력이 자기를 적은 것)을 문서의 도구 목록에 더한다. 병합처럼
    (이름, 버전)이 같은 것은 한 번만 둔다. 가져다 쓴 값이 없으면 손대지 않는다."""
    if not tools:
        return
    listed = merged.setdefault("metadata", {}).setdefault("tools", {}).setdefault("components", [])
    seen = {(t.get("name"), t.get("version")) for t in listed if isinstance(t, dict)}
    for tool in tools:
        if (tool.get("name"), tool.get("version")) not in seen:
            seen.add((tool.get("name"), tool.get("version")))
            listed.append(copy.deepcopy(tool))
