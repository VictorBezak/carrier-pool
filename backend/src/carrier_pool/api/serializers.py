from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from carrier_pool.geo import GeoIndex, ZipCentroid
from carrier_pool.models import Carrier, CarrierRanking, ComponentScore, LoadVersion
from carrier_pool.pool import PoolCarrierRanking
from carrier_pool.pricing import PriceEstimate, lane_weight
from carrier_pool.ranking import _delivery_known_at


def dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def location(value) -> dict[str, Any]:
    return {"city": value.city, "state": value.state, "zip_code": value.zip_code}


CarrierMasters = Mapping[tuple[str, str], Carrier]


def carrier_ref(load: LoadVersion, carriers: CarrierMasters | None) -> dict[str, Any] | None:
    """The booked carrier, or null while the load is still awaiting coverage.

    Carrier IDs are opaque in all three TMS shapes, so the name has to be resolved from
    the carrier master rather than read off the load version.
    """
    if load.carrier_id is None:
        return None
    carrier = (carriers or {}).get((load.broker_id, load.carrier_id))
    return {"id": load.carrier_id, "name": carrier.name if carrier else load.carrier_id}


def load_summary(load: LoadVersion, carriers: CarrierMasters | None = None) -> dict[str, Any]:
    return {
        "broker_id": load.broker_id,
        "load_id": load.raw_load_id,
        "source_file": load.source_file,
        "synced_at": dt(load.synced_at),
        "status": load.status.value,
        "customer": {"id": load.customer_id, "name": load.customer_name},
        "carrier": carrier_ref(load, carriers),
        "equipment": load.equipment.value,
        "pickup": location(load.pickup),
        "delivery": location(load.delivery),
        "distance_miles": round(load.distance_miles, 1),
        "weight_lbs": round(load.weight_lbs, 0) if load.weight_lbs is not None else None,
        "customer_rate_usd": load.customer_rate_usd,
        "carrier_rate_usd": load.carrier_rate_usd,
    }


def load_detail(load: LoadVersion, versions: list[LoadVersion], carriers: CarrierMasters | None = None) -> dict[str, Any]:
    return {
        **load_summary(load, carriers),
        "pickup_window": {"open_at": dt(load.pickup_open_at), "close_at": dt(load.pickup_close_at)},
        "delivery_window": {"open_at": dt(load.delivery_open_at), "close_at": dt(load.delivery_close_at)},
        "actuals": {
            "pickup_arrived_at": dt(load.pickup_arrived_at),
            "pickup_departed_at": dt(load.pickup_departed_at),
            "delivery_arrived_at": dt(load.delivery_arrived_at),
            "delivery_departed_at": dt(load.delivery_departed_at),
        },
        "versions": [load_summary(version, carriers) for version in sorted(versions, key=lambda item: item.synced_at)],
    }


def price_estimate(value: PriceEstimate) -> dict[str, Any]:
    return {
        "point_usd": value.point_usd,
        "low_usd": value.low_usd,
        "high_usd": value.high_usd,
        "point_ppm": value.point_ppm,
        "observed_ppm": value.observed_ppm,
        "prior_ppm": value.prior_ppm,
        "basis": value.basis,
        "effective_loads": value.effective_loads,
        "confidence": value.confidence,
        "comparables": value.comparables,
        "reasons": value.reasons,
        "limitations": value.limitations,
    }


def carrier_ranking(ranking: CarrierRanking, target: LoadVersion, history: list[LoadVersion], geo: GeoIndex) -> dict[str, Any]:
    return {
        "broker_id": ranking.broker_id,
        "load_id": ranking.load_id,
        "carrier_id": ranking.carrier_id,
        "carrier_name": ranking.carrier_name,
        "score": ranking.score,
        "confidence": ranking.confidence,
        "pooled": ranking.pooled,
        "components": [component(component_score) for component_score in ranking.components],
        "reasons": ranking.reasons,
        "limitations": ranking.limitations,
        "geometry": lane_geometry(target, [load for load in history if load.carrier_id == ranking.carrier_id], geo),
    }


def pool_ranking(ranking: PoolCarrierRanking, target: LoadVersion, geo: GeoIndex) -> dict[str, Any]:
    return {
        "carrier_id": ranking.carrier_id,
        "carrier_name": ranking.carrier_name,
        "score": ranking.score,
        "confidence": ranking.confidence,
        "pooled": ranking.pooled,
        "components": [component(component_score) for component_score in ranking.components],
        "expected_carrier_cost_usd": ranking.expected_carrier_cost_usd,
        "reasons": ranking.reasons,
        "limitations": ranking.limitations,
        "payload": ranking.payload,
        "geometry": {"target": target_geometry(target, geo), "historical_lanes": [], "last_delivery": None},
    }


def component(value: ComponentScore) -> dict[str, Any]:
    return {"name": value.name, "score": value.score, "weight": value.weight, "evidence": value.evidence}


def lane_geometry(target: LoadVersion, history: list[LoadVersion], geo: GeoIndex) -> dict[str, Any]:
    weighted = []
    for load in history:
        total, direct, reverse = lane_weight(target, load, geo)
        if total <= 0.02:
            continue
        weighted.append(
            {
                "origin": point(load.pickup.zip_code, geo),
                "destination": point(load.delivery.zip_code, geo),
                "weight": round(total, 3),
                "direct_weight": round(direct, 3),
                "reverse_weight": round(reverse, 3),
            }
        )
    last_load = max((load for load in history if _delivery_known_at(load)), key=lambda load: _delivery_known_at(load), default=None)
    return {
        "target": target_geometry(target, geo),
        "historical_lanes": sorted(weighted, key=lambda item: item["weight"], reverse=True)[:12],
        "last_delivery": point(last_load.delivery.zip_code, geo) if last_load else None,
    }


def target_geometry(target: LoadVersion, geo: GeoIndex) -> dict[str, Any]:
    return {"origin": point(target.pickup.zip_code, geo), "destination": point(target.delivery.zip_code, geo)}


def point(zip_code: str, geo: GeoIndex) -> dict[str, Any] | None:
    centroid = geo.locate(zip_code)
    if centroid is None:
        return None
    return centroid_point(zip_code, centroid)


def centroid_point(zip_code: str, centroid: ZipCentroid) -> dict[str, Any]:
    return {"zip_code": zip_code, "lat": centroid.lat, "lon": centroid.lon}
