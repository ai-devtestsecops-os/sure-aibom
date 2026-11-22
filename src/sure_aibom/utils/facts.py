"""CycloneDX 문서에 자리가 없어 메모리로만 들고 가는 값. 파일로 쓰지 않고 BOM 에도 넣지 않는다. service 가 스캔마다 하나를 만들어 단계
함수에 넘기면, 수집 단계(engine 의 merge.py, model.py, dataset.py)가 채우고 SPDX 변환기(engine/spdx.py)만 읽는다. CycloneDX 출력은
이 값이 있어도 바뀌지 않는다.

    roles   (모델 bom-ref, 데이터셋 bom-ref) → {"training", "evaluation"}
            모델 카드의 datasets(학습), model-index 결과의 dataset(평가), GGUF 헤더의 general.datasets(학습).
            SPDX 에서 trainedOn·testedOn 관계가 된다. CycloneDX 는 dependsOn 뿐이라 구분을 적을 자리가 없다.
    times   bom-ref → {"builtTime" | "releaseTime": "YYYY-MM-DDTHH:MM:SSZ"}
            이미지의 org.opencontainers.image.created 라벨(builtTime), 허브 모델·데이터셋 응답의 lastModified(releaseTime).
            CycloneDX 에는 컴포넌트 단위 시각 필드가 없다.

bom-ref 가 바뀌면(데이터셋의 정식 id 이름 바꾸기, 같은 데이터셋 합치기) repoint 로 따라간다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

ROLES = ("training", "evaluation")
TIME_KEYS = ("builtTime", "releaseTime")
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


@dataclass
class Facts:
    roles: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    times: dict[str, dict[str, str]] = field(default_factory=dict)

    def add_role(self, model_ref: str, dataset_ref: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"role 은 {ROLES} 중 하나여야 한다: {role!r}")
        self.roles.setdefault((model_ref, dataset_ref), set()).add(role)

    def set_time(self, ref: str, key: str, value) -> None:
        """value 가 읽을 수 있는 날짜·시각이면 적고, 아니면 아무것도 하지 않는다. 이미 있는 값은 두지 않고 덮는다."""
        if key not in TIME_KEYS:
            raise ValueError(f"key 는 {TIME_KEYS} 중 하나여야 한다: {key!r}")
        stamp = _normalize_time(value)
        if stamp:
            self.times.setdefault(ref, {})[key] = stamp

    def repoint(self, old: str, new: str) -> None:
        """bom-ref old 를 new 로. 합쳐지는 쪽의 역할은 남는 쪽에 더하고, 시각은 남는 쪽에 없는 키만 가져온다."""
        if old == new:
            return
        for (model, dataset), roles in list(self.roles.items()):
            if old in (model, dataset):
                del self.roles[(model, dataset)]
                key = (new if model == old else model, new if dataset == old else dataset)
                self.roles.setdefault(key, set()).update(roles)
        moved = self.times.pop(old, None)
        if moved:
            target = self.times.setdefault(new, {})
            for k, v in moved.items():
                target.setdefault(k, v)


def _normalize_time(value) -> str | None:
    """ISO 8601 날짜·시각 문자열 → SPDX DateTimeStamp("YYYY-MM-DDTHH:MM:SSZ", UTC). 날짜만 있거나 못 읽으면 None.
    소수점 초는 버리고, 시간대 표시가 없으면 UTC 로 본다."""
    if not isinstance(value, str) or not _DATE_TIME.match(value.strip()):
        return None
    try:
        stamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
