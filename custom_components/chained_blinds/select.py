"""Select entity for Chained Blinds: the tracked current semantic state,
with a manual "force this state now" escape hatch for the user."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SemanticState
from .models import RoomRuntimeData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChainedBlindsStateSelect(room)])


class ChainedBlindsStateSelect(SelectEntity, RestoreEntity):
    """Tracks the current semantic state (rule: only written on a real move).

    Manually selecting an option here routes through the exact same move
    path the coordinator uses, so it never bypasses per-cover calibration
    or the dwell-time bookkeeping. Note this does not disable the automatic
    resolver -- the enable switch or the override switch do that.
    """

    _attr_has_entity_name = True
    _attr_name = "State"
    _attr_options = [state.value for state in SemanticState]

    def __init__(self, room: RoomRuntimeData) -> None:
        self._room = room
        self._attr_unique_id = f"{room.entry_id}_state"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry_id)}, name=room.name
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._room.entities["state_select"] = self
        if self._room.current_state is None and (
            last_state := await self.async_get_last_state()
        ) is not None and last_state.state in self._attr_options:
            self._room.current_state = SemanticState(last_state.state)
        current = self._room.current_state or SemanticState.OPEN
        self._attr_current_option = current.value

    async def async_select_option(self, option: str) -> None:
        # Local import breaks the select.py <-> cover_control.py import
        # cycle (cover_control calls back into this entity by duck-typed
        # method, never by importing this class).
        from .cover_control import async_move_to_state

        await async_move_to_state(self.hass, self._room, SemanticState(option))
        if self._room.coordinator is not None:
            await self._room.coordinator.async_request_refresh()

    @callback
    def apply_external_state_update(self, state: SemanticState) -> None:
        """Called by cover_control right after an automatic move happens."""
        self._attr_current_option = state.value
        self.async_write_ha_state()
