"""Pure helper utilities — no Home Assistant imports.

Centralises repeated arithmetic for timers and percentages so every
caller uses the same formula.
"""
from __future__ import annotations

from datetime import datetime


def minutes_to_seconds(minutes: float) -> float:
    """Convert minutes to seconds."""
    return minutes * 60.0


def elapsed_seconds(since: datetime, now: datetime) -> float:
    """Seconds elapsed between two datetimes (always >= 0 when since <= now)."""
    return (now - since).total_seconds()


def elapsed_minutes(since: datetime, now: datetime) -> float:
    """Minutes elapsed between two datetimes."""
    return elapsed_seconds(since, now) / 60.0


def percent_to_factor(percent: float) -> float:
    """Convert a percentage integer/float to a multiplier (115 → 1.15)."""
    return percent / 100.0


def step_towards(current: float | None, target: float, step: float) -> float:
    """Return next position stepping *current* toward *target* by *step* percent.

    If *current* is None (position unknown) jump straight to *target*.
    """
    step = max(0.1, abs(step))
    if current is None:
        return target
    if abs(target - current) <= step:
        return target
    if target > current:
        return current + step
    return current - step


def is_at_target(commanded: float, target: float, *, tolerance: float = 0.5) -> bool:
    """True when *commanded* position is within *tolerance* percent of *target*."""
    return abs(commanded - target) <= tolerance

