"""Coordinator: periodic + event-driven re-evaluation of the resolver."""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import (
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
    get_astral_event_date,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import cover_control
from .const import (
    CONF_DWELL_MINUTES,
    CONF_LUX_HIGH,
    CONF_LUX_HIGH_REOPEN,
    CONF_LUX_MEDIUM,
    CONF_LUX_MEDIUM_REOPEN,
    CONF_NON_WORKDAY_OPEN_TIME,
    CONF_OPEN_TIME,
    CONF_RAMP_ENABLED,
    CONF_RAMP_INTERVAL_MINUTES,
    CONF_RAMP_STEP_PERCENT,
    CONF_REOPEN_DWELL_MINUTES,
    CONF_SEASONAL_SPLIT,
    CONF_SUMMER_LUX_FACTOR,
    CONF_SUNRISE_OFFSET_MINUTES,
    CONF_SUNSET_OFFSET_MINUTES,
    CONF_USE_SUNRISE_OPEN,
    CONF_WINTER_LUX_FACTOR,
    DEFAULT_DWELL_MINUTES,

    DEFAULT_LUX_HIGH,
    DEFAULT_LUX_HIGH_REOPEN,
    DEFAULT_LUX_MEDIUM,
    DEFAULT_LUX_MEDIUM_REOPEN,
    DEFAULT_NON_WORKDAY_OPEN_TIME,
    DEFAULT_OPEN_TIME,
    DEFAULT_RAMP_ENABLED,
    DEFAULT_RAMP_INTERVAL_MINUTES,
    DEFAULT_RAMP_STEP_PERCENT,
    DEFAULT_REOPEN_DWELL_MINUTES,
    DEFAULT_SEASONAL_SPLIT,
    DEFAULT_SUMMER_LUX_FACTOR_PERCENT,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_SUNRISE_OFFSET_MINUTES,
    DEFAULT_USE_SUNRISE_OPEN,
    DEFAULT_WINTER_LUX_FACTOR_PERCENT,
    EVAL_INTERVAL,
    SemanticState,
    WORKDAY_SENSOR_ENTITY_ID,
)
from .models import RoomRuntimeData
from .resolver import Thresholds, resolve_desired_state, should_apply_move
from .helpers import elapsed_seconds, minutes_to_seconds, percent_to_factor

_LOGGER = logging.getLogger(__name__)


def _get_config_value(
    hass: HomeAssistant, config_entry, key: str, default: float | bool | object
) -> float | bool | object:
    """Read tuning parameter from merged entry.data + entry.options (options take precedence)."""
    config = {**config_entry.data, **config_entry.options}
    return config.get(key, default)


def _as_time(value: object, default: dt_time) -> dt_time:
    """Coerce a config open-time value to datetime.time.

    HA's TimeSelector persists times as ISO strings ("HH:MM:SS"), while tests
    (and restored defaults) may supply a datetime.time directly. Accept both.
    """
    if isinstance(value, dt_time):
        return value
    if isinstance(value, str):
        try:
            return dt_time.fromisoformat(value)
        except ValueError:
            return default
    return default


class ChainedBlindsCoordinator(DataUpdateCoordinator[dict]):
    """Runs one full evaluate-and-move cycle for a single room."""

    def __init__(self, hass: HomeAssistant, room: RoomRuntimeData, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"chained_blinds_{room.entry_id}",
            update_interval=EVAL_INTERVAL,
            config_entry=config_entry,
        )
        self.room = room
        self._config_entry = config_entry
        self._reconciled = False

    def _reconcile_current_state(self) -> None:
        """On first eval, adopt the covers' real position as tracked state.

        Restart recovery: if no state was persisted (fresh install, or the
        Store/RestoreEntity had nothing), infer current_state from the left
        cover's actual reported position instead of blindly defaulting to
        OPEN -- otherwise the resolver's hysteresis runs against a state the
        covers were never in.
        """
        if self._reconciled:
            return
        room = self.room
        state = self.hass.states.get(room.left_cover)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            # Covers not up yet (Zigbee still reconnecting); try again next eval.
            return
        self._reconciled = True
        if room.current_state is not None:
            return
        position = state.attributes.get("current_position")
        try:
            position = float(position) if position is not None else None
        except (TypeError, ValueError):
            position = None
        if position is None:
            return
        room.current_state = cover_control.nearest_semantic_state(
            self._config_entry, "left", position
        )

    def _sunset_with_offset(self, now: datetime) -> datetime:
        offset_minutes = _get_config_value(self.hass, self._config_entry, CONF_SUNSET_OFFSET_MINUTES, DEFAULT_SUNSET_OFFSET_MINUTES)
        sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, now.date())
        if sunset is None:
            # No location configured: never force "night" via sunset alone.
            return now.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
        return dt_util.as_local(sunset) + timedelta(minutes=offset_minutes)

    def _sunrise_with_offset(self, now: datetime) -> datetime:
        offset_minutes = _get_config_value(self.hass, self._config_entry, CONF_SUNRISE_OFFSET_MINUTES, DEFAULT_SUNRISE_OFFSET_MINUTES)
        sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, now.date())
        if sunrise is None:
            # No location configured: keep fixed open_time behavior.
            return now.replace(
                hour=DEFAULT_OPEN_TIME.hour,
                minute=DEFAULT_OPEN_TIME.minute,
                second=0,
                microsecond=0,
            )
        return dt_util.as_local(sunrise) + timedelta(minutes=offset_minutes)

    def _season_factor(self, now: datetime) -> float:
        # Apr-Sep are treated as the sunny season; Oct-Mar as winter season.
        if 4 <= now.month <= 9:
            summer_pct = _get_config_value(self.hass, self._config_entry, CONF_SUMMER_LUX_FACTOR, DEFAULT_SUMMER_LUX_FACTOR_PERCENT)
            return percent_to_factor(summer_pct)
        winter_pct = _get_config_value(self.hass, self._config_entry, CONF_WINTER_LUX_FACTOR, DEFAULT_WINTER_LUX_FACTOR_PERCENT)
        return percent_to_factor(winter_pct)

    async def _async_update_data(self) -> dict:
        room = self.room

        enabled_entity = room.entities.get("enabled")
        override_entity = room.entities.get("override")
        enabled = enabled_entity.is_on if enabled_entity is not None else True
        override_active = bool(override_entity.is_on) if override_entity is not None else False

        lux_state = self.hass.states.get(room.lux_sensor)
        lux_available = lux_state is not None and lux_state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        try:
            lux = float(lux_state.state) if lux_available else 0.0
        except (TypeError, ValueError):
            lux = 0.0
            lux_available = False


        now = dt_util.now()

        open_time = _as_time(
            _get_config_value(self.hass, self._config_entry, CONF_OPEN_TIME, DEFAULT_OPEN_TIME),
            DEFAULT_OPEN_TIME,
        )
        non_workday_open_time = _as_time(
            _get_config_value(self.hass, self._config_entry, CONF_NON_WORKDAY_OPEN_TIME, DEFAULT_NON_WORKDAY_OPEN_TIME),
            DEFAULT_NON_WORKDAY_OPEN_TIME,
        )

        workday_state = self.hass.states.get(WORKDAY_SENSOR_ENTITY_ID)
        is_workday = workday_state is None or workday_state.state != "off"
        open_time = open_time if is_workday else non_workday_open_time

        if _get_config_value(self.hass, self._config_entry, CONF_USE_SUNRISE_OPEN, DEFAULT_USE_SUNRISE_OPEN):
            # Keep resolver's pure time-of-day contract by passing only local HH:MM:SS.
            open_time = self._sunrise_with_offset(now).time().replace(tzinfo=None)
        self._reconcile_current_state()
        current = room.current_state or SemanticState.OPEN

        result = {
            "current": current,
            "desired": current,
            "lux": lux,
            "moved": False,
            "ramping": False,
            "lux_unavailable": not lux_available,
        }

        if not enabled:
            room.ramp_target_state = None
            return result

        # A dropped-out lux sensor must not be read as "0 lux = dark" -- that
        # would reopen shades into direct sun. Hold current position (no move)
        # until a real reading returns.
        if not lux_available:
            _LOGGER.debug(
                "%s: lux sensor %s unavailable — holding position",
                room.name,
                room.lux_sensor,
            )
            room.ramp_target_state = None
            return result

        thresholds = Thresholds(
            lux_medium=_get_config_value(self.hass, self._config_entry, CONF_LUX_MEDIUM, DEFAULT_LUX_MEDIUM),
            lux_high=_get_config_value(self.hass, self._config_entry, CONF_LUX_HIGH, DEFAULT_LUX_HIGH),
            lux_medium_reopen=_get_config_value(self.hass, self._config_entry, CONF_LUX_MEDIUM_REOPEN, DEFAULT_LUX_MEDIUM_REOPEN),
            lux_high_reopen=_get_config_value(self.hass, self._config_entry, CONF_LUX_HIGH_REOPEN, DEFAULT_LUX_HIGH_REOPEN),
        )
        if _get_config_value(self.hass, self._config_entry, CONF_SEASONAL_SPLIT, DEFAULT_SEASONAL_SPLIT):
            factor = self._season_factor(now)
            thresholds = Thresholds(
                lux_medium=thresholds.lux_medium * factor,
                lux_high=thresholds.lux_high * factor,
                lux_medium_reopen=thresholds.lux_medium_reopen * factor,
                lux_high_reopen=thresholds.lux_high_reopen * factor,
            )

        desired = resolve_desired_state(
            now=now,
            lux=lux,
            sun_at_window=None,
            current=current,
            open_time=open_time,
            sunset_with_offset=self._sunset_with_offset(now),
            override_active=override_active,
            thresholds=thresholds,
        )
        result["desired"] = desired

        if override_active:
            room.ramp_target_state = None
            return result

        ramp_enabled = _get_config_value(self.hass, self._config_entry, CONF_RAMP_ENABLED, DEFAULT_RAMP_ENABLED)
        ramp_step_percent = _get_config_value(self.hass, self._config_entry, CONF_RAMP_STEP_PERCENT, DEFAULT_RAMP_STEP_PERCENT)
        ramp_interval_minutes = _get_config_value(self.hass, self._config_entry, CONF_RAMP_INTERVAL_MINUTES, DEFAULT_RAMP_INTERVAL_MINUTES)
        ramp_interval_seconds = max(1.0, minutes_to_seconds(ramp_interval_minutes))

        if not ramp_enabled:
            room.ramp_target_state = None

        if room.ramp_target_state is not None and room.ramp_target_state != desired:
            room.ramp_target_state = desired

        can_start_move = should_apply_move(
            desired=desired,
            current=current,
            last_move_time=room.last_move_time,
            now=now,
            dwell_minutes=_get_config_value(self.hass, self._config_entry, CONF_DWELL_MINUTES, DEFAULT_DWELL_MINUTES),
            reopen_dwell_minutes=_get_config_value(self.hass, self._config_entry, CONF_REOPEN_DWELL_MINUTES, DEFAULT_REOPEN_DWELL_MINUTES),
        )

        if not ramp_enabled:
            if can_start_move:
                await cover_control.async_move_to_state(self.hass, self._config_entry, room, desired)
                result["current"] = desired
                result["moved"] = True
            return result

        ramp_target = room.ramp_target_state
        if ramp_target is None and can_start_move:
            ramp_target = desired
            room.ramp_target_state = desired

        if ramp_target is None:
            return result

        elapsed_since_last_move = (
            elapsed_seconds(room.last_move_time, dt_util.utcnow())
            if room.last_move_time is not None
            else ramp_interval_seconds
        )
        if elapsed_since_last_move < ramp_interval_seconds:
            result["ramping"] = True
            return result

        reached_target = await cover_control.async_move_towards_state(
            self.hass,
            self._config_entry,
            room,
            ramp_target,
            step_percent=ramp_step_percent,
        )
        result["moved"] = True
        if reached_target:
            room.ramp_target_state = None
            result["current"] = ramp_target
            return result

        result["ramping"] = True
        result["current"] = room.current_state or current
        return result
