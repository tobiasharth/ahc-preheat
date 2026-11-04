"""Needs pytest-homeassistant-custom-component. Run from the repo root: pytest tests/test_integration.py"""

from datetime import timedelta
from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.ahc_preheat.const import CONF_AUTOMATION, CONF_OUTDOOR, DOMAIN

# Stand-in for the real AHC blueprint: same path suffix and input names, no-op action.
FAKE_AHC = """
blueprint:
  name: Fake AHC
  domain: automation
  input:
    input_trvs: {default: []}
    input_schedulers: {default: []}
    input_temperature_comfort: {default: []}
    input_temperature_comfort_static: {default: 22}
    input_temperature_sensor: {default: []}
triggers:
  - trigger: event
    event_type: never_fired
actions: []
"""


async def _setup(hass: HomeAssistant, minutes_to_comfort: int) -> None:
    path = Path(hass.config.path("blueprints/automation/panhans/advanced_heating_control.yaml"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_AHC)
    hass.states.async_set("climate.bad", "heat", {"current_temperature": 18.0, "temperature": 20.5})
    hass.states.async_set("climate.handtuch", "heat", {"current_temperature": 30.0, "temperature": 20.5})
    hass.states.async_set("input_number.bad_komfort", "22.5")
    hass.states.async_set("sensor.outdoor", "5.0", {"device_class": "temperature"})
    hass.states.async_set(
        "schedule.heizplan_bad", "off",
        {"next_event": dt_util.now() + timedelta(minutes=minutes_to_comfort)},
    )
    assert await async_setup_component(hass, "automation", {"automation": [
        {"id": "ahc_bad", "alias": "Heizung Bad", "use_blueprint": {
            "path": "panhans/advanced_heating_control.yaml",
            "input": {
                "input_trvs": ["climate.bad", "climate.handtuch"],
                "input_schedulers": ["schedule.heizplan_bad"],
                "input_temperature_comfort": "input_number.bad_komfort",
            },
        }},
        {"id": "plain", "alias": "Plain", "triggers": [{"trigger": "event", "event_type": "x"}], "actions": []},
    ]})
    await hass.async_block_till_done()


async def _create_entry(hass: HomeAssistant, automation: str, **overrides: object) -> dict:
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    user_input = {
        CONF_AUTOMATION: automation, CONF_OUTDOOR: "sensor.outdoor", "heating_profile": "radiator",
        "buffer_minutes": 10, "max_lead_minutes": 180, **overrides,
    }
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {k: v for k, v in user_input.items() if v is not None}
    )
    await hass.async_block_till_done()
    return result


async def test_preheats_when_comfort_is_within_lead(hass: HomeAssistant) -> None:
    await _setup(hass, minutes_to_comfort=60)
    result = await _create_entry(hass, "automation.heizung_bad")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bad"

    state = hass.states.get("binary_sensor.vorheizen_bad_preheat")
    assert state is not None, [s.entity_id for s in hass.states.async_all() if "vorheizen" in s.entity_id]
    assert state.state == "on"
    assert state.attributes["target"] == 22.5
    assert state.attributes["current"] == 18.0  # towel warmer (2nd thermostat, 30 °C) ignored
    # default model: 10 deadtime + 4.5 K / 1.5 K/h + 10 buffer = 200 min, capped at 180
    lead = hass.states.get("sensor.vorheizen_bad_lead_time")
    assert float(lead.state) == 180.0


async def test_floor_profile_uses_its_own_lead_limit(hass: HomeAssistant) -> None:
    await _setup(hass, minutes_to_comfort=600)
    await _create_entry(hass, "automation.heizung_bad", heating_profile="floor", max_lead_minutes=None)
    # 45 deadtime + 4.5 K / 0.4 K/h + 10 buffer = 730 min, capped at the floor limit of 480
    assert float(hass.states.get("sensor.vorheizen_bad_lead_time").state) == 480.0
    assert hass.states.get("binary_sensor.vorheizen_bad_preheat").state == "off"


async def test_idle_when_comfort_is_far_away(hass: HomeAssistant) -> None:
    await _setup(hass, minutes_to_comfort=600)
    await _create_entry(hass, "automation.heizung_bad")
    assert hass.states.get("binary_sensor.vorheizen_bad_preheat").state == "off"


async def test_follows_schedule_and_comfort_changes(hass: HomeAssistant) -> None:
    await _setup(hass, minutes_to_comfort=600)
    await _create_entry(hass, "automation.heizung_bad")
    hass.states.async_set(
        "schedule.heizplan_bad", "off", {"next_event": dt_util.now() + timedelta(minutes=30)}
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.vorheizen_bad_preheat").state == "on"

    hass.states.async_set("schedule.heizplan_bad", "on", {"next_event": dt_util.now() + timedelta(hours=2)})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.vorheizen_bad_preheat").state == "off"


async def test_rejects_non_ahc_automation(hass: HomeAssistant) -> None:
    await _setup(hass, minutes_to_comfort=60)
    result = await _create_entry(hass, "automation.plain")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_AUTOMATION: "not_ahc"}
