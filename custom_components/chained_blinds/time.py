"""Time entity for Chained Blinds: the daily `open_time` (rule 8)."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_NON_WORKDAY_OPEN_TIME, DEFAULT_OPEN_TIME, DOMAIN
from .models import RoomRuntimeData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OpenTimeEntity(room), NonWorkdayOpenTimeEntity(room)])


class _RoomTimeBase(TimeEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        room: RoomRuntimeData,
        *,
        key: str,
        name: str,
        default: time,
        icon: str,
    ) -> None:
        self._room = room
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{room.entry_id}_{key}"
        self._attr_native_value = default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry_id)}, name=room.name
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._room.entities[self._key] = self
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


class OpenTimeEntity(_RoomTimeBase):
    def __init__(self, room: RoomRuntimeData) -> None:
        super().__init__(
            room,
            key="open_time",
            name="Morning opening time",
            default=DEFAULT_OPEN_TIME,
            icon="mdi:clock-start",
        )


class NonWorkdayOpenTimeEntity(_RoomTimeBase):
    def __init__(self, room: RoomRuntimeData) -> None:
        super().__init__(
            room,
            key="non_workday_open_time",
            name="Non-workday opening time",
            default=DEFAULT_NON_WORKDAY_OPEN_TIME,
            icon="mdi:clock-end",
        )

