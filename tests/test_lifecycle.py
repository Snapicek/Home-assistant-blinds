"""Lifecycle-focused tests for setup/unload wiring and override restoration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import custom_components.chained_blinds as integration
from custom_components.chained_blinds.const import (
    CONF_LEFT_COVER,
    CONF_LUX_SENSOR,
    CONF_RIGHT_COVER,
    DOMAIN,
    SemanticState,
    WORKDAY_SENSOR_ENTITY_ID,
)
from custom_components.chained_blinds.switch import OverrideSwitch, _RoomSwitchBase

from .fakes import FakeHass, FakeSelect, FakeStore, make_room


class _TypedFakeStore(FakeStore):
    """Mimic Home Assistant's generic Store[T] constructor shape in tests."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    def __class_getitem__(cls, _item):
        return cls


@dataclass
class _FakeEntry:
    entry_id: str = "entry_1"
    title: str = "Bedroom"
    data: dict | None = None
    options: dict | None = None

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {
                CONF_LEFT_COVER: "cover.bedroom_left",
                CONF_LUX_SENSOR: "sensor.bedroom_lux",
            }
        if self.options is None:
            self.options = {}
        self.unload_callbacks: list = []
        self.update_listener = None

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)

    def add_update_listener(self, listener):
        self.update_listener = listener
        return lambda: None


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.forward_calls: list[tuple[str, list]] = []
        self.unload_calls: list[str] = []
        self.reload_calls: list[str] = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forward_calls.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unload_calls.append(entry.entry_id)
        return True

    async def async_reload(self, entry_id):
        self.reload_calls.append(entry_id)


class _FakeCoordinator:
    def __init__(self, hass, room, config_entry) -> None:
        self.hass = hass
        self.room = room
        self.config_entry = config_entry
        self.refresh_calls = 0
        self.first_refresh_calls = 0

    async def async_request_refresh(self):
        self.refresh_calls += 1

    async def async_config_entry_first_refresh(self):
        self.first_refresh_calls += 1


class _FakeOverride:
    def __init__(self) -> None:
        self.is_on = False
        self.turn_on_calls = 0

    async def async_turn_on(self, **kwargs):
        self.is_on = True
        self.turn_on_calls += 1


def _cover_event(
    entity_id: str,
    position: int,
    *,
    old_state: str | None = "open",
    new_state: str | None = "open",
) -> SimpleNamespace:
    """Build a cover state_changed event. Defaults to a real
    known-state -> known-state transition (a genuine move); pass
    old_state=None / "unavailable" / "unknown" to simulate the
    first-report-after-(re)connect case the manual-move detector must
    ignore."""
    return SimpleNamespace(
        data={
            "entity_id": entity_id,
            "old_state": SimpleNamespace(state=old_state) if old_state is not None else None,
            "new_state": (
                SimpleNamespace(state=new_state, attributes={"current_position": position})
                if new_state is not None
                else None
            ),
        }
    )


async def test_async_setup_entry_manual_move_activates_override(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)

    assert ok is True
    assert len(hass.config_entries.forward_calls) == 1
    assert len(listeners) == 2  # lux listener + cover listener

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override

    # Fire the cover-change listener manually and ensure override is activated.
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)
    event = _cover_event(room.left_cover, 50)
    await cover_listener(event)

    assert override.turn_on_calls == 1


async def test_async_setup_entry_wires_listeners_and_refreshes_on_lux(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry(
        data={
            CONF_LEFT_COVER: "cover.bedroom_left",
            CONF_RIGHT_COVER: "cover.bedroom_right",
            CONF_LUX_SENSOR: "sensor.bedroom_lux",
        }
    )

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)

    assert ok is True
    room = hass.data[DOMAIN][entry.entry_id]
    assert room.coordinator is not None
    assert room.coordinator.first_refresh_calls == 1
    assert len(listeners) == 2

    lux_entities, lux_cb = next((ents, cb) for ents, cb in listeners if room.lux_sensor in ents)
    cover_entities, _ = next((ents, cb) for ents, cb in listeners if room.left_cover in ents)

    assert lux_entities == [room.lux_sensor, WORKDAY_SENSOR_ENTITY_ID]
    assert cover_entities == [room.left_cover, room.right_cover]

    await lux_cb(event={})
    assert room.coordinator.refresh_calls == 1


async def test_manual_move_skipped_when_override_already_on(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    # When override is already on, manual move should be skipped
    override.is_on = True
    event = _cover_event(room.left_cover, 50)
    await cover_listener(event)
    assert override.turn_on_calls == 0

    # When override is off, manual move should activate it
    override.is_on = False
    await cover_listener(event)
    assert override.turn_on_calls == 1


async def test_manual_move_syncs_current_state_and_select(monkeypatch):
    """A manual cover move must update tracked current_state (nearest
    calibrated state) and reflect it on the select, so the resolver doesn't
    later run against a stale position when the override expires."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    room.entities["override"] = _FakeOverride()
    select = FakeSelect()
    room.entities["state_select"] = select
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    # Default calibration: open75 medium50 shade25 closed0. 26% -> SHADE.
    await cover_listener(_cover_event(room.left_cover, 26))

    assert room.current_state == SemanticState.SHADE
    assert select.updates == [SemanticState.SHADE]
    assert room.store.saved is not None


async def test_manual_move_mirrors_position_to_paired_cover(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry(
        data={
            CONF_LEFT_COVER: "cover.bedroom_left",
            CONF_RIGHT_COVER: "cover.bedroom_right",
            CONF_LUX_SENSOR: "sensor.bedroom_lux",
        }
    )

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    # Simulate a manual move of the left cover to 42%.
    event = _cover_event(room.left_cover, 42)
    await cover_listener(event)

    assert override.turn_on_calls == 1
    assert hass.services.calls == [
        ("cover", "set_cover_position", {"entity_id": room.right_cover, "position": 42}),
    ]
    # The mirror call must go through the same Zigbee-spacing gate as every
    # other cover command, not bypass it via a raw service call.
    assert room._last_cover_command_time is not None


async def test_manual_move_of_right_cover_mirrors_onto_left(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry(
        data={
            CONF_LEFT_COVER: "cover.bedroom_left",
            CONF_RIGHT_COVER: "cover.bedroom_right",
            CONF_LUX_SENSOR: "sensor.bedroom_lux",
        }
    )

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    event = _cover_event(room.right_cover, 17)
    await cover_listener(event)

    assert override.turn_on_calls == 1
    assert hass.services.calls == [
        ("cover", "set_cover_position", {"entity_id": room.left_cover, "position": 17}),
    ]


async def test_cover_reconnecting_after_restart_does_not_activate_override(monkeypatch):
    """A cover's first state report after HA (re)starts -- transitioning
    from unavailable/unknown to its real position as the Zigbee network
    reconnects -- must not be mistaken for a manual move. Without this
    guard, every restart paused the automation the instant each cover's
    real state arrived."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    # No prior state at all (entity just registered on this restart).
    await cover_listener(_cover_event(room.left_cover, 50, old_state=None))
    assert override.turn_on_calls == 0

    # Reconnecting from "unavailable" to a real position.
    await cover_listener(_cover_event(room.left_cover, 50, old_state="unavailable"))
    assert override.turn_on_calls == 0

    # Reconnecting from "unknown" to a real position.
    await cover_listener(_cover_event(room.left_cover, 50, old_state="unknown"))
    assert override.turn_on_calls == 0

    # The cover itself dropping offline is not a manual move either.
    await cover_listener(_cover_event(room.left_cover, 50, new_state="unavailable"))
    assert override.turn_on_calls == 0

    # Sanity check: a real known-state -> known-state transition still counts.
    await cover_listener(_cover_event(room.left_cover, 50))
    assert override.turn_on_calls == 1


async def test_late_settling_event_within_grace_period_does_not_activate_override(monkeypatch):
    """A state-changed event arriving after `_automation_move_in_progress`
    has cleared, but still inside the 30s grace window since the move
    started, must be attributed to the automation's own (slow) cover --
    not misread as a manual move that pauses the integration."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)

    # The automation issued a move 10s ago and has already cleared its
    # in-progress flag, but the physical cover is still settling.
    room.last_move_time = now - timedelta(seconds=10)
    room._automation_move_in_progress = False

    event = _cover_event(room.left_cover, 50)
    await cover_listener(event)

    assert override.turn_on_calls == 0


async def test_move_after_grace_period_still_activates_override(monkeypatch):
    """Once the grace window has elapsed, a state change is a real manual
    move again and must still activate the override."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)

    room.last_move_time = now - timedelta(seconds=31)
    room._automation_move_in_progress = False

    event = _cover_event(room.left_cover, 50)
    await cover_listener(event)

    assert override.turn_on_calls == 1


async def test_settling_near_commanded_position_ignored_past_grace_window(monkeypatch):
    """Chain-driven blinds rarely land exactly on the commanded percentage
    and can keep wobbling between adjacent values for minutes. A position
    close to what we last commanded must not activate override no matter
    how long the wobble continues -- unlike the flag/grace-window checks,
    this one isn't time-limited (until _SETTLING_MAX_SECONDS)."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)

    # We commanded 50 several minutes ago -- well past the 30s grace
    # window -- and the flag has long since cleared.
    room.last_move_time = now - timedelta(minutes=3)
    room._automation_move_in_progress = False
    room._last_commanded_position[room.left_cover] = 50

    # The blind is still wobbling near 50 (e.g. 52, then 48).
    await cover_listener(_cover_event(room.left_cover, 52))
    assert override.turn_on_calls == 0
    await cover_listener(_cover_event(room.left_cover, 48))
    assert override.turn_on_calls == 0


async def test_settling_tolerance_does_not_mask_a_real_manual_move(monkeypatch):
    """A position far outside the commanded tolerance is a real manual
    move and must still activate override, even with a recent commanded
    position on record for that cover."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)

    room.last_move_time = now - timedelta(minutes=3)
    room._automation_move_in_progress = False
    room._last_commanded_position[room.left_cover] = 50

    # Someone pulled it most of the way open -- nowhere near the 5%
    # tolerance around the commanded 50.
    await cover_listener(_cover_event(room.left_cover, 90))
    assert override.turn_on_calls == 1


async def test_settling_tolerance_expires_for_a_stale_commanded_position(monkeypatch):
    """A commanded position from long ago (beyond _SETTLING_MAX_SECONDS)
    must not permanently immunize that percentage against manual-move
    detection."""
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()

    listeners: list[tuple[list[str], object]] = []

    def _fake_track_state_change_event(_hass, entities, callback):
        listeners.append((list(entities), callback))
        return lambda: None

    monkeypatch.setattr(integration, "Store", _TypedFakeStore)
    monkeypatch.setattr(integration, "ChainedBlindsCoordinator", _FakeCoordinator)
    monkeypatch.setattr(integration, "async_track_state_change_event", _fake_track_state_change_event)

    ok = await integration.async_setup_entry(hass, entry)
    assert ok is True

    room = hass.data[DOMAIN][entry.entry_id]
    override = _FakeOverride()
    room.entities["override"] = override
    cover_listener = next(cb for ents, cb in listeners if room.left_cover in ents)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)

    room.last_move_time = now - timedelta(seconds=601)
    room._automation_move_in_progress = False
    room._last_commanded_position[room.left_cover] = 50

    await cover_listener(_cover_event(room.left_cover, 52))
    assert override.turn_on_calls == 1


async def test_async_unload_entry_drops_room_data_when_platforms_unload(monkeypatch):
    hass = FakeHass()
    hass.config_entries = _FakeConfigEntries()
    entry = _FakeEntry()
    hass.data[DOMAIN] = {entry.entry_id: make_room(entry_id=entry.entry_id)}

    ok = await integration.async_unload_entry(hass, entry)

    assert ok is True
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_override_switch_restores_future_deadline_and_schedules_remaining(monkeypatch):
    hass = FakeHass()
    room = make_room()
    entity = OverrideSwitch(hass, room, room.config_entry)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    until = now + timedelta(minutes=2)

    async def _fake_base_async_added_to_hass(self):
        self._room.entities[self._key] = self
        self._attr_is_on = True

    class _FakeLastState:
        state = "on"
        attributes = {"override_until": until.isoformat()}

    async def _fake_async_get_last_state():
        return _FakeLastState()

    scheduled: dict[str, float] = {}

    def _fake_schedule_expiry(*, seconds=None):
        scheduled["seconds"] = seconds

    monkeypatch.setattr(_RoomSwitchBase, "async_added_to_hass", _fake_base_async_added_to_hass)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)
    entity.async_get_last_state = _fake_async_get_last_state  # type: ignore[assignment]
    monkeypatch.setattr(entity, "_schedule_expiry", _fake_schedule_expiry)

    await entity.async_added_to_hass()

    assert entity.extra_state_attributes["override_until"] == until.isoformat()
    assert abs(scheduled["seconds"] - 120.0) < 0.001


async def test_override_switch_turns_off_when_restored_deadline_is_expired(monkeypatch):
    hass = FakeHass()
    room = make_room()
    entity = OverrideSwitch(hass, room, room.config_entry)

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    expired_until = now - timedelta(seconds=1)

    async def _fake_base_async_added_to_hass(self):
        self._room.entities[self._key] = self
        self._attr_is_on = True

    class _FakeLastState:
        state = "on"
        attributes = {"override_until": expired_until.isoformat()}

    async def _fake_async_get_last_state():
        return _FakeLastState()

    schedule_calls = {"count": 0}

    def _fake_schedule_expiry(*, seconds=None):
        schedule_calls["count"] += 1

    monkeypatch.setattr(_RoomSwitchBase, "async_added_to_hass", _fake_base_async_added_to_hass)
    monkeypatch.setattr(integration.dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(entity, "_schedule_expiry", _fake_schedule_expiry)
    entity.async_get_last_state = _fake_async_get_last_state  # type: ignore[assignment]
    entity.async_write_ha_state = lambda: None

    await entity.async_added_to_hass()

    assert entity.is_on is False
    assert entity.extra_state_attributes == {}
    assert schedule_calls["count"] == 0


