"""Tests for the menu-based ChainedBlindsOptionsFlow.

Drives the real ChainedBlindsOptionsFlow (against the real HA
config_entries/data_entry_flow base classes, not a fake) and asserts:
- the entry point is a menu linking to every settings section,
- submitting a section persists it immediately via
  hass.config_entries.async_update_entry and returns to the menu,
- the entry title follows the room name,
- "finish" closes the flow.

The persistence assertions guard against a real regression where the old
wizard-style flow discarded every submitted value (async_abort instead of
persisting).
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
    CONF_OVERRIDE_DURATION_MINUTES,
    CONF_REOPEN_DWELL_MINUTES,
    CONF_ROOM_NAME,
)
from tests.fakes import FakeHass


class FakeConfigEntry:
    """Minimal stand-in for config_entries.ConfigEntry: the options flow
    reads .data/.options and FakeConfigEntries writes .options/.title."""

    def __init__(self, data: dict) -> None:
        self.data = data
        self.options: dict = {}
        self.title = "old title"


def _make_flow() -> tuple[ChainedBlindsOptionsFlow, FakeConfigEntry, FakeHass]:
    entry = FakeConfigEntry(
        data={
            CONF_LEFT_COVER: "cover.bedroom_blind_left",
            CONF_LUX_SENSOR: "sensor.balcony_illuminance",
        }
    )
    flow = ChainedBlindsOptionsFlow(entry)
    hass = FakeHass()
    flow.hass = hass
    return flow, entry, hass


async def test_init_shows_menu_with_all_sections():
    flow, _entry, _hass = _make_flow()

    result = await flow.async_step_init()

    assert result["type"] == FlowResultType.MENU
    assert result["menu_options"] == [
        "covers",
        "lux_thresholds",
        "dwell",
        "sun_schedule",
        "seasonal",
        "ramp",
        "calibration",
        "finish",
    ]


async def test_section_submit_persists_immediately_and_returns_to_menu():
    """The regression guard: submitting one section must write the merged
    options to the entry right away."""
    flow, entry, hass = _make_flow()

    result = await flow.async_step_lux_thresholds(
        {
            CONF_LUX_MEDIUM: 15000,
            CONF_LUX_MEDIUM_REOPEN: 9000,
            CONF_LUX_HIGH: 40000,
            CONF_LUX_HIGH_REOPEN: 25000,
        }
    )

    assert len(hass.config_entries.update_calls) == 1
    assert entry.options[CONF_LUX_MEDIUM] == 15000
    assert entry.options[CONF_LUX_HIGH_REOPEN] == 25000
    # Structural data is carried into the merged options unchanged.
    assert entry.options[CONF_LEFT_COVER] == "cover.bedroom_blind_left"
    # Back at the hub menu, ready for the next section.
    assert result["type"] == FlowResultType.MENU


async def test_multiple_sections_accumulate():
    flow, entry, _hass = _make_flow()

    await flow.async_step_lux_thresholds(
        {
            CONF_LUX_MEDIUM: 15000,
            CONF_LUX_MEDIUM_REOPEN: 9000,
            CONF_LUX_HIGH: 40000,
            CONF_LUX_HIGH_REOPEN: 25000,
        }
    )
    await flow.async_step_dwell(
        {
            CONF_DWELL_MINUTES: 12,
            CONF_REOPEN_DWELL_MINUTES: 35,
            CONF_OVERRIDE_DURATION_MINUTES: 90,
        }
    )

    assert entry.options[CONF_LUX_MEDIUM] == 15000
    assert entry.options[CONF_DWELL_MINUTES] == 12


async def test_room_name_updates_entry_title():
    flow, entry, _hass = _make_flow()

    await flow.async_step_covers(
        {
            CONF_ROOM_NAME: "Guest Room",
            CONF_LEFT_COVER: "cover.bedroom_blind_left",
            CONF_LUX_SENSOR: "sensor.balcony_illuminance",
        }
    )

    assert entry.title == "Guest Room"


async def test_covers_section_validates_required_fields():
    flow, entry, hass = _make_flow()

    result = await flow.async_step_covers({CONF_ROOM_NAME: "X"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {
        CONF_LEFT_COVER: "required",
        CONF_LUX_SENSOR: "required",
    }
    assert hass.config_entries.update_calls == []


async def test_finish_closes_flow():
    flow, _entry, _hass = _make_flow()

    result = await flow.async_step_finish()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "finished"
