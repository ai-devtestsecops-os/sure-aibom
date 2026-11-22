"""scan 의 단계 순서. 명령줄 인자를 받지 않는다. 단계는 모두 engine 의 파일이고, 여기서는 순서와 단계 줄, 실패 모으기만 맡는다.

controller/scan_controller.py 가 인자를 확인해 값만 넘기고, 여기서는 단계마다 utils/log.py 의 stage(단계 이름, 결과)와 log(줄)로 알린다.

    check_scan  도구를 돌리기 전 입력 확인 (대상 경로, --data 경로, --data 허브 리비전)
    scan        S-BOM(syft) → 이미지 받기·풀기 → M-BOM(cdxgen) → 병합 → AI 서비스 → M-BOM 보강(로컬 모델, 허브 모델)
                → D-BOM → 규제 필드 → SPDX 변환 (--format spdx 일 때만)
                M-BOM 보강은 로컬 모델, 허브 모델 둘 다 engine/model.py 다 (enrich_local_models, enrich_hub_models)

syft·cdxgen 가운데 하나라도 실패하면 만든 만큼은 돌려주고 failed 에 적는다 (CLI 는 종료 코드 2 로 끝낸다).
"""
from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..engine.ai_service import discover_services
from ..engine.cdxgen import run_cdxgen
from ..engine.common.component import is_dataset
from ..engine.container_tools import pull_image
from ..engine.dataset import discover_datasets, missing_revisions, split_data_args
from ..engine.form import drop_tool_properties, regulate
from ..engine.image_tar import extract_image, is_archive
from ..engine.merge import merge
from ..engine.model import enrich_hub_models, enrich_local_models
from ..engine.spdx import convert_spdx
from ..engine.syft import run_syft
from ..utils.exceptions import ImageExtractionError, RunnerError
from ..utils.facts import Facts
from ..utils.formats import FORM_BY_SPEC, FORMAT_NAME
from ..utils.log import log, stage

# 요약의 묶음: CycloneDX type → S/M/D 와 파일. 목록에 없는 type(library, application, operating-system …)은 packages
GROUP_ORDER = ("packages", "models", "datasets", "files", "other")
SINGULAR = {"packages": "package", "models": "model", "datasets": "dataset", "files": "file", "other": "other"}
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")

# 줄은 utils/log.py 의 함수로 찍는다. stage 는 단계 한 줄, log 는 항상 찍는 줄(실패한 단계의 상세, 경고)이고,
# engine 모듈은 -v 일 때만 찍히는 detail 을 직접 가져다 쓴다.


@dataclass
class ScanResult:
    doc: dict                                         # 내보낼 문서. --format spdx 면 SPDX
    bom: dict                                         # 다 만든 CycloneDX 문서. 요약은 이것을 센다
    failed: list[str] = field(default_factory=list)   # 실패한 단계 (syft, cdxgen, pulling image, unpacking image)


# ── 요약 ────────────────────────────────────────────────────────────────────

def count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def group_of(comp: dict) -> str:
    """packages(S-BOM) · models(M-BOM) · datasets(D-BOM) · files, 그 어디도 아닌 type=data (cdxgen 의 apt 저장소 설정) 는 other."""
    kind = comp.get("type")
    if kind == "machine-learning-model":
        return "models"
    if kind == "file":
        return "files"
    if kind == "data":
        return "datasets" if is_dataset(comp) else "other"
    return "packages"


def groups(components: list[dict], skip: tuple[str, ...] = ()) -> str:
    """컴포넌트를 packages · models · datasets · files (· other) 로 묶어 센다. 0 인 묶음은 뺀다."""
    counts = dict.fromkeys(GROUP_ORDER, 0)
    for c in components:
        counts[group_of(c)] += 1
    parts = [f"{n} {SINGULAR[g] if n == 1 else g}" for g, n in counts.items() if n and g not in skip]
    return ", ".join(parts) or "nothing found"


def coverage_text(report: dict) -> str:
    """"13 of 17 filled (models 8/8, datasets 5/9)" — 채울 수 있는 규제 필드 가운데 채운 수. 종류별 괄호는 분모가 있는 것만."""
    if not report.get("total"):
        return "nothing to fill"
    parts = [f"{kind} {report[kind]['filled']}/{report[kind]['total']}" for kind in ("models", "datasets") if report[kind]["total"]]
    return f"{report['filled']} of {report['total']} filled ({', '.join(parts)})"


# ── scan ────────────────────────────────────────────────────────────────────

def check_scan(target: str, data: list[str]) -> list[str]:
    """도구를 돌리기 전에 입력을 본다. 문제가 있으면 오류 문구들, 없으면 빈 목록. 앞의 확인에서 걸리면 뒤는 보지 않는다.
    --data 의 허브 데이터셋은 리비전이 있는지 허브에 묻는다 (저장소는 있는데 그 리비전이 없다고 답한 것만 오류다)."""
    if _looks_like_path(target) and not Path(target).exists():
        return [f"target not found: {target}"]
    try:
        local_data, hub_data = split_data_args(data)        # hf://datasets/<id> 는 경로가 아니라 허브 데이터셋이다
    except ValueError as e:
        return [str(e)]
    missing = [d for d in local_data if not Path(d).expanduser().exists()]
    if missing:
        return [f"data path not found: {', '.join(missing)}"]
    return [f"--data {ref}: revision not found on huggingface.co ({reason})" for ref, reason in missing_revisions(hub_data)]


def _looks_like_path(target: str) -> bool:
    """이미지 참조가 아니라 파일 경로로 준 것인가. 이미지 이름도 / 를 담으므로(ghcr.io/org/img) 앞머리와 .tar 로만 가른다."""
    return (target.startswith(("/", "./", "../", "~")) or bool(_DRIVE.match(target))
            or target.lower().endswith((".tar", ".tar.gz", ".tgz")))


def scan(target: str, data: list[str], fmt: str, spec: str) -> ScanResult | None:
    """단계를 차례로 돌려 BOM 을 만든다. syft·cdxgen 이 둘 다 BOM 을 내지 못하면 None. 이미지를 푼 임시 폴더는 커서 끝나면 지운다.
    단계마다 stage 로 한 줄씩 찍는다. 항목별 내용은 찍지 않고, 사용자가 할 일이 있는 것(건너뜀·실패)만 그 줄에 붙인다."""
    workdir = Path(tempfile.mkdtemp(prefix="sure-aibom-"))
    try:
        return _scan(target, data, fmt, spec, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _scan(target: str, data: list[str], fmt: str, spec: str, workdir: Path) -> ScanResult | None:
    docs: list[dict] = []
    failed: list[str] = []

    def fail(label: str, what: str, error: Exception) -> None:
        first, *rest = str(error).splitlines() or [""]
        stage(label, f"failed: {first}")
        for line in [r for r in rest if r.strip()][-10:]:
            log(f"[sure-aibom]   {line}")
        failed.append(what)

    try:
        docs.append(run_syft(target, workdir))
        stage("Generating S-BOM (syft)", groups(docs[-1].get("components") or []))
    except RunnerError as e:
        fail("Generating S-BOM (syft)", "syft", e)

    # 이미지는 syft 만 그대로 읽는다. M-BOM·D-BOM 단계는 이미지를 푼 디렉터리에 대해 돌린다 (engine/image_tar.py 참고).
    scan_dir: str | None = target
    image_name: str | None = None
    if not Path(target).is_dir():
        scan_dir = None
        tar: Path | None = Path(target)
        if not is_archive(target):
            try:
                tar, tool = pull_image(target, workdir)
                stage(f"Pulling image ({tool})", "done")
            except RunnerError as e:
                fail("Pulling image", "pulling image", e)
                tar = None
        if tar is not None:
            try:
                layers, image_name = extract_image(tar, workdir / "rootfs")
                stage("Unpacking image", count(layers, "layer"))
                scan_dir = str(workdir / "rootfs")
            except ImageExtractionError as e:
                fail("Unpacking image", "unpacking image", e)

    if scan_dir is None:
        stage("Generating M-BOM (cdxgen)", "skipped: image not unpacked")
    else:
        try:
            docs.append(run_cdxgen(scan_dir, workdir))
            # cdxgen 이 만든 데이터셋은 이름뿐인 참조라 여기서 세지 않는다 (D-BOM 이 채워서 거기서 센다)
            stage("Generating M-BOM (cdxgen)", groups(docs[-1].get("components") or [], skip=("datasets",)))
        except RunnerError as e:
            fail("Generating M-BOM (cdxgen)", "cdxgen", e)

    if not docs:
        return None

    facts = Facts()                                           # CycloneDX 에 자리가 없어 메모리로만 들고 가는 값 (SPDX 출력만 쓴다)
    merged = merge(docs, root=scan_root(target, image_name), facts=facts)
    scan_dir = scan_dir or target                             # 이미지를 못 풀었으면 볼 디렉터리가 없다

    merged = discover_services(merged, scan_dir)              # cdxgen 서비스 가운데 코드가 SDK 로 부르는 것만 (import 는 직접 읽는다)
    merged = enrich_local_models(merged, scan_dir)

    enriched: dict = {}
    merged = enrich_hub_models(merged, workdir, report=enriched, facts=facts)
    if enriched["hub_skipped"]:
        result = f"skipped: {enriched['hub_skipped']}"
    elif enriched["hub_missing"]:
        result = f"{enriched['hub']} of {count(enriched['models'], 'hub model')} ({len(enriched['hub_missing'])} without hub info)"
    else:
        result = count(enriched["hub"], "hub model")
    stage("Enriching M-BOM (Hub API)", result)
    if enriched["skipped"]:
        result = f"skipped: {enriched['skipped']}"
    elif enriched["failed"]:
        result = f"{enriched['enriched']} of {count(enriched['models'], 'hub model')} ({len(enriched['failed'])} failed)"
    else:
        result = count(enriched["enriched"], "hub model")
    stage("Enriching M-BOM (aibom-generator)", result)
    for hf_id, reason in enriched["errors"].items():             # 보강은 선택 단계라 실패해도 failed 에 넣지 않고 이유만 알린다
        log(f"[sure-aibom]   {hf_id}: {reason}")

    # 허브 모델 카드의 데이터셋은 M-BOM 보강이 받아 둔 Hub API 응답에서 읽는다 (같은 응답을 다시 받지 않는다)
    datasets: dict = {}
    merged = discover_datasets(merged, scan_dir, report=datasets, data_paths=data,
                               model_infos=enriched["model_infos"], hub_reachable=enriched["hub_reachable"], facts=facts)
    total = count(sum(1 for c in merged["components"] if is_dataset(c)), "dataset")
    stage("Generating D-BOM", total + (" (huggingface.co unreachable, hub details skipped)" if datasets.get("hub_unreachable") else ""))
    for path in datasets.get("empty_data_paths") or []:
        log(f"[sure-aibom] warning: no data files in {path}")
    for ref in datasets.get("unresolved_hub_data") or []:
        log(f"[sure-aibom] warning: huggingface.co lookup failed for {ref}, kept as given")

    regulation: dict = {}
    merged = regulate(merged, form=FORM_BY_SPEC[spec], report=regulation)
    stage("Adding regulation fields", coverage_text(regulation))
    merged = drop_tool_properties(merged)                         # 출력의 properties 는 aibom:* 뿐이다

    out_doc = merged
    if fmt == "spdx":                                             # 값은 CycloneDX 로 다 만들고 마지막에 모양만 바꾼다
        out_doc = convert_spdx(merged, spec, facts=facts)
        graph = out_doc["@graph"]
        stage(f"Converting to {FORMAT_NAME[(fmt, spec)]}",
              f"{count(sum(1 for e in graph if e['type'] not in ('CreationInfo', 'Relationship')), 'element')}, "
              f"{count(sum(1 for e in graph if e['type'] == 'Relationship'), 'relationship')}")
    return ScanResult(doc=out_doc, bom=merged, failed=failed)


def scan_root(target: str, image_name: str | None = None) -> tuple[str, str]:
    """스캔 대상의 (이름, 종류). 디렉터리는 마지막 경로 이름. 이미지는 tar 에 적힌 이름(aiapp:demo)이 있으면 그것,
    없으면 .tar 는 파일 이름, 이미지 참조는 준 그대로."""
    path = Path(target)
    if path.is_dir():
        return (path.resolve().name or target, "directory")
    return (image_name or (path.name if is_archive(target) else target), "image")

