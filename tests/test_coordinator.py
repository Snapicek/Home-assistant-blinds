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

from .fakes import FakeHass, FakeNumber, FakeSwitch, FakeConfigEntry, make_room

NOON = datetime(2026, 7, 21, 12, 0)
FAR_FUTURE_SUNSET = datetime(2026, 7, 21, 23, 0)


def _make_coordinator(monkeypatch, hass, room, now=NOON):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)
    coord = ChainedBlindsCoordinator(hass, room, FakeConfigEntry())
    monkeypatch.setattr(coord, "_sunset_with_offset", lambda now: FAR_FUTURE_SUNSET)
    return coord


async def test_disabled_never_moves(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "5000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(False)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False


async def test_override_active_holds(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "5000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["override"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["desired"] == result["current"]


async def test_first_evaluation_moves_immediately(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")  # bright -> SHADE
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
    hass.states.set("sensor.living_room_illuminance", "0")  # dark -> OPEN, a lightening from SHADE
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
    # bright -> SHADE, a darkening from MEDIUM
    hass.states.set("sensor.living_room_illuminance", "60000")
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


async def test_seasonal_split_changes_thresholds_by_month(monkeypatch):
    # January: winter factor lowers thresholds, so 30k lux should darken to SHADE.
    hass_winter = FakeHass()
    hass_winter.states.set("sensor.living_room_illuminance", "30000")
    room_winter = make_room()
    room_winter.current_state = SemanticState.MEDIUM
    room_winter.entities["enabled"] = FakeSwitch(True)
    room_winter.entities["seasonal_split"] = FakeSwitch(True)
    room_winter.entities["summer_lux_factor"] = FakeNumber(150)
    room_winter.entities["winter_lux_factor"] = FakeNumber(50)

    winter_now = datetime(2026, 1, 21, 12, 0)
    coord_winter = _make_coordinator(monkeypatch, hass_winter, room_winter, now=winter_now)
    winter_result = await coord_winter._async_update_data()

    assert winter_result["desired"] == SemanticState.SHADE
    assert winter_result["moved"] is True

    # July: summer factor raises thresholds, so the same 30k lux should hold MEDIUM.
    hass_summer = FakeHass()
    hass_summer.states.set("sensor.living_room_illuminance", "30000")
    room_summer = make_room()
    room_summer.current_state = SemanticState.MEDIUM
    room_summer.entities["enabled"] = FakeSwitch(True)
    room_summer.entities["seasonal_split"] = FakeSwitch(True)
    room_summer.entities["summer_lux_factor"] = FakeNumber(150)
    room_summer.entities["winter_lux_factor"] = FakeNumber(50)

    summer_now = datetime(2026, 7, 21, 12, 0)
    coord_summer = _make_coordinator(monkeypatch, hass_summer, room_summer, now=summer_now)
    summer_result = await coord_summer._async_update_data()

    assert summer_result["desired"] == SemanticState.MEDIUM
    assert summer_result["moved"] is False


async def test_seasonal_split_off_does_not_scale_thresholds(monkeypatch):
    hass = FakeHass()
    # above default lux_high 35k → SHADE
    hass.states.set("sensor.living_room_illuminance", "40000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["seasonal_split"] = FakeSwitch(False)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE
    assert result["moved"] is True


async def test_sunrise_open_off_uses_fixed_open_time(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["sunrise_open"] = FakeSwitch(False)

    before_fixed_open = datetime(2026, 7, 21, 6, 30)  # 06:30 < default 07:00
    coord = _make_coordinator(monkeypatch, hass, room, now=before_fixed_open)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.CLOSED


async def test_sunrise_open_after_sunrise_allows_lux_evaluation(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["sunrise_open"] = FakeSwitch(True)

    after_sunrise = datetime(2026, 7, 21, 8, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=after_sunrise)
    monkeypatch.setattr(coord, "_sunrise_with_offset", lambda now: datetime(2026, 7, 21, 7, 0))

    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE
    assert result["moved"] is True


async def test_lux_sensor_unavailable_state_treated_as_zero(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "unavailable")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["lux"] == 0.0
    assert result["desired"] == SemanticState.OPEN


async def test_missing_lux_sensor_defaults_to_open(monkeypatch):
    hass = FakeHass()  # no lux state registered at all
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["lux"] == 0.0
    assert result["desired"] == SemanticState.OPEN



async def test_evaluation_reports_lux_value_in_result(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "18000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["lux"] == 18000.0


# ── Seasonal factor percentage conversion ────────────────────────────────────

async def test_seasonal_factor_percent_converts_correctly(monkeypatch):
    """150 % entity value should become a ×1.5 multiplier on the thresholds."""
    hass = FakeHass()
    # default lux_high = 35000; with summer factor 150 % → 35000 × 1.5 = 52500.
    # lux of 40000 is above 35000 (would normally → SHADE) but below 52500, so
    # with the scaling applied it should stay OPEN (current).
    hass.states.set("sensor.living_room_illuminance", "40000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["seasonal_split"] = FakeSwitch(True)
    room.entities["summer_lux_factor"] = FakeNumber(150)  # 150 % == ×1.5
    room.entities["winter_lux_factor"] = FakeNumber(100)

    summer_now = datetime(2026, 7, 21, 12, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=summer_now)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.OPEN


async def test_winter_factor_percent_lowers_thresholds(monkeypatch):
    """50 % entity value should become a ×0.5 multiplier on the thresholds."""
    hass = FakeHass()
    # default lux_high = 35000; with winter factor 50 % → 35000 × 0.5 = 17500.
    # lux of 20000 is below 35000 (would normally → MEDIUM) but above 17500, so
    # with scaling it should go to SHADE.
    hass.states.set("sensor.living_room_illuminance", "20000")
    room = make_room()
    room.current_state = SemanticState.OPEN
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["seasonal_split"] = FakeSwitch(True)
    room.entities["summer_lux_factor"] = FakeNumber(100)
    room.entities["winter_lux_factor"] = FakeNumber(50)  # 50 % == ×0.5

    winter_now = datetime(2026, 1, 21, 12, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=winter_now)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE


# ── Sunset/sunrise offset arithmetic ─────────────────────────────────────────

async def test_positive_sunset_offset_delays_night_start(monkeypatch):
    """A +60 min sunset offset should keep the blinds daytime-active 1 h past raw sunset."""
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "0")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["sunset_offset_minutes"] = FakeNumber(60)

    # Raw sunset is at 20:00; with +60 min offset the night boundary moves to 21:00.
    # At 20:30 the blinds should still be in daytime mode (desired = OPEN at 0 lux).
    at_2030 = datetime(2026, 7, 21, 20, 30)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_2030)
    raw_sunset = datetime(2026, 7, 21, 20, 0)
    monkeypatch.setattr(
        coord, "_sunset_with_offset",
        lambda now: raw_sunset + __import__("datetime").timedelta(minutes=60),
    )
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.OPEN


async def test_negative_sunset_offset_brings_night_start_forward(monkeypatch):
    """A −60 min sunset offset should trigger night/closed 1 h before raw sunset."""
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "5000")
    room = make_room()
    room.entities["enabled"] = FakeSwitch(True)
    room.entities["sunset_offset_minutes"] = FakeNumber(-60)

    # Raw sunset 20:00; offset makes effective sunset 19:00.
    # At 19:30 desired state should be CLOSED (night).
    at_1930 = datetime(2026, 7, 21, 19, 30)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_1930)
    raw_sunset = datetime(2026, 7, 21, 20, 0)
    monkeypatch.setattr(
        coord, "_sunset_with_offset",
        lambda now: raw_sunset + __import__("datetime").timedelta(minutes=-60),
    )
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.CLOSED

