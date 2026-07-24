"""Tests for cover_control.async_move_to_state against a fake hass.

Covers the hard invariants from the original rules: only
cover.set_cover_position is ever called (never open_cover/close_cover), the
right cover is staggered after the left one, calibrated positions come from
the config entry (falling back to defaults), and current_state /
last_move_time / the state select are updated only here.
"""
from datetime import datetime, timedelta, timezone

from custom_components.chained_blinds import cover_control
from custom_components.chained_blinds.const import SemanticState

from .fakes import FakeHass, FakeSelect, make_room


async def test_moves_left_cover_only_using_calibrated_position():
    hass = FakeHass()
    room = make_room(config_data={"left_shade_pos": 30.0})

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.SHADE)

    assert hass.services.calls == [
        (
            "cover",
            "set_cover_position",
            {"entity_id": "cover.living_room_left_blind", "position": 30.0},
        )
    ]


async def test_falls_back_to_default_calibration_when_uncalibrated():
    hass = FakeHass()
    # Config without any left_open_pos key -> should fall back to DEFAULT_CALIBRATION.
    room = make_room()
    # Remove the seeded calibration so the fallback path is exercised.
    room.config_entry.data.pop("left_open_pos", None)

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.OPEN)

    assert hass.services.calls[0][2]["position"] == 75.0  # DEFAULT_CALIBRATION[OPEN]


async def test_staggers_right_cover_after_left(monkeypatch):
    monkeypatch.setattr(cover_control, "STAGGER_SECONDS", 0)
    hass = FakeHass()
    room = make_room(
        config_data={"left_closed_pos": 0.0, "right_closed_pos": 2.0},
        right_cover="cover.living_room_right_blind",
    )

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.CLOSED)

    called_entity_ids = [c[2]["entity_id"] for c in hass.services.calls]
    assert called_entity_ids == ["cover.living_room_left_blind", "cover.living_room_right_blind"]
    assert hass.services.calls[1][2]["position"] == 2.0


async def test_never_calls_open_or_close_cover():
    hass = FakeHass()
    room = make_room(right_cover="cover.living_room_right_blind")

    for state in SemanticState:
        await cover_control.async_move_to_state(hass, room.config_entry, room, state)

    services_called = {call[1] for call in hass.services.calls}
    assert services_called == {"set_cover_position"}


async def test_updates_current_state_last_move_time_and_persists():
    hass = FakeHass()
    room = make_room()

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.MEDIUM)

    assert room.current_state == SemanticState.MEDIUM
    assert room.last_move_time is not None
    assert room.store.saved == {
        "current_state": SemanticState.MEDIUM,
        "last_move_time": room.last_move_time.isoformat(),
    }


async def test_notifies_state_select():
    hass = FakeHass()
    room = make_room()
    select = FakeSelect()
    room.entities["state_select"] = select

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.SHADE)

    assert select.updates == [SemanticState.SHADE]


async def test_ramp_move_steps_toward_target_without_updating_semantic_state():
    hass = FakeHass()
    room = make_room()
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 75},
    )

    reached = await cover_control.async_move_towards_state(
        hass,
        room.config_entry,
        room,
        SemanticState.SHADE,
        step_percent=20,
    )

    assert reached is False
    assert room.current_state is None
    assert hass.services.calls[-1][2]["position"] == 55.0


async def test_call_cover_service_waits_stagger_seconds_between_commands(monkeypatch):
    """Zigbee covers share a mesh: any two commands this integration issues
    for a room, regardless of call site, must be at least STAGGER_SECONDS
    apart -- not just the left/right pair inside a single move."""
    hass = FakeHass()
    room = make_room()

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(cover_control.dt_util, "utcnow", lambda: now)

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cover_control.asyncio, "sleep", _fake_sleep)

    await cover_control.async_call_cover_service(hass, room, "cover.a", 10)
    assert sleep_calls == []  # nothing to wait for on the very first command

    await cover_control.async_call_cover_service(hass, room, "cover.b", 20)
    assert sleep_calls == [cover_control.STAGGER_SECONDS]

    called_entity_ids = [c[2]["entity_id"] for c in hass.services.calls]
    assert called_entity_ids == ["cover.a", "cover.b"]


async def test_call_cover_service_records_commanded_position(monkeypatch):
    """The manual-move detector in __init__.py relies on
    room._last_commanded_position to recognize a cover settling near its
    own commanded target, so every call must record it here."""
    hass = FakeHass()
    room = make_room()

    await cover_control.async_call_cover_service(hass, room, "cover.a", 42)

    assert room._last_commanded_position["cover.a"] == 42


async def test_call_cover_service_skips_wait_once_interval_has_elapsed(monkeypatch):
    hass = FakeHass()
    room = make_room()

    clock = {"now": datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(cover_control.dt_util, "utcnow", lambda: clock["now"])

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cover_control.asyncio, "sleep", _fake_sleep)

    await cover_control.async_call_cover_service(hass, room, "cover.a", 10)
    clock["now"] = clock["now"] + timedelta(seconds=cover_control.STAGGER_SECONDS + 1)
    await cover_control.async_call_cover_service(hass, room, "cover.b", 20)

    assert sleep_calls == []


async def test_ramp_move_marks_state_when_target_reached():
    hass = FakeHass()
    room = make_room()
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 30},
    )

    reached = await cover_control.async_move_towards_state(
        hass,
        room.config_entry,
        room,
        SemanticState.SHADE,
        step_percent=20,
    )

    assert reached is True
    assert room.current_state == SemanticState.SHADE
    assert hass.services.calls[-1][2]["position"] == 25.0


async def test_move_skipped_when_left_cover_unavailable():
    """A cover actively reporting unavailable (dropped off the Zigbee mesh)
    must not be commanded, and tracked state must not be mutated to record a
    move that never physically happened."""
    hass = FakeHass()
    room = make_room()
    hass.states.set("cover.living_room_left_blind", "unavailable")

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.SHADE)

    assert hass.services.calls == []
    assert room.current_state is None
    assert room.last_move_time is None
    assert room.store.saved is None


async def test_call_cover_service_skips_unavailable_cover():
    hass = FakeHass()
    room = make_room()
    hass.states.set("cover.a", "unknown")

    await cover_control.async_call_cover_service(hass, room, "cover.a", 42)

    assert hass.services.calls == []
    assert "cover.a" not in room._last_commanded_position


async def test_nearest_semantic_state_maps_position_to_closest_calibration():
    room = make_room()  # default calibration: open75 medium50 shade25 closed0

    entry = room.config_entry
    assert cover_control.nearest_semantic_state(entry, "left", 74) == SemanticState.OPEN
    assert cover_control.nearest_semantic_state(entry, "left", 48) == SemanticState.MEDIUM
    assert cover_control.nearest_semantic_state(entry, "left", 27) == SemanticState.SHADE
    assert cover_control.nearest_semantic_state(entry, "left", 3) == SemanticState.CLOSED


def test_stagger_is_at_least_one_second():
    """Zigbee mesh safety: the enforced gap between any two commands must be
    at least 1 second."""
    assert cover_control.STAGGER_SECONDS >= 1


async def test_full_move_waits_one_second_between_left_and_right(monkeypatch):
    """Within a single left+right move, the right cover command must be
    staggered by at least STAGGER_SECONDS after the left one."""
    hass = FakeHass()
    room = make_room(
        config_data={"left_closed_pos": 0.0, "right_closed_pos": 2.0},
        right_cover="cover.living_room_right_blind",
    )

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(cover_control.dt_util, "utcnow", lambda: now)

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cover_control.asyncio, "sleep", _fake_sleep)

    await cover_control.async_move_to_state(hass, room.config_entry, room, SemanticState.CLOSED)

    # left issued first (no prior command -> no wait), then the 0.5s
    # post-move settle sleep, then right waits STAGGER_SECONDS.
    assert cover_control.STAGGER_SECONDS in sleep_calls
    called_entity_ids = [c[2]["entity_id"] for c in hass.services.calls]
    assert called_entity_ids == ["cover.living_room_left_blind", "cover.living_room_right_blind"]


async def test_manual_mirror_path_respects_global_stagger(monkeypatch):
    """A mirror command issued right after a prior integration command (e.g.
    an automation move that just ran, or the other cover in a manual sync)
    must still wait out the Zigbee gap -- the gate is keyed off the last
    command to *any* of the room's covers, regardless of call site."""
    hass = FakeHass()
    room = make_room(right_cover="cover.living_room_right_blind")

    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(cover_control.dt_util, "utcnow", lambda: now)

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cover_control.asyncio, "sleep", _fake_sleep)

    # A prior command just went out to the left cover.
    await cover_control.async_call_cover_service(hass, room, room.left_cover, 40)
    assert sleep_calls == []

    # The mirror onto the right cover must wait STAGGER_SECONDS (frozen clock
    # => zero elapsed => full wait).
    await cover_control.async_call_cover_service(hass, room, room.right_cover, 40)
    assert sleep_calls == [cover_control.STAGGER_SECONDS]


