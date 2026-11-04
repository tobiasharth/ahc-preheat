"""Preheat signal for AHC's presence-sensor input."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PreheatConfigEntry
from .entity import PreheatEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: PreheatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([PreheatBinarySensor(entry.runtime_data, "preheat")])


class PreheatBinarySensor(PreheatEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.preheat

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "automation": self.coordinator.automation_id,
            "in_comfort": data.in_comfort,
            "next_comfort": data.next_comfort,
            "target": data.target,
            "current": data.current,
            "outdoor": data.outdoor,
            "problem": data.problem,
        }
