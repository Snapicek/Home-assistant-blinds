"""Tests for cover_control.async_move_to_state against a fake hass.

Covers the hard invariants from the original rules: only
cover.set_cover_position is ever called (never open_cover/close_cover), the
right cover is staggered after the left one, calibrated positions come from
the room's number entities (falling back to defaults), and current_state /
last_move_time / the state select are updated only here.
"""
from custom_components.chained_blinds import cover_control
from custom_components.chained_blinds.const import SemanticState

from .fakes import FakeHass, FakeNumber, FakeSelect, make_room


async def test_moves_left_cover_only_using_calibrated_position():
    hass = FakeHass()
    room = make_room()
    room.entities["left_shade_pos"] = FakeNumber(30.0)

    await cover_control.async_move_to_state(hass, room, SemanticState.SHADE)

    assert hass.services.calls == [
        ("cover", "set_cover_position", {"entity_id": "cover.left", "position": 30.0})
    ]


async def test_falls_back_to_default_calibration_when_uncalibrated():
    hass = FakeHass()
    room = make_room()

    await cover_control.async_move_to_state(hass, room, SemanticState.OPEN)

    assert hass.services.calls[0][2]["position"] == 75.0  # DEFAULT_CALIBRATION[OPEN]


async def test_staggers_right_cover_after_left(monkeypatch):
    monkeypatch.setattr(cover_control, "STAGGER_SECONDS", 0)
    hass = FakeHass()
    room = make_room(right_cover="cover.right")
    room.entities["left_closed_pos"] = FakeNumber(0.0)
    room.entities["right_closed_pos"] = FakeNumber(2.0)

    await cover_control.async_move_to_state(hass, room, SemanticState.CLOSED)

    assert [c[2]["entity_id"] for c in hass.services.calls] == ["cover.left", "cover.right"]
    assert hass.services.calls[1][2]["position"] == 2.0


async def test_never_calls_open_or_close_cover():
    hass = FakeHass()
    room = make_room(right_cover="cover.right")

    for state in SemanticState:
        await cover_control.async_move_to_state(hass, room, state)

    services_called = {call[1] for call in hass.services.calls}
    assert services_called == {"set_cover_position"}


async def test_updates_current_state_last_move_time_and_persists():
    hass = FakeHass()
    room = make_room()

    await cover_control.async_move_to_state(hass, room, SemanticState.MEDIUM)

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

    await cover_control.async_move_to_state(hass, room, SemanticState.SHADE)

    assert select.updates == [SemanticState.SHADE]
