"""OWASP aibom-generator — 모델 보강자.

디렉터리를 못 받고 HF 모델 ID 만 받는다. cdxgen 결과의 pkg:huggingface/… purl 에서 ID 를 뽑아
하나씩 호출한다. 콘솔 스크립트 이름 `aibom` 이 cdxgen 의 `aibom` 과 겹치므로 모듈 경로로 부른다.

    AIBOM_GENERATOR_DIR=/path/to/aibom-generator
    python -m src.cli <owner/model> -o <out>
"""
import os
import sys
from pathlib import Path

from ..exceptions import RunnerError
from . import hub
from ._proc import load_json_file, run


def skip_reason() -> str | None:
    """aibom-generator 를 건너뛰어야 하면 그 이유를, 돌려도 되면 None 을 돌려준다. 클론을 먼저 보고 네트워크는 마지막에 본다.
    이유는 CLI 요약에 그대로 나가므로 영어다."""
    repo = os.environ.get("AIBOM_GENERATOR_DIR")
    if not repo:
        return "AIBOM_GENERATOR_DIR not set"
    if not Path(repo).is_dir():
        return f"AIBOM_GENERATOR_DIR not found: {repo}"
    if not (Path(repo) / "src" / "cli.py").is_file():
        return f"AIBOM_GENERATOR_DIR is not an aibom-generator clone (no src/cli.py): {repo}"
    if not hub.hf_reachable():
        return "huggingface.co unreachable"
    return None


def run_aibom_generator(hf_id: str, workdir: Path) -> dict:
    repo = os.environ.get("AIBOM_GENERATOR_DIR")
    if not repo:
        raise RunnerError("AIBOM_GENERATOR_DIR not set")
    python = sys.executable
    safe = hf_id.replace("/", "__")
    out = workdir / f"owasp.{safe}.cdx.json"
    cmd = [python, "-m", "src.cli", hf_id, "-o", str(out)]
    proc = run(cmd, cwd=repo)
    if proc.returncode != 0:
        raise RunnerError(f"aibom-generator exited with {proc.returncode} for {hf_id}\n{proc.stderr[-2000:]}")
    return load_json_file(out, "aibom-generator")
