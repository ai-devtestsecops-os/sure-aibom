"""syft — 소프트웨어 생산자.

모델 카탈로거(ai 태그: gguf, safetensors)는 끈다. 모델은 cdxgen 이 맡는다.
    syft <target> --select-catalogers -ai -o cyclonedx-json@1.7=<out>
"""
from pathlib import Path

from ._proc import RunnerError, load_json_file, run

SPEC_VERSION = "1.7"


def run_syft(target: str, workdir: Path) -> dict:
    out = workdir / "syft.cdx.json"
    cmd = [
        "syft",
        target,
        "--select-catalogers", "-ai",
        "-o", f"cyclonedx-json@{SPEC_VERSION}={out}",
        "-q",
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RunnerError(f"syft exited with {proc.returncode}\n{proc.stderr[-2000:]}")
    return _relativize_file_components(load_json_file(out, "syft"), target)


def _relativize_file_components(doc: dict, target: str) -> dict:
    """syft 는 패키지가 발견된 파일을 `type: file` 컴포넌트(해시 포함)로 내는데, 이름이 스캔 시
    넘긴 절대경로다. 패키지 쪽 `syft:location:N:path` 는 스캔 루트 기준(`/requirements.txt`)이라
    둘을 맞추고 스캔 머신의 경로가 BOM 에 새지 않게 한다. 디렉터리 스캔에만 해당한다."""
    root = str(Path(target).resolve())
    if not Path(root).is_dir():
        return doc
    for comp in doc.get("components") or []:
        name = comp.get("name") or ""
        if comp.get("type") == "file" and name.startswith(root):
            comp["name"] = "/" + name[len(root):].lstrip("/")
    return doc
