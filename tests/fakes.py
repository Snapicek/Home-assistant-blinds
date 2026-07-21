"""Minimal test doubles used instead of the heavy pytest-homeassistant test
harness, which proved impractical to install in this environment (several
of its transitive dependencies fail to build on modern Python/setuptools).

These fakes only implement the exact surface our own code touches
(`hass.states.get`, `hass.services.async_call`, `entity.native_value`,
`entity.is_on`, `select.apply_external_state_update`), so they exercise the
integration's own glue logic (cover_control, coordinator) precisely, without
depending on HA's real state machine, service registry, or storage layer.
"""
from __future__ import annotations


class FakeState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self):
        self._states: dict[str, FakeState] = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def set(self, entity_id, state, attributes=None):
        self._states[entity_id] = FakeState(state, attributes)


class FakeServices:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=True):
        self.calls.append((domain, service, dict(data)))


class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.services = FakeServices()
        self.data: dict = {}


class FakeStore:
    """Stands in for homeassistant.helpers.storage.Store."""

    def __init__(self):
        self.saved: dict | None = None

    async def async_load(self):
        return None

    async def async_save(self, data):
        self.saved = data


class FakeConfigEntry:
    """Minimal stand-in for homeassistant.config_entries.ConfigEntry.

    Only needs to satisfy what DataUpdateCoordinator.__init__ accesses.
    """

    entry_id = "test_entry"
    domain = "chained_blinds"
    title = "Test Room"
    state = "loaded"

    def async_on_unload(self, callback):
        """Register a callback to be called when the config entry is unloaded."""
        pass


class FakeNumber:
    def __init__(self, value):
        self.native_value = value


class FakeSwitch:
    def __init__(self, is_on):
        self.is_on = is_on


class FakeSelect:
    def __init__(self):
        self.updates: list = []

    def apply_external_state_update(self, state):
        self.updates.append(state)


def make_room(**overrides):
    from custom_components.chained_blinds.models import RoomRuntimeData

    defaults = dict(
        entry_id="test_entry",
        name="Test Room",
        left_cover="cover.living_room_left_blind",
        right_cover=None,
        lux_sensor="sensor.living_room_illuminance",
        store=FakeStore(),
    )
    defaults.update(overrides)
    return RoomRuntimeData(**defaults)
