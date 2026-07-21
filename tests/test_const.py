"""Unit tests for integration constants and the SemanticState enum (const.py)."""
from datetime import time

from custom_components.chained_blinds.const import (
    DEFAULT_CALIBRATION,
    DEFAULT_DWELL_MINUTES,
    DEFAULT_LUX_HIGH,
    DEFAULT_LUX_HIGH_REOPEN,
    DEFAULT_LUX_MEDIUM,
    DEFAULT_LUX_MEDIUM_REOPEN,
    DEFAULT_NON_WORKDAY_OPEN_TIME,
    DEFAULT_OPEN_TIME,
    DEFAULT_REOPEN_DWELL_MINUTES,
    DEFAULT_SUMMER_LUX_FACTOR_PERCENT,
    DEFAULT_WINTER_LUX_FACTOR_PERCENT,
    EVAL_INTERVAL,
    RANK,
    SemanticState,
)


# ── SemanticState enum ───────────────────────────────────────────────────────

def test_semantic_state_has_exactly_four_positions():
    assert [s.value for s in SemanticState] == ["open", "medium", "shade", "closed"]


def test_semantic_state_is_string_comparable():
    assert SemanticState.OPEN == "open"
    assert SemanticState("closed") is SemanticState.CLOSED


# ── RANK ordering ────────────────────────────────────────────────────────────

def test_rank_covers_every_semantic_state():
    assert set(RANK) == set(SemanticState)


def test_rank_increases_from_open_to_closed():
    assert RANK[SemanticState.OPEN] < RANK[SemanticState.MEDIUM]
    assert RANK[SemanticState.MEDIUM] < RANK[SemanticState.SHADE]
    assert RANK[SemanticState.SHADE] < RANK[SemanticState.CLOSED]


def test_rank_darkening_has_higher_value_than_lightening():
    darkening = RANK[SemanticState.CLOSED] - RANK[SemanticState.OPEN]
    assert darkening > 0


# ── DEFAULT_CALIBRATION ──────────────────────────────────────────────────────

def test_default_calibration_defines_every_semantic_state():
    assert set(DEFAULT_CALIBRATION) == set(SemanticState)


def test_default_calibration_open_is_most_open_and_closed_is_least():
    assert DEFAULT_CALIBRATION[SemanticState.OPEN] == 75.0
    assert DEFAULT_CALIBRATION[SemanticState.CLOSED] == 0.0


def test_default_calibration_decreases_with_rank():
    ordered = sorted(SemanticState, key=lambda s: RANK[s])
    positions = [DEFAULT_CALIBRATION[s] for s in ordered]
    assert positions == sorted(positions, reverse=True)


def test_default_calibration_positions_within_percentage_bounds():
    assert all(0.0 <= pos <= 100.0 for pos in DEFAULT_CALIBRATION.values())


# ── Lux threshold hysteresis invariants ──────────────────────────────────────

def test_medium_reopen_default_is_below_medium_close_default():
    assert DEFAULT_LUX_MEDIUM_REOPEN < DEFAULT_LUX_MEDIUM


def test_high_reopen_default_is_below_high_close_default():
    assert DEFAULT_LUX_HIGH_REOPEN < DEFAULT_LUX_HIGH


def test_high_close_default_is_brighter_than_medium_close_default():
    assert DEFAULT_LUX_HIGH > DEFAULT_LUX_MEDIUM


# ── Dwell defaults ───────────────────────────────────────────────────────────

def test_reopen_dwell_default_is_longer_than_close_dwell_default():
    assert DEFAULT_REOPEN_DWELL_MINUTES > DEFAULT_DWELL_MINUTES


# ── Seasonal factor defaults ─────────────────────────────────────────────────

def test_summer_factor_default_raises_thresholds():
    assert DEFAULT_SUMMER_LUX_FACTOR_PERCENT > 100


def test_winter_factor_default_lowers_thresholds():
    assert DEFAULT_WINTER_LUX_FACTOR_PERCENT < 100


# ── Open-time defaults ───────────────────────────────────────────────────────

def test_open_time_defaults_are_time_objects():
    assert isinstance(DEFAULT_OPEN_TIME, time)
    assert isinstance(DEFAULT_NON_WORKDAY_OPEN_TIME, time)


def test_non_workday_open_time_default_is_later_than_workday():
    assert DEFAULT_NON_WORKDAY_OPEN_TIME > DEFAULT_OPEN_TIME


# ── Evaluation interval ──────────────────────────────────────────────────────

def test_eval_interval_default_is_five_minutes():
    assert EVAL_INTERVAL.total_seconds() == 300.0

