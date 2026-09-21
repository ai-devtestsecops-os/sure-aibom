"""cdxgen — 모델·데이터셋 생산자.

-t ai 로 소프트웨어 분기를 끄고 AI 인벤토리만 훑는다.
    cdxgen <target> -t ai --include-formulation --spec-version 1.7 --no-install-deps -o <out>

CDXGEN_BIN 이 .js 파일이면 node 로 실행한다(클론한 저장소를 바로 쓰는 경우).
"""
import os
from pathlib import Path

from ._proc import RunnerError, load_json_file, run, which_or_env

SPEC_VERSION = "1.7"


def _command() -> list[str]:
    binary = which_or_env("CDXGEN_BIN", "cdxgen")
    if binary.endswith(".js"):
        return [os.environ.get("NODE_BIN", "node"), binary]
    return [binary]


def run_cdxgen(target: str, workdir: Path, install_deps: bool = False) -> dict:
    out = workdir / "cdxgen.cdx.json"
    cmd = _command() + [
        target,
        "-t", "ai",
        "--include-formulation",
        "--spec-version", SPEC_VERSION,
        "-o", str(out),
    ]
    if not install_deps:
        cmd.append("--no-install-deps")
    proc = run(cmd)
    if proc.returncode != 0:
        raise RunnerError(f"cdxgen 실패 (exit {proc.returncode})\n{proc.stderr[-2000:]}")
    return load_json_file(out, "cdxgen")
