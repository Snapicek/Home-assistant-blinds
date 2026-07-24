"""Executes cover moves for a resolved semantic state.

Only ever calls `cover.set_cover_position` with an explicit calibrated
percentage -- never `open_cover`/`close_cover` (hard rule 1).
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_CALIBRATION, CommandSource, SemanticState
from .helpers import elapsed_seconds, is_at_target, step_towards
from .models import CoverCommand, RoomRuntimeData

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
    hass: HomeAssistant,
    room: RoomRuntimeData,
    entity_id: str,
    position: float,
    *,
    source: CommandSource = CommandSource.MANUAL_MIRROR,
) -> bool:
    """Call cover.set_cover_position, waiting out STAGGER_SECONDS since the
    last command this integration sent to any of the room's covers.

    Serialized per-room via room._command_lock so the coordinator loop and
    the manual-move mirror can't race on stagger spacing / command-context
    bookkeeping. `source` controls the command-time abort gate (see
    _do_call_cover_service). Returns True if the command was issued.
    """
    async with room._command_lock:
        return await _do_call_cover_service(hass, room, entity_id, position, source=source)


def _automation_blocked(room: RoomRuntimeData) -> bool:
    """True when an AUTOMATION command must be aborted right now.

    Re-checked inside the command lock immediately before the service call
    so a coordinator decision made before a manual move (or before the
    override switch flipped on) can't overwrite the user.
    """
    if room.manual_pending:
        return True
    override = room.entities.get("override")
    return bool(override is not None and override.is_on)


async def _do_call_cover_service(
    hass: HomeAssistant,
    room: RoomRuntimeData,
    entity_id: str,
    position: float,
    *,
    source: CommandSource = CommandSource.AUTOMATION,
) -> bool:
    """Actual command work. Must be called with room._command_lock held.

    Returns False (and skips the call) when the target cover is unavailable,
    or when an AUTOMATION command is aborted because override/manual_pending
    is active -- so callers don't record a move that never physically
    happened. Non-AUTOMATION sources (user select, manual mirror,
    reconciliation) are never blocked by the gate.
    """
    if source == CommandSource.AUTOMATION and _automation_blocked(room):
        _LOGGER.debug(
            "%s: aborting AUTOMATION set_cover_position(%s=%s%%) -- override/manual hold active",
            room.name,
            entity_id,
            position,
        )
        return False

    if not _is_cover_available(hass, entity_id):
        _LOGGER.warning(
            "%s: skipping set_cover_position(%s=%s%%) -- cover unavailable",
            room.name,
            entity_id,
            position,
        )
        return False

    if room._last_cover_command_time is not None:
        wait = STAGGER_SECONDS - elapsed_seconds(room._last_cover_command_time, dt_util.utcnow())
        if wait > 0:
            await asyncio.sleep(wait)

    room._last_cover_command_time = dt_util.utcnow()
    room._command_context[entity_id] = CoverCommand(
        source=source,
        start=_current_cover_position(hass, entity_id),
        target=position,
        started_at=dt_util.utcnow(),
    )
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": entity_id, "position": position},
        blocking=True,
    )
    return True


def _is_cover_available(hass: HomeAssistant, entity_id: str) -> bool:
    """False only when the cover explicitly reports unavailable/unknown.

    A missing state (None) means the entity isn't in the state machine yet
    (very early startup); we let the service call proceed rather than block
    -- the real bug this guards against is a device that dropped off the
    Zigbee mesh and is actively reporting STATE_UNAVAILABLE.
    """
    state = hass.states.get(entity_id)
    if state is None:
        return True
    return state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _calibrated_position(config_entry: ConfigEntry, role: str, state: SemanticState) -> float:
    """Read calibration from config, falling back to DEFAULT_CALIBRATION."""
    config = {**config_entry.data, **config_entry.options}
    key = f"{role}_{state.value}_pos"
    return float(config.get(key, DEFAULT_CALIBRATION[state]))


def calibrated_position(config_entry: ConfigEntry, role: str, state: SemanticState) -> float:
    """Public accessor for a cover's calibrated position for a semantic state.

    Used by the manual-move mirror so the paired cover is driven to *its
    own* calibrated position for the semantic state the moved cover mapped
    to -- never to the other cover's raw percentage.
    """
    return _calibrated_position(config_entry, role, state)


def nearest_semantic_state(config_entry: ConfigEntry, role: str, position: float) -> SemanticState:
    """Map an actual cover position to the closest calibrated semantic state.

    Used to keep internal state synchronized with reality after a manual
    move (and on startup reconciliation) so hysteresis/dwell decisions run
    against where the covers really are, not a stale tracked state.
    """
    return min(
        SemanticState,
        key=lambda state: abs(_calibrated_position(config_entry, role, state) - position),
    )

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
    source: CommandSource = CommandSource.AUTOMATION,
) -> None:
    # Never command a cover that isn't there: an unavailable left cover
    # (Zigbee mesh down, or first refresh before the device reconnects on
    # startup) means the move can't physically happen -- recording it would
    # desync tracked state from reality. Abort without touching state.
    if not _is_cover_available(hass, room.left_cover):
        _LOGGER.warning(
            "%s: skipping move -- left cover %s unavailable",
            room.name,
            room.left_cover,
        )
        return

    async with room._command_lock:
        # Flag that we're making an automation move so the manual-move detector
        # can distinguish this from actual manual moves via state-changed events.
        room._automation_move_in_progress = True
        try:
            issued = await _do_call_cover_service(
                hass, room, room.left_cover, left_position, source=source
            )
            # Command-time gate (override/manual_pending) or an unavailable
            # cover aborted the left command: the move never happened, so
            # don't record last_move_time / current_state against it.
            if not issued:
                return

            # Record move start only once a command actually went out, so
            # dwell bookkeeping reflects real physical moves.
            room.last_move_time = dt_util.utcnow()

            if room.right_cover and right_position is not None:
                await _do_call_cover_service(
                    hass, room, room.right_cover, right_position, source=source
                )
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
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    room: RoomRuntimeData,
    target_state: SemanticState,
    *,
    source: CommandSource = CommandSource.AUTOMATION,
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
        source=source,
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
        source=CommandSource.AUTOMATION,
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

