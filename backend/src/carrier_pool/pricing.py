from __future__ import annotations

import math
from dataclasses import dataclass

from .geo import GeoIndex
from .models import CanonicalStore, Equipment, LoadStatus, LoadVersion

SHRINKAGE_K = 4.0
LANE_DECAY_MILES = 35.0
REVERSE_LANE_DISCOUNT = 0.35


@dataclass(frozen=True)
class PriceEstimate:
    point_usd: float
    low_usd: float
    high_usd: float
    point_ppm: float
    observed_ppm: float
    prior_ppm: float
    basis: str
    effective_loads: float
    confidence: str
    comparables: list[dict[str, float | str | None]]
    reasons: list[str]
    limitations: list[str]


def equipment_affinity(target: Equipment, historical: Equipment) -> float:
    if target == historical:
        return 1.0
    if target == Equipment.UNKNOWN or historical == Equipment.UNKNOWN:
        return 0.6
    return 0.35


def geographic_lane_weight(target: LoadVersion, historical: LoadVersion, geo: GeoIndex) -> tuple[float, float, float]:
    direct = math.exp(-geo.miles(target.pickup.zip_code, historical.pickup.zip_code) / LANE_DECAY_MILES) * math.exp(
        -geo.miles(target.delivery.zip_code, historical.delivery.zip_code) / LANE_DECAY_MILES
    )
    reverse = REVERSE_LANE_DISCOUNT * math.exp(-geo.miles(target.pickup.zip_code, historical.delivery.zip_code) / LANE_DECAY_MILES) * math.exp(
        -geo.miles(target.delivery.zip_code, historical.pickup.zip_code) / LANE_DECAY_MILES
    )
    return max(direct, reverse), direct, reverse


def lane_weight(target: LoadVersion, historical: LoadVersion, geo: GeoIndex) -> tuple[float, float, float]:
    affinity = equipment_affinity(target.equipment, historical.equipment)
    total, direct, reverse = geographic_lane_weight(target, historical, geo)
    return total * affinity, direct * affinity, reverse * affinity


def estimate_price(store: CanonicalStore, target: LoadVersion, geo: GeoIndex | None = None, as_of=None) -> PriceEstimate:
    geo = geo or GeoIndex.bundled()
    as_of = as_of or target.synced_at
    history = _priced_history(store, target, as_of)
    broker_prior = _broker_equipment_prior(history, target)

    lane = _weighted_rates(history, target, geo, mode="lane")
    if lane.effective_loads >= 0.75:
        return _estimate_from_rates(target, lane, broker_prior, "similar_lane")

    distance = _weighted_rates(history, target, geo, mode="distance")
    if distance.effective_loads >= 1.0:
        return _estimate_from_rates(target, distance, broker_prior, "distance_band")

    broker = _weighted_rates(history, target, geo, mode="broker_equipment")
    return _estimate_from_rates(target, broker, broker_prior, "broker_equipment_prior")


def estimate_carrier_price(store: CanonicalStore, target: LoadVersion, carrier_id: str, geo: GeoIndex | None = None, as_of=None, market_prior: float | None = None) -> PriceEstimate:
    geo = geo or GeoIndex.bundled()
    as_of = as_of or target.synced_at
    broker_history = _priced_history(store, target, as_of)
    carrier_history = [load for load in broker_history if load.carrier_id == carrier_id]
    market_prior = estimate_price(store, target, geo, as_of=as_of).point_ppm if market_prior is None else market_prior

    lane = _weighted_rates(carrier_history, target, geo, mode="lane")
    if lane.effective_loads >= 0.35:
        return _estimate_from_rates(target, lane, market_prior, "carrier_similar_lane")

    distance = _weighted_rates(carrier_history, target, geo, mode="distance")
    if distance.effective_loads >= 0.75:
        return _estimate_from_rates(target, distance, market_prior, "carrier_distance_band")

    carrier = _weighted_rates(carrier_history, target, geo, mode="broker_equipment")
    if carrier.effective_loads > 0:
        return _estimate_from_rates(target, carrier, market_prior, "carrier_history_prior")

    return _estimate_from_rates(target, _WeightedRates([], 0.0, market_prior, 0.0), market_prior, "broker_market_fallback")


def _priced_history(store: CanonicalStore, target: LoadVersion, as_of) -> list[LoadVersion]:
    return [
        load
        for load in store.loads_as_of(target.broker_id, as_of)
        if load.broker_id == target.broker_id
        and load.raw_load_id != target.raw_load_id
        and load.carrier_id is not None
        and load.carrier_rate_usd is not None
        and load.distance_miles > 0
        and load.status in {LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED}
    ]


@dataclass(frozen=True)
class _WeightedRate:
    load: LoadVersion
    weight: float
    ppm: float


@dataclass(frozen=True)
class _WeightedRates:
    rates: list[_WeightedRate]
    effective_loads: float
    observed_ppm: float
    dispersion_ppm: float


def _weighted_rates(history: list[LoadVersion], target: LoadVersion, geo: GeoIndex, mode: str) -> _WeightedRates:
    rates = []
    for load in history:
        if not load.carrier_rate_usd or load.distance_miles <= 0:
            continue
        if mode == "lane":
            weight = lane_weight(target, load, geo)[0]
        elif mode == "distance":
            weight = _distance_band_weight(target, load) * equipment_affinity(target.equipment, load.equipment)
        elif mode == "broker_equipment":
            weight = equipment_affinity(target.equipment, load.equipment)
        else:
            raise ValueError(f"Unknown pricing mode {mode!r}")
        if weight <= 0:
            continue
        rates.append(_WeightedRate(load=load, weight=weight, ppm=load.carrier_rate_usd / load.distance_miles))
    return _summarize(rates)


def _distance_band_weight(target: LoadVersion, historical: LoadVersion) -> float:
    if target.distance_miles <= 0 or historical.distance_miles <= 0:
        return 0.0
    return math.exp(-abs(math.log(historical.distance_miles / target.distance_miles)) / 0.35)


def _summarize(rates: list[_WeightedRate]) -> _WeightedRates:
    effective = sum(rate.weight for rate in rates)
    if effective <= 0:
        return _WeightedRates(rates=[], effective_loads=0.0, observed_ppm=0.0, dispersion_ppm=0.0)
    observed = sum(rate.weight * rate.ppm for rate in rates) / effective
    variance = sum(rate.weight * (rate.ppm - observed) ** 2 for rate in rates) / effective
    return _WeightedRates(rates=rates, effective_loads=effective, observed_ppm=observed, dispersion_ppm=math.sqrt(variance))


def _broker_equipment_prior(history: list[LoadVersion], target: LoadVersion) -> float:
    weighted = _summarize(
        [
            _WeightedRate(load=load, weight=max(0.2, equipment_affinity(target.equipment, load.equipment)), ppm=load.carrier_rate_usd / load.distance_miles)
            for load in history
            if load.carrier_rate_usd and load.distance_miles > 0
        ]
    )
    return weighted.observed_ppm if weighted.effective_loads else 4.0


def _estimate_from_rates(target: LoadVersion, weighted: _WeightedRates, prior_ppm: float, basis: str) -> PriceEstimate:
    if weighted.effective_loads > 0:
        point_ppm = ((weighted.effective_loads * weighted.observed_ppm) + (SHRINKAGE_K * prior_ppm)) / (weighted.effective_loads + SHRINKAGE_K)
        observed_ppm = weighted.observed_ppm
    else:
        point_ppm = prior_ppm
        observed_ppm = prior_ppm

    base_dispersion = max(weighted.dispersion_ppm, point_ppm * 0.08)
    uncertainty_multiplier = 1.0 + (1.0 / math.sqrt(weighted.effective_loads + 0.25))
    band_ppm = base_dispersion * uncertainty_multiplier
    point_usd = point_ppm * target.distance_miles
    low_usd = max(0.0, (point_ppm - band_ppm) * target.distance_miles)
    high_usd = (point_ppm + band_ppm) * target.distance_miles

    return PriceEstimate(
        point_usd=round(point_usd, 2),
        low_usd=round(low_usd, 2),
        high_usd=round(high_usd, 2),
        point_ppm=round(point_ppm, 2),
        observed_ppm=round(observed_ppm, 2),
        prior_ppm=round(prior_ppm, 2),
        basis=basis,
        effective_loads=round(weighted.effective_loads, 2),
        confidence=_confidence(basis, weighted.effective_loads),
        comparables=_comparables(weighted),
        reasons=_reasons(basis, weighted, observed_ppm, prior_ppm),
        limitations=_limitations(basis, weighted),
    )


def _confidence(basis: str, effective_loads: float) -> str:
    if basis in {"similar_lane", "carrier_similar_lane"} and effective_loads >= 4:
        return "high"
    if basis in {"similar_lane", "carrier_similar_lane"} and effective_loads >= 1.25:
        return "medium"
    return "low"


def _comparables(weighted: _WeightedRates) -> list[dict[str, float | str | None]]:
    rows = []
    for rate in sorted(weighted.rates, key=lambda item: item.weight, reverse=True)[:8]:
        load = rate.load
        rows.append(
            {
                "load_id": load.raw_load_id,
                "source_file": load.source_file,
                "carrier_id": load.carrier_id,
                "origin": f"{load.pickup.city}, {load.pickup.state} {load.pickup.zip_code}",
                "destination": f"{load.delivery.city}, {load.delivery.state} {load.delivery.zip_code}",
                "equipment": load.equipment.value,
                "weight": round(rate.weight, 3),
                "ppm": round(rate.ppm, 2),
                "carrier_rate_usd": round(load.carrier_rate_usd or 0.0, 2),
            }
        )
    return rows


def _reasons(basis: str, weighted: _WeightedRates, observed_ppm: float, prior_ppm: float) -> list[str]:
    labels = {
        "similar_lane": "similar lane history",
        "distance_band": "same-broker distance-band history",
        "broker_equipment_prior": "broker equipment prior",
        "carrier_similar_lane": "carrier-specific similar lane history",
        "carrier_distance_band": "carrier-specific distance-band history",
        "carrier_history_prior": "carrier-specific broker history",
        "broker_market_fallback": "broker market fallback",
    }
    return [
        f"based on {weighted.effective_loads:.1f} effective loads from {labels[basis]}",
        f"observed ${observed_ppm:.2f}/mi shrunk toward ${prior_ppm:.2f}/mi prior",
    ]


def _limitations(basis: str, weighted: _WeightedRates) -> list[str]:
    limitations = []
    if basis not in {"similar_lane", "carrier_similar_lane"}:
        limitations.append("no strong similar-lane price history; estimate uses fallback evidence")
    if weighted.effective_loads < 1:
        limitations.append("very thin price evidence")
    elif weighted.effective_loads < 3:
        limitations.append("limited price evidence; range widened for uncertainty")
    return limitations
