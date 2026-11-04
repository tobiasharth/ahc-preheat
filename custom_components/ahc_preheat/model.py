"""Learning model for room warm-up. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, median

MIN_RATE_K_PER_H = 0.05
MAX_RATE_K_PER_H = 6.0
MAX_SAMPLES = 30
MIN_SAMPLES_FOR_FIT = 4
DEADTIME_ALPHA = 0.3

RAMP_START_DELTA_K = 0.5
RISE_DETECT_K = 0.2
REACHED_TOLERANCE_K = 0.2
MIN_RISE_K = 0.3
MIN_MEASURE_MIN = 10.0


@dataclass(frozen=True)
class Profile:
    """Starting values and limits per heating type; learning refines rate and deadtime."""

    default_rate: float
    default_deadtime_min: float
    max_deadtime_min: float
    max_ramp_hours: float
    max_lead_min: float


PROFILES: dict[str, Profile] = {
    "floor": Profile(default_rate=0.4, default_deadtime_min=45.0, max_deadtime_min=240.0,
                     max_ramp_hours=12.0, max_lead_min=480.0),
    "radiator": Profile(default_rate=1.5, default_deadtime_min=10.0, max_deadtime_min=90.0,
                        max_ramp_hours=6.0, max_lead_min=180.0),
}
DEFAULT_PROFILE = "floor"


@dataclass
class Sample:
    rate: float
    gap: float | None


@dataclass
class RoomModel:
    profile: Profile = PROFILES[DEFAULT_PROFILE]
    samples: list[Sample] = field(default_factory=list)
    deadtime_min: float | None = None

    def __post_init__(self) -> None:
        if self.deadtime_min is None:
            self.deadtime_min = self.profile.default_deadtime_min

    def add_sample(self, rate: float, gap: float | None) -> None:
        clamped = min(max(rate, MIN_RATE_K_PER_H), MAX_RATE_K_PER_H)
        self.samples.append(Sample(clamped, gap))
        del self.samples[:-MAX_SAMPLES]

    def add_deadtime(self, minutes: float) -> None:
        bounded = min(max(minutes, 0.0), self.profile.max_deadtime_min)
        self.deadtime_min += DEADTIME_ALPHA * (bounded - self.deadtime_min)

    def rate_for(self, gap: float | None) -> float:
        """Warm-up rate in K/h; slower when it is colder outside (bigger gap)."""
        if not self.samples:
            return self.profile.default_rate
        fitted = self._fit()
        if fitted is None or gap is None:
            return mean(s.rate for s in self.samples)
        intercept, slope = fitted
        return min(max(intercept + slope * gap, MIN_RATE_K_PER_H), MAX_RATE_K_PER_H)

    def _fit(self) -> tuple[float, float] | None:
        points = [(s.gap, s.rate) for s in self.samples if s.gap is not None]
        if len(points) < MIN_SAMPLES_FOR_FIT:
            return None
        gap_mean = mean(p[0] for p in points)
        rate_mean = mean(p[1] for p in points)
        spread = sum((g - gap_mean) ** 2 for g, _ in points)
        # Gaps all alike: slope is pure noise, fall back to the plain mean.
        if spread < 4.0:
            return None
        slope = sum((g - gap_mean) * (r - rate_mean) for g, r in points) / spread
        # A warmer outside can't make heating slower; reject inverted fits.
        if slope > 0:
            return None
        return rate_mean - slope * gap_mean, slope

    def typical_gap(self) -> float | None:
        gaps = [s.gap for s in self.samples if s.gap is not None]
        return median(gaps) if gaps else None

    def lead_minutes(
        self, current: float, target: float, outdoor: float | None, buffer_min: float
    ) -> float:
        delta = target - current
        if delta <= 0:
            return 0.0
        gap = current - outdoor if outdoor is not None else self.typical_gap()
        return self.deadtime_min + delta / self.rate_for(gap) * 60.0 + buffer_min

    def to_dict(self) -> dict:
        return {
            "samples": [[s.rate, s.gap] for s in self.samples],
            "deadtime_min": self.deadtime_min,
        }

    @classmethod
    def from_dict(cls, data: dict | None, profile: Profile) -> RoomModel:
        if not data:
            return cls(profile=profile)
        samples = [Sample(float(r), None if g is None else float(g)) for r, g in data.get("samples", [])]
        # Without measurements the stored deadtime is just an old default; take the profile's.
        deadtime = data.get("deadtime_min") if samples else None
        return cls(profile=profile, samples=samples, deadtime_min=None if deadtime is None else float(deadtime))


def preheat_window_open(
    now: datetime, next_start: datetime | None, lead_min: float, max_lead_min: float
) -> bool:
    if next_start is None or lead_min <= 0:
        return False
    remaining = next_start - now
    return timedelta(0) < remaining <= timedelta(minutes=min(lead_min, max_lead_min))


@dataclass
class RampResult:
    rate: float | None
    gap: float | None
    deadtime_min: float | None


@dataclass
class RampTracker:
    """Measures one heat-up ramp: setpoint raised -> room reaches it."""

    profile: Profile = PROFILES[DEFAULT_PROFILE]
    start_time: datetime | None = None
    start_temp: float = 0.0
    gap: float | None = None
    rise_time: datetime | None = None
    rise_temp: float = 0.0

    @property
    def active(self) -> bool:
        return self.start_time is not None

    def update(
        self, now: datetime, current: float, target: float, outdoor: float | None
    ) -> RampResult | None:
        if not self.active:
            if target - current >= RAMP_START_DELTA_K:
                self.start_time, self.start_temp = now, current
                self.gap = current - outdoor if outdoor is not None else None
                self.rise_time = None
            return None

        if self.rise_time is None and current >= self.start_temp + RISE_DETECT_K:
            self.rise_time, self.rise_temp = now, current

        reached = current >= target - REACHED_TOLERANCE_K
        aborted = target < current + REACHED_TOLERANCE_K and not reached
        timed_out = now - self.start_time > timedelta(hours=self.profile.max_ramp_hours)
        if not (reached or aborted or timed_out):
            return None
        return self._finish(now, current)

    def _finish(self, now: datetime, current: float) -> RampResult | None:
        start_time, rise_time = self.start_time, self.rise_time
        self.start_time = None
        if start_time is None or rise_time is None:
            return None
        measured_min = (now - rise_time).total_seconds() / 60.0
        rise = current - self.rise_temp
        deadtime = (rise_time - start_time).total_seconds() / 60.0
        if measured_min < MIN_MEASURE_MIN or rise < MIN_RISE_K:
            return RampResult(None, self.gap, deadtime)
        return RampResult(rise / (measured_min / 60.0), self.gap, deadtime)
