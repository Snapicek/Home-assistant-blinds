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


async def async_move_to_state(
    hass: HomeAssistant, room: RoomRuntimeData, target_state: SemanticState
) -> None:
    """Move the room's cover(s) to `target_state`'s calibrated position."""
    left_position = _calibrated_position(room, "left", target_state)
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": room.left_cover, "position": left_position},
        blocking=True,
    )

    right_position: float | None = None
    if room.right_cover:
        await asyncio.sleep(STAGGER_SECONDS)
        right_position = _calibrated_position(room, "right", target_state)
        await hass.services.async_call(
            "cover",
            "set_cover_position",
            {"entity_id": room.right_cover, "position": right_position},
            blocking=True,
        )

    # Only place current_state/last_move_time are updated (rule 10): this
    # is the single choke point every move -- automatic or manual -- funnels
    # through, so dwell tracking always reflects the last *real* move.
    room.current_state = target_state
    room.last_move_time = dt_util.utcnow()
    await room.async_persist()

    state_select = room.entities.get("state_select")
    if state_select is not None:
        state_select.apply_external_state_update(target_state)

    _LOGGER.debug(
        "%s: moved to %s (left=%s%%, right=%s)",
        room.name,
        target_state.value,
        left_position,
        f"{right_position}%" if right_position is not None else "n/a",
    )
