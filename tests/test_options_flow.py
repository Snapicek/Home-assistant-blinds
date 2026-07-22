"""Regression test for ChainedBlindsOptionsFlow persistence.

Drives the real ChainedBlindsOptionsFlow (against the real HA
config_entries/data_entry_flow base classes, not a fake) through all 7
reconfigure steps and asserts the final result actually persists the
submitted values. This guards against a real regression where the final
step returned `async_abort(...)` instead of `async_create_entry(...)`,
silently discarding every value a user entered while "reconfiguring".
"""
from homeassistant.data_entry_flow import FlowResultType

from custom_components.chained_blinds.config_flow import ChainedBlindsOptionsFlow
from custom_components.chained_blinds.const import (
    CONF_DWELL_MINUTES,
    CONF_LEFT_COVER,
    CONF_LUX_HIGH,
    CONF_LUX_HIGH_REOPEN,
    CONF_LUX_MEDIUM,
    CONF_LUX_MEDIUM_REOPEN,
    CONF_LUX_SENSOR,
    CONF_NON_WORKDAY_OPEN_TIME,
    CONF_OPEN_TIME,
    CONF_OVERRIDE_DURATION_MINUTES,
    CONF_RAMP_ENABLED,
    CONF_RAMP_INTERVAL_MINUTES,
    CONF_RAMP_STEP_PERCENT,
    CONF_REOPEN_DWELL_MINUTES,
    CONF_ROOM_NAME,
    CONF_SEASONAL_SPLIT,
    CONF_SUMMER_LUX_FACTOR,
    CONF_SUNRISE_OFFSET_MINUTES,
    CONF_SUNSET_OFFSET_MINUTES,
    CONF_USE_SUNRISE_OPEN,
    CONF_WINTER_LUX_FACTOR,
    DEFAULT_NON_WORKDAY_OPEN_TIME,
    DEFAULT_OPEN_TIME,
)


class FakeConfigEntry:
    """Minimal stand-in for config_entries.ConfigEntry: only .data/.options
    are read by ChainedBlindsOptionsFlow."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.options: dict = {}


def _base_entry() -> FakeConfigEntry:
    return FakeConfigEntry(
        data={
            CONF_LEFT_COVER: "cover.bedroom_blind_left",
            CONF_LUX_SENSOR: "sensor.balcony_illuminance",
        }
    )


async def _drive_to_completion(flow: ChainedBlindsOptionsFlow, room_name: str = "Bedroom"):
    """Walk all 7 options-flow steps with representative input and return
    the final flow result."""
    await flow.async_step_init(
        {
            CONF_ROOM_NAME: room_name,
            CONF_LEFT_COVER: "cover.bedroom_blind_left",
            CONF_LUX_SENSOR: "sensor.balcony_illuminance",
        }
    )
    await flow.async_step_reconfigure_lux(
        {
            CONF_LUX_MEDIUM: 15000,
            CONF_LUX_MEDIUM_REOPEN: 9000,
            CONF_LUX_HIGH: 40000,
            CONF_LUX_HIGH_REOPEN: 25000,
        }
    )
    await flow.async_step_reconfigure_dwell(
        {
            CONF_DWELL_MINUTES: 12,
            CONF_REOPEN_DWELL_MINUTES: 35,
            CONF_OVERRIDE_DURATION_MINUTES: 90,
        }
    )
    await flow.async_step_reconfigure_sun(
        {
            CONF_OPEN_TIME: DEFAULT_OPEN_TIME,
            CONF_NON_WORKDAY_OPEN_TIME: DEFAULT_NON_WORKDAY_OPEN_TIME,
            CONF_USE_SUNRISE_OPEN: False,
            CONF_SUNRISE_OFFSET_MINUTES: 0,
            CONF_SUNSET_OFFSET_MINUTES: 0,
        }
    )
    await flow.async_step_reconfigure_seasonal(
        {
            CONF_SEASONAL_SPLIT: False,
            CONF_SUMMER_LUX_FACTOR: 115,
            CONF_WINTER_LUX_FACTOR: 85,
        }
    )
    await flow.async_step_reconfigure_ramp(
        {
            CONF_RAMP_ENABLED: False,
            CONF_RAMP_STEP_PERCENT: 20,
            CONF_RAMP_INTERVAL_MINUTES: 5,
        }
    )
    return await flow.async_step_reconfigure_calibration(
        {
            "left_open_pos": 80,
            "left_medium_pos": 55,
            "left_shade_pos": 30,
            "left_closed_pos": 0,
        }
    )


async def test_reconfigure_persists_submitted_values():
    """The regression: reconfiguring must actually write entry.options,
    not just show a success message."""
    entry = _base_entry()
    flow = ChainedBlindsOptionsFlow(entry)

    result = await _drive_to_completion(flow)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LUX_MEDIUM] == 15000
    assert result["data"][CONF_DWELL_MINUTES] == 12
    assert result["data"][CONF_OVERRIDE_DURATION_MINUTES] == 90
    assert result["data"]["left_open_pos"] == 80


async def test_reconfigure_title_reflects_new_room_name():
    """Submitting a room name should update the entry title, matching the
    entry point used for HA's device/entity naming."""
    entry = _base_entry()
    flow = ChainedBlindsOptionsFlow(entry)

    result = await _drive_to_completion(flow, room_name="Guest Room")

    assert result["title"] == "Guest Room"
