"""Executes cover moves for a resolved semantic state.

Only ever calls `cover.set_cover_position` with an explicit calibrated
percentage -- never `open_cover`/`close_cover` (hard rule 1).
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_CALIBRATION, SemanticState
from .models import RoomRuntimeData

_LOGGER = logging.getLogger(__name__)

STAGGER_SECONDS = 1


def _calibrated_position(room: RoomRuntimeData, role: str, state: SemanticState) -> float:
    entity = room.entities.get(f"{role}_{state.value}_pos")
    if entity is not None and entity.native_value is not None:
        return float(entity.native_value)
    return DEFAULT_CALIBRATION[state]


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


def _step_towards(current: float | None, target: float, step: float) -> float:
    step = max(0.1, abs(step))
    if current is None:
        return target
    if abs(target - current) <= step:
        return target
    if target > current:
        return current + step
    return current - step


def _is_at_target(commanded: float, target: float, *, tolerance: float = 0.5) -> bool:
    return abs(commanded - target) <= tolerance


async def _async_apply_positions(
    hass: HomeAssistant,
    room: RoomRuntimeData,
    *,
    left_position: float,
    right_position: float | None,
    final_state: SemanticState | None,
) -> None:
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": room.left_cover, "position": left_position},
        blocking=True,
    )

    if room.right_cover and right_position is not None:
        await asyncio.sleep(STAGGER_SECONDS)
        await hass.services.async_call(
            "cover",
            "set_cover_position",
            {"entity_id": room.right_cover, "position": right_position},
            blocking=True,
        )

    # Keep dwell/manual-detection timing on every real move.
    if final_state is not None:
        room.current_state = final_state
    room.last_move_time = dt_util.utcnow()
    await room.async_persist()

    state_select = room.entities.get("state_select")
    if state_select is not None and final_state is not None:
        state_select.apply_external_state_update(final_state)


async def async_move_to_state(
    hass: HomeAssistant, room: RoomRuntimeData, target_state: SemanticState
) -> None:
    """Move the room's cover(s) to `target_state`'s calibrated position."""
    left_position = _calibrated_position(room, "left", target_state)
    right_position: float | None = None
    if room.right_cover:
        right_position = _calibrated_position(room, "right", target_state)
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
    room: RoomRuntimeData,
    target_state: SemanticState,
    *,
    step_percent: float,
) -> bool:
    """Move one incremental step toward a semantic target; return True if reached."""
    left_target = _calibrated_position(room, "left", target_state)
    left_current = _current_cover_position(hass, room.left_cover)
    left_next = _step_towards(left_current, left_target, step_percent)

    right_next: float | None = None
    right_target: float | None = None
    if room.right_cover:
        right_target = _calibrated_position(room, "right", target_state)
        right_current = _current_cover_position(hass, room.right_cover)
        right_next = _step_towards(right_current, right_target, step_percent)

    reached = _is_at_target(left_next, left_target)
    if right_target is not None and right_next is not None:
        reached = reached and _is_at_target(right_next, right_target)

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

