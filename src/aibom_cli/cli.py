"""aibom-cli 진입점 (scan(생성) · validate(검증). 사용법은 README 또는 `aibom-cli --help`."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from . import __version__
from .dataset import discover as discover_datasets
from .enrich import enrich
from .merge import merge
from .model import discover as discover_models
from .form import apply as regulate
from .runners import run_cdxgen, run_syft
from .runners._proc import RunnerError
from .validate import CDX_SCHEMA_BY_SPEC, validate_cdx

EXIT_TOOL = 2      # 실행 오류 (잘못된 인자·입력, 도구 없음·실패)
EXIT_INVALID = 3   # 스키마 불일치 (1 은 파이썬이 처리 못 한 예외로 죽을 때 내므로 비워 둔다)

SCHEMA_NAME = {"1.7": "CycloneDX 1.7 schema", "v0.6": "AI-BOM v0.6 schema"}   # validate 는 문서를 어떻게 만들었는지 모른다
# scan --spec → 규제 필드를 넣는 형태. 1.7 은 표준 properties 라 1.7·v0.6 스키마 모두에 맞고, v0.6 은 v0.6 스키마에만 맞는다
FORM_BY_SPEC = {"1.7": "properties", "v0.6": "typed"}
FIELDS_LABEL = {"1.7": "CycloneDX 1.7 properties", "v0.6": "AI-BOM v0.6 fields"}
STAGE_WIDTH = 36                                   # 단계 이름 뒤 점선까지의 너비


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _quiet(msg: str) -> None:
    """모듈의 항목별 로그는 CLI 에서 찍지 않는다 (단계마다 한 줄만 찍는다)."""


def _stage(label: str, result: str = "") -> None:
    dots = "." * max(3, STAGE_WIDTH - len(label))
    _log(f"[aibom-cli] {label} {dots} {result}".rstrip())


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_path(target: str) -> bool:
    """이미지 참조가 아니라 파일 경로로 준 것인가. 이미지 이름도 / 를 담으므로(ghcr.io/org/img) 앞머리와 .tar 로만 가른다."""
    return (target.startswith(("/", "./", "../", "~")) or bool(_DRIVE.match(target))
            or target.lower().endswith((".tar", ".tar.gz", ".tgz")))


def _emit(doc: dict, path: str | None) -> None:
    """경로가 있으면 파일로, 없으면 표준출력으로."""
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log(f"[aibom-cli] error: cannot read {path} ({e})")
        return None


# ── scan ────────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> int:
    """단계마다 한 줄씩 찍는다. 항목별 내용은 찍지 않고, 사용자가 할 일이 있는 것(건너뜀·실패)만 그 줄에 붙인다.
    syft·cdxgen 중 하나라도 실패하면 만든 만큼은 쓰되 종료 코드 2 로 끝낸다 (CI 가 모자란 BOM 을 성공으로 넘기지 않게)."""
    if args.target.startswith("~"):
        args.target = str(Path(args.target).expanduser())
    if _looks_like_path(args.target) and not Path(args.target).exists():
        _log(f"[aibom-cli] error: target not found: {args.target}")
        return EXIT_TOOL

    workdir = Path(tempfile.mkdtemp(prefix="aibom-cli-"))
    docs: list[dict] = []
    failed: list[str] = []
    for tool, label, runner, summarize in (
        ("syft", "Generating S-BOM (syft)", run_syft, lambda d: _count(len(d.get("components") or []), "component")),
        ("cdxgen", "Generating M-BOM (cdxgen)", run_cdxgen, lambda d: _count(_models(d), "model")),
    ):
        try:
            doc = runner(args.target, workdir)
        except RunnerError as e:
            first, *rest = str(e).splitlines() or [""]
            _stage(label, f"failed: {first}")
            for line in [r for r in rest if r.strip()][-10:]:
                _log(f"[aibom-cli]   {line}")
            failed.append(tool)
            continue
        _stage(label, summarize(doc))
        if runner is run_cdxgen and not Path(args.target).is_dir() and not doc.get("components"):
            # cdxgen 은 레지스트리에서 이미지를 직접 받지 못한다. 데몬이 없으면 조용히 빈 결과를 내므로 여기서 알린다.
            _log("[aibom-cli] warning: cdxgen read nothing from the image (it needs a Docker/Podman daemon; "
                 "pass the image as a .tar to scan without one)")
        docs.append(doc)

    if not docs:
        _log("[aibom-cli] error: neither syft nor cdxgen produced a BOM")
        return EXIT_TOOL

    merged = merge(docs, root=scan_root(args.target))

    datasets: dict = {}
    merged = discover_datasets(merged, args.target, log=_quiet, report=datasets)
    n = _count(sum(1 for c in merged["components"] if c.get("type") == "data"), "dataset")
    _stage("Generating D-BOM", n + (" (huggingface.co unreachable, hub details skipped)" if datasets.get("hub_unreachable") else ""))

    merged = discover_models(merged, args.target, log=_quiet)

    enriched: dict = {}
    merged = enrich(merged, workdir, log=_quiet, report=enriched)
    if enriched["skipped"]:
        result = f"skipped: {enriched['skipped']}"
    elif enriched["failed"]:
        result = f"{enriched['enriched']} of {_count(enriched['models'], 'model')}, {len(enriched['failed'])} failed"
    else:
        result = _count(enriched["enriched"], "model")
    _stage("Enriching M-BOM (aibom-generator)", result)
    for hf_id, reason in enriched["errors"].items():             # 보강은 선택 단계라 종료 코드는 그대로 두고 이유만 알린다
        _log(f"[aibom-cli]   {hf_id}: {reason}")

    merged = regulate(merged, form=FORM_BY_SPEC[args.spec], log=_quiet)
    _stage("Adding regulation fields", FIELDS_LABEL[args.spec])

    _emit(merged, args.output)
    _log(f"[aibom-cli] Wrote {args.output or 'stdout'} ({_count(len(merged['components']), 'component')}, "
         f"{_count(len(merged['dependencies']), 'dependency', 'dependencies')})")
    if failed:
        _log(f"[aibom-cli] error: {' and '.join(failed)} failed, so the BOM is incomplete")
        return EXIT_TOOL
    return 0


def _models(doc: dict) -> int:
    return sum(1 for c in doc.get("components") or [] if c.get("type") == "machine-learning-model")


def scan_root(target: str) -> tuple[str, str]:
    """스캔 대상의 (이름, 종류). 디렉터리는 마지막 경로 이름, 그 외(이미지 참조)는 그대로."""
    path = Path(target)
    if path.is_dir():
        return (path.resolve().name or target, "directory")
    return (target, "image")


# ── validate ────────────────────────────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> int:
    doc = _read(args.bom)
    if doc is None:
        return EXIT_TOOL
    if "bomFormat" not in doc:
        _log(f"[aibom-cli] error: not a CycloneDX document (no bomFormat): {args.bom}")
        return EXIT_TOOL
    if not validate_cdx(doc, args.spec, log=_log):
        _log(f"[aibom-cli] Invalid against the {SCHEMA_NAME[args.spec]} (--spec {args.spec}): {args.bom}")
        return EXIT_INVALID
    _log(f"[aibom-cli] Valid against the {SCHEMA_NAME[args.spec]}: {args.bom}")
    return 0


# ── parser ──────────────────────────────────────────────────────────────────

EXAMPLES = """\
examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  aibom-cli scan ./project -o bom.cdx.json --spec v0.6        디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 필드로 넣음
  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  컨테이너 이미지를 스캔 (Docker/Podman 데몬이 없는 경우)
  aibom-cli scan ./project                                    표준출력으로 출력
  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 스키마로 검증

exit codes:
  0  성공        2  실행 오류        3  스키마 불일치
"""


def _formatter(prog: str) -> argparse.HelpFormatter:
    """옵션 이름과 설명을 한 줄에 놓고(max_help_position), 설명 안의 줄바꿈은 그대로 둔다."""
    return argparse.RawTextHelpFormatter(prog, max_help_position=32, width=110)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aibom-cli",
        usage="aibom-cli <command> [flags]",
        description="syft·cdxgen·OWASP aibom-generator 로 데이터셋·모델·소프트웨어 BOM 을 만들고 규제 필드를 더해 CycloneDX 1.7 로 낸다.",
        epilog=EXAMPLES,
        formatter_class=_formatter,
    )
    p.add_argument("--version", action="version", version=f"aibom-cli {__version__}")
    sub = p.add_subparsers(dest="command", required=True, title="commands", metavar="<command>")

    s = sub.add_parser(
        "scan",
        help="디렉터리 또는 컨테이너 이미지를 스캔해 CycloneDX 1.7 AI-BOM 을 만든다",
        usage="aibom-cli scan <TARGET> [-o PATH] [--spec {1.7,v0.6}]",
        epilog="environment:\n  AIBOM_GENERATOR_DIR           aibom-generator 클론 경로 (설치 절에서 설정)",
        formatter_class=_formatter,
    )
    s.add_argument("target", metavar="TARGET", help="디렉터리 경로, 컨테이너 이미지 참조, 또는 이미지 .tar")
    s.add_argument("-o", "--output", metavar="PATH", help="출력 경로. 없으면 표준출력")
    s.add_argument("--spec", choices=tuple(FORM_BY_SPEC), default="1.7", metavar="{1.7,v0.6}",
                   help="규제 필드를 넣을 스키마 (default: 1.7)\n"
                        "  1.7   CycloneDX 1.7 의 properties 로 넣음\n"
                        "  v0.6  AI-BOM v0.6 의 필드로 넣음 (문서의 specVersion 은 1.7 그대로)")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser(
        "validate",
        help="CycloneDX 문서를 --spec 이 고른 스키마로 검증한다",
        usage="aibom-cli validate <BOM> --spec {1.7,v0.6}",
        formatter_class=_formatter,
    )
    v.add_argument("bom", metavar="BOM", help="검증할 CycloneDX JSON 파일")
    v.add_argument("--spec", choices=tuple(CDX_SCHEMA_BY_SPEC), required=True, metavar="{1.7,v0.6}",
                   help="검증할 스키마 (필수)\n"
                        "  1.7   CycloneDX 1.7\n"
                        "  v0.6  AI-BOM v0.6")
    v.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
