"""Tests for ChainedBlindsCoordinator._async_update_data against fake hass.

Exercises the full glue: reading live entity values, calling the resolver,
applying (or not) a move via cover_control. Sunset/location-dependent
behaviour is monkeypatched to a fixed value since it's already covered by
test_resolver.py's is_night tests and needs a real HA instance to verify for
real (see README's manual-verification checklist).
"""
from datetime import datetime, timedelta

from custom_components.chained_blinds import coordinator as coordinator_module
from custom_components.chained_blinds import cover_control as cover_control_module
from custom_components.chained_blinds.const import SemanticState
from custom_components.chained_blinds.coordinator import ChainedBlindsCoordinator

from .fakes import FakeHass, FakeSwitch, make_room

NOON = datetime(2026, 7, 21, 12, 0)
FAR_FUTURE_SUNSET = datetime(2026, 7, 21, 23, 0)


def _make_coordinator(monkeypatch, hass, room, now=NOON):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: now)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: now)
    monkeypatch.setattr(cover_control_module.dt_util, "utcnow", lambda: now)
    # dt_util.utcnow() is frozen above, so the Zigbee command-spacing gate in
    # async_call_cover_service would otherwise see zero elapsed time between
    # calls and fall back to a real asyncio.sleep(STAGGER_SECONDS) -- fine
    # for production, just needless wall-clock delay in these unit tests.
    monkeypatch.setattr(cover_control_module, "STAGGER_SECONDS", 0)
    # Use room.config_entry (populated by make_room with test tuning data),
    # not a fresh empty FakeConfigEntry -- otherwise config-driven values
    # (thresholds, dwell, seasonal factors, etc.) silently fall back to
    # hardcoded defaults regardless of what the test configured.
    coord = ChainedBlindsCoordinator(hass, room, room.config_entry)
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
    from custom_components.chained_blinds.const import CONF_REOPEN_DWELL_MINUTES, CONF_DWELL_MINUTES

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "0")  # dark -> OPEN, a lightening from SHADE
    room = make_room(config_data={
        CONF_REOPEN_DWELL_MINUTES: 30,
        CONF_DWELL_MINUTES: 10,
    })
    room.current_state = SemanticState.SHADE
    room.last_move_time = NOON - timedelta(minutes=5)
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False
    assert room.current_state == SemanticState.SHADE


async def test_darkening_move_applies_after_short_dwell(monkeypatch):
    from custom_components.chained_blinds.const import CONF_REOPEN_DWELL_MINUTES, CONF_DWELL_MINUTES

    hass = FakeHass()
    # bright -> SHADE, a darkening from MEDIUM
    hass.states.set("sensor.living_room_illuminance", "60000")
    room = make_room(config_data={
        CONF_REOPEN_DWELL_MINUTES: 30,
        CONF_DWELL_MINUTES: 10,
    })
    room.current_state = SemanticState.MEDIUM
    room.last_move_time = NOON - timedelta(minutes=15)
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["moved"] is True
    assert room.current_state == SemanticState.SHADE


async def test_seasonal_split_changes_thresholds_by_month(monkeypatch):
    from custom_components.chained_blinds.const import (
        CONF_SEASONAL_SPLIT,
        CONF_SUMMER_LUX_FACTOR,
        CONF_WINTER_LUX_FACTOR,
    )

    # January: winter factor lowers thresholds, so 30k lux should darken to SHADE.
    hass_winter = FakeHass()
    hass_winter.states.set("sensor.living_room_illuminance", "30000")
    room_winter = make_room(config_data={
        CONF_SEASONAL_SPLIT: True,
        CONF_SUMMER_LUX_FACTOR: 150,
        CONF_WINTER_LUX_FACTOR: 50,
    })
    room_winter.current_state = SemanticState.MEDIUM
    room_winter.entities["enabled"] = FakeSwitch(True)

    winter_now = datetime(2026, 1, 21, 12, 0)
    coord_winter = _make_coordinator(monkeypatch, hass_winter, room_winter, now=winter_now)
    winter_result = await coord_winter._async_update_data()

    assert winter_result["desired"] == SemanticState.SHADE
    assert winter_result["moved"] is True

    # July: summer factor raises thresholds, so the same 30k lux should hold MEDIUM.
    hass_summer = FakeHass()
    hass_summer.states.set("sensor.living_room_illuminance", "30000")
    room_summer = make_room(config_data={
        CONF_SEASONAL_SPLIT: True,
        CONF_SUMMER_LUX_FACTOR: 150,
        CONF_WINTER_LUX_FACTOR: 50,
    })
    room_summer.current_state = SemanticState.MEDIUM
    room_summer.entities["enabled"] = FakeSwitch(True)

    summer_now = datetime(2026, 7, 21, 12, 0)
    coord_summer = _make_coordinator(monkeypatch, hass_summer, room_summer, now=summer_now)
    summer_result = await coord_summer._async_update_data()

    assert summer_result["desired"] == SemanticState.MEDIUM
    assert summer_result["moved"] is False


async def test_seasonal_split_off_does_not_scale_thresholds(monkeypatch):
    from custom_components.chained_blinds.const import CONF_SEASONAL_SPLIT

    hass = FakeHass()
    # above default lux_high 35k → SHADE
    hass.states.set("sensor.living_room_illuminance", "40000")
    room = make_room(config_data={
        CONF_SEASONAL_SPLIT: False,
    })
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE
    assert result["moved"] is True


async def test_sunrise_open_off_uses_fixed_open_time(monkeypatch):
    from custom_components.chained_blinds.const import CONF_USE_SUNRISE_OPEN

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    room = make_room(config_data={
        CONF_USE_SUNRISE_OPEN: False,
    })
    room.entities["enabled"] = FakeSwitch(True)

    before_fixed_open = datetime(2026, 7, 21, 6, 30)  # 06:30 < default 07:00
    coord = _make_coordinator(monkeypatch, hass, room, now=before_fixed_open)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.CLOSED


async def test_sunrise_open_after_sunrise_allows_lux_evaluation(monkeypatch):
    from custom_components.chained_blinds.const import CONF_USE_SUNRISE_OPEN

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    room = make_room(config_data={
        CONF_USE_SUNRISE_OPEN: True,
    })
    room.entities["enabled"] = FakeSwitch(True)

    after_sunrise = datetime(2026, 7, 21, 8, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=after_sunrise)
    monkeypatch.setattr(coord, "_sunrise_with_offset", lambda now: datetime(2026, 7, 21, 7, 0))

    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE
    assert result["moved"] is True


async def test_workday_sensor_off_uses_non_workday_open_time(monkeypatch):
    from datetime import time
    from custom_components.chained_blinds.const import CONF_OPEN_TIME, CONF_NON_WORKDAY_OPEN_TIME

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    hass.states.set("binary_sensor.workday_sensor", "off")
    room = make_room(config_data={
        CONF_OPEN_TIME: time(7, 0),
        CONF_NON_WORKDAY_OPEN_TIME: time(9, 30),
    })
    room.entities["enabled"] = FakeSwitch(True)

    at_0800 = datetime(2026, 7, 21, 8, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_0800)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.CLOSED
    assert result["moved"] is True


async def test_workday_sensor_on_uses_workday_open_time(monkeypatch):
    from datetime import time
    from custom_components.chained_blinds.const import CONF_OPEN_TIME, CONF_NON_WORKDAY_OPEN_TIME

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    hass.states.set("binary_sensor.workday_sensor", "on")
    room = make_room(config_data={
        CONF_OPEN_TIME: time(7, 0),
        CONF_NON_WORKDAY_OPEN_TIME: time(9, 30),
    })
    room.entities["enabled"] = FakeSwitch(True)

    at_0800 = datetime(2026, 7, 21, 8, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_0800)
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
    """150 % config value should become a ×1.5 multiplier on the thresholds."""
    from custom_components.chained_blinds.const import (
        CONF_SEASONAL_SPLIT,
        CONF_SUMMER_LUX_FACTOR,
        CONF_WINTER_LUX_FACTOR,
    )

    hass = FakeHass()
    # default lux_medium = 12000; with summer factor 150 % → 12000 × 1.5 = 18000.
    # lux of 17000 would normally darken to MEDIUM, but after scaling it should
    # remain OPEN (current), which validates the percent conversion.
    hass.states.set("sensor.living_room_illuminance", "17000")
    room = make_room(config_data={
        CONF_SEASONAL_SPLIT: True,
        CONF_SUMMER_LUX_FACTOR: 150,  # 150 % == ×1.5
        CONF_WINTER_LUX_FACTOR: 100,
    })
    room.entities["enabled"] = FakeSwitch(True)

    summer_now = datetime(2026, 7, 21, 12, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=summer_now)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.OPEN


async def test_winter_factor_percent_lowers_thresholds(monkeypatch):
    """50 % config value should become a ×0.5 multiplier on the thresholds."""
    from custom_components.chained_blinds.const import (
        CONF_SEASONAL_SPLIT,
        CONF_SUMMER_LUX_FACTOR,
        CONF_WINTER_LUX_FACTOR,
    )

    hass = FakeHass()
    # default lux_high = 35000; with winter factor 50 % → 35000 × 0.5 = 17500.
    # lux of 20000 is below 35000 (would normally → MEDIUM) but above 17500, so
    # with scaling it should go to SHADE.
    hass.states.set("sensor.living_room_illuminance", "20000")
    room = make_room(config_data={
        CONF_SEASONAL_SPLIT: True,
        CONF_SUMMER_LUX_FACTOR: 100,
        CONF_WINTER_LUX_FACTOR: 50,  # 50 % == ×0.5
    })
    room.current_state = SemanticState.OPEN
    room.entities["enabled"] = FakeSwitch(True)

    winter_now = datetime(2026, 1, 21, 12, 0)
    coord = _make_coordinator(monkeypatch, hass, room, now=winter_now)
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.SHADE


# ── Sunset/sunrise offset arithmetic ─────────────────────────────────────────

async def test_positive_sunset_offset_delays_night_start(monkeypatch):
    """A +60 min sunset offset should keep the blinds daytime-active 1 h past raw sunset."""
    from custom_components.chained_blinds.const import CONF_SUNSET_OFFSET_MINUTES

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "0")
    room = make_room(config_data={
        CONF_SUNSET_OFFSET_MINUTES: 60,
    })
    room.entities["enabled"] = FakeSwitch(True)

    # Raw sunset is at 20:00; with +60 min offset the night boundary moves to 21:00.
    # At 20:30 the blinds should still be in daytime mode (desired = OPEN at 0 lux).
    at_2030 = datetime(2026, 7, 21, 20, 30)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_2030)
    raw_sunset = datetime(2026, 7, 21, 20, 0)
    monkeypatch.setattr(
        coord, "_sunset_with_offset",
        lambda now: raw_sunset + timedelta(minutes=60),
    )
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.OPEN


async def test_negative_sunset_offset_brings_night_start_forward(monkeypatch):
    """A −60 min sunset offset should trigger night/closed 1 h before raw sunset."""
    from custom_components.chained_blinds.const import CONF_SUNSET_OFFSET_MINUTES

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "5000")
    room = make_room(config_data={
        CONF_SUNSET_OFFSET_MINUTES: -60,
    })
    room.entities["enabled"] = FakeSwitch(True)

    # Raw sunset 20:00; offset makes effective sunset 19:00.
    # At 19:30 desired state should be CLOSED (night).
    at_1930 = datetime(2026, 7, 21, 19, 30)
    coord = _make_coordinator(monkeypatch, hass, room, now=at_1930)
    raw_sunset = datetime(2026, 7, 21, 20, 0)
    monkeypatch.setattr(
        coord, "_sunset_with_offset",
        lambda now: raw_sunset + timedelta(minutes=-60),
    )
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.CLOSED


async def test_ramp_enabled_moves_one_step_toward_target(monkeypatch):
    from custom_components.chained_blinds.const import (
        CONF_RAMP_ENABLED,
        CONF_RAMP_STEP_PERCENT,
        CONF_RAMP_INTERVAL_MINUTES,
    )

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 75},
    )
    room = make_room(config_data={
        CONF_RAMP_ENABLED: True,
        CONF_RAMP_STEP_PERCENT: 20,
        CONF_RAMP_INTERVAL_MINUTES: 1,
    })
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["moved"] is True
    assert result["ramping"] is True
    assert room.ramp_target_state == SemanticState.SHADE
    assert hass.services.calls[0][2]["position"] == 55.0


async def test_ramp_waits_for_configured_interval_between_steps(monkeypatch):
    from custom_components.chained_blinds.const import (
        CONF_RAMP_ENABLED,
        CONF_RAMP_STEP_PERCENT,
        CONF_RAMP_INTERVAL_MINUTES,
    )

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 75},
    )
    room = make_room(config_data={
        CONF_RAMP_ENABLED: True,
        CONF_RAMP_STEP_PERCENT: 20,
        CONF_RAMP_INTERVAL_MINUTES: 1,
    })
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    first = await coord._async_update_data()
    assert first["moved"] is True

    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 55},
    )
    second = await coord._async_update_data()

    assert second["moved"] is False
    assert second["ramping"] is True
    assert len(hass.services.calls) == 1


async def test_ramp_retargets_when_desired_state_changes(monkeypatch):
    from custom_components.chained_blinds.const import (
        CONF_RAMP_ENABLED,
        CONF_RAMP_STEP_PERCENT,
        CONF_RAMP_INTERVAL_MINUTES,
    )

    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "60000")
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 75},
    )
    room = make_room(config_data={
        CONF_RAMP_ENABLED: True,
        CONF_RAMP_STEP_PERCENT: 20,
        CONF_RAMP_INTERVAL_MINUTES: 1,
    })
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    await coord._async_update_data()
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 55},
    )

    # Force interval elapsed, then drop lux so desired direction flips to OPEN.
    room.last_move_time = room.last_move_time - timedelta(minutes=2)
    hass.states.set("sensor.living_room_illuminance", "0")
    result = await coord._async_update_data()

    assert result["desired"] == SemanticState.OPEN
    assert result["moved"] is True
    assert result["ramping"] is False
    assert room.current_state == SemanticState.OPEN
    assert room.ramp_target_state is None
    assert hass.services.calls[-1][2]["position"] == 75.0


async def test_unavailable_lux_holds_position_and_never_moves(monkeypatch):
    """A lux sensor reporting unavailable must not be read as 0 lux (dark),
    which would reopen shades into direct sun. The coordinator holds."""
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "unavailable")
    room = make_room()
    room.current_state = SemanticState.SHADE
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False
    assert result["lux_unavailable"] is True
    assert room.current_state == SemanticState.SHADE


async def test_missing_lux_state_holds_position(monkeypatch):
    hass = FakeHass()  # no lux state set at all
    room = make_room()
    room.current_state = SemanticState.MEDIUM
    room.entities["enabled"] = FakeSwitch(True)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert hass.services.calls == []
    assert result["moved"] is False
    assert result["lux_unavailable"] is True


async def test_startup_reconciles_current_state_from_actual_position(monkeypatch):
    """With no persisted state, the coordinator adopts the cover's real
    reported position (nearest calibrated state) instead of defaulting to
    OPEN, so hysteresis runs against reality after a restart."""
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "0")  # dark daytime -> OPEN tier
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 26},  # nearest to shade (25)
    )
    room = make_room()
    room.current_state = None
    # Disabled so the reconciled state is observable in the result without an
    # immediate resolver move overwriting result["current"].
    room.entities["enabled"] = FakeSwitch(False)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["current"] == SemanticState.SHADE
    assert room.current_state == SemanticState.SHADE


async def test_startup_reconcile_does_not_override_persisted_state(monkeypatch):
    hass = FakeHass()
    hass.states.set("sensor.living_room_illuminance", "0")
    hass.states.set(
        "cover.living_room_left_blind",
        "open",
        attributes={"current_position": 26},
    )
    room = make_room()
    room.current_state = SemanticState.MEDIUM  # persisted
    room.entities["enabled"] = FakeSwitch(False)

    coord = _make_coordinator(monkeypatch, hass, room)
    result = await coord._async_update_data()

    assert result["current"] == SemanticState.MEDIUM
    assert room.current_state == SemanticState.MEDIUM


