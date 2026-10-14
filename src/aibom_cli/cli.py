"""aibom-cli 진입점 (scan(생성) · validate(검증). 사용법은 README 또는 `aibom-cli --help`."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from .dataset import discover as discover_datasets, is_dataset
from .enrich import enrich
from .merge import merge
from .model import discover as discover_models
from .form import apply as regulate, drop_tool_properties
from .image import extract as extract_image, is_archive, pull as pull_image
from .runners import run_cdxgen, run_syft
from .runners._proc import RunnerError
from .validate import CDX_SCHEMA_BY_SPEC, validate_cdx

EXIT_TOOL = 2      # 실행 오류 (잘못된 인자·입력, 도구 없음·실패)
EXIT_INVALID = 3   # 스키마 불일치 (1 은 파이썬이 처리 못 한 예외로 죽을 때 내므로 비워 둔다)

SCHEMA_NAME = {"1.7": "CycloneDX 1.7 schema", "v0.6": "AI-BOM v0.6 (CycloneDX) schema"}   # validate 는 문서를 어떻게 만들었는지 모른다
# scan --spec → 규제 필드를 넣는 형태. 1.7 은 표준 properties 라 1.7·v0.6 스키마 모두에 맞고, v0.6 은 v0.6 스키마에만 맞는다
FORM_BY_SPEC = {"1.7": "properties", "v0.6": "typed"}
FORMAT_NAME = {"1.7": "CycloneDX 1.7", "v0.6": "AI-BOM v0.6 (CycloneDX)"}
# 요약 줄의 묶음: CycloneDX type → S/M/D 와 파일. 목록에 없는 type(library, application, operating-system …)은 packages
GROUP_ORDER = ("packages", "models", "datasets", "files", "other")
SINGULAR = {"packages": "package", "models": "model", "datasets": "dataset", "files": "file", "other": "other"}
STAGE_WIDTH = 36                                   # 단계 이름 뒤 점선까지의 너비


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _quiet(msg: str) -> None:
    """모듈의 항목별 로그는 -v 없이는 찍지 않는다 (단계마다 한 줄만 찍는다)."""


def _stage(label: str, result: str = "") -> None:
    dots = "." * max(3, STAGE_WIDTH - len(label))
    _log(f"[aibom-cli] {label} {dots} {result}".rstrip())


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _group_of(comp: dict) -> str:
    """packages(S-BOM) · models(M-BOM) · datasets(D-BOM) · files, 그 어디도 아닌 type=data (cdxgen 의 apt 저장소 설정) 는 other."""
    kind = comp.get("type")
    if kind == "machine-learning-model":
        return "models"
    if kind == "file":
        return "files"
    if kind == "data":
        return "datasets" if is_dataset(comp) else "other"
    return "packages"


def _groups(components: list[dict], skip: tuple[str, ...] = ()) -> str:
    """컴포넌트를 packages · models · datasets · files (· other) 로 묶어 센다. 0 인 묶음은 뺀다."""
    counts = dict.fromkeys(GROUP_ORDER, 0)
    for c in components:
        counts[_group_of(c)] += 1
    parts = [f"{n} {SINGULAR[g] if n == 1 else g}" for g, n in counts.items() if n and g not in skip]
    return ", ".join(parts) or "nothing found"


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
    missing = [d for d in args.data if not Path(d).expanduser().exists()]
    if missing:
        _log(f"[aibom-cli] error: data path not found: {', '.join(missing)}")
        return EXIT_TOOL

    data = f", data from {', '.join(args.data)}" if args.data else ""
    _log(f"[aibom-cli] Generating {FORMAT_NAME[args.spec]} for {args.target}{data}")

    workdir = Path(tempfile.mkdtemp(prefix="aibom-cli-"))
    try:
        return _scan(args, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)             # 이미지를 푼 디렉터리가 커서 남기지 않는다


def _failed(label: str, what: str, error: Exception, failed: list[str]) -> None:
    first, *rest = str(error).splitlines() or [""]
    _stage(label, f"failed: {first}")
    for line in [r for r in rest if r.strip()][-10:]:
        _log(f"[aibom-cli]   {line}")
    failed.append(what)


def _scan(args: argparse.Namespace, workdir: Path) -> int:
    detail = _log if getattr(args, "verbose", False) else _quiet     # -v: 모듈의 항목별 로그(건너뛴 것, 버린 값, 빈 필드)도 찍는다
    docs: list[dict] = []
    failed: list[str] = []
    try:
        docs.append(run_syft(args.target, workdir))
        _stage("Generating S-BOM (syft)", _groups(docs[-1].get("components") or []))
    except RunnerError as e:
        _failed("Generating S-BOM (syft)", "syft", e, failed)

    # 이미지는 syft 만 그대로 읽는다. M-BOM·D-BOM 단계는 이미지를 푼 디렉터리에 대해 돌린다 (image.py 참고).
    scan_dir: str | None = args.target
    image_name: str | None = None
    if not Path(args.target).is_dir():
        scan_dir = None
        label = "Pulling image"
        try:
            tar = Path(args.target)
            if not is_archive(args.target):
                tar, tool = pull_image(args.target, workdir)
                _stage(f"{label} ({tool})", "done")
            label = "Unpacking image"
            layers, image_name = extract_image(tar, workdir / "rootfs")
            _stage(label, _count(layers, "layer"))
            scan_dir = str(workdir / "rootfs")
        except RunnerError as e:
            _failed(label, label.lower(), e, failed)

    if scan_dir is None:
        _stage("Generating M-BOM (cdxgen)", "skipped: image not unpacked")
    else:
        try:
            docs.append(run_cdxgen(scan_dir, workdir))
            # cdxgen 이 만든 데이터셋은 이름뿐인 참조라 여기서 세지 않는다 (D-BOM 이 채워서 거기서 센다)
            _stage("Generating M-BOM (cdxgen)", _groups(docs[-1].get("components") or [], skip=("datasets",)))
        except RunnerError as e:
            _failed("Generating M-BOM (cdxgen)", "cdxgen", e, failed)

    if not docs:
        _log("[aibom-cli] error: neither syft nor cdxgen produced a BOM")
        return EXIT_TOOL

    merged = merge(docs, root=scan_root(args.target, image_name))
    scan_dir = scan_dir or args.target                        # 이미지를 못 풀었으면 볼 디렉터리가 없다

    merged = discover_models(merged, scan_dir, log=detail)

    enriched: dict = {}
    merged = enrich(merged, workdir, log=detail, report=enriched)
    if enriched["hub_skipped"]:
        result = f"skipped: {enriched['hub_skipped']}"
    elif enriched["hub_missing"]:
        result = f"{enriched['hub']} of {_count(enriched['models'], 'hub model')} ({len(enriched['hub_missing'])} without hub info)"
    else:
        result = _count(enriched["hub"], "hub model")
    _stage("Enriching M-BOM (Hub API)", result)
    if enriched["skipped"]:
        result = f"skipped: {enriched['skipped']}"
    elif enriched["failed"]:
        result = f"{enriched['enriched']} of {_count(enriched['models'], 'hub model')} ({len(enriched['failed'])} failed)"
    else:
        result = _count(enriched["enriched"], "hub model")
    _stage("Enriching M-BOM (aibom-generator)", result)
    for hf_id, reason in enriched["errors"].items():             # 보강은 선택 단계라 종료 코드는 그대로 두고 이유만 알린다
        _log(f"[aibom-cli]   {hf_id}: {reason}")

    # 허브 모델 카드의 데이터셋은 M-BOM 보강이 받아 둔 Hub API 응답에서 읽는다 (같은 응답을 다시 받지 않는다)
    datasets: dict = {}
    merged = discover_datasets(merged, scan_dir, log=detail, report=datasets, data_paths=args.data,
                               model_infos=enriched["model_infos"], hub_reachable=enriched["hub_reachable"])
    total = _count(sum(1 for c in merged["components"] if is_dataset(c)), "dataset")
    _stage("Generating D-BOM", total + (" (huggingface.co unreachable, hub details skipped)" if datasets.get("hub_unreachable") else ""))
    for path in datasets.get("empty_data_paths") or []:
        _log(f"[aibom-cli] warning: no data files in {path}")

    regulation: dict = {}
    merged = regulate(merged, form=FORM_BY_SPEC[args.spec], log=detail, report=regulation)
    _stage("Adding regulation fields", _coverage_text(regulation))
    merged = drop_tool_properties(merged)                         # 출력의 properties 는 aibom:* 뿐이다

    _emit(merged, args.output)
    # 위 줄들을 더하지 않고 다 만든 BOM 을 다시 센다 (병합·별칭 합치기로 줄어든 만큼이 여기 반영된다)
    _log(f"[aibom-cli] Wrote {args.output or 'stdout'} ({_count(len(merged['components']), 'component')}: "
         f"{_groups(merged['components'])}; {_count(len(merged['dependencies']), 'dependency', 'dependencies')})")
    if failed:
        _log(f"[aibom-cli] error: {' and '.join(failed)} failed, so the BOM is incomplete")
        return EXIT_TOOL
    return 0


def _coverage_text(report: dict) -> str:
    """"13 of 17 filled (models 8/8, datasets 5/9)" — 채울 수 있는 규제 필드 가운데 채운 수. 종류별 괄호는 분모가 있는 것만."""
    if not report.get("total"):
        return "nothing to fill"
    parts = [f"{kind} {report[kind]['filled']}/{report[kind]['total']}" for kind in ("models", "datasets") if report[kind]["total"]]
    return f"{report['filled']} of {report['total']} filled ({', '.join(parts)})"


def scan_root(target: str, image_name: str | None = None) -> tuple[str, str]:
    """스캔 대상의 (이름, 종류). 디렉터리는 마지막 경로 이름. 이미지는 tar 에 적힌 이름(aiapp:demo)이 있으면 그것,
    없으면 .tar 는 파일 이름, 이미지 참조는 준 그대로."""
    path = Path(target)
    if path.is_dir():
        return (path.resolve().name or target, "directory")
    return (image_name or (path.name if is_archive(target) else target), "image")


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
# 도움말은 한 장이다. aibom-cli --help, scan --help, validate --help, 인자 없이 실행이 모두 이것을 찍고,
# README 의 사용 절도 이 글자 그대로다 (tests/test_cli.py 가 둘이 같은지 본다).

BANNER = r"""
    ___    ________  ____  __  ___   ________    ____
   /   |  /  _/ __ )/ __ \/  |/  /  / ____/ /   /  _/
  / /| |  / // __  / / / / /|_/ /  / /   / /    / /
 / ___ |_/ // /_/ / /_/ / /  / /  / /___/ /____/ /
/_/  |_/___/_____/\____/_/  /_/   \____/_____/___/
"""[1:]

HELP = BANNER + """
Usage:
  aibom-cli scan <target> [options]
  aibom-cli validate <bom> --spec <1.7|v0.6>

Commands:
  scan <target>               디렉터리 또는 컨테이너 이미지를 스캔해 AI-BOM 을 만든다
  validate <bom>              BOM 을 --spec 이 고른 스키마로 검증한다

Options:
  -o, --output <path>         [scan] 출력 경로 (default: 표준출력)
  --data <path>               [scan] 로컬 데이터 경로. 여러 번 줄 수 있음 (optional)
  --spec <1.7|v0.6>           [scan] 규제 필드를 넣을 스키마 (default: 1.7)
                                1.7   CycloneDX 1.7 의 properties 로 넣음
                                v0.6  AI-BOM v0.6 (CycloneDX) 의 필드로 넣음
                              [validate] 검증할 스키마 (required)
  -v, --verbose               [scan] 항목별 상세 로그
  --version                   버전을 보여 준다
  -h, --help                  도움말을 보여 준다

Examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  aibom-cli scan ./project -o bom.cdx.json --spec v0.6        디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 (CycloneDX) 필드로 넣음
  aibom-cli scan ./project -o bom.cdx.json --data ./dataset   로컬 데이터 경로를 함께 지정

  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  이미지 .tar 를 스캔

  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 (CycloneDX) 스키마로 검증

Exit codes:
  0  성공        2  실행 오류        3  스키마 불일치
"""


class _Help(argparse.Action):
    """-h, --help: argparse 가 만드는 도움말 대신 HELP 한 장을 찍는다."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        sys.stdout.write(HELP)
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aibom-cli", usage="aibom-cli <command> [options]", add_help=False)
    p.add_argument("-h", "--help", action=_Help)
    p.add_argument("--version", action="version", version=f"aibom-cli {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("scan", prog="aibom-cli scan", usage="aibom-cli scan <target> [options]", add_help=False)
    s.add_argument("-h", "--help", action=_Help)
    s.add_argument("target", metavar="<target>")
    s.add_argument("-o", "--output", metavar="<path>")
    s.add_argument("--data", action="append", default=[], metavar="<path>")
    s.add_argument("--spec", choices=tuple(FORM_BY_SPEC), default="1.7", metavar="<1.7|v0.6>")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("validate", prog="aibom-cli validate", usage="aibom-cli validate <bom> --spec <1.7|v0.6>",
                       add_help=False)
    v.add_argument("-h", "--help", action=_Help)
    v.add_argument("bom", metavar="<bom>")
    v.add_argument("--spec", choices=tuple(CDX_SCHEMA_BY_SPEC), required=True, metavar="<1.7|v0.6>")
    v.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not hasattr(args, "func"):                      # 명령 없이 실행하면 도움말
        sys.stdout.write(HELP)
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
