"""테스트가 같이 쓰는 준비. 로그는 sure_aibom/utils/log.py 한 곳에서 찍으므로, 여기서 그 출구를 바꿔 끼워 받아 본다."""
import pytest

from sure_aibom.utils import log


@pytest.fixture(autouse=True)
def quiet_start():
    """앞 테스트가 -v 로 돌렸어도 다음 테스트는 조용히 시작한다."""
    log.set_verbose(False)
    yield
    log.set_verbose(False)


@pytest.fixture
def logs(monkeypatch):
    """이 테스트가 찍는 로그 줄을 순서대로 모은 목록. -v 일 때만 찍히는 상세 줄도 모은다."""
    lines: list[str] = []
    monkeypatch.setattr(log, "_write", lines.append)
    log.set_verbose(True)
    return lines
