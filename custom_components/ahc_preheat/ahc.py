"""Read an Advanced Heating Control automation's blueprint inputs."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.automation import DATA_COMPONENT
from homeassistant.core import HomeAssistant

from .const import AHC_BLUEPRINT_SUFFIX


@dataclass(frozen=True)
class AhcRoom:
    trvs: tuple[str, ...]
    schedulers: tuple[str, ...]
    comfort_entity: str | None
    comfort_static: float
    temperature_sensor: str | None


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v]
    return []


def read_ahc_room(hass: HomeAssistant, automation_entity_id: str) -> AhcRoom | None:
    """None when the automation is missing or not built on the AHC blueprint."""
    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        return None
    entity = component.get_entity(automation_entity_id)
    if entity is None or not str(entity.referenced_blueprint or "").endswith(AHC_BLUEPRINT_SUFFIX):
        return None
    # ponytail: private attribute — raw_config holds the already-substituted config, not the inputs.
    # Breaks if HA renames it; then read automations.yaml instead.
    blueprint_inputs = getattr(entity, "_blueprint_inputs", None) or {}
    inputs = (blueprint_inputs.get("use_blueprint") or {}).get("input") or {}
    comfort = _as_list(inputs.get("input_temperature_comfort"))
    sensor = _as_list(inputs.get("input_temperature_sensor"))
    try:
        comfort_static = float(inputs.get("input_temperature_comfort_static", 22))
    except (TypeError, ValueError):
        comfort_static = 22.0
    return AhcRoom(
        trvs=tuple(_as_list(inputs.get("input_trvs"))),
        schedulers=tuple(_as_list(inputs.get("input_schedulers"))),
        comfort_entity=comfort[0] if comfort else None,
        comfort_static=comfort_static,
        temperature_sensor=sensor[0] if sensor else None,
    )
