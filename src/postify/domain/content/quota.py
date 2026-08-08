from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuotaState:
    fresh_credit: int = 0
    reserve_credit: int = 0


@dataclass(frozen=True, slots=True)
class Allocation:
    tiers: tuple[str, ...]
    state: QuotaState


def allocate_weighted_slots(
    *,
    state: QuotaState,
    slots: int,
    fresh_available: int,
    reserve_available: int,
    fresh_share: int,
    reserve_share: int,
) -> Allocation:
    tiers = []
    for _ in range(slots):
        tier, state = choose_tier(
            state,
            fresh_available=fresh_available > 0,
            reserve_available=reserve_available > 0,
            fresh_share=fresh_share,
            reserve_share=reserve_share,
        )
        if tier is None:
            break
        tiers.append(tier)
        if tier == "fresh":
            fresh_available -= 1
        else:
            reserve_available -= 1
    return Allocation(tuple(tiers), state)


def choose_tier(
    state: QuotaState,
    *,
    fresh_available: bool,
    reserve_available: bool,
    fresh_share: int,
    reserve_share: int,
) -> tuple[str | None, QuotaState]:
    fresh, reserve = (
        state.fresh_credit + fresh_share,
        state.reserve_credit + reserve_share,
    )
    if fresh_available and (not reserve_available or fresh >= reserve):
        return "fresh", QuotaState(fresh - 100, reserve)
    if reserve_available:
        return "reserve", QuotaState(fresh, reserve - 100)
    return None, QuotaState(fresh, reserve)


def consume_tier_credit(
    state: QuotaState, *, tier: str, fresh_share: int, reserve_share: int
) -> QuotaState:
    """Начисляет доли и списывает credit для уже выбранного tier."""
    fresh = state.fresh_credit + fresh_share
    reserve = state.reserve_credit + reserve_share
    if tier == "fresh":
        return QuotaState(fresh - 100, reserve)
    return QuotaState(fresh, reserve - 100)
