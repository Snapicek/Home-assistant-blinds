"""Constants for the Chained Blinds integration."""
from __future__ import annotations

from datetime import timedelta
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
