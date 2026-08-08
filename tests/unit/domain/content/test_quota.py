from __future__ import annotations


def _quota_api():
    from postify.domain.content.quota import QuotaState, allocate_weighted_slots

    return QuotaState, allocate_weighted_slots


def _allocate_days(*, fresh_available: int, reserve_available: int):
    QuotaState, allocate_weighted_slots = _quota_api()
    state = QuotaState(fresh_credit=0, reserve_credit=0)
    days: list[tuple[str, ...]] = []
    for _ in range(5):
        allocation = allocate_weighted_slots(
            state=state,
            slots=12,
            fresh_available=fresh_available,
            reserve_available=reserve_available,
            fresh_share=90,
            reserve_share=10,
        )
        days.append(tuple(allocation.tiers))
        state = allocation.state
        fresh_available -= allocation.tiers.count("fresh")
        reserve_available -= allocation.tiers.count("reserve")
    return days, state


def test_weighted_credits_allocate_exactly_54_fresh_and_6_reserve_over_60_slots() -> None:
    # Поломка (gate 2): округление 90/10 каждый день даёт 55/5.
    days, _ = _allocate_days(fresh_available=100, reserve_available=100)
    tiers = [tier for day in days for tier in day]

    assert tiers.count("fresh") == 54
    assert tiers.count("reserve") == 6


def test_weighted_credits_do_not_repeat_a_fixed_eleven_to_one_daily_split() -> None:
    # Поломка (gate 2): каждая партия хардкодом сведена к 11/1.
    days, _ = _allocate_days(fresh_available=100, reserve_available=100)
    daily_counts = [(day.count("fresh"), day.count("reserve")) for day in days]

    assert len(set(daily_counts)) > 1
    assert sum(fresh for fresh, _ in daily_counts) == 54
    assert sum(reserve for _, reserve in daily_counts) == 6


def test_empty_reserve_uses_fresh_without_forgiving_reserve_debt() -> None:
    # Поломка (gate 2): fallback обнуляет credit пустого reserve-класса.
    QuotaState, allocate_weighted_slots = _quota_api()
    first = allocate_weighted_slots(
        state=QuotaState(0, 0),
        slots=12,
        fresh_available=12,
        reserve_available=0,
        fresh_share=90,
        reserve_share=10,
    )
    second = allocate_weighted_slots(
        state=first.state,
        slots=12,
        fresh_available=12,
        reserve_available=12,
        fresh_share=90,
        reserve_share=10,
    )

    assert first.tiers == ("fresh",) * 12
    assert second.tiers.count("reserve") >= 2
    assert second.state.reserve_credit < first.state.reserve_credit + 120


def test_tie_prefers_fresh_and_never_allocates_unavailable_rows() -> None:
    # Поломка: tie-break нестабилен или scheduler выдаёт больше demand.
    QuotaState, allocate_weighted_slots = _quota_api()

    allocation = allocate_weighted_slots(
        state=QuotaState(0, 0),
        slots=4,
        fresh_available=1,
        reserve_available=1,
        fresh_share=50,
        reserve_share=50,
    )

    assert allocation.tiers == ("fresh", "reserve")
