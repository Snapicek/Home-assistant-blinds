"""Tests for config_flow.py's pure helpers (schema building, validation,
title generation).
"""
from custom_components.chained_blinds.config_flow import (
    _build_covers_sensor_schema,
    _build_lux_thresholds_schema,
    _title,
    _validate,
)
from custom_components.chained_blinds.const import (
    CONF_LEFT_COVER,
    CONF_LUX_SENSOR,
    CONF_RIGHT_COVER,
    CONF_LUX_MEDIUM,
    CONF_LUX_HIGH,
    DEFAULT_LUX_MEDIUM,
    DEFAULT_LUX_HIGH,
)


def test_validate_requires_left_cover_and_lux_sensor():
    errors = _validate({})
    assert errors == {CONF_LEFT_COVER: "required", CONF_LUX_SENSOR: "required"}


def test_validate_passes_with_only_required_fields():
    errors = _validate(
        {
            CONF_LEFT_COVER: "cover.living_room_left_blind",
            CONF_LUX_SENSOR: "sensor.living_room_illuminance",
        }
    )
    assert errors == {}



def test_title_single_cover():
    title = _title({CONF_LEFT_COVER: "cover.living_room_left_blind"})
    assert title == "Chained Blinds (cover.living_room_left_blind)"


def test_title_two_covers():
    title = _title(
        {
            CONF_LEFT_COVER: "cover.living_room_left_blind",
            CONF_RIGHT_COVER: "cover.living_room_right_blind",
        }
    )
    assert title == "Chained Blinds (cover.living_room_left_blind & cover.living_room_right_blind)"


def test_build_covers_sensor_schema_prefills_current_values():
    schema = _build_covers_sensor_schema(
        {
            CONF_LEFT_COVER: "cover.living_room_left_blind",
            CONF_LUX_SENSOR: "sensor.living_room_illuminance",
        }
    )
    defaults = {
        marker.schema: marker.default() if callable(marker.default) else marker.default
        for marker in schema.schema
    }
    assert defaults[CONF_LEFT_COVER] == "cover.living_room_left_blind"
    assert defaults[CONF_LUX_SENSOR] == "sensor.living_room_illuminance"
    assert defaults[CONF_RIGHT_COVER] == ""


def test_build_lux_thresholds_schema_uses_defaults():
    schema = _build_lux_thresholds_schema({})
    defaults = {
        marker.schema: marker.default() if callable(marker.default) else marker.default
        for marker in schema.schema
    }
    assert defaults[CONF_LUX_MEDIUM] == DEFAULT_LUX_MEDIUM
    assert defaults[CONF_LUX_HIGH] == DEFAULT_LUX_HIGH

