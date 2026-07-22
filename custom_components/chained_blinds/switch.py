"""Switch entities for Chained Blinds: master enable and manual override.

The override switch replaces the original blueprint's dependency on a
user-supplied `timer.` helper: turning it on means "hold, do nothing" and it
auto-clears after `override_duration_minutes` from config, reproducing `timer.finished`
semantics without requiring the user to pre-create anything.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_OVERRIDE_DURATION_MINUTES,
    DEFAULT_OVERRIDE_DURATION_MINUTES,
    DOMAIN,
)
from .models import RoomRuntimeData
from .helpers import elapsed_seconds, minutes_to_seconds


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EnabledSwitch(room),
            OverrideSwitch(hass, room, entry),
        ]
    )


class _RoomSwitchBase(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(self, room: RoomRuntimeData, key: str, translation_key: str, default: bool) -> None:
        self._room = room
        self._key = key
        self._attr_unique_id = f"{room.entry_id}_{key}"
        self._attr_translation_key = translation_key
        self._attr_is_on = default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry_id)}, name=room.name
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._room.entities[self._key] = self
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        if self._room.coordinator is not None:
            await self._room.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
        if self._room.coordinator is not None:
            await self._room.coordinator.async_request_refresh()


class EnabledSwitch(_RoomSwitchBase):
    """Master enable: off means the automatic resolver never moves the covers."""

    def __init__(self, room: RoomRuntimeData) -> None:
        super().__init__(room, "enabled", "automation_enabled", True)
        self._attr_icon = "mdi:auto-mode"


class OverrideSwitch(_RoomSwitchBase):
    """On means "hold current position" -- checked first, before anything else."""

    def __init__(self, hass: HomeAssistant, room: RoomRuntimeData, entry: ConfigEntry) -> None:
        super().__init__(room, "override", "pause_automation", False)
        self._attr_icon = "mdi:hand-back-right"
        self._hass = hass
        self._entry = entry
        self._unsub_expiry: CALLBACK_TYPE | None = None
        self._override_until = None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self._override_until is None:
            return {}
        return {"override_until": self._override_until.isoformat()}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._attr_is_on:
            return

        last_state = await self.async_get_last_state()
        override_until_raw = (
            last_state.attributes.get("override_until")
            if last_state is not None
            else None
        )

        if isinstance(override_until_raw, str):
            override_until = dt_util.parse_datetime(override_until_raw)
            if override_until is not None:
                self._override_until = dt_util.as_utc(override_until)
                remaining = elapsed_seconds(dt_util.utcnow(), self._override_until)
                if remaining <= 0:
                    self._override_until = None
                    await super().async_turn_off()
                    return
                self._schedule_expiry(seconds=remaining)
                return

        # Legacy fallback: if no persisted deadline exists, keep old behavior.
        self._schedule_expiry()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_expiry()
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs) -> None:
        await super().async_turn_on(**kwargs)
        self._schedule_expiry()

    async def async_turn_off(self, **kwargs) -> None:
        self._cancel_expiry()
        self._override_until = None
        await super().async_turn_off(**kwargs)

    @callback
    def _schedule_expiry(self, *, seconds: float | None = None) -> None:
        self._cancel_expiry()
        if seconds is None:
            config = {**self._entry.data, **self._entry.options}
            minutes = config.get(CONF_OVERRIDE_DURATION_MINUTES, DEFAULT_OVERRIDE_DURATION_MINUTES)
            seconds = minutes_to_seconds(minutes)

        self._override_until = dt_util.utcnow() + timedelta(seconds=seconds)
        self._unsub_expiry = async_call_later(self._hass, seconds, self._async_expire)
        self.async_write_ha_state()

    @callback
    def _cancel_expiry(self) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None

    async def _async_expire(self, _now) -> None:
        self._unsub_expiry = None
        self._override_until = None
        await super().async_turn_off()
