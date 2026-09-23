"""cdxgen — 모델·데이터셋 생산자.

-t ai 로 소프트웨어 분기를 끄고 AI 인벤토리만 훑는다.
    cdxgen <target> -t ai --spec-version 1.7 --no-install-deps -o <out>

--include-formulation 은 쓰지 않는다. 모델·데이터셋 컴포넌트에는 영향이 없고, cdxgen 실행 환경
(git 트리 전체, CONDA_PREFIX 같은 환경변수)을 formulation[] 에 실어 스캔 머신 정보가 새기 때문이다.
"""
from pathlib import Path

from ._proc import RunnerError, load_json_file, run

SPEC_VERSION = "1.7"


def run_cdxgen(target: str, workdir: Path, install_deps: bool = False) -> dict:
    out = workdir / "cdxgen.cdx.json"
    cmd = [
        "cdxgen",
        target,
        "-t", "ai",
        "--spec-version", SPEC_VERSION,
        "-o", str(out),
    ]
    if not install_deps:
        cmd.append("--no-install-deps")
    proc = run(cmd)
    if proc.returncode != 0:
        raise RunnerError(f"cdxgen 실패 (exit {proc.returncode})\n{proc.stderr[-2000:]}")
    return load_json_file(out, "cdxgen")
