"""Config flow for Chained Blinds.

Each config entry represents one room: a required "left" cover, an optional
"right" cover, a required lux sensor, and an optional sun-at-window binary
sensor. Everything else (thresholds, dwell, calibration, enable, override)
is exposed as live-tunable entities created by the number/select/switch/time
platforms, not as config-entry data -- see const.py's *_NUMBER_SPECS.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_LEFT_COVER, CONF_LUX_SENSOR, CONF_RIGHT_COVER, CONF_SUN_SENSOR, DOMAIN


def _build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LEFT_COVER, default=current.get(CONF_LEFT_COVER, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
            vol.Optional(
                CONF_RIGHT_COVER, default=current.get(CONF_RIGHT_COVER, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
            vol.Required(
                CONF_LUX_SENSOR, default=current.get(CONF_LUX_SENSOR, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_SUN_SENSOR, default=current.get(CONF_SUN_SENSOR, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not user_input.get(CONF_LEFT_COVER):
        errors[CONF_LEFT_COVER] = "required"
    if not user_input.get(CONF_LUX_SENSOR):
        errors[CONF_LUX_SENSOR] = "required"
    return errors


def _title(user_input: dict[str, Any]) -> str:
    left = user_input[CONF_LEFT_COVER]
    right = user_input.get(CONF_RIGHT_COVER)
    return f"Chained Blinds ({left} & {right})" if right else f"Chained Blinds ({left})"


class ChainedBlindsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chained Blinds."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ChainedBlindsOptionsFlow":
        return ChainedBlindsOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                unique_id = f"{user_input[CONF_LEFT_COVER]}|{user_input.get(CONF_RIGHT_COVER, '')}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=_title(user_input), data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_build_schema(user_input or {}), errors=errors
        )


class ChainedBlindsOptionsFlow(config_entries.OptionsFlow):
    """Let the user re-point a room's covers/sensors after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        # Merge options over data so that previously saved options are shown
        # as current values rather than always reverting to initial config.
        current = user_input or {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_build_schema(current), errors=errors
        )
