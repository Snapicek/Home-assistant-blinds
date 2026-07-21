"""Time entity for Chained Blinds: the daily `open_time` (rule 8)."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_OPEN_TIME, DOMAIN
from .models import RoomRuntimeData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OpenTimeEntity(room)])


class OpenTimeEntity(TimeEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "Morning opening time"
    _attr_icon = "mdi:clock-start"

    def __init__(self, room: RoomRuntimeData) -> None:
        self._room = room
        self._attr_unique_id = f"{room.entry_id}_open_time"
        self._attr_native_value = DEFAULT_OPEN_TIME
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry_id)}, name=room.name
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._room.entities["open_time"] = self
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._attr_native_value = time.fromisoformat(last_state.state)
            except ValueError:
                pass

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        if self._room.coordinator is not None:
            await self._room.coordinator.async_request_refresh()
