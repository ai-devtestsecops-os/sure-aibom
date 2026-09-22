"""aibom-cli — 서브커맨드 셋.

    scan     <target> [-o bom.json] [--no-enrich]   디렉터리·이미지를 스캔해 CycloneDX 1.7 을 만든다 (생성만)
    validate <bom> [--strict]                       CycloneDX 또는 SPDX 문서를 스키마로 검증한다
    convert  <bom> [-o out.spdx.json] [--strict]    CycloneDX 1.7 → SPDX 3.0.1 (실험 단계)

scan 은 syft(소프트웨어) + cdxgen(모델·데이터셋) 을 돌려 병합하고 aibom-generator 로 보강한다.
검증·변환은 scan 안에서 하지 않고 파일을 받아 따로 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import __version__
from .enrich import enrich
from .merge import merge
from .runners import run_cdxgen, run_syft
from .runners._proc import RunnerError
from .spdx import cdx_to_spdx
from .validate import validate_cdx, validate_spdx

EXIT_TOOL = 2      # 생산자·입력 문제
EXIT_INVALID = 3   # 검증 실패


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
            docs.append(runner())
        except RunnerError as e:
            _log(f"[aibom-cli] {name}: {e}")

    if not docs:
        _log("[aibom-cli] 생산자 결과가 하나도 없다")
        return EXIT_TOOL

    merged = merge(docs, root=scan_root(args.target))
    if not args.no_enrich:
        merged = enrich(merged, workdir, log=_log)

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
    if "bomFormat" in doc:
        ok = validate_cdx(doc, log=_log)
        kind = "CycloneDX"
    elif "@graph" in doc:
        ok = validate_spdx(doc, strict=args.strict, log=_log)
        kind = "SPDX 3.0.1" + (" (공식 스키마)" if args.strict else " (v0.6 스키마)")
    else:
        _log("[aibom-cli] CycloneDX(bomFormat) 도 SPDX(@graph) 도 아니다")
        return EXIT_TOOL
    _log(f"[aibom-cli] {kind} 검증 {'통과' if ok else '실패'}: {args.bom}")
    return 0 if ok else EXIT_INVALID


# ── convert ─────────────────────────────────────────────────────────────────

def cmd_convert(args: argparse.Namespace) -> int:
    _log("[convert] 실험 단계 — SPDX 3.0.1 변환은 최종 검증 전이다. 결과를 validate 로 확인하라.")
    doc = _read(args.bom)
    if doc is None:
        return EXIT_TOOL
    if "bomFormat" not in doc:
        _log("[aibom-cli] convert 의 입력은 CycloneDX 문서여야 한다")
        return EXIT_TOOL
    try:
        spdx_doc = cdx_to_spdx(doc, strict=args.strict, log=_log)
    except ValueError as e:
        _log(f"[aibom-cli] 변환 실패: {e}")
        return EXIT_TOOL
    _emit(spdx_doc, args.output)
    return 0


# ── parser ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aibom-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"aibom-cli {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "scan",
        help="디렉터리 또는 컨테이너 이미지를 스캔해 CycloneDX 1.7 AI-BOM 을 만든다",
        epilog="환경변수: AIBOM_GENERATOR_DIR (owasp 클론 경로, 필수) · SYFT_BIN, CDXGEN_BIN (PATH 에 없을 때만)",
    )
    s.add_argument("target", help="디렉터리 경로 또는 이미지 참조")
    s.add_argument("-o", "--output", metavar="PATH", help="CycloneDX 1.7 JSON 출력 경로 (없으면 표준출력)")
    s.add_argument("--no-enrich", action="store_true", help="aibom-generator 보강 생략 (HF 네트워크가 없을 때)")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("validate", help="CycloneDX 또는 SPDX 문서를 aibom-v0.6 스키마로 검증한다")
    v.add_argument("bom", help="검증할 JSON 파일. 형식은 내용으로 판별한다")
    v.add_argument("--strict", action="store_true", help="SPDX 문서를 v0.6 대신 공식 3.0.1 스키마로 검증한다")
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("convert", help="CycloneDX 1.7 → SPDX 3.0.1 JSON-LD (실험 단계)")
    c.add_argument("bom", help="CycloneDX 1.7 JSON 파일")
    c.add_argument("-o", "--output", metavar="PATH", help="SPDX 출력 경로 (없으면 표준출력)")
    c.add_argument("--strict", action="store_true", help="v0.6 전용 aibom_* 속성을 확장 항목으로 내려 공식 3.0.1 스키마에 맞춘다")
    c.set_defaults(func=cmd_convert)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
