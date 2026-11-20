"""container_tools — docker, podman, crane 으로 이미지 이름을 .tar 로 받기. 도구는 가짜로 바꿔 끼워 확인한다."""
import subprocess
from pathlib import Path

import pytest

import sure_aibom.engine.container_tools as ct
from sure_aibom.exceptions import RunnerError


@pytest.fixture
def fake_tools(monkeypatch):
    """PATH 에 있는 도구(present)와 실패시킬 명령(fail, "docker image save" 꼴)을 정한다. 성공한 save 와 crane pull 은 tar 를 만든다."""
    state = {"present": set(), "fail": set(), "calls": []}
    monkeypatch.setattr(ct.shutil, "which", lambda name: f"/usr/bin/{name}" if name in state["present"] else None)

    def run(cmd, cwd=None, timeout=None):
        state["calls"].append(cmd)
        key = " ".join(cmd[:3] if cmd[1] == "image" else cmd[:2])
        if key in state["fail"]:
            state["fail"].discard(key + " once")
            return subprocess.CompletedProcess(cmd, 1, "", f"Error: {key} failed\n")
        if cmd[0] == "crane":
            Path(cmd[-1]).write_bytes(b"tar")
        elif cmd[1] == "image":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"tar")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(ct, "run", run)
    monkeypatch.setattr(ct, "host_arch", lambda: "amd64")
    return state


def test_pull_saves_from_the_daemon_first(tmp_path, fake_tools):
    fake_tools["present"] = {"docker", "crane"}
    tar, tool = ct.pull_image("alpine:3.20", tmp_path)
    assert (tar, tool) == (tmp_path / "image.tar", "docker")
    assert fake_tools["calls"] == [["docker", "image", "save", "-o", str(tar), "alpine:3.20"]]


def test_pull_fetches_when_the_daemon_does_not_have_the_image(tmp_path, fake_tools, monkeypatch):
    fake_tools["present"] = {"docker"}
    real = ct.run
    seen = {"save": 0}

    def run(cmd, cwd=None, timeout=None):                       # 첫 save 는 없다고 하고, pull 뒤의 save 는 된다
        if cmd[:3] == ["docker", "image", "save"]:
            seen["save"] += 1
            if seen["save"] == 1:
                fake_tools["calls"].append(cmd)
                return subprocess.CompletedProcess(cmd, 1, "", "Error: reference does not exist\n")
        return real(cmd, cwd, timeout)
    monkeypatch.setattr(ct, "run", run)
    tar, tool = ct.pull_image("alpine:3.20", tmp_path)
    assert tool == "docker" and [c[:2] for c in fake_tools["calls"]] == [["docker", "image"], ["docker", "pull"], ["docker", "image"]]


def test_pull_moves_on_to_the_next_tool_and_reports_every_failure(tmp_path, fake_tools):
    fake_tools["present"] = {"docker", "podman", "crane"}
    fake_tools["fail"] = {"docker image save", "docker pull", "podman image save", "podman pull"}     # 데몬이 둘 다 죽어 있다
    tar, tool = ct.pull_image("alpine:3.20", tmp_path)
    assert tool == "crane" and fake_tools["calls"][-1] == ["crane", "pull", "--platform", "linux/amd64", "alpine:3.20", str(tar)]

    fake_tools["fail"].add("crane pull")
    with pytest.raises(RunnerError) as e:
        ct.pull_image("alpine:3.20", tmp_path)
    lines = str(e.value).splitlines()
    assert lines[0] == "could not fetch alpine:3.20" and [line.split(":")[0] for line in lines[1:]] == ["docker", "podman", "crane"]
    assert lines[1] == "docker: docker pull exited with 1: Error: docker pull failed"


def test_pull_without_any_tool_says_which_are_needed(tmp_path, fake_tools):
    with pytest.raises(RunnerError, match=r"docker, podman or crane is needed to fetch alpine:3.20 \(or pass the image as a .tar\)"):
        ct.pull_image("alpine:3.20", tmp_path)
