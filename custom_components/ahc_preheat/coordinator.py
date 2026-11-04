"""Per-room coordinator: reads AHC, learns warm-up, decides when to preheat."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from statistics import mean

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .ahc import AhcRoom, read_ahc_room
from .const import (
    CONF_AUTOMATION,
    CONF_BUFFER,
    CONF_MAX_LEAD,
    CONF_OUTDOOR,
    DEFAULT_BUFFER,
    DEFAULT_MAX_LEAD,
    DOMAIN,
    STORAGE_VERSION,
)
from .model import RampTracker, RoomModel, preheat_window_open

_LOGGER = logging.getLogger(__name__)


@dataclass
class PreheatState:
    preheat: bool
    in_comfort: bool
    next_comfort: datetime | None
    preheat_start: datetime | None
    lead_min: float | None
    target: float | None
    current: float | None
    outdoor: float | None
    rate: float
    deadtime_min: float
    samples: int
    problem: str | None


def _float_state(hass: HomeAssistant, entity_id: str | None, attribute: str | None = None) -> float | None:
    if not entity_id or (state := hass.states.get(entity_id)) is None:
        return None
    raw = state.attributes.get(attribute) if attribute else state.state
    if raw in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class PreheatCoordinator(DataUpdateCoordinator[PreheatState]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=1),
        )
        self.automation_id: str = entry.data[CONF_AUTOMATION]
        self.model = RoomModel()
        self.tracker = RampTracker()
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._tracked: frozenset[str] = frozenset()
        self._unsub_states: CALLBACK_TYPE | None = None

    async def async_load(self) -> None:
        self.model = RoomModel.from_dict(await self._store.async_load())

    @callback
    def async_shutdown_listeners(self) -> None:
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None

    def _option(self, key: str, default: float | str | None) -> float | str | None:
        return self.config_entry.options.get(key, self.config_entry.data.get(key, default))

    def _outdoor(self) -> float | None:
        entity_id = self._option(CONF_OUTDOOR, None)
        if not isinstance(entity_id, str):
            return None
        attribute = "temperature" if entity_id.startswith("weather.") else None
        return _float_state(self.hass, entity_id, attribute)

    def _current(self, room: AhcRoom) -> float | None:
        if (value := _float_state(self.hass, room.temperature_sensor)) is not None:
            return value
        readings = [v for t in room.trvs if (v := _float_state(self.hass, t, "current_temperature")) is not None]
        return mean(readings) if readings else None

    def _comfort_window(self, room: AhcRoom) -> tuple[bool, datetime | None]:
        # ponytail: ignores AHC's schedule selector; with several schedules the earliest start wins.
        in_comfort, starts = False, []
        for scheduler in room.schedulers:
            if (state := self.hass.states.get(scheduler)) is None:
                continue
            if state.state == STATE_ON:
                in_comfort = True
            elif isinstance(nxt := state.attributes.get("next_event"), datetime):
                starts.append(nxt)
        return in_comfort, min(starts, default=None)

    def _track(self, room: AhcRoom) -> None:
        wanted = frozenset(
            e for e in (*room.trvs, *room.schedulers, room.comfort_entity, room.temperature_sensor,
                        self._option(CONF_OUTDOOR, None))
            if isinstance(e, str)
        )
        if wanted == self._tracked:
            return
        self.async_shutdown_listeners()
        self._tracked = wanted
        self._unsub_states = async_track_state_change_event(self.hass, list(wanted), self._on_state_change)

    @callback
    def _on_state_change(self, _event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self.async_refresh())

    def _learn(self, now: datetime, room: AhcRoom, current: float, outdoor: float | None) -> None:
        trv_target = _float_state(self.hass, room.trvs[0], "temperature") if room.trvs else None
        if trv_target is None:
            return
        result = self.tracker.update(now, current, trv_target, outdoor)
        if result is None:
            return
        if result.deadtime_min is not None:
            self.model.add_deadtime(result.deadtime_min)
        if result.rate is not None:
            self.model.add_sample(result.rate, result.gap)
            _LOGGER.debug("%s learned %.2f K/h at gap %s", self.automation_id, result.rate, result.gap)
        self._store.async_delay_save(self.model.to_dict, 30)

    async def _async_update_data(self) -> PreheatState:
        now = dt_util.now()
        room = read_ahc_room(self.hass, self.automation_id)
        if room is None:
            return self._empty(f"{self.automation_id} is missing or not an AHC automation")
        self._track(room)
        current, outdoor = self._current(room), self._outdoor()
        target = _float_state(self.hass, room.comfort_entity) or room.comfort_static
        in_comfort, next_comfort = self._comfort_window(room)
        if current is None:
            return self._empty("no room temperature", in_comfort, next_comfort, target)
        self._learn(now, room, current, outdoor)
        buffer_min = float(self._option(CONF_BUFFER, DEFAULT_BUFFER) or 0)
        max_lead = float(self._option(CONF_MAX_LEAD, DEFAULT_MAX_LEAD) or DEFAULT_MAX_LEAD)
        lead = min(self.model.lead_minutes(current, target, outdoor, buffer_min), max_lead)
        gap = current - outdoor if outdoor is not None else self.model.typical_gap()
        return PreheatState(
            preheat=not in_comfort and preheat_window_open(now, next_comfort, lead, max_lead),
            in_comfort=in_comfort,
            next_comfort=next_comfort,
            preheat_start=next_comfort - timedelta(minutes=lead) if next_comfort and lead > 0 else next_comfort,
            lead_min=round(lead, 1),
            target=target,
            current=current,
            outdoor=outdoor,
            rate=round(self.model.rate_for(gap), 2),
            deadtime_min=round(self.model.deadtime_min, 1),
            samples=len(self.model.samples),
            problem=None,
        )

    def _empty(
        self, problem: str, in_comfort: bool = False, next_comfort: datetime | None = None,
        target: float | None = None,
    ) -> PreheatState:
        return PreheatState(
            preheat=False, in_comfort=in_comfort, next_comfort=next_comfort, preheat_start=None,
            lead_min=None, target=target, current=None, outdoor=self._outdoor(),
            rate=round(self.model.rate_for(None), 2), deadtime_min=round(self.model.deadtime_min, 1),
            samples=len(self.model.samples), problem=problem,
        )

    async def async_reset_model(self) -> None:
        self.model = RoomModel()
        self.tracker = RampTracker()
        await self._store.async_save(self.model.to_dict())
        await self.async_refresh()
