"""A read-only, single-broker view of history.

This is the *only* thing the ranking engine is given. It is constructed from one
broker id, so an engine physically cannot reach another tenant's loads - the
isolation is structural rather than a filter somebody has to remember to apply.
It is also the seam a shared carrier pool would be built at: a pooled view would
be a different implementation of this same surface, with an explicit and
inspectable list of what it exposes.

Everything here is derived on demand from current load state. Nothing is cached,
so a correction that landed thirty seconds ago is already reflected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

from . import geo
from .domain import Carrier, Equipment, Load, LoadStatus, Offer
from .store import Store


@dataclass(frozen=True)
class CarrierLaneHistory:
    """What one broker knows about one carrier, relative to one load."""

    carrier: Carrier
    loads_total: int
    loads_on_lane: int
    loads_from_origin: int
    loads_with_equipment: int
    last_load_at: datetime | None
    days_since_last_load: float | None
    last_delivery_market: str | None
    lane_rates_per_mile: tuple[float, ...]
    # Service record. `service_known` counts only loads whose outcome is actually
    # observable - a load still in transit is not evidence of anything.
    service_known: int
    service_on_time: int
    fall_offs: int
    offers: tuple[Offer, ...]

    @property
    def median_lane_rate_per_mile(self) -> float | None:
        return round(median(self.lane_rates_per_mile), 3) if self.lane_rates_per_mile else None

    @property
    def on_time_ratio(self) -> float | None:
        """Raw and therefore dangerous on small samples. Present for display next
        to the shrunk estimate, never for ranking."""
        if not self.service_known:
            return None
        return round(self.service_on_time / self.service_known, 3)


class BrokerHistory:
    def __init__(self, store: Store, broker_id: str, as_of: datetime | None = None) -> None:
        self.broker_id = broker_id
        self._store = store
        self._loads = store.loads(broker_id)
        self._carriers = {carrier.carrier_id: carrier for carrier in store.carriers(broker_id)}
        # The latest sync we have seen, not wall-clock time: "days since this
        # carrier last ran" must mean the same thing on every replay.
        self.as_of = as_of or store.last_synced_at or datetime.now(timezone.utc)

    # ---- corpora -------------------------------------------------------

    @property
    def all_loads(self) -> list[Load]:
        return self._loads

    @property
    def priced_loads(self) -> list[Load]:
        """Loads a carrier committed to at a known price - the only ones that
        say anything about what this broker actually pays."""
        return [
            load
            for load in self._loads
            if load.is_booked and load.carrier_rate is not None and load.distance_miles
        ]

    @property
    def carriers(self) -> list[Carrier]:
        return list(self._carriers.values())

    def carrier(self, carrier_id: str) -> Carrier | None:
        return self._carriers.get(carrier_id)

    def open_loads(self) -> list[Load]:
        return [load for load in self._loads if load.status == LoadStatus.ACTIVE]

    # ---- carrier-level history ----------------------------------------

    def carrier_loads(self, carrier_id: str) -> list[Load]:
        return [load for load in self._loads if load.carrier_id == carrier_id and load.is_booked]

    def carrier_history_for(self, carrier_id: str, target: Load) -> CarrierLaneHistory | None:
        carrier = self._carriers.get(carrier_id)
        if carrier is None:
            return None

        loads = self.carrier_loads(carrier_id)
        if not loads:
            return None

        lane = target.lane
        origin_market = target.origin_market

        on_lane = [load for load in loads if load.lane == lane]
        from_origin = [load for load in loads if load.origin_market == origin_market]
        with_equipment = [
            load
            for load in loads
            if target.equipment is not Equipment.UNKNOWN and load.equipment == target.equipment
        ]

        dated = [(load.delivered_at or load.updated_at, load) for load in loads]
        dated = [(when, load) for when, load in dated if when is not None]
        dated.sort(key=lambda pair: pair[0])
        last_load_at = dated[-1][0] if dated else None
        last_delivery_market = dated[-1][1].destination_market if dated else None

        days_since = None
        if last_load_at is not None:
            days_since = round((self.as_of - last_load_at).total_seconds() / 86400, 1)

        lane_rates = tuple(
            load.carrier_rate_per_mile
            for load in on_lane
            if load.carrier_rate_per_mile is not None
        )

        outcomes = [load.service_failed for load in loads if load.service_failed is not None]

        return CarrierLaneHistory(
            carrier=carrier,
            loads_total=len(loads),
            loads_on_lane=len(on_lane),
            loads_from_origin=len(from_origin),
            loads_with_equipment=len(with_equipment),
            last_load_at=last_load_at,
            days_since_last_load=days_since,
            last_delivery_market=last_delivery_market,
            lane_rates_per_mile=lane_rates,
            service_known=len(outcomes),
            service_on_time=sum(1 for failed in outcomes if not failed),
            fall_offs=self.fall_off_count(carrier.name),
            offers=tuple(self.carrier_offers(carrier_id)),
        )

    # ---- offers and service outcomes ----------------------------------

    @property
    def offers(self) -> list[Offer]:
        """The platform's own record of what was asked of whom.

        Empty for a tenant the platform has never made a call for, which is the
        state every new broker starts in - so every consumer of this has to work
        without it.
        """
        return self._store.offers(self.broker_id)

    def carrier_offers(self, carrier_id: str) -> list[Offer]:
        return [offer for offer in self.offers if offer.carrier_id == carrier_id]

    def offers_for_load(self, load_id: str) -> list[Offer]:
        return self._store.offers_for_load(self.broker_id, load_id)

    def fall_off_count(self, carrier_name: str) -> int:
        """How many times this carrier came off a load after accepting it.

        Reconstructed from the change log, since no feed reports a fall-off: the
        evidence is a booked load whose carrier stopped being this one.
        """
        return sum(
            1
            for change in self._store.changes(self.broker_id)
            if change.kind == "FALL_OFF"
            and change.field == "carrier_name"
            and change.old_value == carrier_name
        )

    def total_fall_offs(self) -> int:
        """Fall-offs across the whole broker, for use as a shrinkage prior."""
        return sum(
            1
            for change in self._store.changes(self.broker_id)
            if change.kind == "FALL_OFF" and change.field == "carrier_name"
        )

    def service_record(self) -> tuple[int, int]:
        """Broker-wide (on-time, known) counts, used as a shrinkage prior."""
        outcomes = [
            load.service_failed for load in self._loads if load.service_failed is not None
        ]
        return sum(1 for failed in outcomes if not failed), len(outcomes)

    # ---- lane-level history -------------------------------------------

    def lane_loads(
        self,
        lane: str | None = None,
        origin_market: str | None = None,
        equipment: Equipment | None = None,
    ) -> list[Load]:
        result = self.priced_loads
        if lane is not None:
            result = [load for load in result if load.lane == lane]
        if origin_market is not None:
            result = [load for load in result if load.origin_market == origin_market]
        if equipment is not None and equipment is not Equipment.UNKNOWN:
            result = [load for load in result if load.equipment == equipment]
        return result

    def lane_summary(self) -> list[dict]:
        """Per-lane volume and rate, for showing where history is thick or thin."""
        buckets: dict[str, list[Load]] = {}
        for load in self.priced_loads:
            buckets.setdefault(load.lane, []).append(load)

        summaries = []
        for lane, loads in buckets.items():
            rates = [load.carrier_rate_per_mile for load in loads if load.carrier_rate_per_mile]
            origin, _, destination = lane.partition("->")
            summaries.append(
                {
                    "lane": lane,
                    "lane_label": geo.lane_label(origin, destination),
                    "load_count": len(loads),
                    "median_rate_per_mile": round(median(rates), 3) if rates else None,
                    "carrier_count": len({load.carrier_id for load in loads if load.carrier_id}),
                }
            )
        summaries.sort(key=lambda item: item["load_count"], reverse=True)
        return summaries
