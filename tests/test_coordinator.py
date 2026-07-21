"""Tests for ChainedBlindsCoordinator._async_update_data against fake hass.

Exercises the full glue: reading live entity values, calling the resolver,
applying (or not) a move via cover_control. Sunset/location-dependent
behaviour is monkeypatched to a fixed value since it's already covered by
test_resolver.py's is_night tests and needs a real HA instance to verify for
real (see README's manual-verification checklist).
"""
from datetime import datetime, timedelta

from custom_components.chained_blinds import coordinator as coordinator_module
from custom_components.chained_blinds.const import SemanticState
from custom_components.chained_blinds.coordinator import ChainedBlindsCoordinator

from .fakes import FakeHass, FakeNumber, FakeSwitch, make_room

NOON = datetime(2026, 7, 21, 12, 0)
FAR_FUTURE_SUNSET = datetime(2026, 7, 21, 23, 0)


def _make_coordinator(monkeypatch, hass, room, now=NOON):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)
    coord = ChainedBlindsCoordinator(hass, room)
    monkeypatch.setattr(coord, "_sunset_with_offset", lambda now: FAR_FUTURE_SUNSET)
    return coord


async def test_disabled_never_moves(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.lux", "5000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(False)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False


async def test_override_active_holds(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.lux", "5000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["override"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["desired"] == result["current"]


async def test_first_evaluation_moves_immediately(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.lux", "5000")  # bright -> SHADE
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["moved"] is True
    assert result["desired"] == SemanticState.SHADE
    assert hass.services.calls[0][1] == "set_cover_position"
    assert room.current_state == SemanticState.SHADE


async def test_dwell_lock_blocks_a_too_soon_lightening_move(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.lux", "0")  # dark -> OPEN, a lightening from SHADE
    room = make_room()
    room.current_state = SemanticState.SHADE
    room.last_move_time = NOON - timedelta(minutes=5)
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["reopen_dwell_minutes"] = FakeNumber(30)
    room.entities["dwell_minutes"] = FakeNumber(10)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False
    assert room.current_state == SemanticState.SHADE


async def test_darkening_move_applies_after_short_dwell(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.lux", "5000")  # bright -> SHADE, a darkening from MEDIUM
    room = make_room()
    room.current_state = SemanticState.MEDIUM
    room.last_move_time = NOON - timedelta(minutes=15)
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["reopen_dwell_minutes"] = FakeNumber(30)
    room.entities["dwell_minutes"] = FakeNumber(10)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["moved"] is True
    assert room.current_state == SemanticState.SHADE
