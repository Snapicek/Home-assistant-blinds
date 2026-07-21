"""Constants for the Chained Blinds integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time, timedelta
from enum import StrEnum

from homeassistant.helpers.entity import EntityCategory

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

# Default calibrated raw positions (%), per semantic state. Must be tuned
# per physical cover — these are just seed values for the number entities.
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
DEFAULT_OPEN_TIME = dt_time(7, 0)
DEFAULT_SUMMER_LUX_FACTOR = 1.15
DEFAULT_WINTER_LUX_FACTOR = 0.85
DEFAULT_SUMMER_LUX_FACTOR_PERCENT = 115
DEFAULT_WINTER_LUX_FACTOR_PERCENT = 85
DEFAULT_SEASONAL_SPLIT = False
DEFAULT_USE_SUNRISE_OPEN = False

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
    icon: str | None = None
    suggested_display_precision: int | None = None
    entity_category: EntityCategory | None = EntityCategory.CONFIG


# Thresholds/dwell/offsets: one instance per room (config entry).
THRESHOLD_NUMBER_SPECS: tuple[NumberSpec, ...] = (
    NumberSpec(
        "lux_medium",
        "Close to medium (lux)",
        DEFAULT_LUX_MEDIUM,
        0,
        100000,
        100,
        "lx",
        icon="mdi:brightness-5",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "lux_medium_reopen",
        "Reopen from medium (lux)",
        DEFAULT_LUX_MEDIUM_REOPEN,
        0,
        100000,
        100,
        "lx",
        icon="mdi:brightness-5",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "lux_high",
        "Close to shade (lux)",
        DEFAULT_LUX_HIGH,
        0,
        100000,
        100,
        "lx",
        icon="mdi:brightness-7",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "lux_high_reopen",
        "Reopen from shade (lux)",
        DEFAULT_LUX_HIGH_REOPEN,
        0,
        100000,
        100,
        "lx",
        icon="mdi:brightness-7",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "dwell_minutes",
        "Close delay",
        DEFAULT_DWELL_MINUTES,
        0,
        720,
        1,
        "min",
        icon="mdi:timer-outline",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "reopen_dwell_minutes",
        "Open delay",
        DEFAULT_REOPEN_DWELL_MINUTES,
        0,
        720,
        1,
        "min",
        icon="mdi:timer-outline",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "override_duration_minutes",
        "Pause duration",
        DEFAULT_OVERRIDE_DURATION_MINUTES,
        1,
        1440,
        1,
        "min",
        icon="mdi:timer-lock-outline",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "sunrise_offset_minutes",
        "Sunrise offset",
        DEFAULT_SUNRISE_OFFSET_MINUTES,
        -180,
        180,
        1,
        "min",
        icon="mdi:weather-sunset-up",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "sunset_offset_minutes",
        "Sunset offset",
        DEFAULT_SUNSET_OFFSET_MINUTES,
        -180,
        180,
        1,
        "min",
        icon="mdi:weather-sunset",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "summer_lux_factor",
        "Summer sensitivity",
        DEFAULT_SUMMER_LUX_FACTOR_PERCENT,
        20,
        300,
        1,
        "%",
        icon="mdi:weather-sunny",
        suggested_display_precision=0,
    ),
    NumberSpec(
        "winter_lux_factor",
        "Winter sensitivity",
        DEFAULT_WINTER_LUX_FACTOR_PERCENT,
        20,
        300,
        1,
        "%",
        icon="mdi:weather-snowy",
        suggested_display_precision=0,
    ),
)


def calibration_number_specs(role: str) -> tuple[NumberSpec, ...]:
    """Per-cover-per-state calibrated raw position (%), e.g. left_shade_pos."""
    return tuple(
        NumberSpec(
            key=f"{role}_{state.value}_pos",
            name=f"{role.capitalize()} {state.value.capitalize()} position",
            default=DEFAULT_CALIBRATION[state],
            min_value=0,
            max_value=100,
            step=1,
            unit="%",
            icon="mdi:blinds-horizontal",
            suggested_display_precision=0,
        )
        for state in SemanticState
    )
