"""Runtime data shared between the coordinator and this integration's own
entities for a single config entry (= one room)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.storage import Store

from .const import SemanticState

if TYPE_CHECKING:
    from .coordinator import ChainedBlindsCoordinator


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

    # When the integration last issued a cover.set_cover_position call for
    # *any* cover in this room (left, right, or a mirrored move). Covers are
    # Zigbee devices sharing one mesh, so every call site funnels through
    # cover_control.async_call_cover_service, which reads/updates this to
    # keep at least STAGGER_SECONDS between any two outgoing commands.
    _last_cover_command_time: datetime | None = None

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
