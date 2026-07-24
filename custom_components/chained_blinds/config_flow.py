"""Config flow for Chained Blinds.

Each config entry represents one room: structural wiring (left cover, optional right cover,
lux sensor) plus all tuning (lux thresholds, dwell, calibration, offsets, seasonal factors).
Initial setup asks only for the essentials (room/covers/sensor + calibration); every tuning
value starts at a sensible default and is adjusted afterwards from the options-flow menu,
where each section page saves immediately on submit.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DWELL_MINUTES,
    CONF_LEFT_COVER,
    CONF_LUX_HIGH,
    CONF_LUX_HIGH_REOPEN,
    CONF_LUX_MEDIUM,
    CONF_LUX_MEDIUM_REOPEN,
    CONF_LUX_SENSOR,
    CONF_MAX_TRAVEL_SECONDS,
    CONF_NON_WORKDAY_OPEN_TIME,
    CONF_OPEN_TIME,
    CONF_OVERRIDE_DURATION_MINUTES,
    CONF_RAMP_ENABLED,
    CONF_RAMP_INTERVAL_MINUTES,
    CONF_RAMP_STEP_PERCENT,
    CONF_REOPEN_DWELL_MINUTES,
    CONF_RIGHT_COVER,
    CONF_ROOM_NAME,
    CONF_SEASONAL_SPLIT,
    CONF_SUMMER_LUX_FACTOR,
    CONF_SUNRISE_OFFSET_MINUTES,
    CONF_SUNSET_OFFSET_MINUTES,
    CONF_USE_SUNRISE_OPEN,
    CONF_WINTER_LUX_FACTOR,
    DEFAULT_CALIBRATION,
    DEFAULT_DWELL_MINUTES,
    DEFAULT_LUX_HIGH,
    DEFAULT_LUX_HIGH_REOPEN,
    DEFAULT_LUX_MEDIUM,
    DEFAULT_LUX_MEDIUM_REOPEN,
    DEFAULT_MAX_TRAVEL_SECONDS,
    DEFAULT_NON_WORKDAY_OPEN_TIME,
    DEFAULT_OPEN_TIME,
    DEFAULT_OVERRIDE_DURATION_MINUTES,
    DEFAULT_RAMP_ENABLED,
    DEFAULT_RAMP_INTERVAL_MINUTES,
    DEFAULT_RAMP_STEP_PERCENT,
    DEFAULT_REOPEN_DWELL_MINUTES,
    DEFAULT_SEASONAL_SPLIT,
    DEFAULT_SUMMER_LUX_FACTOR_PERCENT,
    DEFAULT_SUNRISE_OFFSET_MINUTES,
    DEFAULT_SUNSET_OFFSET_MINUTES,
    DEFAULT_USE_SUNRISE_OPEN,
    DEFAULT_WINTER_LUX_FACTOR_PERCENT,
    DOMAIN,
    SemanticState,
)


def _build_covers_sensor_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 1: Covers and Lux Sensor."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_ROOM_NAME, default=current.get(CONF_ROOM_NAME, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_LEFT_COVER, default=current.get(CONF_LEFT_COVER, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
            vol.Optional(
                CONF_RIGHT_COVER, default=current.get(CONF_RIGHT_COVER, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="cover")),
            vol.Required(
                CONF_LUX_SENSOR, default=current.get(CONF_LUX_SENSOR, "")
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="illuminance")),
        }
    )


def _build_lux_thresholds_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 2: Lux Thresholds."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LUX_MEDIUM, default=current.get(CONF_LUX_MEDIUM, DEFAULT_LUX_MEDIUM)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100000, step=100, unit_of_measurement="lx")
            ),
            vol.Required(
                CONF_LUX_MEDIUM_REOPEN, default=current.get(CONF_LUX_MEDIUM_REOPEN, DEFAULT_LUX_MEDIUM_REOPEN)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100000, step=100, unit_of_measurement="lx")
            ),
            vol.Required(
                CONF_LUX_HIGH, default=current.get(CONF_LUX_HIGH, DEFAULT_LUX_HIGH)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100000, step=100, unit_of_measurement="lx")
            ),
            vol.Required(
                CONF_LUX_HIGH_REOPEN, default=current.get(CONF_LUX_HIGH_REOPEN, DEFAULT_LUX_HIGH_REOPEN)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100000, step=100, unit_of_measurement="lx")
            ),
        }
    )


def _build_dwell_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 3: Dwell Times."""
    return vol.Schema(
        {
            vol.Required(
                CONF_DWELL_MINUTES, default=current.get(CONF_DWELL_MINUTES, DEFAULT_DWELL_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=720, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_REOPEN_DWELL_MINUTES, default=current.get(CONF_REOPEN_DWELL_MINUTES, DEFAULT_REOPEN_DWELL_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=720, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_OVERRIDE_DURATION_MINUTES,
                default=current.get(CONF_OVERRIDE_DURATION_MINUTES, DEFAULT_OVERRIDE_DURATION_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=1440, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_MAX_TRAVEL_SECONDS,
                default=current.get(CONF_MAX_TRAVEL_SECONDS, DEFAULT_MAX_TRAVEL_SECONDS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=600, step=5, unit_of_measurement="s")
            ),
        }
    )


def _build_sun_schedule_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 4: Sun and Scheduling."""
    return vol.Schema(
        {
            vol.Required(
                CONF_OPEN_TIME, default=current.get(CONF_OPEN_TIME, DEFAULT_OPEN_TIME)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_NON_WORKDAY_OPEN_TIME, default=current.get(CONF_NON_WORKDAY_OPEN_TIME, DEFAULT_NON_WORKDAY_OPEN_TIME)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_USE_SUNRISE_OPEN, default=current.get(CONF_USE_SUNRISE_OPEN, DEFAULT_USE_SUNRISE_OPEN)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SUNRISE_OFFSET_MINUTES, default=current.get(CONF_SUNRISE_OFFSET_MINUTES, DEFAULT_SUNRISE_OFFSET_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-180, max=180, step=1, unit_of_measurement="min")
            ),
            vol.Required(
                CONF_SUNSET_OFFSET_MINUTES, default=current.get(CONF_SUNSET_OFFSET_MINUTES, DEFAULT_SUNSET_OFFSET_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=-180, max=180, step=1, unit_of_measurement="min")
            ),
        }
    )


def _build_seasonal_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 5: Seasonal Light Sensitivity."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SEASONAL_SPLIT, default=current.get(CONF_SEASONAL_SPLIT, DEFAULT_SEASONAL_SPLIT)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SUMMER_LUX_FACTOR, default=current.get(CONF_SUMMER_LUX_FACTOR, DEFAULT_SUMMER_LUX_FACTOR_PERCENT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=20, max=300, step=1, unit_of_measurement="%")
            ),
            vol.Required(
                CONF_WINTER_LUX_FACTOR, default=current.get(CONF_WINTER_LUX_FACTOR, DEFAULT_WINTER_LUX_FACTOR_PERCENT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=20, max=300, step=1, unit_of_measurement="%")
            ),
        }
    )


def _build_ramp_schema(current: dict[str, Any]) -> vol.Schema:
    """Step 6: Gradual Movement."""
    return vol.Schema(
        {
            vol.Required(
                CONF_RAMP_ENABLED, default=current.get(CONF_RAMP_ENABLED, DEFAULT_RAMP_ENABLED)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_RAMP_STEP_PERCENT, default=current.get(CONF_RAMP_STEP_PERCENT, DEFAULT_RAMP_STEP_PERCENT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=100, step=5, unit_of_measurement="%")
            ),
            vol.Required(
                CONF_RAMP_INTERVAL_MINUTES, default=current.get(CONF_RAMP_INTERVAL_MINUTES, DEFAULT_RAMP_INTERVAL_MINUTES)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=30, step=1, unit_of_measurement="min")
            ),
        }
    )


def _build_calibration_schema(current: dict[str, Any], cover_roles: list[str]) -> vol.Schema:
    """Step 7: Cover Calibration (per-cover-per-state positions)."""
    schema_dict = {}
    for role in cover_roles:
        for state in SemanticState:
            key = f"{role}_{state.value}_pos"
            schema_dict[
                vol.Required(key, default=current.get(key, DEFAULT_CALIBRATION[state]))
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="%")
            )
    return vol.Schema(schema_dict)


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate structural fields only (covers/sensor must exist)."""
    errors: dict[str, str] = {}
    if not user_input.get(CONF_LEFT_COVER):
        errors[CONF_LEFT_COVER] = "required"
    if not user_input.get(CONF_LUX_SENSOR):
        errors[CONF_LUX_SENSOR] = "required"
    return errors


def _title(user_input: dict[str, Any]) -> str:
    """Generate config entry title: the room name if given, else fall back
    to the covers so existing entries created before this field existed
    keep working."""
    room_name = user_input.get(CONF_ROOM_NAME)
    if room_name:
        return room_name
    left = user_input[CONF_LEFT_COVER]
    right = user_input.get(CONF_RIGHT_COVER)
    return f"Chained Blinds ({left} & {right})" if right else f"Chained Blinds ({left})"


class ChainedBlindsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup: the full set of settings, grouped page by page.

    Every page comes prefilled with sensible defaults, so users who just want
    to get going can submit straight through; everything can be revisited
    later from the options-flow menu.
    """

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._step_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ChainedBlindsOptionsFlow":
        return ChainedBlindsOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 1: Room name, covers, and lux sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                self._step_data.update(user_input)
                return await self.async_step_lux_thresholds()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_covers_sensor_schema(user_input or self._step_data),
            errors=errors,
        )

    async def async_step_lux_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 2: Light thresholds."""
        if user_input is not None:
            self._step_data.update(user_input)
            return await self.async_step_dwell()

        return self.async_show_form(
            step_id="lux_thresholds",
            data_schema=_build_lux_thresholds_schema(self._step_data),
        )

    async def async_step_dwell(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 3: Delay times."""
        if user_input is not None:
            self._step_data.update(user_input)
            return await self.async_step_sun_schedule()

        return self.async_show_form(
            step_id="dwell",
            data_schema=_build_dwell_schema(self._step_data),
        )

    async def async_step_sun_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 4: Opening schedule."""
        if user_input is not None:
            self._step_data.update(user_input)
            return await self.async_step_seasonal()

        return self.async_show_form(
            step_id="sun_schedule",
            data_schema=_build_sun_schedule_schema(self._step_data),
        )

    async def async_step_seasonal(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 5: Seasonal sensitivity."""
        if user_input is not None:
            self._step_data.update(user_input)
            return await self.async_step_ramp()

        return self.async_show_form(
            step_id="seasonal",
            data_schema=_build_seasonal_schema(self._step_data),
        )

    async def async_step_ramp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 6: Gradual movement."""
        if user_input is not None:
            self._step_data.update(user_input)
            return await self.async_step_calibration()

        return self.async_show_form(
            step_id="ramp",
            data_schema=_build_ramp_schema(self._step_data),
        )

    async def async_step_calibration(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Page 7: Cover Calibration, then create the entry."""
        if user_input is not None:
            self._step_data.update(user_input)
            unique_id = f"{self._step_data[CONF_LEFT_COVER]}|{self._step_data.get(CONF_RIGHT_COVER, '')}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=_title(self._step_data), data=self._step_data)

        cover_roles = ["left"]
        if self._step_data.get(CONF_RIGHT_COVER):
            cover_roles.append("right")

        return self.async_show_form(
            step_id="calibration",
            data_schema=_build_calibration_schema(self._step_data, cover_roles),
        )


class ChainedBlindsOptionsFlow(config_entries.OptionsFlow):
    """Menu-based settings: a hub page linking to focused section pages.

    Each section page saves immediately on submit (via async_update_entry,
    which triggers the entry-reload update listener) and returns to the menu,
    so users can adjust several sections in one visit and never have to walk
    a fixed wizard.
    """

    MENU_OPTIONS = [
        "covers",
        "lux_thresholds",
        "dwell",
        "sun_schedule",
        "seasonal",
        "ramp",
        "calibration",
        "finish",
    ]

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry

    @callback
    def _merge_current(self) -> dict[str, Any]:
        """Merge options over data (options take precedence)."""
        return {**self._config_entry.data, **self._config_entry.options}

    @callback
    def _save(self, user_input: dict[str, Any]) -> None:
        """Persist one section immediately and retitle the entry."""
        new_options = {**self._merge_current(), **user_input}
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            options=new_options,
            title=_title(new_options),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Hub menu: pick a section to adjust."""
        return self.async_show_menu(step_id="init", menu_options=self.MENU_OPTIONS)

    async def async_step_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Room name, covers, and lux sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                self._save(user_input)
                return await self.async_step_init()

        return self.async_show_form(
            step_id="covers",
            data_schema=_build_covers_sensor_schema(user_input or self._merge_current()),
            errors=errors,
        )

    async def async_step_lux_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Light thresholds."""
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="lux_thresholds",
            data_schema=_build_lux_thresholds_schema(self._merge_current()),
        )

    async def async_step_dwell(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Delay times."""
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="dwell",
            data_schema=_build_dwell_schema(self._merge_current()),
        )

    async def async_step_sun_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Opening schedule."""
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="sun_schedule",
            data_schema=_build_sun_schedule_schema(self._merge_current()),
        )

    async def async_step_seasonal(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Seasonal sensitivity."""
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="seasonal",
            data_schema=_build_seasonal_schema(self._merge_current()),
        )

    async def async_step_ramp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Gradual movement."""
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="ramp",
            data_schema=_build_ramp_schema(self._merge_current()),
        )

    async def async_step_calibration(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Section: Position calibration."""
        current = self._merge_current()
        if user_input is not None:
            self._save(user_input)
            return await self.async_step_init()

        cover_roles = ["left"]
        if current.get(CONF_RIGHT_COVER):
            cover_roles.append("right")

        return self.async_show_form(
            step_id="calibration",
            data_schema=_build_calibration_schema(current, cover_roles),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Close the menu; every section was already saved on submit."""
        return self.async_abort(reason="finished")
