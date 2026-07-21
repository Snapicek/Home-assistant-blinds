"""Coordinator: periodic + event-driven re-evaluation of the resolver."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import SUN_EVENT_SUNSET, get_astral_event_date
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
    DEFAULT_REOPEN_DWELL_MINUTES,
    DEFAULT_SUNSET_OFFSET_MINUTES,
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


class ChainedBlindsCoordinator(DataUpdateCoordinator[dict]):
    """Runs one full evaluate-and-move cycle for a single room."""

    def __init__(self, hass: HomeAssistant, room: RoomRuntimeData) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"chained_blinds_{room.entry_id}",
            update_interval=EVAL_INTERVAL,
        )
        self.room = room

    def _sunset_with_offset(self, now: datetime) -> datetime:
        offset_minutes = _num(self.room, "sunset_offset_minutes", DEFAULT_SUNSET_OFFSET_MINUTES)
        sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, now.date())
        if sunset is None:
            # No location configured: never force "night" via sunset alone.
            return now.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=1)
        return dt_util.as_local(sunset) + timedelta(minutes=offset_minutes)

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

        sun_at_window: bool | None = None
        if room.sun_sensor:
            sun_state = self.hass.states.get(room.sun_sensor)
            sun_at_window = sun_state.state == "on" if sun_state is not None else None

        open_time_entity = room.entities.get("open_time")
        open_time = (
            open_time_entity.native_value
            if open_time_entity is not None and open_time_entity.native_value is not None
            else DEFAULT_OPEN_TIME
        )

        now = dt_util.now()
        current = room.current_state or SemanticState.OPEN

        result = {"current": current, "desired": current, "lux": lux, "moved": False}

        if not enabled:
            return result

        thresholds = Thresholds(
            lux_medium=_num(room, "lux_medium", DEFAULT_LUX_MEDIUM),
            lux_high=_num(room, "lux_high", DEFAULT_LUX_HIGH),
            lux_medium_reopen=_num(room, "lux_medium_reopen", DEFAULT_LUX_MEDIUM_REOPEN),
            lux_high_reopen=_num(room, "lux_high_reopen", DEFAULT_LUX_HIGH_REOPEN),
        )

        desired = resolve_desired_state(
            now=now,
            lux=lux,
            sun_at_window=sun_at_window,
            current=current,
            open_time=open_time,
            sunset_with_offset=self._sunset_with_offset(now),
            override_active=override_active,
            thresholds=thresholds,
        )
        result["desired"] = desired

        if should_apply_move(
            desired=desired,
            current=current,
            last_move_time=room.last_move_time,
            now=now,
            dwell_minutes=_num(room, "dwell_minutes", DEFAULT_DWELL_MINUTES),
            reopen_dwell_minutes=_num(room, "reopen_dwell_minutes", DEFAULT_REOPEN_DWELL_MINUTES),
        ):
            await cover_control.async_move_to_state(self.hass, room, desired)
            result["current"] = desired
            result["moved"] = True

        return result
