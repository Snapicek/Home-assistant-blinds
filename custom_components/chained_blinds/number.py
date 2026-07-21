"""Live-tunable `number` entities: lux thresholds, dwell minutes, sunset
offset, override duration, and per-cover-per-state calibrated positions."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, THRESHOLD_NUMBER_SPECS, NumberSpec, calibration_number_specs
from .models import RoomRuntimeData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    room: RoomRuntimeData = hass.data[DOMAIN][entry.entry_id]

    specs: list[NumberSpec] = list(THRESHOLD_NUMBER_SPECS)
    for role in room.cover_roles:
        specs.extend(calibration_number_specs(role))

    async_add_entities(ChainedBlindsNumber(room, spec) for spec in specs)


class ChainedBlindsNumber(NumberEntity, RestoreEntity):
    """A single live-tunable numeric value for one room."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def _normalize_native_value(self, value: float) -> int | float:
        precision = self._spec.suggested_display_precision
        if precision is None:
            return float(value)
        if precision == 0:
            return int(round(value))
        return round(float(value), precision)

    def __init__(self, room: RoomRuntimeData, spec: NumberSpec) -> None:
        self._room = room
        self._spec = spec
        self._attr_unique_id = f"{room.entry_id}_{spec.key}"
        self._attr_name = spec.name
        self._attr_entity_category = spec.entity_category
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_native_value = self._normalize_native_value(spec.default)
        if spec.suggested_display_precision is not None:
            self._attr_suggested_display_precision = spec.suggested_display_precision
        if spec.icon:
            self._attr_icon = spec.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room.entry_id)}, name=room.name
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._room.entities[self._spec.key] = self
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                restored = self._normalize_native_value(float(last_state.state))
                # Guard against persisted values from an older scale (e.g. a float
                # factor like 1.15 that was stored before the unit changed to %).
                # If the value is outside the current valid range, reset to the
                # spec default so the entity starts in a sensible state.
                if self._spec.min_value <= restored <= self._spec.max_value:
                    self._attr_native_value = restored
                else:
                    self._attr_native_value = self._normalize_native_value(self._spec.default)
            except (TypeError, ValueError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = self._normalize_native_value(value)
        self.async_write_ha_state()
