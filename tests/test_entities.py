"""Construction/attribute-wiring tests for the surviving entity classes.

After moving all tuning into the config flow, the only entities this
integration still creates are operational: the enable switch, the pause
(override) switch, and the semantic-state select. The number/time platforms
and the seasonal/sunrise/ramp config switches were removed.

These only exercise the plain constructors (attributes, unique_id,
DeviceInfo) -- not `async_added_to_hass`/RestoreEntity lifecycle, which
requires a real attached `hass` and is impractical with the lightweight
fakes used elsewhere in this suite (see tests/fakes.py). Full
entity-lifecycle coverage is follow-up work via
pytest-homeassistant-custom-component.
"""
from custom_components.chained_blinds.const import DOMAIN
from custom_components.chained_blinds.select import ChainedBlindsStateSelect
from custom_components.chained_blinds.switch import EnabledSwitch, OverrideSwitch

from .fakes import make_room


def test_select_entity_defaults_options_and_unique_id():
    room = make_room()

    entity = ChainedBlindsStateSelect(room)

    assert entity.unique_id == f"{room.entry_id}_state"
    assert set(entity.options) == {"open", "medium", "shade", "closed"}


def test_select_entity_device_info_identifiers():
    room = make_room()

    entity = ChainedBlindsStateSelect(room)

    assert entity.device_info["identifiers"] == {(DOMAIN, room.entry_id)}


def test_state_select_has_correct_icon():
    room = make_room()
    entity = ChainedBlindsStateSelect(room)
    assert entity.icon == "mdi:blinds"


def test_enabled_switch_defaults_on():
    room = make_room()
    entity = EnabledSwitch(room)
    assert entity.is_on is True
    assert entity.unique_id == f"{room.entry_id}_enabled"


def test_enabled_switch_has_correct_icon():
    room = make_room()
    entity = EnabledSwitch(room)
    assert entity.icon == "mdi:auto-mode"


def test_override_switch_defaults_off():
    from .fakes import FakeConfigEntry, FakeHass

    room = make_room()
    entity = OverrideSwitch(FakeHass(), room, FakeConfigEntry())
    assert entity.is_on is False
    assert entity.unique_id == f"{room.entry_id}_override"


def test_override_switch_has_correct_icon():
    from .fakes import FakeConfigEntry, FakeHass

    room = make_room()
    entity = OverrideSwitch(FakeHass(), room, FakeConfigEntry())
    assert entity.icon == "mdi:hand-back-right"
