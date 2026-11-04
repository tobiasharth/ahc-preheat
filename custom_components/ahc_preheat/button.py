"""Button to forget everything learned for a room."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PreheatConfigEntry
from .entity import PreheatEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: PreheatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ResetModelButton(entry.runtime_data, "reset_model")])


class ResetModelButton(PreheatEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_reset_model()
