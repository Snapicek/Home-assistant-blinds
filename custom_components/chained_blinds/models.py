"""Runtime data shared between the coordinator and this integration's own
entities for a single config entry (= one room)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.storage import Store

from .const import SemanticState

if TYPE_CHECKING:
    from .coordinator import ChainedBlindsCoordinator


@dataclass
class CoverCommand:
    """Record of the last cover.set_cover_position call for one cover.

    Used for direction-aware own-move detection: while the reported
    position stays within the [start, target] travel band (plus tolerance)
    and inside the max-travel window, movement is attributed to this
    command; movement outside the band is a manual move.
    """

    source: str
    start: float | None
    target: float
    started_at: datetime


@dataclass
class RoomRuntimeData:
    """Static wiring + mutable tracked state for one config entry."""

    entry_id: str
    name: str
    left_cover: str
    right_cover: str | None
    lux_sensor: str
    config_entry: ConfigEntry
    store: Store

    # Tracked state (rule 10: only written when a real move happens).
    current_state: SemanticState | None = None
    last_move_time: datetime | None = None
    ramp_target_state: SemanticState | None = None

    # Flag to distinguish automation-initiated moves from manual moves during
    # state-changed event processing.
    _automation_move_in_progress: bool = False

    # Latched True the instant a manual move is detected, and held for the
    # whole override period. The command-time gate in cover_control aborts
    # AUTOMATION commands while this is set, so an in-flight coordinator
    # decision can't overwrite a manual move. Cleared only when the override
    # expires, after current_state has been re-seeded from live position.
    manual_pending: bool = False

    # When the integration last issued a cover.set_cover_position call for
    # *any* cover in this room (left, right, or a mirrored move). Covers are
    # Zigbee devices sharing one mesh, so every call site funnels through
    # cover_control.async_call_cover_service, which reads/updates this to
    # keep at least STAGGER_SECONDS between any two outgoing commands.
    _last_cover_command_time: datetime | None = None

    # Per-cover entity_id -> the last command this integration issued for it
    # (source, start position, target, timestamp). Drives direction-aware
    # own-move detection in __init__.py so a physical move away from the
    # commanded target is recognised as manual even while a slow cover is
    # still settling.
    _command_context: dict[str, CoverCommand] = field(default_factory=dict)

    # Serializes all outgoing cover commands for this room. The coordinator
    # evaluate loop and the manual-move mirror in __init__.py can otherwise
    # enter cover_control concurrently and race on _last_cover_command_time,
    # _last_commanded_position, last_move_time and the single
    # _automation_move_in_progress flag -- defeating Zigbee stagger spacing
    # and mis-attributing state-changed events.
    _command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Populated by the switch/select platforms during async_setup_entry so the
    # coordinator can read the operational entities (enabled, override,
    # state_select) directly. All tuning now lives on config_entry, not here.
    entities: dict[str, Any] = field(default_factory=dict)

    coordinator: "ChainedBlindsCoordinator | None" = None

    @property
    def cover_roles(self) -> list[str]:
        roles = ["left"]
        if self.right_cover:
            roles.append("right")
        return roles

    async def async_load_persisted(self) -> None:
        """Restore current_state/last_move_time saved before a restart."""
        data = await self.store.async_load()
        if not data:
            return
        state = data.get("current_state")
        if state is not None:
            self.current_state = SemanticState(state)
        moved_at = data.get("last_move_time")
        if moved_at is not None:
            self.last_move_time = datetime.fromisoformat(moved_at)

    async def async_persist(self) -> None:
        """Save current_state/last_move_time so dwell survives a restart."""
        await self.store.async_save(
            {
                "current_state": self.current_state,
                "last_move_time": (
                    self.last_move_time.isoformat() if self.last_move_time else None
                ),
            }
        )
