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
    CONF_COVER_NAME,
    CONF_COVER_UP_VAR,
    CONF_COVER_DOWN_VAR,
    CONF_COVER_POSITION_VAR,
    CONF_COVER_TILT_UP_VAR,
    CONF_COVER_TILT_DOWN_VAR,
    CONF_BINARY_SENSORS,
    CONF_SENSORS,
    CONF_SWITCHES,
    CONF_BUTTONS,
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
                        CONF_COVERS: [],  # List of cover config dicts
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
        """Configure cover entities - show menu to add or manage covers."""
        current_covers = self._config_entry.options.get(CONF_COVERS, [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add_cover":
                return await self.async_step_add_cover()
            if action and action.startswith("delete_"):
                # Delete a cover by index
                idx = int(action.split("_")[1])
                new_covers = [c for i, c in enumerate(current_covers) if i != idx]
                new_options = {**self._config_entry.options, CONF_COVERS: new_covers}
                return self.async_create_entry(title="", data=new_options)
            # Done - return to main menu
            return await self.async_step_init()

        # Build menu options
        menu_options = [
            selector.SelectOptionDict(value="add_cover", label="Add new cover"),
        ]
        # Add delete options for existing covers
        for idx, cover in enumerate(current_covers):
            if isinstance(cover, dict):
                cover_name = cover.get(CONF_COVER_NAME, f"Cover {idx + 1}")
            else:
                # Legacy format: cover is a string (base name)
                cover_name = str(cover)
            menu_options.append(
                selector.SelectOptionDict(value=f"delete_{idx}", label=f"Delete: {cover_name}")
            )
        menu_options.append(selector.SelectOptionDict(value="done", label="Done"))

        # Show current covers info
        description = f"Currently configured covers: {len(current_covers)}"
        if current_covers:
            names = []
            for c in current_covers:
                if isinstance(c, dict):
                    names.append(c.get(CONF_COVER_NAME, "Unnamed"))
                else:
                    names.append(str(c))
            description += f"\n{', '.join(names)}"

        return self.async_show_form(
            step_id="covers",
            data_schema=vol.Schema({
                vol.Required("action"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=menu_options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
            description_placeholders={"cover_count": str(len(current_covers))},
        )

    async def async_step_add_cover(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a new cover with individual variable selection."""
        if user_input is not None:
            # Create cover config dict
            cover_config = {
                CONF_COVER_NAME: user_input.get(CONF_COVER_NAME, ""),
                CONF_COVER_UP_VAR: user_input.get(CONF_COVER_UP_VAR, ""),
                CONF_COVER_DOWN_VAR: user_input.get(CONF_COVER_DOWN_VAR, ""),
            }
            # Add optional fields if provided
            if user_input.get(CONF_COVER_TILT_UP_VAR):
                cover_config[CONF_COVER_TILT_UP_VAR] = user_input[CONF_COVER_TILT_UP_VAR]
            if user_input.get(CONF_COVER_TILT_DOWN_VAR):
                cover_config[CONF_COVER_TILT_DOWN_VAR] = user_input[CONF_COVER_TILT_DOWN_VAR]
            if user_input.get(CONF_COVER_POSITION_VAR):
                cover_config[CONF_COVER_POSITION_VAR] = user_input[CONF_COVER_POSITION_VAR]

            # Add to existing covers
            current_covers = list(self._config_entry.options.get(CONF_COVERS, []))
            current_covers.append(cover_config)

            new_options = {**self._config_entry.options, CONF_COVERS: current_covers}
            return self.async_create_entry(title="", data=new_options)

        # Fetch all BOOL variables for control selection
        variables = await self._fetch_variables()
        bool_vars = [v for v in variables if v.get("type", "").upper() == "BOOL"]
        bool_options = [
            selector.SelectOptionDict(value=v["name"], label=v["name"])
            for v in sorted(bool_vars, key=lambda x: x["name"])
        ]

        # Fetch numeric variables for position (USINT typically 0-100)
        numeric_types = ("USINT", "INT", "SINT", "UINT")
        numeric_vars = [v for v in variables if any(v.get("type", "").upper().startswith(t) for t in numeric_types)]
        position_options = [
            selector.SelectOptionDict(value="", label="(None)"),
        ] + [
            selector.SelectOptionDict(value=v["name"], label=f"{v['name']} ({v.get('type', '?')})")
            for v in sorted(numeric_vars, key=lambda x: x["name"])
        ]

        # Add empty option for optional fields
        optional_bool_options = [
            selector.SelectOptionDict(value="", label="(None)"),
        ] + bool_options

        return self.async_show_form(
            step_id="add_cover",
            data_schema=vol.Schema({
                vol.Required(CONF_COVER_NAME): str,
                vol.Required(CONF_COVER_UP_VAR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=bool_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_COVER_DOWN_VAR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=bool_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_COVER_TILT_UP_VAR, default=""): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=optional_bool_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_COVER_TILT_DOWN_VAR, default=""): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=optional_bool_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_COVER_POSITION_VAR, default=""): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=position_options,
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
