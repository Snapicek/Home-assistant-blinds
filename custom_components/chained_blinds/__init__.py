"""The Chained Blinds integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_LEFT_COVER, CONF_LUX_SENSOR, CONF_RIGHT_COVER, DOMAIN
from .coordinator import ChainedBlindsCoordinator
from .helpers import elapsed_seconds
from .models import RoomRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SELECT, Platform.SWITCH, Platform.TIME]

STORAGE_VERSION = 1


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one room (config entry) from a config entry."""
    store = Store[dict](hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    # entry.options (written by the options flow) takes precedence over the
    # original entry.data so that reconfiguration is actually applied.
    config = {**entry.data, **entry.options}
    room = RoomRuntimeData(
        entry_id=entry.entry_id,
        name=entry.title,
        left_cover=config[CONF_LEFT_COVER],
        right_cover=config.get(CONF_RIGHT_COVER) or None,
        lux_sensor=config[CONF_LUX_SENSOR],
        store=store,
    )
    await room.async_load_persisted()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = room

    # Entity platforms populate room.entities during their async_setup_entry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator = ChainedBlindsCoordinator(hass, room, entry)
    room.coordinator = coordinator

    tracked_entities = [room.lux_sensor]

    async def _async_handle_tracked_state_change(event) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_state_change_event(
            hass, tracked_entities, _async_handle_tracked_state_change
        )
    )

    # ------------------------------------------------------------------ #
    # Manual-move detection: watch the cover entities themselves.
    # Any position change that arrives more than 30 s after the last
    # integration-initiated move is treated as a manual move and the
    # Override switch is activated automatically so the automation does
    # not immediately undo what the user just did.
    # ------------------------------------------------------------------ #
    _MANUAL_MOVE_GRACE_SECONDS = 30

    cover_entities = [room.left_cover]
    if room.right_cover:
        cover_entities.append(room.right_cover)

    async def _async_handle_cover_state_change(event) -> None:
        # Skip if the integration itself triggered the move recently.
        if room.last_move_time is not None:
            if elapsed_seconds(room.last_move_time, dt_util.utcnow()) < _MANUAL_MOVE_GRACE_SECONDS:
                return
        # Skip if automation is already paused.
        override = room.entities.get("override")
        if override is not None and override.is_on:
            return
        # Activate override so the new manual position is held.
        _LOGGER.info(
            "%s: manual cover move detected — activating override", room.name
        )
        if override is not None:
            await override.async_turn_on()

    entry.async_on_unload(
        async_track_state_change_event(
            hass, cover_entities, _async_handle_cover_state_change
        )
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await coordinator.async_config_entry_first_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a room's platforms and drop its runtime data."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its config/options change (structural fields)."""
    await hass.config_entries.async_reload(entry.entry_id)
