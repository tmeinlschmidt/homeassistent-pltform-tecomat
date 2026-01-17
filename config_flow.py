"""Config flow for Tecomat integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    CONF_LIGHTS,
    CONF_COVERS,
    CONF_COVER_UP_SUFFIX,
    CONF_COVER_DOWN_SUFFIX,
    CONF_BINARY_SENSORS,
    CONF_SENSORS,
    CONF_SWITCHES,
    CONF_BUTTONS,
    DEFAULT_COVER_UP_SUFFIX,
    DEFAULT_COVER_DOWN_SUFFIX,
)
from .plccoms import PlcComSClient, PlcComSConnectionError

_LOGGER = logging.getLogger(__name__)


async def validate_connection(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    client = PlcComSClient(data[CONF_HOST], data.get(CONF_PORT, DEFAULT_PORT))

    try:
        await client.connect()
        try:
            version = await client.get_info("version_plc")
        except Exception:
            version = "unknown"

        # Get list of available variables with types
        variables = await client.list_variables()

        return {
            "title": f"Tecomat ({data[CONF_HOST]})",
            "version": version,
            "variables": variables,
        }
    except PlcComSConnectionError as err:
        raise CannotConnect(str(err)) from err
    finally:
        await client.disconnect()


class TecoматConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tecomat."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._available_variables: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input.get(CONF_PORT, DEFAULT_PORT)

            try:
                info = await validate_connection(self.hass, user_input)
                self._available_variables = info.get("variables", [])

                await self.async_set_unique_id(self._host)
                self._abort_if_unique_id_configured()

                # Create entry with empty entity lists - user configures via options
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                    },
                    options={
                        CONF_LIGHTS: [],
                        CONF_COVERS: [],
                        CONF_COVER_UP_SUFFIX: DEFAULT_COVER_UP_SUFFIX,
                        CONF_COVER_DOWN_SUFFIX: DEFAULT_COVER_DOWN_SUFFIX,
                        CONF_BINARY_SENSORS: [],
                        CONF_SENSORS: [],
                        CONF_SWITCHES: [],
                        CONF_BUTTONS: [],
                    },
                )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return TecoматOptionsFlowHandler(config_entry)


class TecoматOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Tecomat."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._available_variables: list[dict[str, str]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - select entity type to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["lights", "covers", "binary_sensors", "sensors", "switches", "buttons"],
        )

    async def _fetch_variables(self) -> list[dict[str, str]]:
        """Fetch available variables from PLC."""
        if self._available_variables:
            return self._available_variables

        client = PlcComSClient(
            self._config_entry.data[CONF_HOST],
            self._config_entry.data.get(CONF_PORT, DEFAULT_PORT),
        )

        try:
            await client.connect()
            self._available_variables = await client.list_variables()
        except Exception as err:
            _LOGGER.warning("Failed to fetch variables: %s", err)
            self._available_variables = []
        finally:
            await client.disconnect()

        return self._available_variables

    async def _create_variable_selector(
        self, filter_type: str | None = None
    ) -> selector.SelectSelector:
        """Create a variable selector, optionally filtered by type."""
        variables = await self._fetch_variables()

        if filter_type:
            variables = [v for v in variables if v.get("type", "").upper().startswith(filter_type.upper())]

        options = [
            selector.SelectOptionDict(value=v["name"], label=f"{v['name']} ({v.get('type', '?')})")
            for v in sorted(variables, key=lambda x: x["name"])
        ]

        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    async def async_step_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure light entities."""
        if user_input is not None:
            new_options = {**self._config_entry.options, CONF_LIGHTS: user_input.get(CONF_LIGHTS, [])}
            return self.async_create_entry(title="", data=new_options)

        # Filter to BOOL type for lights
        var_selector = await self._create_variable_selector("BOOL")
        current = self._config_entry.options.get(CONF_LIGHTS, [])

        return self.async_show_form(
            step_id="lights",
            data_schema=vol.Schema({
                vol.Optional(CONF_LIGHTS, default=current): var_selector,
            }),
            description_placeholders={"entity_type": "light"},
        )

    async def async_step_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure cover entities (blinds with UP/DN pairs)."""
        if user_input is not None:
            new_options = {
                **self._config_entry.options,
                CONF_COVERS: user_input.get(CONF_COVERS, []),
                CONF_COVER_UP_SUFFIX: user_input.get(CONF_COVER_UP_SUFFIX, DEFAULT_COVER_UP_SUFFIX),
                CONF_COVER_DOWN_SUFFIX: user_input.get(CONF_COVER_DOWN_SUFFIX, DEFAULT_COVER_DOWN_SUFFIX),
            }
            return self.async_create_entry(title="", data=new_options)

        # For covers, user selects base names (without UP/DN suffix)
        # We'll match pairs based on configured suffixes
        variables = await self._fetch_variables()
        bool_vars = [v for v in variables if v.get("type", "").upper() == "BOOL"]

        # Find potential cover bases (variables ending with UP suffix)
        up_suffix = self._config_entry.options.get(CONF_COVER_UP_SUFFIX, DEFAULT_COVER_UP_SUFFIX)
        cover_bases = set()
        for v in bool_vars:
            if v["name"].endswith(up_suffix):
                cover_bases.add(v["name"][:-len(up_suffix)])

        options = [
            selector.SelectOptionDict(value=base, label=base)
            for base in sorted(cover_bases)
        ]

        current_covers = self._config_entry.options.get(CONF_COVERS, [])
        current_up = self._config_entry.options.get(CONF_COVER_UP_SUFFIX, DEFAULT_COVER_UP_SUFFIX)
        current_down = self._config_entry.options.get(CONF_COVER_DOWN_SUFFIX, DEFAULT_COVER_DOWN_SUFFIX)

        return self.async_show_form(
            step_id="covers",
            data_schema=vol.Schema({
                vol.Optional(CONF_COVER_UP_SUFFIX, default=current_up): str,
                vol.Optional(CONF_COVER_DOWN_SUFFIX, default=current_down): str,
                vol.Optional(CONF_COVERS, default=current_covers): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_binary_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure binary sensor entities."""
        if user_input is not None:
            new_options = {**self._config_entry.options, CONF_BINARY_SENSORS: user_input.get(CONF_BINARY_SENSORS, [])}
            return self.async_create_entry(title="", data=new_options)

        var_selector = await self._create_variable_selector("BOOL")
        current = self._config_entry.options.get(CONF_BINARY_SENSORS, [])

        return self.async_show_form(
            step_id="binary_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_BINARY_SENSORS, default=current): var_selector,
            }),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure sensor entities."""
        if user_input is not None:
            new_options = {**self._config_entry.options, CONF_SENSORS: user_input.get(CONF_SENSORS, [])}
            return self.async_create_entry(title="", data=new_options)

        # Sensors can be any numeric type
        variables = await self._fetch_variables()
        numeric_types = ("INT", "SINT", "USINT", "DINT", "UDINT", "REAL", "TIME", "TOD", "DATE", "DT")
        numeric_vars = [v for v in variables if any(v.get("type", "").upper().startswith(t) for t in numeric_types)]

        options = [
            selector.SelectOptionDict(value=v["name"], label=f"{v['name']} ({v.get('type', '?')})")
            for v in sorted(numeric_vars, key=lambda x: x["name"])
        ]

        current = self._config_entry.options.get(CONF_SENSORS, [])

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_SENSORS, default=current): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_switches(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure switch entities."""
        if user_input is not None:
            new_options = {**self._config_entry.options, CONF_SWITCHES: user_input.get(CONF_SWITCHES, [])}
            return self.async_create_entry(title="", data=new_options)

        var_selector = await self._create_variable_selector("BOOL")
        current = self._config_entry.options.get(CONF_SWITCHES, [])

        return self.async_show_form(
            step_id="switches",
            data_schema=vol.Schema({
                vol.Optional(CONF_SWITCHES, default=current): var_selector,
            }),
        )

    async def async_step_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure button entities (momentary triggers)."""
        if user_input is not None:
            new_options = {**self._config_entry.options, CONF_BUTTONS: user_input.get(CONF_BUTTONS, [])}
            return self.async_create_entry(title="", data=new_options)

        var_selector = await self._create_variable_selector("BOOL")
        current = self._config_entry.options.get(CONF_BUTTONS, [])

        return self.async_show_form(
            step_id="buttons",
            data_schema=vol.Schema({
                vol.Optional(CONF_BUTTONS, default=current): var_selector,
            }),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
