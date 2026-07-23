"""Executes cover moves for a resolved semantic state.

Only ever calls `cover.set_cover_position` with an explicit calibrated
percentage -- never `open_cover`/`close_cover` (hard rule 1).
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_CALIBRATION, SemanticState
from .helpers import elapsed_seconds, is_at_target, step_towards
from .models import RoomRuntimeData

_LOGGER = logging.getLogger(__name__)

# Minimum gap enforced between any two cover.set_cover_position calls this
# integration issues for a room -- covers are Zigbee devices on a shared
# mesh, so back-to-back commands to different devices risk being dropped or
# delayed. Every call site (the staggered left/right move below, ramp
# steps, and the manual-move mirror in __init__.py) goes through
# async_call_cover_service so the spacing holds globally, not just between
# the two calls inside a single move.
STAGGER_SECONDS = 1


async def async_call_cover_service(
    hass: HomeAssistant, room: RoomRuntimeData, entity_id: str, position: float
) -> None:
    """Call cover.set_cover_position, waiting out STAGGER_SECONDS since the
    last command this integration sent to any of the room's covers."""
    if room._last_cover_command_time is not None:
        wait = STAGGER_SECONDS - elapsed_seconds(room._last_cover_command_time, dt_util.utcnow())
        if wait > 0:
            await asyncio.sleep(wait)

    room._last_cover_command_time = dt_util.utcnow()
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": entity_id, "position": position},
        blocking=True,
    )


def _calibrated_position(config_entry: ConfigEntry, role: str, state: SemanticState) -> float:
    """Read calibration from config, falling back to DEFAULT_CALIBRATION."""
    config = {**config_entry.data, **config_entry.options}
    key = f"{role}_{state.value}_pos"
    return float(config.get(key, DEFAULT_CALIBRATION[state]))

def _current_cover_position(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    current_position = state.attributes.get("current_position")
    if current_position is None:
        return None
    try:
        return float(current_position)
    except (TypeError, ValueError):
        return None



async def _async_apply_positions(
    hass: HomeAssistant,
    room: RoomRuntimeData,
    *,
    left_position: float,
    right_position: float | None,
    final_state: SemanticState | None,
) -> None:
    # Record the move start time before issuing any command so the
    # manual-move detector's grace window (in __init__.py) covers the whole
    # staggered sequence below -- not just the moment after it finishes.
    # Otherwise a state_changed event fired by the left cover the instant
    # it starts moving can race ahead of this timestamp and be mistaken for
    # a manual move mid-automatic-move.
    room.last_move_time = dt_util.utcnow()

    # Flag that we're making an automation move so the manual-move detector
    # can distinguish this from actual manual moves via state-changed events.
    room._automation_move_in_progress = True
    try:
        await async_call_cover_service(hass, room, room.left_cover, left_position)

        if room.right_cover and right_position is not None:
            await async_call_cover_service(hass, room, room.right_cover, right_position)
    finally:
        # Brief delay to let state-changed events be processed while flag is still True.
        await asyncio.sleep(0.5)
        room._automation_move_in_progress = False

    # Keep dwell bookkeeping on every real move.
    if final_state is not None:
        room.current_state = final_state
    await room.async_persist()

    state_select = room.entities.get("state_select")
    if state_select is not None and final_state is not None:
        state_select.apply_external_state_update(final_state)


async def async_move_to_state(
    hass: HomeAssistant, config_entry: ConfigEntry, room: RoomRuntimeData, target_state: SemanticState
) -> None:
    """Move the room's cover(s) to `target_state`'s calibrated position."""
    left_position = _calibrated_position(config_entry, "left", target_state)
    right_position: float | None = None
    if room.right_cover:
        right_position = _calibrated_position(config_entry, "right", target_state)
    await _async_apply_positions(
        hass,
        room,
        left_position=left_position,
        right_position=right_position,
        final_state=target_state,
    )

    _LOGGER.debug(
        "%s: moved to %s (left=%s%%, right=%s)",
        room.name,
        target_state.value,
        left_position,
        f"{right_position}%" if right_position is not None else "n/a",
    )


async def async_move_towards_state(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    room: RoomRuntimeData,
    target_state: SemanticState,
    *,
    step_percent: float,
) -> bool:
    """Move one incremental step toward a semantic target; return True if reached."""
    left_target = _calibrated_position(config_entry, "left", target_state)
    left_current = _current_cover_position(hass, room.left_cover)
    left_next = step_towards(left_current, left_target, step_percent)

    right_next: float | None = None
    right_target: float | None = None
    if room.right_cover:
        right_target = _calibrated_position(config_entry, "right", target_state)
        right_current = _current_cover_position(hass, room.right_cover)
        right_next = step_towards(right_current, right_target, step_percent)

    reached = is_at_target(left_next, left_target)
    if right_target is not None and right_next is not None:
        reached = reached and is_at_target(right_next, right_target)

    await _async_apply_positions(
        hass,
        room,
        left_position=left_next,
        right_position=right_next,
        final_state=target_state if reached else None,
    )

    _LOGGER.debug(
        "%s: ramp step toward %s (left %s->%s, right=%s, reached=%s)",
        room.name,
        target_state.value,
        left_current,
        left_next,
        right_next,
        reached,
    )
    return reached

