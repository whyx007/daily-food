import math
import random
from typing import Sequence

from app.models import Poi


def seed_text(date: str, grid: str, mode: str, radius: int, nonce: int = 0) -> str:
    parts = [date, grid, mode]
    if mode != "classic":
        parts.append(str(radius))
    if nonce:
        parts.append(f"n{nonce}")
    return "|".join(parts)


def pick(
    pool: Sequence[Poi],
    *,
    date: str,
    grid: str,
    mode: str = "area",
    radius: int = 1000,
    nonce: int = 0,
) -> tuple[Poi, str | None]:
    items = _clean(pool)
    if not items:
        raise ValueError("empty_pool")

    seed = seed_text(date, grid, mode, radius, nonce)
    if len(items) < 3:
        rng = random.Random(seed)
        return rng.choice(items), "pool_too_small"

    rng = random.Random(seed)
    if mode == "weighted":
        median = _median_rating(items)
        weights = [_weight(p, radius, median) for p in items]
        return _weighted_choice(items, weights, rng.random()), None
    index = math.floor(rng.random() * len(items))
    return items[index], None


def _clean(pool: Sequence[Poi]) -> list[Poi]:
    seen: set[str] = set()
    out: list[Poi] = []
    for poi in pool:
        if not poi.id or not poi.name or poi.id in seen:
            continue
        seen.add(poi.id)
        out.append(poi)
    return out


def _rating(poi: Poi) -> float | None:
    try:
        value = float(poi.rating) if poi.rating not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if value is None or not 0 < value <= 5:
        return None
    return value


def _median_rating(items: Sequence[Poi]) -> float:
    ratings = sorted(r for r in (_rating(p) for p in items) if r is not None)
    if not ratings:
        return 2.5
    return ratings[len(ratings) // 2]


def _weight(poi: Poi, radius: int, median: float) -> float:
    rating = _rating(poi)
    rating_norm = (rating if rating is not None else median) / 5.0
    distance = poi.distance or 0
    distance_decay = 1.0 - min(distance / max(radius, 1), 1.0)
    score = 0.65 * rating_norm + 0.35 * distance_decay
    return score ** 2 + 1e-6


def _weighted_choice(items: Sequence[Poi], weights: Sequence[float], rnd: float) -> Poi:
    total = sum(weights)
    cursor = rnd * total
    for poi, weight in zip(items, weights):
        cursor -= weight
        if cursor <= 0:
            return poi
    return items[-1]
