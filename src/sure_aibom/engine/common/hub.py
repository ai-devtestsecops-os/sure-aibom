"""Hugging Face 허브로 나가는 호출을 모은다 (Hub API, datasets-server).

    hf_reachable              huggingface.co(또는 HF_ENDPOINT 의 호스트) 443 포트에 TCP 로 닿는지
    fetch_model_info          GET {HF_ENDPOINT}/api/models/<id>
    fetch_dataset_info        GET {HF_ENDPOINT}/api/datasets/<id>, 리비전을 주면 /revision/<리비전>
    fetch_revision_error      그 리비전 조회가 HTTP 오류로 끝나면 (상태 번호, 허브의 오류 문구)
    fetch_dataset_size        GET datasets-server /size
    fetch_dataset_statistics  GET datasets-server /statistics

주소는 HF_ENDPOINT, HF_DATASETS_SERVER 로 바꿀 수 있고, HF_TOKEN 이 있으면 Authorization 헤더로 보낸다.
부르는 쪽(model.py, dataset.py, aibom_generator.py)은 `hub.fetch_dataset_info(...)` 처럼 모듈을 거쳐 부른다. 그래서 테스트는 이 모듈의
함수만 바꿔 끼우면 된다.
"""
from __future__ import annotations

import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ...utils.log import detail

HUB = "https://huggingface.co"
DATASETS_SERVER = "https://datasets-server.huggingface.co"
FETCH_TIMEOUT = 15.0


def hf_reachable(timeout: float = 3.0) -> bool:
    """huggingface.co(또는 HF_ENDPOINT 의 호스트) 443 포트에 TCP 로 닿는지만 본다."""
    host = urlparse(os.environ.get("HF_ENDPOINT") or HUB).hostname or "huggingface.co"
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


def _hf_endpoint() -> str:
    return (os.environ.get("HF_ENDPOINT") or HUB).rstrip("/")


def _datasets_server() -> str:
    return (os.environ.get("HF_DATASETS_SERVER") or DATASETS_SERVER).rstrip("/")


def _hub_request(url: str) -> Request:
    req = Request(url, headers={"User-Agent": "sure-aibom", "Accept": "application/json"})
    if os.environ.get("HF_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['HF_TOKEN']}")
    return req


def _get_json(url: str, hf_id: str, what: str) -> dict | None:
    try:
        with urlopen(_hub_request(url), timeout=FETCH_TIMEOUT) as resp:
            info = json.load(resp)
    except HTTPError as e:
        detail(f"[dataset] {hf_id}: {what} returned {e.code}")
        return None
    except (URLError, OSError, ValueError) as e:
        detail(f"[dataset] {hf_id}: {what} request failed ({e.__class__.__name__})")
        return None
    return info if isinstance(info, dict) else None


def fetch_dataset_info(hf_id: str, revision: str | None = None) -> dict | None:
    """GET {HF_ENDPOINT}/api/datasets/<id>, 리비전을 주면 /api/datasets/<id>/revision/<리비전> (응답의 sha 는 그 리비전의 전체 커밋 해시).
    실패하면 None 을 돌려주고 알린다. 테스트는 이 함수를 바꿔 끼운다."""
    url = f"{_hf_endpoint()}/api/datasets/{quote(hf_id, safe='/')}"
    if revision:
        return _get_json(f"{url}/revision/{quote(revision, safe='')}", hf_id, f"Hub API at revision {revision}")
    return _get_json(url, hf_id, "Hub API")


def fetch_revision_error(hf_id: str, revision: str) -> tuple[int, str] | None:
    """GET {HF_ENDPOINT}/api/datasets/<id>/revision/<리비전> 이 HTTP 오류로 끝나면 (상태 번호, 허브의 오류 문구).
    성공했거나 허브에 닿지 않았으면 None. 테스트는 이 함수를 바꿔 끼운다."""
    url = f"{_hf_endpoint()}/api/datasets/{quote(hf_id, safe='/')}/revision/{quote(revision, safe='')}"
    try:
        with urlopen(_hub_request(url), timeout=FETCH_TIMEOUT):
            return None
    except HTTPError as e:
        try:
            message = json.loads(e.read() or b"{}").get("error")
        except (ValueError, AttributeError, OSError):
            message = None
        return e.code, message if isinstance(message, str) and message else f"HTTP {e.code}"
    except (URLError, OSError, ValueError):
        return None


def fetch_model_info(hf_id: str) -> dict | None:
    """GET {HF_ENDPOINT}/api/models/<id>. M-BOM 보강이 빈 필드를 채우고, D-BOM 이 모델 카드(cardData)의 데이터셋을 읽는 응답이다.
    실패하면 None. 테스트는 이 함수를 바꿔 끼운다."""
    return _get_json(f"{_hf_endpoint()}/api/models/{quote(hf_id, safe='/')}", hf_id, "Hub API (model)")


def fetch_dataset_size(hf_id: str) -> dict | None:
    """GET datasets-server /size?dataset=<id>. 바이트 크기와 config·split 목록."""
    return _get_json(f"{_datasets_server()}/size?dataset={quote(hf_id, safe='/')}", hf_id, "datasets-server /size")


def fetch_dataset_statistics(hf_id: str, config: str, split: str) -> dict | None:
    """GET datasets-server /statistics?dataset=<id>&config=&split=. 열마다 통계."""
    url = f"{_datasets_server()}/statistics?dataset={quote(hf_id, safe='/')}&config={quote(config, safe='')}&split={quote(split, safe='')}"
    return _get_json(url, hf_id, f"datasets-server /statistics {config}/{split}")
