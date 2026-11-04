"""Config flow: one entry per AHC automation (room)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .ahc import read_ahc_room
from .const import (
    CONF_AUTOMATION,
    CONF_BUFFER,
    CONF_MAX_LEAD,
    CONF_OUTDOOR,
    DEFAULT_BUFFER,
    DEFAULT_MAX_LEAD,
    DOMAIN,
)

OUTDOOR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        filter=[selector.EntityFilterSelectorConfig(domain="sensor", device_class="temperature"),
                selector.EntityFilterSelectorConfig(domain="weather")]
    )
)
MINUTES = selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=360, step=5, unit_of_measurement="min", mode="box")
)


def _tuning_schema(defaults: dict[str, Any]) -> dict:
    outdoor = defaults.get(CONF_OUTDOOR)
    return {
        vol.Optional(CONF_OUTDOOR, **({"default": outdoor} if outdoor else {})): OUTDOOR_SELECTOR,
        vol.Required(CONF_BUFFER, default=defaults.get(CONF_BUFFER, DEFAULT_BUFFER)): MINUTES,
        vol.Required(CONF_MAX_LEAD, default=defaults.get(CONF_MAX_LEAD, DEFAULT_MAX_LEAD)): MINUTES,
    }


class AhcPreheatConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            automation = user_input[CONF_AUTOMATION]
            room = read_ahc_room(self.hass, automation)
            if room is None:
                errors[CONF_AUTOMATION] = "not_ahc"
            elif not room.schedulers:
                errors[CONF_AUTOMATION] = "no_schedule"
            else:
                await self.async_set_unique_id(automation)
                self._abort_if_unique_id_configured()
                state = self.hass.states.get(automation)
                name = state.name if state else automation
                return self.async_create_entry(title=name.removeprefix("Heizung ").strip(), data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_AUTOMATION): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="automation")
            ),
            **_tuning_schema(user_input or {}),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AhcPreheatOptionsFlow()


class AhcPreheatOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # An emptied selector is omitted; store None so it overrides the setup value.
            return self.async_create_entry(data={CONF_OUTDOOR: None, **user_input})
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema(_tuning_schema(current)))
