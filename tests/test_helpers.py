"""Unit tests for shared helper utilities (helpers.py)."""
from datetime import datetime

import pytest

from custom_components.chained_blinds.helpers import (
    elapsed_minutes,
    elapsed_seconds,
    is_at_target,
    minutes_to_seconds,
    percent_to_factor,
    step_towards,
)


# ── minutes_to_seconds ───────────────────────────────────────────────────────

def test_minutes_to_seconds_basic():
    assert minutes_to_seconds(1) == 60.0


def test_minutes_to_seconds_fractional():
    assert minutes_to_seconds(1.5) == 90.0


def test_minutes_to_seconds_zero():
    assert minutes_to_seconds(0) == 0.0


# ── elapsed_seconds / elapsed_minutes ────────────────────────────────────────

def test_elapsed_seconds_simple():
    t0 = datetime(2026, 7, 21, 12, 0, 0)
    t1 = datetime(2026, 7, 21, 12, 0, 45)
    assert elapsed_seconds(t0, t1) == 45.0


def test_elapsed_minutes_simple():
    t0 = datetime(2026, 7, 21, 12, 0, 0)
    t1 = datetime(2026, 7, 21, 12, 10, 0)
    assert elapsed_minutes(t0, t1) == 10.0


def test_elapsed_minutes_fractional():
    t0 = datetime(2026, 7, 21, 12, 0, 0)
    t1 = datetime(2026, 7, 21, 12, 0, 30)
    assert elapsed_minutes(t0, t1) == pytest.approx(0.5)


# ── percent_to_factor ─────────────────────────────────────────────────────────

def test_percent_to_factor_100():
    assert percent_to_factor(100) == 1.0


def test_percent_to_factor_115():
    assert percent_to_factor(115) == pytest.approx(1.15)


def test_percent_to_factor_85():
    assert percent_to_factor(85) == pytest.approx(0.85)


def test_percent_to_factor_50():
    assert percent_to_factor(50) == pytest.approx(0.5)


# ── step_towards ─────────────────────────────────────────────────────────────

def test_step_towards_down():
    assert step_towards(75.0, 25.0, 20.0) == 55.0


def test_step_towards_up():
    assert step_towards(25.0, 75.0, 20.0) == 45.0


def test_step_towards_reaches_target_exactly():
    assert step_towards(30.0, 25.0, 20.0) == 25.0


def test_step_towards_unknown_current_jumps_to_target():
    assert step_towards(None, 25.0, 20.0) == 25.0


def test_step_towards_clamps_step_minimum():
    # step of 0 should be clamped to 0.1
    assert step_towards(50.0, 100.0, 0.0) == pytest.approx(50.1)


# ── is_at_target ─────────────────────────────────────────────────────────────

def test_is_at_target_exact():
    assert is_at_target(25.0, 25.0) is True


def test_is_at_target_within_tolerance():
    assert is_at_target(25.3, 25.0) is True


def test_is_at_target_outside_tolerance():
    assert is_at_target(25.6, 25.0) is False


def test_is_at_target_custom_tolerance():
    assert is_at_target(26.0, 25.0, tolerance=1.0) is True
    assert is_at_target(26.1, 25.0, tolerance=1.0) is False

