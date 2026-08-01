"""End-to-end checks over the real data in `data/`.

These are the claims the system makes about itself, written down so they can be
re-run: units are normalised, tenants are isolated, replaying the feed is
idempotent, corrections are detected, and every recommendation can be traced
back to its arithmetic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import brokers, config, ingest, ranking
from app.domain import Equipment, LoadStatus
from app.history import BrokerHistory
from app.main import app
from app.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return ingest.ingest_all(config.data_dir())


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ---- ingestion ---------------------------------------------------------


def test_files_are_ingested_in_chronological_order() -> None:
    pending = ingest.discover(config.data_dir())
    assert pending, "no sync files discovered - has data_gen/generate.py been run?"
    timestamps = [item.scheduled_at for item in pending]
    assert timestamps == sorted(timestamps)
    # All three feeds interleave into one timeline rather than running one
    # broker to completion before starting the next.
    assert len({item.broker_id for item in pending[:6]}) > 1


def test_documentation_files_are_not_ingested() -> None:
    names = {item.path.name for item in ingest.discover(config.data_dir())}
    assert not any(name.endswith(".jsonc") for name in names)


def test_replay_is_idempotent(store: Store) -> None:
    """Ingesting the same feed twice must produce the same state. This is what
    makes 'rebuild from scratch' a viable answer to corrections."""
    again = ingest.ingest_all(config.data_dir())
    for broker in brokers.BROKERS:
        first = {load.load_id: load.model_dump() for load in store.loads(broker.broker_id)}
        second = {load.load_id: load.model_dump() for load in again.loads(broker.broker_id)}
        assert first.keys() == second.keys()
        for load_id, snapshot in first.items():
            assert snapshot == second[load_id], f"{load_id} differs on replay"


# ---- normalisation ----------------------------------------------------


def test_metric_units_are_converted(store: Store) -> None:
    """HaulDesk reports kilograms and kilometres; nothing downstream should
    ever see them."""
    loads = store.loads("anchor")
    assert loads
    for load in loads:
        if load.weight_lbs is not None:
            # A 10-tonne shipment is ~22,000 lbs. Anything near 10,000 means a
            # kilogram value leaked through unconverted.
            assert load.weight_lbs > 15000
        if load.distance_miles is not None:
            assert load.distance_miles < 400


def test_reefer_is_not_read_as_dry_van(store: Store) -> None:
    """FreightFlow describes a reefer as "53 ft Van | Reefer", so a naive
    substring check on "Van" would misclassify every reefer."""
    equipment = {load.equipment for load in store.loads("redline")}
    assert Equipment.REEFER in equipment
    assert Equipment.DRY_VAN in equipment


def test_missing_equipment_is_unknown_not_assumed(store: Store) -> None:
    """BrokerOS says null equipment must not be read as dry van."""
    unknown = [load for load in store.loads("summit") if load.equipment is Equipment.UNKNOWN]
    assert unknown, "expected at least one load with no equipment type recorded"


def test_append_only_rate_lines_are_summed(store: Store) -> None:
    """HaulDesk money is a ledger. A booked load must have a carrier rate built
    from its `pay` rows, and an unbooked one must have none at all rather than
    zero."""
    booked = [load for load in store.loads("anchor") if load.is_booked]
    assert booked
    assert all(load.carrier_rate and load.carrier_rate > 0 for load in booked)

    unbooked = [load for load in store.loads("anchor") if not load.is_booked]
    assert all(load.carrier_rate is None for load in unbooked)


def test_markets_group_suburbs_not_city_names(store: Store) -> None:
    """Grand Prairie, Mesquite and Arlington are different cities but one lane."""
    dfw_origins = {
        load.origin.city
        for load in store.loads("redline")
        if load.origin and load.origin.market == "DFW"
    }
    assert len(dfw_origins) > 3, f"expected several distinct DFW-area towns, got {dfw_origins}"


# ---- corrections ------------------------------------------------------


def test_corrections_are_detected_and_distinguished_from_progress(store: Store) -> None:
    for broker in brokers.BROKERS:
        changes = store.changes(broker.broker_id)
        kinds = {change.kind for change in changes}
        assert "PROGRESS" in kinds, f"{broker.broker_id} recorded no status progression"
        assert "REVEALED" in kinds, f"{broker.broker_id} never saw an amount become known"
        corrections = [change for change in changes if change.kind == "CORRECTION"]
        assert corrections, f"{broker.broker_id} recorded no corrections"
        # A correction means a real value was replaced by a different real value.
        for change in corrections:
            if change.field != "status":
                assert change.old_value is not None
                assert change.old_value != change.new_value


def test_a_correction_moves_the_derived_price(store: Store) -> None:
    """The point of computing on read: a corrected amount is reflected in the
    estimate with no rebuild step. Here we prove the corrected load is the one
    the estimate actually reads from."""
    history = BrokerHistory(store, "redline")
    corrected_ids = {
        change.load_id
        for change in store.changes("redline")
        if change.kind == "CORRECTION" and change.field == "carrier_rate"
    }
    assert corrected_ids
    priced_ids = {load.load_id for load in history.priced_loads}
    assert corrected_ids & priced_ids, "corrected loads are not feeding the price estimate"


# ---- tenancy ----------------------------------------------------------


def test_same_carrier_has_independent_history_per_broker(store: Store) -> None:
    """IBRAHIM TRANSPORT works for two brokers under the same MC number. Each
    broker must see only its own loads with them."""
    mc = "1346382"
    views = {}
    for broker_id in ("redline", "anchor"):
        history = BrokerHistory(store, broker_id)
        matches = [
            carrier
            for carrier in history.carriers
            if carrier.mc_number == mc or carrier.name.startswith("IBRAHIM")
        ]
        assert matches, f"{broker_id} does not know this carrier"
        views[broker_id] = len(history.carrier_loads(matches[0].carrier_id))

    assert views["redline"] != views["anchor"], (
        "both brokers see the same load count for a shared carrier, which suggests "
        f"history is leaking across tenants: {views}"
    )


def test_load_ids_do_not_resolve_across_brokers(store: Store, client: TestClient) -> None:
    reference = store.loads("redline")[0].source_ref
    assert client.get(f"/api/brokers/redline/loads/{reference}").status_code == 200
    assert client.get(f"/api/brokers/anchor/loads/{reference}").status_code == 404


def test_history_only_ever_holds_one_broker(store: Store) -> None:
    for broker in brokers.BROKERS:
        history = BrokerHistory(store, broker.broker_id)
        assert all(load.broker_id == broker.broker_id for load in history.all_loads)


# ---- recommendations --------------------------------------------------


@pytest.mark.parametrize("engine_key", sorted(ranking.ENGINES))
def test_every_open_load_gets_a_traceable_answer(store: Store, engine_key: str) -> None:
    """Run the contract against *every* registered engine.

    The point of having a contract is that it binds whatever is plugged into it,
    so this is parametrised rather than pinned to the default. An earlier version
    of this test also required a one-to-one match between reasons and score
    components, which was really an assertion about how the heuristic engine
    happened to be written - it fails for any engine whose prose does not
    enumerate its arithmetic one line at a time.
    """
    engine = ranking.get_engine(engine_key)
    open_loads = 0

    for broker in brokers.BROKERS:
        history = BrokerHistory(store, broker.broker_id)
        for load in history.open_loads():
            open_loads += 1
            result = engine.recommend(load, history, limit=5)

            assert result.carriers, f"{load.reference} got no carriers at all"
            assert result.price_estimate is not None, f"{load.reference} got no price"

            estimate = result.price_estimate
            assert estimate.low_usd <= estimate.point_usd <= estimate.high_usd
            assert estimate.sample_size == len(estimate.comparables)
            assert estimate.reasons, "a price with no explanation is not useful"
            # Every comparable must be a real load of this broker's, so the
            # number can be checked by hand.
            for comparable in estimate.comparables:
                assert store.load(broker.broker_id, comparable.load_id) is not None

            ranks = [carrier.rank for carrier in result.carriers]
            assert ranks == sorted(ranks) == list(range(1, len(ranks) + 1))
            scores = [carrier.score for carrier in result.carriers]
            assert scores == sorted(scores, reverse=True)

            for carrier in result.carriers:
                assert carrier.reasons, f"{carrier.carrier_name} ranked with no reasoning"
                # The explanation must add up to the score it explains, or the
                # narrative and the ranking can drift apart without anyone noticing.
                total = round(sum(component.points for component in carrier.components), 1)
                assert abs(total - carrier.score) < 0.05, (
                    f"{engine_key}: {carrier.carrier_name} scored {carrier.score} but its "
                    f"components sum to {total}"
                )
                assert carrier.components, "a score with no breakdown cannot be audited"

    assert open_loads >= 5, "the day-11 style answer set looks too small to be interesting"


def test_every_normalised_datetime_is_timezone_aware(store: Store) -> None:
    """The three feeds disagree about time: FreightFlow sends offsets, HaulDesk
    sends naive Central wall time, BrokerOS sends bare dates for appointments. The
    canonical model's job is to erase that difference, and a single naive value
    surviving normalisation does not fail here - it fails later, in whichever
    comparison happens to touch it first.
    """
    offenders: list[str] = []
    for broker in brokers.BROKERS:
        for load in store.loads(broker.broker_id):
            fields = {"created_at": load.created_at, "updated_at": load.updated_at}
            for index, stop in enumerate(load.stops):
                for name in ("scheduled_start", "scheduled_end", "actual_arrival", "actual_departure"):
                    fields[f"stop[{index}].{name}"] = getattr(stop, name)
            for name, value in fields.items():
                if value is not None and value.tzinfo is None:
                    offenders.append(f"{broker.broker_id}/{load.reference}.{name}")

    assert not offenders, f"naive datetimes escaped normalisation: {offenders[:5]}"


def test_price_basis_never_overstates_the_match(store: Store) -> None:
    """An estimate may only claim "same trailer type" if the load has one."""
    engine = ranking.get_engine()
    for broker in brokers.BROKERS:
        history = BrokerHistory(store, broker.broker_id)
        for load in history.all_loads:
            estimate = ranking.estimate_price(load, history)
            if estimate is None:
                continue
            if load.equipment is Equipment.UNKNOWN:
                assert "EQUIPMENT" not in estimate.basis, (
                    f"{load.reference} has no equipment type but the price claims {estimate.basis}"
                )


def test_thin_history_is_flagged_rather_than_hidden(store: Store) -> None:
    """A carrier with one load must be marked as thin evidence, so the UI can
    say so instead of presenting it as equivalent to a veteran."""
    engine = ranking.get_engine()
    history = BrokerHistory(store, "redline")
    load = history.open_loads()[0]
    result = engine.recommend(load, history, limit=20)
    thin = [carrier for carrier in result.carriers if carrier.history_depth.is_thin]
    assert thin, "expected at least one thin-history carrier in this dataset"


def test_a_load_is_never_a_comparable_for_itself(store: Store) -> None:
    engine = ranking.get_engine()
    history = BrokerHistory(store, "redline")
    for load in history.priced_loads:
        estimate = ranking.estimate_price(load, history)
        if estimate is None:
            continue
        assert load.load_id not in {item.load_id for item in estimate.comparables}


# ---- HTTP surface -----------------------------------------------------


def test_health_and_broker_list(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["sync_files"] > 0

    listing = client.get("/api/brokers").json()
    assert len(listing) == len(brokers.BROKERS)
    assert all(broker["active_load_count"] > 0 for broker in listing)


def test_unknown_broker_is_a_404(client: TestClient) -> None:
    assert client.get("/api/brokers/nope/loads").status_code == 404


def test_load_list_puts_active_loads_first(client: TestClient) -> None:
    loads = client.get("/api/brokers/redline/loads").json()
    statuses = [load["status"] for load in loads]
    active_positions = [index for index, status in enumerate(statuses) if status == "ACTIVE"]
    assert active_positions == list(range(len(active_positions)))


def test_status_filter_and_search(client: TestClient) -> None:
    active = client.get("/api/brokers/redline/loads", params={"status": "ACTIVE"}).json()
    assert active and all(load["status"] == "ACTIVE" for load in active)

    hits = client.get("/api/brokers/redline/loads", params={"q": "katy"}).json()
    assert hits, "expected the search to find loads through Katy"


def test_recommendations_endpoint_matches_the_engine(client: TestClient) -> None:
    active = client.get("/api/brokers/redline/loads", params={"status": "ACTIVE"}).json()
    reference = active[0]["source_ref"]
    payload = client.get(
        f"/api/brokers/redline/loads/{reference}/recommendations", params={"limit": 3}
    ).json()

    assert payload["engine"]["key"] == ranking.DEFAULT_ENGINE_KEY
    assert len(payload["carriers"]) <= 3
    assert payload["price_estimate"]["comparables"]
    assert all(carrier["reasons"] for carrier in payload["carriers"])


def test_load_detail_exposes_its_own_change_log(client: TestClient, store: Store) -> None:
    corrected = next(
        change for change in store.changes("redline") if change.kind == "CORRECTION"
    )
    reference = corrected.load_id.split(":", 1)[1]
    detail = client.get(f"/api/brokers/redline/loads/{reference}").json()
    assert detail["correction_count"] >= 1
    assert any(entry["kind"] == "CORRECTION" for entry in detail["history"])
    assert detail["sync_count"] > 1, "a load that was corrected must have been seen more than once"


def test_lane_summary_shows_thick_and_thin_lanes(client: TestClient) -> None:
    lanes = client.get("/api/brokers/redline/lanes").json()
    counts = [lane["load_count"] for lane in lanes]
    assert counts == sorted(counts, reverse=True)
    assert max(counts) >= 3 and min(counts) == 1, (
        "the dataset should contrast a deep lane against a one-load lane"
    )
