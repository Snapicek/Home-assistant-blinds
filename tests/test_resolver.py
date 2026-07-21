"""Unit tests for the pure resolver logic.

These tests are the executable spec for the resolver: the original prompt
described the rules in prose but no reference blueprint YAML implementing
them was ever committed, so these cases pin down the exact combining
behaviour (hysteresis, dwell direction, sun-gating, night window) instead of
leaving it ambiguous.
"""
from datetime import datetime, time as dt_time

import pytest

from custom_components.chained_blinds.const import SemanticState
from custom_components.chained_blinds.resolver import (
    Thresholds,
    is_night,
    resolve_desired_state,
    should_apply_move,
)

OPEN = SemanticState.OPEN
MEDIUM = SemanticState.MEDIUM
SHADE = SemanticState.SHADE
CLOSED = SemanticState.CLOSED

OPEN_TIME = dt_time(7, 0)


def _thresholds(
    lux_medium=200.0, lux_high=1000.0, lux_medium_reopen=120.0, lux_high_reopen=700.0
) -> Thresholds:
    return Thresholds(
        lux_medium=lux_medium,
        lux_high=lux_high,
        lux_medium_reopen=lux_medium_reopen,
        lux_high_reopen=lux_high_reopen,
    )


def _resolve(*, now, lux, current, sun_at_window=None, override_active=False,
             sunset_with_offset=None, thresholds=None):
    return resolve_desired_state(
        now=now,
        lux=lux,
        sun_at_window=sun_at_window,
        current=current,
        open_time=OPEN_TIME,
        sunset_with_offset=sunset_with_offset or datetime(2026, 7, 21, 20, 0),
        override_active=override_active,
        thresholds=thresholds or _thresholds(),
    )


# --- is_night -----------------------------------------------------------

def test_is_night_before_open_time():
    now = datetime(2026, 7, 21, 6, 59)
    assert is_night(now, OPEN_TIME, datetime(2026, 7, 21, 20, 0)) is True


def test_is_night_after_sunset_with_offset():
    now = datetime(2026, 7, 21, 20, 0)
    assert is_night(now, OPEN_TIME, datetime(2026, 7, 21, 20, 0)) is True


def test_is_night_false_during_day():
    now = datetime(2026, 7, 21, 12, 0)
    assert is_night(now, OPEN_TIME, datetime(2026, 7, 21, 20, 0)) is False


# --- override always wins -------------------------------------------------

def test_override_holds_current_regardless_of_lux_or_time():
    now = datetime(2026, 7, 21, 3, 0)  # night, would otherwise force CLOSED
    assert _resolve(now=now, lux=5000, current=MEDIUM, override_active=True) == MEDIUM


# --- night forces closed --------------------------------------------------

def test_night_forces_closed_even_at_high_lux():
    now = datetime(2026, 7, 21, 21, 0)
    assert _resolve(now=now, lux=5000, current=OPEN) == CLOSED


def test_night_closed_is_a_noop_when_already_closed():
    now = datetime(2026, 7, 21, 3, 0)
    assert _resolve(now=now, lux=0, current=CLOSED) == CLOSED


# --- basic tier resolution, boundaries inclusive --------------------------

@pytest.mark.parametrize(
    "lux,expected",
    [
        (0, OPEN),
        (199.9, OPEN),
        (200.0, MEDIUM),  # boundary is inclusive
        (999.9, MEDIUM),
        (1000.0, SHADE),  # boundary is inclusive
        (5000, SHADE),
    ],
)
def test_tier_thresholds_darkening_from_open(lux, expected):
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=lux, current=OPEN) == expected


def test_darkening_applies_immediately_no_hysteresis_needed():
    now = datetime(2026, 7, 21, 12, 0)
    # current=OPEN, lux jumps straight to SHADE-tier: darkening, always allowed.
    assert _resolve(now=now, lux=5000, current=OPEN) == SHADE


# --- sun-at-window gating of SHADE ----------------------------------------

def test_sun_at_window_none_treated_as_always_true():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=5000, current=OPEN, sun_at_window=None) == SHADE


def test_sun_at_window_false_suppresses_shade_falls_back_to_medium():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=5000, current=OPEN, sun_at_window=False) == MEDIUM


def test_sun_at_window_false_still_allows_medium():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=300, current=OPEN, sun_at_window=False) == MEDIUM


# --- hysteresis on lightening ----------------------------------------------

def test_lightening_blocked_when_reopen_threshold_not_yet_crossed():
    now = datetime(2026, 7, 21, 12, 0)
    # Primary thresholds say MEDIUM (lux<1000), but reopen HIGH threshold (700)
    # hasn't been crossed yet, so we must hold at SHADE.
    assert _resolve(now=now, lux=800, current=SHADE) == SHADE


def test_lightening_allowed_once_reopen_threshold_crossed():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=650, current=SHADE) == MEDIUM


def test_lightening_all_the_way_to_open_when_both_reopen_thresholds_crossed():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=50, current=SHADE) == OPEN


def test_lightening_from_medium_blocked_until_medium_reopen_crossed():
    now = datetime(2026, 7, 21, 12, 0)
    # primary tier would be OPEN (lux<200), but medium_reopen is 120, so at
    # lux=150 we must still hold at MEDIUM.
    assert _resolve(now=now, lux=150, current=MEDIUM) == MEDIUM


def test_lightening_from_medium_allowed_below_medium_reopen():
    now = datetime(2026, 7, 21, 12, 0)
    assert _resolve(now=now, lux=50, current=MEDIUM) == OPEN


def test_oscillation_right_at_reopen_threshold_boundary_still_blocked():
    now = datetime(2026, 7, 21, 12, 0)
    # exactly at high_reopen (700) counts as "still bright" (>=), so no lighten.
    assert _resolve(now=now, lux=700, current=SHADE) == SHADE


# --- should_apply_move: dwell lock -----------------------------------------

def test_no_move_needed_when_desired_equals_current():
    now = datetime(2026, 7, 21, 12, 0)
    assert should_apply_move(
        desired=MEDIUM, current=MEDIUM, last_move_time=None, now=now,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is False


def test_first_ever_move_always_allowed():
    now = datetime(2026, 7, 21, 12, 0)
    assert should_apply_move(
        desired=SHADE, current=OPEN, last_move_time=None, now=now,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is True


def test_darkening_uses_short_dwell():
    last_move = datetime(2026, 7, 21, 12, 0)
    now = datetime(2026, 7, 21, 12, 9)  # 9 min elapsed, < 10 min dwell
    assert should_apply_move(
        desired=SHADE, current=MEDIUM, last_move_time=last_move, now=now,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is False

    now_ok = datetime(2026, 7, 21, 12, 10)  # exactly 10 min
    assert should_apply_move(
        desired=SHADE, current=MEDIUM, last_move_time=last_move, now=now_ok,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is True


def test_lightening_requires_longer_reopen_dwell():
    last_move = datetime(2026, 7, 21, 12, 0)
    # 15 min elapsed clears the short dwell but not the reopen dwell.
    now = datetime(2026, 7, 21, 12, 15)
    assert should_apply_move(
        desired=MEDIUM, current=SHADE, last_move_time=last_move, now=now,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is False

    now_ok = datetime(2026, 7, 21, 12, 30)
    assert should_apply_move(
        desired=MEDIUM, current=SHADE, last_move_time=last_move, now=now_ok,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is True


def test_darkening_after_a_recent_lighten_only_needs_short_dwell():
    # Chain-load rule: down->down is fine. A darkening move right after a
    # lightening move should only need the short dwell, not the reopen one,
    # since it's the lightening ("up") step that risks the damaging cycle.
    last_move = datetime(2026, 7, 21, 12, 0)  # this was the lightening move
    now = datetime(2026, 7, 21, 12, 10)  # only 10 min later
    assert should_apply_move(
        desired=SHADE, current=MEDIUM, last_move_time=last_move, now=now,
        dwell_minutes=10, reopen_dwell_minutes=30,
    ) is True
