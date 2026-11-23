"""facts — CycloneDX 문서에 자리가 없어 메모리로만 들고 가는 값 (데이터셋 역할, 생성·공개 시각). SPDX 변환기만 읽는다."""
import pytest

from sure_aibom.utils.facts import Facts, _normalize_time


@pytest.mark.parametrize("value, expected", [
    ("2024-02-19T11:06:12.000Z", "2024-02-19T11:06:12Z"),                  # 허브 lastModified
    ("2025-09-30T12:34:56.123456789Z", "2025-09-30T12:34:56Z"),            # OCI created (나노초)
    ("2026-10-01T09:00:00+09:00", "2026-10-01T00:00:00Z"),                 # 시간대는 UTC 로
    ("2026-10-01 00:00:00", "2026-10-01T00:00:00Z"),                       # 시간대 표시가 없으면 UTC 로 본다
    ("2026-10-01", None),                                                  # 날짜만 있으면 시각을 지어내지 않는다
    ("yesterday", None), ("", None), (None, None), (1700000000, None),
])
def test_normalize_time_gives_spdx_date_time_stamps_or_nothing(value, expected):
    assert _normalize_time(value) == expected


def test_roles_and_times_are_checked_and_unreadable_times_are_ignored():
    facts = Facts()
    facts.add_role("m", "d", "training")
    facts.add_role("m", "d", "evaluation")
    facts.set_time("d", "releaseTime", "2024-01-04T12:09:45.000Z")
    facts.set_time("m", "builtTime", "2024-01-04")                         # 못 읽는 값은 아무것도 안 적는다
    assert facts.roles == {("m", "d"): {"training", "evaluation"}} and facts.times == {"d": {"releaseTime": "2024-01-04T12:09:45Z"}}
    with pytest.raises(ValueError):
        facts.add_role("m", "d", "validation")
    with pytest.raises(ValueError):
        facts.set_time("m", "validUntilTime", "2030-01-01T00:00:00Z")


def test_repoint_follows_a_changed_bom_ref_and_merges_into_the_survivor():
    facts = Facts()
    facts.add_role("m", "old", "training")
    facts.add_role("m", "new", "evaluation")
    facts.add_role("old-model", "x", "training")
    facts.set_time("old", "releaseTime", "2024-01-01T00:00:00Z")
    facts.set_time("new", "builtTime", "2023-01-01T00:00:00Z")
    facts.set_time("new", "releaseTime", "2025-01-01T00:00:00Z")           # 남는 쪽의 값이 이긴다
    facts.repoint("old", "new")
    facts.repoint("old-model", "m2")
    facts.repoint("same", "same")
    assert facts.roles == {("m", "new"): {"training", "evaluation"}, ("m2", "x"): {"training"}}
    assert facts.times == {"new": {"builtTime": "2023-01-01T00:00:00Z", "releaseTime": "2025-01-01T00:00:00Z"}}


def test_repoint_all_moves_many_refs_at_once_and_keeps_the_order():
    """병합이 bom-ref 를 다시 매길 때 쓴다. 옛 이름과 새 이름이 엇갈려도 한 번에 옮기고, 기록의 순서는 그대로다."""
    facts = Facts()
    facts.add_role("a", "d1", "training")
    facts.add_role("b", "d2", "evaluation")
    facts.add_role("c", "d1", "training")
    facts.set_time("a", "releaseTime", "2024-01-01T00:00:00Z")
    facts.set_time("b", "releaseTime", "2025-01-01T00:00:00Z")
    facts.set_time("b", "builtTime", "2023-01-01T00:00:00Z")
    facts.repoint_all({"a": "b", "b": "c", "d1": "d1"})                    # a → b, b → c. 하나씩 차례로 옮기면 a 의 기록까지 c 로 간다
    assert list(facts.roles.items()) == [(("b", "d1"), {"training"}), (("c", "d2"), {"evaluation"}), (("c", "d1"), {"training"})]
    assert facts.times == {"b": {"releaseTime": "2024-01-01T00:00:00Z"}, "c": {"releaseTime": "2025-01-01T00:00:00Z", "builtTime": "2023-01-01T00:00:00Z"}}
    facts.repoint_all({"b": "c"})                                          # 같은 bom-ref 로 모이면 역할은 합치고 시각은 먼저 적힌 값이 남는다
    assert list(facts.roles.items()) == [(("c", "d1"), {"training"}), (("c", "d2"), {"evaluation"})]
    assert facts.times == {"c": {"releaseTime": "2024-01-01T00:00:00Z", "builtTime": "2023-01-01T00:00:00Z"}}
