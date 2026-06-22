"""Pure signal logic for METAR-based daily-high nowcasting. No network/DB I/O here.

Core idea: Polymarket's "Highest temperature in {city} on {date}" markets resolve
to a whole-degree-C bucket containing the day's actual max temperature, sourced
from the airport station's observations. The day's running max-so-far only ever
increases through the day, so any bucket whose upper bound is already exceeded
by the running max is mathematically dead -- it cannot be the final answer.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")

_BUCKET_RE = re.compile(r"(-?\d+)\s*°?C?")


@dataclass(frozen=True)
class MetarObs:
    obs_time_utc: int  # epoch seconds, UTC
    temp_c: float


@dataclass(frozen=True)
class Bucket:
    label: str
    lower: float  # -inf for open-ended "or below"
    upper: float  # +inf for open-ended "or higher"


def parse_bucket(label: str) -> Bucket:
    """Parse outcome labels like '37°C', '36°C or below', '46°C or higher'."""
    match = _BUCKET_RE.search(label)
    if not match:
        raise ValueError(f"cannot parse bucket label: {label!r}")
    value = float(match.group(1))
    lowered = label.lower()
    if "or below" in lowered:
        return Bucket(label, -math.inf, value)
    if "or higher" in lowered or "or above" in lowered:
        return Bucket(label, value, math.inf)
    return Bucket(label, value, value)


def local_date(obs_time_utc: int, tz: ZoneInfo = MADRID_TZ) -> dt.date:
    return dt.datetime.fromtimestamp(obs_time_utc, tz=tz).date()


def running_max_series(obs: list[MetarObs], target_date: dt.date, tz: ZoneInfo = MADRID_TZ) -> list[tuple[int, float]]:
    """Chronological [(obs_time_utc, running_max_so_far), ...] restricted to one local civil day.

    A >90 minute gap between consecutive observations marks the signal "stale" by
    omission -- callers should not trust a running max that hasn't been refreshed
    recently late in the day. This function does not hide that; it is surfaced via
    `staleness_gaps`.
    """
    day_obs = sorted(
        (o for o in obs if local_date(o.obs_time_utc, tz) == target_date),
        key=lambda o: o.obs_time_utc,
    )
    series = []
    running = -math.inf
    for o in day_obs:
        running = max(running, o.temp_c)
        series.append((o.obs_time_utc, running))
    return series


def staleness_gaps(obs_times: list[int], max_gap_seconds: int = 90 * 60) -> list[tuple[int, int]]:
    """Return [(gap_start, gap_end), ...] for consecutive obs more than max_gap_seconds apart."""
    gaps = []
    for prev, cur in zip(obs_times, obs_times[1:]):
        if cur - prev > max_gap_seconds:
            gaps.append((prev, cur))
    return gaps


def dead_buckets(running_max_so_far: float, buckets: list[Bucket]) -> set[str]:
    """Buckets whose upper bound is strictly below the running max -- mathematically eliminated."""
    return {b.label for b in buckets if b.upper < running_max_so_far}


def first_death_times(obs: list[MetarObs], target_date: dt.date, buckets: list[Bucket], tz: ZoneInfo = MADRID_TZ) -> dict[str, int]:
    """For each bucket, the obs_time_utc at which it first became dead (absent if never, within the obs given)."""
    series = running_max_series(obs, target_date, tz)
    death_time: dict[str, int] = {}
    for obs_time, running_max in series:
        for label in dead_buckets(running_max, buckets):
            death_time.setdefault(label, obs_time)
    return death_time
