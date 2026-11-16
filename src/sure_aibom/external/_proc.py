"""서브프로세스 공통 처리."""
import json
import os
import subprocess
from pathlib import Path

from ..exceptions import RunnerError


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
