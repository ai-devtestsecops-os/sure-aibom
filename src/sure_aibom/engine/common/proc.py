"""다른 프로그램을 돌리고 그 출력 파일을 읽는 공용 함수. syft.py, cdxgen.py, container_tools.py, owasp_aibom_generator.py 가 쓴다.

    run              프로그램을 돌려 종료 코드와 출력을 돌려준다. 프로그램이 없거나 시간을 넘기면 RunnerError
    load_json_file   프로그램이 쓴 출력 JSON 을 읽는다. 파일이 없거나 비었으면 RunnerError

종료 코드가 0 이 아닌 것은 여기서 막지 않는다. 부른 쪽이 도구에 맞는 문구로 RunnerError 를 던진다.
"""
import json
import os
import subprocess
from pathlib import Path

from ...utils.exceptions import RunnerError


def run(cmd: list[str], cwd: str | None = None, timeout: int = 1800, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """env 는 지금 환경에 더하거나 덮어쓸 변수다."""
    if cwd is not None and not Path(cwd).is_dir():
        raise RunnerError(f"working directory not found: {cwd}")
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                              env={**os.environ, **env} if env else None)
    except FileNotFoundError as e:
        raise RunnerError(f"{cmd[0]} not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise RunnerError(f"{cmd[0]} timed out after {timeout}s") from e


def load_json_file(path: Path, tool: str) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise RunnerError(f"{tool} produced no output file")
    with path.open(encoding="utf-8") as f:
        return json.load(f)
