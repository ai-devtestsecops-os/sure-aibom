"""서브프로세스 공통 처리."""
import json
import subprocess
import sys
from pathlib import Path


class RunnerError(RuntimeError):
    pass




def run(cmd: list[str], cwd: str | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    print(f"[aibom-cli] $ {' '.join(cmd)}", file=sys.stderr)
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise RunnerError(f"실행 파일을 찾을 수 없다: {cmd[0]} ({e})") from e


def load_json_file(path: Path, tool: str) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise RunnerError(f"{tool} 가 결과 파일을 만들지 않았다: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)
