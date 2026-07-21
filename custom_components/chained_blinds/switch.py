"""Switch entities for Chained Blinds: master enable and manual override.

The override switch replaces the original blueprint's dependency on a
user-supplied `timer.` helper: turning it on means "hold, do nothing" and it
auto-clears after `override_duration_minutes`, reproducing `timer.finished`
semantics without requiring the user to pre-create anything.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, DEFAULT_OVERRIDE_DURATION_MINUTES
from .models import RoomRuntimeData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EnabledSwitch(room), OverrideSwitch(hass, room)])


class _RoomSwitchBase(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(self, room: RoomRuntimeData, key: str, name: str, default: bool) -> None:
        self._room = room
        self._key = key
        self._attr_unique_id = f"{room.entry_id}_{key}"
        self._attr_name = name
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
        super().__init__(room, "enabled", "Enabled", True)
        self._attr_icon = "mdi:auto-mode"


class OverrideSwitch(_RoomSwitchBase):
    """On means "hold current position" -- checked first, before anything else."""

    def __init__(self, hass: HomeAssistant, room: RoomRuntimeData) -> None:
        super().__init__(room, "override", "Override", False)
        self._attr_icon = "mdi:hand-back-right"
        self._hass = hass
        self._unsub_expiry: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._attr_is_on:
            self._schedule_expiry()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_expiry()
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs) -> None:
        await super().async_turn_on(**kwargs)
        self._schedule_expiry()

    async def async_turn_off(self, **kwargs) -> None:
        self._cancel_expiry()
        await super().async_turn_off(**kwargs)

    @callback
    def _schedule_expiry(self) -> None:
        self._cancel_expiry()
        duration_entity = self._room.entities.get("override_duration_minutes")
        minutes = (
            duration_entity.native_value
            if duration_entity is not None and duration_entity.native_value is not None
            else DEFAULT_OVERRIDE_DURATION_MINUTES
        )
        self._unsub_expiry = async_call_later(self._hass, minutes * 60, self._async_expire)

    @callback
    def _cancel_expiry(self) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None

    async def _async_expire(self, _now) -> None:
        self._unsub_expiry = None
        await super().async_turn_off()
