"""Constants for the Chained Blinds integration."""
from __future__ import annotations

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
CONF_ROOM_NAME = "room_name"
CONF_LEFT_COVER = "left_cover"
CONF_RIGHT_COVER = "right_cover"
CONF_LUX_SENSOR = "lux_sensor"

# Config entry keys (tuning, now moved from entity platform to config flow).
CONF_LUX_MEDIUM = "lux_medium"
CONF_LUX_HIGH = "lux_high"
CONF_LUX_MEDIUM_REOPEN = "lux_medium_reopen"
CONF_LUX_HIGH_REOPEN = "lux_high_reopen"
CONF_DWELL_MINUTES = "dwell_minutes"
CONF_REOPEN_DWELL_MINUTES = "reopen_dwell_minutes"
CONF_OVERRIDE_DURATION_MINUTES = "override_duration_minutes"
CONF_RAMP_STEP_PERCENT = "ramp_step_percent"
CONF_RAMP_INTERVAL_MINUTES = "ramp_interval_minutes"
CONF_SUNRISE_OFFSET_MINUTES = "sunrise_offset_minutes"
CONF_SUNSET_OFFSET_MINUTES = "sunset_offset_minutes"
CONF_SUMMER_LUX_FACTOR = "summer_lux_factor"
CONF_WINTER_LUX_FACTOR = "winter_lux_factor"
CONF_SEASONAL_SPLIT = "seasonal_split"
CONF_USE_SUNRISE_OPEN = "use_sunrise_open"
CONF_RAMP_ENABLED = "ramp_enabled"
CONF_OPEN_TIME = "open_time"
CONF_NON_WORKDAY_OPEN_TIME = "non_workday_open_time"

# Default calibrated raw positions (%), per semantic state. Must be tuned
# per physical cover — these are just seed values for the config-flow
# calibration step.
DEFAULT_CALIBRATION: dict[SemanticState, float] = {
    SemanticState.OPEN: 75.0,
    SemanticState.MEDIUM: 50.0,
    SemanticState.SHADE: 25.0,
    SemanticState.CLOSED: 0.0,
}

# Default live-tunable lux thresholds and dwell minutes.
# Calibrated for an OUTDOOR lux sensor (full-sky measurement).
# Typical outdoor ranges:
#   heavy overcast  1 000 – 5 000 lx
#   bright overcast 5 000 – 20 000 lx
#   hazy sun       20 000 – 50 000 lx
#   clear direct   60 000 – 100 000 lx
#
# Rule of thumb: set lux_medium at the point where you want partial shading
# (hazy / bright sun starts), lux_high where full shade is needed (strong direct
# sun).  The *_reopen values are set at ~60 % of the corresponding close
# threshold to provide hysteresis and avoid close/open cycling on passing clouds.
DEFAULT_LUX_MEDIUM = 12000.0
DEFAULT_LUX_HIGH = 35000.0
DEFAULT_LUX_MEDIUM_REOPEN = 7000.0
DEFAULT_LUX_HIGH_REOPEN = 21000.0
DEFAULT_DWELL_MINUTES = 10.0
DEFAULT_REOPEN_DWELL_MINUTES = 30.0
DEFAULT_SUNSET_OFFSET_MINUTES = 0.0
DEFAULT_SUNRISE_OFFSET_MINUTES = 0.0
DEFAULT_OVERRIDE_DURATION_MINUTES = 60.0
DEFAULT_RAMP_STEP_PERCENT = 20.0
DEFAULT_RAMP_INTERVAL_MINUTES = 5.0
DEFAULT_OPEN_TIME = dt_time(8, 0)
DEFAULT_NON_WORKDAY_OPEN_TIME = dt_time(9, 30)
DEFAULT_SUMMER_LUX_FACTOR = 1.15
DEFAULT_WINTER_LUX_FACTOR = 0.85
DEFAULT_SUMMER_LUX_FACTOR_PERCENT = 115
DEFAULT_WINTER_LUX_FACTOR_PERCENT = 85
DEFAULT_SEASONAL_SPLIT = False
DEFAULT_USE_SUNRISE_OPEN = False
DEFAULT_RAMP_ENABLED = False
WORKDAY_SENSOR_ENTITY_ID = "binary_sensor.workday_sensor"

COVER_ROLES = ("left", "right")

