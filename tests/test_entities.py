"""Construction/attribute-wiring tests for the number/select/switch/time
entity classes.

These only exercise the plain constructors (spec -> entity attributes,
unique_id, DeviceInfo) -- not `async_added_to_hass`/RestoreEntity lifecycle
or `async_write_ha_state`, both of which require a real attached `hass` and
are impractical with the lightweight fakes used elsewhere in this test
suite (see tests/fakes.py). Full entity-lifecycle coverage is follow-up work
via pytest-homeassistant-custom-component.
"""
from custom_components.chained_blinds.const import DOMAIN, THRESHOLD_NUMBER_SPECS
from custom_components.chained_blinds.number import ChainedBlindsNumber
from custom_components.chained_blinds.select import ChainedBlindsStateSelect
from custom_components.chained_blinds.switch import (
    EnabledSwitch,
    OverrideSwitch,
    SeasonalSplitSwitch,
    SunriseOpenSwitch,
)
from custom_components.chained_blinds.time import OpenTimeEntity

from .fakes import make_room


def test_number_entity_wires_spec_onto_attributes():
    room = make_room()
    spec = THRESHOLD_NUMBER_SPECS[0]  # lux_medium

    entity = ChainedBlindsNumber(room, spec)

    assert entity.unique_id == f"{room.entry_id}_{spec.key}"
    assert entity.native_value == spec.default
    assert entity.native_min_value == spec.min_value
    assert entity.native_max_value == spec.max_value
    assert entity.device_info["identifiers"] == {(DOMAIN, room.entry_id)}


def test_select_entity_defaults_options_and_unique_id():
    room = make_room()

    entity = ChainedBlindsStateSelect(room)

    assert entity.unique_id == f"{room.entry_id}_state"
    assert set(entity.options) == {"open", "medium", "shade", "closed"}


def test_enabled_switch_defaults_on():
    room = make_room()
    entity = EnabledSwitch(room)
    assert entity.is_on is True
    assert entity.unique_id == f"{room.entry_id}_enabled"


def test_override_switch_defaults_off():
    from .fakes import FakeHass

    room = make_room()
    entity = OverrideSwitch(FakeHass(), room)
    assert entity.is_on is False
    assert entity.unique_id == f"{room.entry_id}_override"


def test_seasonal_split_switch_defaults_off():
    room = make_room()
    entity = SeasonalSplitSwitch(room)
    assert entity.is_on is False
    assert entity.unique_id == f"{room.entry_id}_seasonal_split"


def test_sunrise_open_switch_defaults_off():
    room = make_room()
    entity = SunriseOpenSwitch(room)
    assert entity.is_on is False
    assert entity.unique_id == f"{room.entry_id}_sunrise_open"


def test_open_time_entity_defaults():
    from datetime import time

    room = make_room()
    entity = OpenTimeEntity(room)
    assert entity.native_value == time(7, 0)
    assert entity.unique_id == f"{room.entry_id}_open_time"
