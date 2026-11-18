"""라이선스 값 → CycloneDX licenses[] 항목. SPDX id 면 license.id (스키마의 표기로), 아니면 license.name.

    license_entry   라이선스 값 하나 → 항목 하나. engine/merge.py(이미지 라벨), external/cdxgen.py(Modelfile) 가 쓴다
    card_licenses   Hugging Face 카드의 license → 항목 목록. engine/model.py, engine/dataset.py 가 쓴다

Hugging Face 카드는 목록에 없는 라이선스를 `license: other` 와 license_name · license_link 로 적는다 (card_licenses).
"""
from __future__ import annotations

import json
from importlib.resources import files


def _load_spdx_ids() -> dict[str, str]:
    """소문자 id → 스키마의 표기 (apache-2.0 → Apache-2.0). 패키지 안 schemas/spdx.schema.json 의 enum 이다."""
    with (files("sure_aibom") / "schemas" / "spdx.schema.json").open(encoding="utf-8") as fh:
        return {i.lower(): i for i in json.load(fh).get("enum") or []}


SPDX_IDS = _load_spdx_ids()          # 모듈을 읽을 때 한 번 만들고 바꾸지 않는 상수


def license_entry(value: str, url: str | None = None) -> dict:
    canonical = SPDX_IDS.get(value.strip().lower())
    entry: dict = {"id": canonical} if canonical else {"name": value.strip()}
    if url:
        entry["url"] = url
    return {"license": entry}


def card_licenses(card: dict) -> list[dict]:
    """모델·데이터셋 카드 머리말의 license (문자열이나 목록). `other` 는 license_name 이 있으면 그 이름으로, license_link 는 url 로."""
    values = card.get("license")
    values = values if isinstance(values, list) else [values]
    name, link = card.get("license_name"), card.get("license_link")
    out = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        if value.strip().lower() == "other":
            out.append(license_entry(name if isinstance(name, str) and name.strip() else value,
                                     link if isinstance(link, str) and link.startswith(("http://", "https://")) else None))
        else:
            out.append(license_entry(value))
    return out
