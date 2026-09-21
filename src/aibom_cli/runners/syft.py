"""syft — 소프트웨어 생산자.

모델 카탈로거(ai 태그: gguf, safetensors)는 끈다. 모델은 cdxgen 이 맡는다.
    syft <target> --select-catalogers -ai -o cyclonedx-json@1.7=<out>
"""
from pathlib import Path

from ._proc import RunnerError, load_json_file, run, which_or_env

SPEC_VERSION = "1.7"


def run_syft(target: str, workdir: Path) -> dict:
    binary = which_or_env("SYFT_BIN", "syft")
    out = workdir / "syft.cdx.json"
    cmd = [
        binary,
        target,
        "--select-catalogers", "-ai",
        "-o", f"cyclonedx-json@{SPEC_VERSION}={out}",
        "-q",
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RunnerError(f"syft 실패 (exit {proc.returncode})\n{proc.stderr[-2000:]}")
    return load_json_file(out, "syft")
