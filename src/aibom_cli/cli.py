"""aibom-cli scan <target> [--cdx out.json] [--spdx out.spdx.json]

    syft  (--select-catalogers -ai)         → 소프트웨어
    cdxgen (-t ai --include-formulation)    → 모델·데이터셋
    병합 → aibom-generator 보강 → 검증 → CycloneDX 1.7 → SPDX 3.0.1
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


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _log(f"[aibom-cli] wrote {path}")


def cmd_scan(args: argparse.Namespace) -> int:
    workdir = Path(args.keep_intermediate) if args.keep_intermediate else Path(tempfile.mkdtemp(prefix="aibom-cli-"))
    workdir.mkdir(parents=True, exist_ok=True)
    docs: list[dict] = []

    for name, runner, enabled in (
        ("syft", lambda: run_syft(args.target, workdir), not args.no_syft),
        ("cdxgen", lambda: run_cdxgen(args.target, workdir, install_deps=args.install_deps), not args.no_cdxgen),
    ):
        if not enabled:
            continue
        try:
            docs.append(runner())
        except RunnerError as e:
            _log(f"[aibom-cli] {name}: {e}")
            if args.strict:
                return 2

    if not docs:
        _log("[aibom-cli] 생산자 결과가 하나도 없다")
        return 2

    merged = merge(docs, root=scan_root(args.target))
    if not args.no_enrich:
        merged = enrich(merged, workdir, log=_log)

    ok = True
    if not args.no_validate:
        ok = validate_cdx(merged, log=_log)

    if args.cdx:
        _write(Path(args.cdx), merged)
    if args.spdx:
        spdx_doc = cdx_to_spdx(merged, strict=args.spdx_strict, log=_log)
        if not args.no_validate:
            ok = validate_spdx(spdx_doc, strict=args.spdx_strict, log=_log) and ok
        _write(Path(args.spdx), spdx_doc)
    if not args.cdx and not args.spdx:
        json.dump(merged, sys.stdout, ensure_ascii=False, indent=2)
        print()

    _log(f"[aibom-cli] components={len(merged['components'])} dependencies={len(merged['dependencies'])} intermediate={workdir}")
    return 0 if (ok or not args.strict) else 3


def scan_root(target: str) -> tuple[str, str]:
    """스캔 대상의 (이름, 종류). 디렉터리는 마지막 경로 이름, 그 외(이미지 참조)는 그대로."""
    path = Path(target)
    if path.is_dir():
        return (path.resolve().name or target, "directory")
    return (target, "image")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aibom-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"aibom-cli {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "scan",
        help="디렉터리 또는 컨테이너 이미지를 스캔해 AI-BOM 을 만든다",
        epilog="환경변수: AIBOM_GENERATOR_DIR (owasp 클론 경로, 필수) · SYFT_BIN, CDXGEN_BIN (PATH 에 없을 때만)",
    )
    s.add_argument("target", help="디렉터리 경로 또는 이미지 참조")
    s.add_argument("--cdx", metavar="PATH", help="CycloneDX 1.7 JSON 출력 경로")
    s.add_argument("--spdx", metavar="PATH", help="SPDX 3.0.1 JSON-LD 출력 경로")
    s.add_argument("--spdx-strict", action="store_true",
                   help="SPDX 출력에서 v0.6 전용 aibom_* 속성을 확장 항목으로 내려 공식 3.0.1 스키마에 맞춘다")
    s.add_argument("--no-syft", action="store_true", help="소프트웨어 스캔 생략")
    s.add_argument("--no-cdxgen", action="store_true", help="모델·데이터셋 스캔 생략")
    s.add_argument("--no-enrich", action="store_true", help="aibom-generator 보강 생략")
    s.add_argument("--no-validate", action="store_true", help="aibom-v0.6 스키마 검증 생략 (CycloneDX·SPDX 모두)")
    s.add_argument("--install-deps", action="store_true", help="cdxgen 이 락파일 없는 프로젝트에서 설치 명령을 돌리도록 허용")
    s.add_argument("--strict", action="store_true", help="도구 실패·검증 실패를 종료 코드로 반영")
    s.add_argument("--keep-intermediate", metavar="DIR", help="도구별 원본 출력을 이 디렉터리에 남긴다")
    s.set_defaults(func=cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "spdx_strict", False) and not args.spdx:
        parser.error("--spdx-strict 는 --spdx 와 함께 써야 한다")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
