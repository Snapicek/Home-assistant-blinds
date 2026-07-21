"""Constants for the Chained Blinds integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time, timedelta
from enum import StrEnum

DOMAIN = "chained_blinds"

EVAL_INTERVAL = timedelta(minutes=5)


class SemanticState(StrEnum):
    """The four discrete positions every cover is calibrated for."""

    OPEN = "open"
    MEDIUM = "medium"
    SHADE = "shade"
    CLOSED = "closed"


# Darkening = moving to a higher rank; lightening = moving to a lower rank.
RANK: dict[SemanticState, int] = {
    SemanticState.OPEN: 0,
    SemanticState.MEDIUM: 1,
    SemanticState.SHADE: 2,
    SemanticState.CLOSED: 3,
}

# Config entry keys (structural, set via config/options flow).
CONF_LEFT_COVER = "left_cover"
CONF_RIGHT_COVER = "right_cover"
CONF_LUX_SENSOR = "lux_sensor"
CONF_SUN_SENSOR = "sun_sensor"

# Default calibrated raw positions (%), per semantic state. Must be tuned
# per physical cover — these are just seed values for the number entities.
DEFAULT_CALIBRATION: dict[SemanticState, float] = {
    SemanticState.OPEN: 75.0,
    SemanticState.MEDIUM: 50.0,
    SemanticState.SHADE: 25.0,
    SemanticState.CLOSED: 0.0,
}

# Default live-tunable lux thresholds and dwell minutes.
DEFAULT_LUX_MEDIUM = 200.0
DEFAULT_LUX_HIGH = 1000.0
DEFAULT_LUX_MEDIUM_REOPEN = 120.0
DEFAULT_LUX_HIGH_REOPEN = 700.0
DEFAULT_DWELL_MINUTES = 10.0
DEFAULT_REOPEN_DWELL_MINUTES = 30.0
DEFAULT_SUNSET_OFFSET_MINUTES = 0.0
DEFAULT_OVERRIDE_DURATION_MINUTES = 60.0
DEFAULT_OPEN_TIME = dt_time(7, 0)

COVER_ROLES = ("left", "right")


@dataclass(frozen=True)
class NumberSpec:
    """Describes one live-tunable `number` entity this integration creates."""

    key: str
    name: str
    default: float
    min_value: float
    max_value: float
    step: float
    unit: str | None = None


# Thresholds/dwell/offsets: one instance per room (config entry).
THRESHOLD_NUMBER_SPECS: tuple[NumberSpec, ...] = (
    NumberSpec("lux_medium", "Lux threshold: medium", DEFAULT_LUX_MEDIUM, 0, 100000, 1, "lx"),
    NumberSpec("lux_high", "Lux threshold: shade", DEFAULT_LUX_HIGH, 0, 100000, 1, "lx"),
    NumberSpec(
        "lux_medium_reopen", "Lux threshold: reopen to medium",
        DEFAULT_LUX_MEDIUM_REOPEN, 0, 100000, 1, "lx",
    ),
    NumberSpec(
        "lux_high_reopen", "Lux threshold: reopen to shade",
        DEFAULT_LUX_HIGH_REOPEN, 0, 100000, 1, "lx",
    ),
    NumberSpec(
        "dwell_minutes", "Dwell before darkening",
        DEFAULT_DWELL_MINUTES, 0, 720, 1, "min",
    ),
    NumberSpec(
        "reopen_dwell_minutes", "Dwell before lightening",
        DEFAULT_REOPEN_DWELL_MINUTES, 0, 720, 1, "min",
    ),
    NumberSpec(
        "sunset_offset_minutes", "Sunset offset",
        DEFAULT_SUNSET_OFFSET_MINUTES, -180, 180, 1, "min",
    ),
    NumberSpec(
        "override_duration_minutes", "Override duration",
        DEFAULT_OVERRIDE_DURATION_MINUTES, 1, 1440, 1, "min",
    ),
)


def calibration_number_specs(role: str) -> tuple[NumberSpec, ...]:
    """Per-cover-per-state calibrated raw position (%), e.g. left_shade_pos."""
    return tuple(
        NumberSpec(
            key=f"{role}_{state.value}_pos",
            name=f"{role.capitalize()} cover: {state.value} position",
            default=DEFAULT_CALIBRATION[state],
            min_value=0,
            max_value=100,
            step=1,
            unit="%",
        )
        for state in SemanticState
    )
