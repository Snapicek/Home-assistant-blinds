"""Pure resolver logic for the Chained Blinds integration.

No Home Assistant imports here on purpose: everything the coordinator needs
to decide "what state should the covers be in right now" is expressed as
plain functions over primitives/datetimes so it can be unit tested in
isolation and reasoned about without a running `hass` instance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time

from .const import RANK, SemanticState
from .helpers import elapsed_minutes


@dataclass(frozen=True)
class Thresholds:
    """Live-tunable lux thresholds, in lux."""

    lux_medium: float
    lux_high: float
    lux_medium_reopen: float
    lux_high_reopen: float


def _tier(lux: float, high: float, medium: float) -> SemanticState:
    """Map a lux reading to a tier using the given HIGH/MEDIUM pair."""
    if lux >= high:
        return SemanticState.SHADE
    if lux >= medium:
        return SemanticState.MEDIUM
    return SemanticState.OPEN



def is_night(now: datetime, open_time: dt_time, sunset_with_offset: datetime) -> bool:
    """True before `open_time` or at/after `sunset_with_offset` (today)."""
    return now.time() < open_time or now >= sunset_with_offset


def resolve_desired_state(
    *,
    now: datetime,
    lux: float,
    sun_at_window: bool | None,
    current: SemanticState,
    open_time: dt_time,
    sunset_with_offset: datetime,
    override_active: bool,
    thresholds: Thresholds,
) -> SemanticState:
    """Resolve the desired semantic state per the documented priority order.

    1. override active -> hold current
    2. night (before open_time or after sunset+offset) -> closed
    3/4/5. lux tier via primary thresholds

    Darkening (rank increases) is applied immediately. Lightening (rank
    decreases) is only applied if the *_reopen thresholds also call for it
    -- this hysteresis is what prevents down->up->down chain-load cycling.
    """
    if override_active:
        return current

    if is_night(now, open_time, sunset_with_offset):
        return SemanticState.CLOSED

    raw = _tier(lux, thresholds.lux_high, thresholds.lux_medium)

    if RANK[raw] >= RANK[current]:
        return raw

    raw_lighten = _tier(lux, thresholds.lux_high_reopen, thresholds.lux_medium_reopen)

    if RANK[raw_lighten] < RANK[current]:
        return raw_lighten
    return current


def should_apply_move(
    *,
    desired: SemanticState,
    current: SemanticState,
    last_move_time: datetime | None,
    now: datetime,
    dwell_minutes: float,
    reopen_dwell_minutes: float,
) -> bool:
    """Dwell lock: require a cooldown since the last real move before moving
    again, using the longer `reopen_dwell_minutes` for lightening moves."""
    if desired == current:
        return False
    if last_move_time is None:
        return True

    lightening = RANK[desired] < RANK[current]
    required_minutes = reopen_dwell_minutes if lightening else dwell_minutes
    return elapsed_minutes(last_move_time, now) >= required_minutes
