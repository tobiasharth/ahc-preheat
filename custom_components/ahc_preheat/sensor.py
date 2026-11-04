"""Diagnostic sensors: next start, lead time, learned rate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PreheatConfigEntry
from .coordinator import PreheatCoordinator, PreheatState
from .entity import PreheatEntity


@dataclass(frozen=True, kw_only=True)
class PreheatSensorDescription(SensorEntityDescription):
    value: Callable[[PreheatState], float | int | datetime | None]


SENSORS = (
    PreheatSensorDescription(
        key="preheat_start", device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda d: d.preheat_start,
    ),
    PreheatSensorDescription(
        key="lead_time", native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION, value=lambda d: d.lead_min,
    ),
    PreheatSensorDescription(
        key="heating_rate", native_unit_of_measurement="K/h", state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.rate,
    ),
    PreheatSensorDescription(
        key="measurements", state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC, value=lambda d: d.samples,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PreheatConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PreheatSensor(entry.runtime_data, d) for d in SENSORS)


class PreheatSensor(PreheatEntity, SensorEntity):
    entity_description: PreheatSensorDescription

    def __init__(self, coordinator: PreheatCoordinator, description: PreheatSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | datetime | None:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "heating_rate":
            return None
        return {"deadtime_min": self.coordinator.data.deadtime_min}
