"""aibom-cli — 서브커맨드 셋.

    scan     <target> [-o bom.json] [--form properties|typed]   디렉터리·이미지를 스캔해 CycloneDX 1.7 을 만든다 (생성만)
    validate <bom> --spec 1.7|v0.6                              CycloneDX 문서를 고른 스키마 하나로 검증한다

scan 은 syft(소프트웨어) + cdxgen(모델·데이터셋) 을 돌려 병합하고 aibom-generator 로 보강한 뒤,
regulation 이 모델 컴포넌트의 v0.6 규제 필드를 정규화한다 — --form properties(기본) 는 aibom:model:* 프로퍼티로
(공식 1.7 소비자용), --form typed 는 v0.6 스키마의 타입 있는 필드로.
보강은 huggingface.co 에 닿을 때만 한다 (AIBOM_OFFLINE=1 이면 강제 생략).
검증은 scan 안에서 하지 않고 파일을 받아 따로 한다. --spec 은 필수이고 다른 쪽으로 자동 전환하지 않는다.
SPDX 3.0.1 변환기(spdx/)는 재검증이 끝날 때까지 CLI 에 노출하지 않는다.
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
            docs.append(runner())
        except RunnerError as e:
            _log(f"[aibom-cli] {name}: {e}")

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

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aibom-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"aibom-cli {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "scan",
        help="디렉터리 또는 컨테이너 이미지를 스캔해 CycloneDX 1.7 AI-BOM 을 만든다",
        epilog="환경변수: AIBOM_GENERATOR_DIR (owasp 클론 경로) · AIBOM_OFFLINE=1 (보강 강제 생략) · SYFT_BIN, CDXGEN_BIN (PATH 에 없을 때만)",
    )
    s.add_argument("target", help="디렉터리 경로 또는 이미지 참조")
    s.add_argument("-o", "--output", metavar="PATH", help="CycloneDX 1.7 JSON 출력 경로 (없으면 표준출력)")
    s.add_argument("--form", choices=FORMS, default="properties",
                   help="규제 필드를 싣는 형태 — properties: aibom:model:* 프로퍼티 (기본, 공식 1.7 적합) · typed: v0.6 타입 있는 필드")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("validate", help="CycloneDX 문서를 --spec 이 고른 스키마 하나로 검증한다")
    v.add_argument("bom", help="검증할 CycloneDX JSON 파일")
    v.add_argument("--spec", choices=tuple(CDX_SCHEMA_BY_SPEC), required=True,
                   help="1.7: 공식 CycloneDX 1.7 (properties 형) · v0.6: aibom-v0.6 CycloneDX 스키마 (typed 형)")
    v.set_defaults(func=cmd_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
