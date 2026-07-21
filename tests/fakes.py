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

    Includes data and options for tuning configuration.
    """

    def __init__(self, data: dict | None = None, options: dict | None = None):
        self.entry_id = "test_entry"
        self.domain = "chained_blinds"
        self.title = "Test Room"
        self.state = "loaded"
        self.data = data or {}
        self.options = options or {}

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


def disable_ha_state_writes(entity) -> None:
    """Disable HA state-write side effects for unattached entity unit tests."""

    entity.async_write_ha_state = lambda: None


def make_room(config_data: dict | None = None, **overrides):
    from custom_components.chained_blinds.models import RoomRuntimeData
    from custom_components.chained_blinds.const import (
        CONF_LEFT_COVER,
        CONF_LUX_SENSOR,
        CONF_LUX_MEDIUM,
        CONF_LUX_HIGH,
        CONF_LUX_MEDIUM_REOPEN,
        CONF_LUX_HIGH_REOPEN,
        CONF_DWELL_MINUTES,
        CONF_REOPEN_DWELL_MINUTES,
        CONF_OVERRIDE_DURATION_MINUTES,
        CONF_RAMP_STEP_PERCENT,
        CONF_RAMP_INTERVAL_MINUTES,
        CONF_OPEN_TIME,
        CONF_NON_WORKDAY_OPEN_TIME,
        DEFAULT_LUX_MEDIUM,
        DEFAULT_LUX_HIGH,
        DEFAULT_LUX_MEDIUM_REOPEN,
        DEFAULT_LUX_HIGH_REOPEN,
        DEFAULT_DWELL_MINUTES,
        DEFAULT_REOPEN_DWELL_MINUTES,
        DEFAULT_OVERRIDE_DURATION_MINUTES,
        DEFAULT_RAMP_STEP_PERCENT,
        DEFAULT_RAMP_INTERVAL_MINUTES,
        DEFAULT_OPEN_TIME,
        DEFAULT_NON_WORKDAY_OPEN_TIME,
        DEFAULT_CALIBRATION,
        SemanticState,
    )

    # Build default config data with all tuning values
    default_config = {
        CONF_LEFT_COVER: "cover.living_room_left_blind",
        CONF_LUX_SENSOR: "sensor.living_room_illuminance",
        CONF_LUX_MEDIUM: DEFAULT_LUX_MEDIUM,
        CONF_LUX_HIGH: DEFAULT_LUX_HIGH,
        CONF_LUX_MEDIUM_REOPEN: DEFAULT_LUX_MEDIUM_REOPEN,
        CONF_LUX_HIGH_REOPEN: DEFAULT_LUX_HIGH_REOPEN,
        CONF_DWELL_MINUTES: DEFAULT_DWELL_MINUTES,
        CONF_REOPEN_DWELL_MINUTES: DEFAULT_REOPEN_DWELL_MINUTES,
        CONF_OVERRIDE_DURATION_MINUTES: DEFAULT_OVERRIDE_DURATION_MINUTES,
        CONF_RAMP_STEP_PERCENT: DEFAULT_RAMP_STEP_PERCENT,
        CONF_RAMP_INTERVAL_MINUTES: DEFAULT_RAMP_INTERVAL_MINUTES,
        CONF_OPEN_TIME: DEFAULT_OPEN_TIME,
        CONF_NON_WORKDAY_OPEN_TIME: DEFAULT_NON_WORKDAY_OPEN_TIME,
        # Calibration for left cover
        "left_open_pos": DEFAULT_CALIBRATION[SemanticState.OPEN],
        "left_medium_pos": DEFAULT_CALIBRATION[SemanticState.MEDIUM],
        "left_shade_pos": DEFAULT_CALIBRATION[SemanticState.SHADE],
        "left_closed_pos": DEFAULT_CALIBRATION[SemanticState.CLOSED],
    }

    # Allow test to override config values
    if config_data:
        default_config.update(config_data)

    config_entry = FakeConfigEntry(data=default_config)

    defaults = dict(
        entry_id="test_entry",
        name="Test Room",
        left_cover="cover.living_room_left_blind",
        right_cover=None,
        lux_sensor="sensor.living_room_illuminance",
        config_entry=config_entry,
        store=FakeStore(),
    )
    defaults.update(overrides)
    return RoomRuntimeData(**defaults)
