"""aibom-cli 진입점 — scan(생성) · validate(검증). 사용법은 README 또는 `aibom-cli --help`."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
from .enrich import enrich
from .merge import merge
from .regulation import FORMS
from .regulation import apply as regulate
from .runners import run_cdxgen, run_syft
from .runners._proc import RunnerError
from .validate import CDX_SCHEMA_BY_SPEC, validate_cdx

EXIT_TOOL = 2      # 생산자·입력 문제
EXIT_INVALID = 3   # 검증 실패

SPEC_NOTE = {"1.7": "공식 CycloneDX 1.7 — properties 형, 표준 소비자가 읽을 수 있다",
             "v0.6": "aibom-v0.6 CycloneDX 스키마 — typed 형, v0.6 를 아는 소비자만 읽을 수 있다"}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _emit(doc: dict, path: str | None) -> None:
    """경로가 있으면 파일로, 없으면 표준출력으로."""
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        _log(f"[aibom-cli] wrote {out}")
    else:
        sys.stdout.write(text)


def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log(f"[aibom-cli] 읽을 수 없다: {path} ({e})")
        return None


# ── scan ────────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> int:
    workdir = Path(tempfile.mkdtemp(prefix="aibom-cli-"))
    docs: list[dict] = []
    for name, runner in (
        ("syft", lambda: run_syft(args.target, workdir)),
        ("cdxgen", lambda: run_cdxgen(args.target, workdir)),
    ):
        try:
            doc = runner()
        except RunnerError as e:
            _log(f"[aibom-cli] {name}: {e}")
            continue
        if name == "cdxgen" and not Path(args.target).is_dir() and not doc.get("components"):
            # cdxgen 은 레지스트리에서 이미지를 직접 받지 못한다. 데몬이 없으면 조용히 빈 결과를 내므로 여기서 알린다.
            _log("[aibom-cli] cdxgen 이 이미지에서 아무것도 읽지 못했다 — Docker/Podman 데몬이 없으면 모델·데이터셋이 빠진다. "
                 "이미지를 .tar 로 내보내 넘기면 데몬 없이도 읽는다")
        docs.append(doc)

    if not docs:
        _log("[aibom-cli] 생산자 결과가 하나도 없다")
        return EXIT_TOOL

    merged = merge(docs, root=scan_root(args.target))
    merged = enrich(merged, workdir, log=_log)
    merged = regulate(merged, form=args.form, log=_log)

    _emit(merged, args.output)
    _log(f"[aibom-cli] components={len(merged['components'])} dependencies={len(merged['dependencies'])}")
    return 0


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
        _log("[aibom-cli] CycloneDX 문서(bomFormat)가 아니다")
        return EXIT_TOOL
    if not validate_cdx(doc, args.spec, log=_log):
        _log(f"[aibom-cli] 검증 실패 (--spec {args.spec}): {args.bom}")
        return EXIT_INVALID
    _log(f"[aibom-cli] CycloneDX {args.spec} 적합 ({SPEC_NOTE[args.spec]}): {args.bom}")
    return 0


# ── parser ──────────────────────────────────────────────────────────────────

EXAMPLES = """\
examples:
  aibom-cli scan ./project -o bom.cdx.json                    디렉터리를 스캔하여 규제 필드를 properties로 넣음
  aibom-cli scan ./project -o bom.cdx.json --form typed       디렉터리를 스캔하여 규제 필드를 v0.6 필드로 넣음
  aibom-cli scan alpine:3.20 -o alpine.cdx.json               컨테이너 이미지를 스캔
  aibom-cli scan image.tar -o image.cdx.json                  컨테이너 이미지를 스캔 (Docker/Podman 데몬이 없는 경우)
  aibom-cli scan ./project                                    표준출력으로 출력
  aibom-cli validate bom.cdx.json --spec 1.7                  CycloneDX 1.7 스키마로 검증
  aibom-cli validate bom.cdx.json --spec v0.6                 AI-BOM v0.6 스키마로 검증

exit codes:
  0  성공        2  도구·입력 문제        3  검증 실패
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
        usage="aibom-cli scan <TARGET> [-o PATH] [--form {properties,typed}]",
        epilog="environment:\n  AIBOM_GENERATOR_DIR           aibom-generator 클론 경로 (설치 절에서 설정)",
        formatter_class=_formatter,
    )
    s.add_argument("target", metavar="TARGET", help="디렉터리 경로, 컨테이너 이미지 참조, 또는 이미지 .tar")
    s.add_argument("-o", "--output", metavar="PATH", help="출력 경로. 없으면 표준출력")
    s.add_argument("--form", choices=FORMS, default="properties", metavar="{properties,typed}",
                   help="규제 필드를 내보내는 형태 (default: properties)\n"
                        "  properties  CycloneDX의 properties로 내보냄\n"
                        "  typed       AI-BOM v0.6 스키마의 필드로 내보냄")
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
