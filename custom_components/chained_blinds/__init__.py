"""The Chained Blinds integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LEFT_COVER,
    CONF_LUX_SENSOR,
    CONF_MAX_TRAVEL_SECONDS,
    CONF_RIGHT_COVER,
    CommandSource,
    DEFAULT_MAX_TRAVEL_SECONDS,
    DOMAIN,
    WORKDAY_SENSOR_ENTITY_ID,
)
from . import cover_control
from .coordinator import ChainedBlindsCoordinator
from .helpers import elapsed_seconds
from .models import RoomRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SWITCH]

STORAGE_VERSION = 1


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one room (config entry) from a config entry."""
    store = Store[dict](hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
    # entry.options (written by the options flow) takes precedence over the    # original entry.data so that reconfiguration is actually applied.
    config = {**entry.data, **entry.options}
    room = RoomRuntimeData(
        entry_id=entry.entry_id,
        name=entry.title,
        left_cover=config[CONF_LEFT_COVER],
        right_cover=config.get(CONF_RIGHT_COVER) or None,
        lux_sensor=config[CONF_LUX_SENSOR],
        config_entry=entry,
        store=store,
    )
    await room.async_load_persisted()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = room

    # Entity platforms populate room.entities during their async_setup_entry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator = ChainedBlindsCoordinator(hass, room, entry)
    room.coordinator = coordinator

    tracked_entities = [room.lux_sensor, WORKDAY_SENSOR_ENTITY_ID]

    async def _async_handle_tracked_state_change(event) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_state_change_event(
            hass, tracked_entities, _async_handle_tracked_state_change
        )
    )

    # ------------------------------------------------------------------ #
    # Manual-move detection: watch the cover entities themselves.
    #
    # A position change is attributed to our own move only while the cover
    # is still travelling toward the position we last commanded -- i.e. the
    # reported position stays within the [start, target] band (plus a small
    # tolerance for chain-blind wobble) and inside the max-travel window.
    # Anything moving *away* from the commanded target, or arriving after the
    # travel window, is a manual move: the override switch is engaged so the
    # automation does not immediately undo what the user just did.
    # ------------------------------------------------------------------ #
    # Chain-driven blinds rarely land exactly on the commanded percentage
    # (a "50" can settle at 52, or wobble between adjacent values), so allow
    # this tolerance around the travel band before calling a move manual.
    _BAND_TOLERANCE_PERCENT = 5
    _config = {**entry.data, **entry.options}
    _max_travel_seconds = float(
        _config.get(CONF_MAX_TRAVEL_SECONDS, DEFAULT_MAX_TRAVEL_SECONDS)
    )

    cover_entities = [room.left_cover]
    if room.right_cover:
        cover_entities.append(room.right_cover)

    def _is_own_move(entity_id, position, now) -> bool:
        """True while the cover is still travelling toward our last command."""
        ctx = room._command_context.get(entity_id)
        if ctx is None:
            return False
        if elapsed_seconds(ctx.started_at, now) > _max_travel_seconds:
            return False
        if position is None:
            # Can't judge direction; trust the travel window.
            return True
        if abs(position - ctx.target) <= _BAND_TOLERANCE_PERCENT:
            return True
        start = ctx.start if ctx.start is not None else ctx.target
        low = min(start, ctx.target) - _BAND_TOLERANCE_PERCENT
        high = max(start, ctx.target) + _BAND_TOLERANCE_PERCENT
        return low <= position <= high

    async def _async_mirror_manual(moved_entity_id, position) -> None:
        """Mirror a confirmed manual move onto the paired cover.

        Maps the moved cover's actual position to its nearest semantic state,
        then drives the paired cover to *its own* calibrated position for that
        state -- never the raw percentage, since the two covers may have
        different calibration.
        """
        if not room.right_cover or position is None:
            return
        if moved_entity_id == room.left_cover:
            role, other_cover, other_role = "left", room.right_cover, "right"
        else:
            role, other_cover, other_role = "right", room.left_cover, "left"
        state = cover_control.nearest_semantic_state(room.config_entry, role, position)
        other_position = cover_control.calibrated_position(
            room.config_entry, other_role, state
        )
        await cover_control.async_call_cover_service(
            hass, room, other_cover, other_position, source=CommandSource.MANUAL_MIRROR
        )

    async def _async_handle_cover_state_change(event) -> None:
        # A cover reporting in for the first time -- e.g. transitioning from
        # unknown/unavailable to its real position as the Zigbee network
        # reconnects after a Home Assistant restart -- is not a manual move.
        # Without this guard, every restart pauses the automation the
        # instant the cover's real state arrives.
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if (
            old_state is None
            or old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            or new_state is None
            or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        ):
            return

        moved_entity_id = event.data.get("entity_id")
        position = new_state.attributes.get("current_position")
        now = dt_util.utcnow()

        # Own automation move (either issuing right now, or the cover still
        # travelling toward what we commanded): don't pause, don't mirror --
        # the automation move path already commanded both covers.
        if room._automation_move_in_progress or _is_own_move(moved_entity_id, position, now):
            return

        # Real manual move. Latch synchronously *before any await* so an
        # in-flight coordinator decision re-checks manual_pending before its
        # own set_cover_position and aborts instead of overwriting the user.
        room.manual_pending = True

        override = room.entities.get("override")

        # Keep internal state synchronized with reality on every manual move
        # (even when override is already on) so that when it later expires the
        # resolver runs hysteresis/dwell against where the covers really are.
        if position is not None:
            role = "left" if moved_entity_id == room.left_cover else "right"
            synced_state = cover_control.nearest_semantic_state(
                room.config_entry, role, position
            )
            room.current_state = synced_state
            await room.async_persist()
            state_select = room.entities.get("state_select")
            if state_select is not None:
                state_select.apply_external_state_update(synced_state)

        # Engage / extend the hold. A fresh manual move slides the expiry so
        # continued manual activity keeps the automation paused.
        if override is not None:
            if override.is_on:
                override.slide_expiry()
            else:
                _LOGGER.info(
                    "%s: manual cover move detected — activating override", room.name
                )
                await override.async_turn_on()

        # Keep both covers aligned: mirror the moved cover's semantic state
        # onto its pair using the pair's own calibration.
        await _async_mirror_manual(moved_entity_id, position)

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
