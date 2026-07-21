"""Coordinator: periodic + event-driven re-evaluation of the resolver."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
    DEFAULT_DWELL_MINUTES,
    DEFAULT_LUX_HIGH,
    DEFAULT_LUX_HIGH_REOPEN,
    DEFAULT_LUX_MEDIUM,
    DEFAULT_LUX_MEDIUM_REOPEN,
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
)
from .models import RoomRuntimeData
from .resolver import Thresholds, resolve_desired_state, should_apply_move

_LOGGER = logging.getLogger(__name__)


def _num(room: RoomRuntimeData, key: str, default: float) -> float:
    entity = room.entities.get(key)
    if entity is not None and entity.native_value is not None:
        return float(entity.native_value)
    return default


def _is_on(room: RoomRuntimeData, key: str, default: bool) -> bool:
    entity = room.entities.get(key)
    if entity is not None:
        return bool(entity.is_on)
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

    def _sunset_with_offset(self, now: datetime) -> datetime:
        offset_minutes = _num(self.room, "sunset_offset_minutes", DEFAULT_SUNSET_OFFSET_MINUTES)
        sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, now.date())
        if sunset is None:
            # No location configured: never force "night" via sunset alone.
            return now.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
        return dt_util.as_local(sunset) + timedelta(minutes=offset_minutes)

    def _sunrise_with_offset(self, now: datetime) -> datetime:
        offset_minutes = _num(self.room, "sunrise_offset_minutes", DEFAULT_SUNRISE_OFFSET_MINUTES)
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
            return _num(self.room, "summer_lux_factor", DEFAULT_SUMMER_LUX_FACTOR_PERCENT) / 100.0
        return _num(self.room, "winter_lux_factor", DEFAULT_WINTER_LUX_FACTOR_PERCENT) / 100.0

    async def _async_update_data(self) -> dict:
        room = self.room

        enabled_entity = room.entities.get("enabled")
        override_entity = room.entities.get("override")
        enabled = enabled_entity.is_on if enabled_entity is not None else True
        override_active = bool(override_entity.is_on) if override_entity is not None else False

        lux_state = self.hass.states.get(room.lux_sensor)
        try:
            lux = float(lux_state.state) if lux_state is not None else 0.0
        except (TypeError, ValueError):
            lux = 0.0


        now = dt_util.now()

        open_time_entity = room.entities.get("open_time")
        open_time = (
            open_time_entity.native_value
            if open_time_entity is not None and open_time_entity.native_value is not None
            else DEFAULT_OPEN_TIME
        )
        if _is_on(room, "sunrise_open", DEFAULT_USE_SUNRISE_OPEN):
            # Keep resolver's pure time-of-day contract by passing only local HH:MM:SS.
            open_time = self._sunrise_with_offset(now).time().replace(tzinfo=None)
        current = room.current_state or SemanticState.OPEN

        result = {
            "current": current,
            "desired": current,
            "lux": lux,
            "moved": False,
            "ramping": False,
        }

        if not enabled:
            room.ramp_target_state = None
            return result

        thresholds = Thresholds(
            lux_medium=_num(room, "lux_medium", DEFAULT_LUX_MEDIUM),
            lux_high=_num(room, "lux_high", DEFAULT_LUX_HIGH),
            lux_medium_reopen=_num(room, "lux_medium_reopen", DEFAULT_LUX_MEDIUM_REOPEN),
            lux_high_reopen=_num(room, "lux_high_reopen", DEFAULT_LUX_HIGH_REOPEN),
        )
        if _is_on(room, "seasonal_split", DEFAULT_SEASONAL_SPLIT):
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

        ramp_enabled = _is_on(room, "ramp_enabled", DEFAULT_RAMP_ENABLED)
        ramp_step_percent = _num(room, "ramp_step_percent", DEFAULT_RAMP_STEP_PERCENT)
        ramp_interval_minutes = _num(room, "ramp_interval_minutes", DEFAULT_RAMP_INTERVAL_MINUTES)
        ramp_interval_seconds = max(1.0, ramp_interval_minutes * 60.0)

        if not ramp_enabled:
            room.ramp_target_state = None

        if room.ramp_target_state is not None and room.ramp_target_state != desired:
            room.ramp_target_state = desired

        can_start_move = should_apply_move(
            desired=desired,
            current=current,
            last_move_time=room.last_move_time,
            now=now,
            dwell_minutes=_num(room, "dwell_minutes", DEFAULT_DWELL_MINUTES),
            reopen_dwell_minutes=_num(room, "reopen_dwell_minutes", DEFAULT_REOPEN_DWELL_MINUTES),
        )

        if not ramp_enabled:
            if can_start_move:
                await cover_control.async_move_to_state(self.hass, room, desired)
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
            (dt_util.utcnow() - room.last_move_time).total_seconds()
            if room.last_move_time is not None
            else ramp_interval_seconds
        )
        if elapsed_since_last_move < ramp_interval_seconds:
            result["ramping"] = True
            return result

        reached_target = await cover_control.async_move_towards_state(
            self.hass,
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
