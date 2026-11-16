"""sure-aibom 진입점. 인자를 등록하고 명령에 맞는 controller 함수로 넘긴다. 사용법은 README 또는 `sure-aibom --help`.

참고 구조로 보면 이 파일이 app.py 다. 명령 처리는 controller/ 에, 단계 순서는 service/ 에 명령마다 파일 하나씩 있다."""
from __future__ import annotations

import argparse
import sys

from . import NAME, __version__
from .controller.scan import cmd_scan
from .controller.validate import cmd_validate
from .formats import FORMATS, SPECS


# ── parser ──────────────────────────────────────────────────────────────────
# 도움말은 한 장이다. sure-aibom --help, scan --help, validate --help, 인자 없이 실행이 모두 이것을 찍고,
# README 의 사용 절도 이 글자 그대로다 (tests/test_cli.py 가 둘이 같은지 본다).

BANNER = r"""
   _____ __  ______  ______   ___    ________  ____  __  ___
  / ___// / / / __ \/ ____/  /   |  /  _/ __ )/ __ \/  |/  /
  \__ \/ / / / /_/ / __/    / /| |  / // __  / / / / /|_/ /
 ___/ / /_/ / _, _/ /___   / ___ |_/ // /_/ / /_/ / /  / /
/____/\____/_/ |_/_____/  /_/  |_/___/_____/\____/_/  /_/
"""[1:]

HELP = BANNER + f"""
{NAME} {__version__}
AI 규제·표준 요구사항을 반영한 AI-BOM 자동 생성 프로그램
(Compliance-Aware AI-BOM Generation Tool)

Usage:
  sure-aibom scan <target> [options]
  sure-aibom validate <bom> [--spec <1.7|v0.6|3.0.1>]

Commands:
  scan <target>               디렉터리 또는 컨테이너 이미지를 스캔해 AI-BOM 을 만든다
  validate <bom>              BOM 을 --spec 이 고른 스키마로 검증한다 (형식은 문서에서 알아낸다)

Options:
  -o, --output <path>         [scan] 출력 경로 (default: 표준출력)
  --data <path|hf://...>      [scan] 데이터셋. 로컬 경로 또는 hf://datasets/<id>[@<revision>]. 여러 번 줄 수 있음 (optional)
  --format <cyclonedx|spdx>   [scan] 출력 형식 (default: cyclonedx)
  --spec <1.7|v0.6|3.0.1>     [scan] 출력 스펙 (default: cyclonedx 는 1.7, spdx 는 3.0.1)
                                1.7    CycloneDX 1.7 의 properties 로 넣음
                                3.0.1  SPDX 3.0.1 의 CdxPropertiesExtension 으로 넣음
                                v0.6   AI-BOM v0.6 의 필드로 넣음 (cyclonedx, spdx 모두)
                              [validate] 검증할 스키마 (default: CycloneDX 문서는 1.7, SPDX 문서는 3.0.1)
  -v, --verbose               [scan] 항목별 상세 로그
  --version                   버전을 보여 준다
  -h, --help                  도움말을 보여 준다

Examples:
  sure-aibom scan ./project -o bom.cdx.json                               디렉터리를 스캔하여 규제 필드를 CycloneDX 1.7 properties 로 넣음
  sure-aibom scan ./project -o bom.cdx.json --spec v0.6                   디렉터리를 스캔하여 규제 필드를 AI-BOM v0.6 (CycloneDX) 필드로 넣음
  sure-aibom scan ./project -o bom.spdx.json --format spdx                SPDX 3.0.1 로 냄
  sure-aibom scan ./project -o bom.spdx.json --format spdx --spec v0.6    AI-BOM v0.6 (SPDX) 로 냄
  sure-aibom scan ./project -o bom.cdx.json --data ./dataset              로컬 데이터 경로를 함께 지정
  sure-aibom scan ./project -o bom.cdx.json --data hf://datasets/stanfordnlp/imdb
                                                                          HuggingFace 데이터셋을 함께 지정 (@<revision> 으로 고정, 없으면 최신 커밋)

  sure-aibom scan alpine:3.20 -o alpine.cdx.json                          컨테이너 이미지를 스캔
  sure-aibom scan image.tar -o image.cdx.json                             이미지 .tar 를 스캔

  sure-aibom validate bom.cdx.json                                        CycloneDX 1.7 스키마로 검증
  sure-aibom validate bom.cdx.json --spec v0.6                            AI-BOM v0.6 (CycloneDX) 스키마로 검증
  sure-aibom validate bom.spdx.json                                       SPDX 3.0.1 스키마로 검증
  sure-aibom validate bom.spdx.json --spec v0.6                           AI-BOM v0.6 (SPDX) 스키마로 검증

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
    p = argparse.ArgumentParser(prog="sure-aibom", usage="sure-aibom <command> [options]", add_help=False, allow_abbrev=False)
    p.add_argument("-h", "--help", action=_Help)
    p.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("scan", prog="sure-aibom scan", usage="sure-aibom scan <target> [options]", add_help=False, allow_abbrev=False)
    s.add_argument("-h", "--help", action=_Help)
    s.add_argument("target", metavar="<target>")
    s.add_argument("-o", "--output", metavar="<path>")
    s.add_argument("--data", action="append", default=[], metavar="<path|hf://...>")
    s.add_argument("--format", choices=FORMATS, default="cyclonedx", metavar="<cyclonedx|spdx>")
    s.add_argument("--spec", choices=SPECS, default=None, metavar="<1.7|v0.6|3.0.1>")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("validate", prog="sure-aibom validate", usage="sure-aibom validate <bom> [--spec <1.7|v0.6|3.0.1>]",
                       add_help=False, allow_abbrev=False)
    v.add_argument("-h", "--help", action=_Help)
    v.add_argument("bom", metavar="<bom>")
    v.add_argument("--spec", choices=SPECS, default=None, metavar="<1.7|v0.6|3.0.1>")
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
