#!/usr/bin/env python3
"""Generate the three TMS sync feeds under data/.

The dataset is designed, not random: every load below exists to exercise a
specific behaviour of the platform (rich lane vs thin lane, veteran carrier vs
first-timer, corrections landing after the fact, money appearing as it becomes
known). Randomness is limited to a seeded jitter on rates and mileage so the
numbers do not look synthetic; re-running the script reproduces byte-identical
files.

Days 1..HISTORY_DAYS are history. The final day holds loads that are still
looking for a carrier - those are the ones the platform must answer for.

    python3 data_gen/generate.py
"""

from __future__ import annotations

import json
import random
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"

START_DATE = date(2026, 7, 6)
SYNC_HOURS = (0, 6, 12, 18)
HISTORY_DAYS = 6
ANSWER_DAY = HISTORY_DAYS + 1
TOTAL_DAYS = ANSWER_DAY
SLOTS_PER_DAY = len(SYNC_HOURS)
HISTORY_SLOTS = HISTORY_DAYS * SLOTS_PER_DAY
TOTAL_SLOTS = TOTAL_DAYS * SLOTS_PER_DAY
MAX_LOADS_PER_SYNC = 3

LBS_PER_KG = 2.20462262
MILES_PER_KM = 0.621371192

RNG = random.Random(20260706)


def stable_hash(value: str) -> int:
    """Python's hash() is salted per process; these IDs must be reproducible."""
    return zlib.crc32(value.encode())


# --------------------------------------------------------------------------
# Geography: Texas Triangle, spread across suburbs rather than city centres.
# The 4th element is the metro market, which is what "lane" is built from.
# --------------------------------------------------------------------------

PLACES: dict[str, tuple[str, str, str, str]] = {
    # Dallas-Fort Worth
    "grand_prairie": ("Grand Prairie", "TX", "75050", "DFW"),
    "mesquite": ("Mesquite", "TX", "75149", "DFW"),
    "lancaster": ("Lancaster", "TX", "75134", "DFW"),
    "garland": ("Garland", "TX", "75041", "DFW"),
    "waxahachie": ("Waxahachie", "TX", "75165", "DFW"),
    "plano": ("Plano", "TX", "75074", "DFW"),
    "fort_worth": ("Fort Worth", "TX", "76106", "DFW"),
    "arlington": ("Arlington", "TX", "76011", "DFW"),
    "alliance": ("Fort Worth", "TX", "76177", "DFW"),
    "denton": ("Denton", "TX", "76205", "DFW"),
    # Houston
    "katy": ("Katy", "TX", "77449", "HOU"),
    "pasadena": ("Pasadena", "TX", "77502", "HOU"),
    "sugar_land": ("Sugar Land", "TX", "77478", "HOU"),
    "baytown": ("Baytown", "TX", "77520", "HOU"),
    "stafford": ("Stafford", "TX", "77477", "HOU"),
    "houston_north": ("Houston", "TX", "77032", "HOU"),
    "spring": ("Spring", "TX", "77373", "HOU"),
    "rosenberg": ("Rosenberg", "TX", "77471", "HOU"),
    "conroe": ("Conroe", "TX", "77301", "HOU"),
    # San Antonio
    "san_antonio_e": ("San Antonio", "TX", "78219", "SAT"),
    "new_braunfels": ("New Braunfels", "TX", "78130", "SAT"),
    "schertz": ("Schertz", "TX", "78154", "SAT"),
    "seguin": ("Seguin", "TX", "78155", "SAT"),
    "converse": ("Converse", "TX", "78109", "SAT"),
    # Austin
    "austin_se": ("Austin", "TX", "78744", "AUS"),
    "round_rock": ("Round Rock", "TX", "78664", "AUS"),
    "san_marcos": ("San Marcos", "TX", "78666", "AUS"),
    "buda": ("Buda", "TX", "78610", "AUS"),
    "georgetown": ("Georgetown", "TX", "78626", "AUS"),
}

MARKET_MILES: dict[frozenset[str], float] = {
    frozenset({"DFW", "HOU"}): 240,
    frozenset({"DFW", "SAT"}): 275,
    frozenset({"DFW", "AUS"}): 195,
    frozenset({"HOU", "SAT"}): 197,
    frozenset({"HOU", "AUS"}): 165,
    frozenset({"SAT", "AUS"}): 80,
    frozenset({"DFW"}): 35,
    frozenset({"HOU"}): 40,
    frozenset({"SAT"}): 30,
    frozenset({"AUS"}): 30,
}

# Calibrated against the rates in the provided schema examples: FreightFlow
# pays 1180 for 242 miles and HaulDesk 1035 for 389.6 km (242 mi), i.e. short
# intra-Texas hauls priced around $4.30-4.90 per mile rather than the ~$2 of a
# long-haul run.
RATE_PER_MILE = {"DRY_VAN": 4.85, "REEFER": 5.60, "FLATBED": 5.25}


def market_of(place_key: str) -> str:
    return PLACES[place_key][3]


def distance_miles(pickup: str, delivery: str) -> float:
    base = MARKET_MILES[frozenset({market_of(pickup), market_of(delivery)})]
    return round(base + RNG.uniform(-18, 22), 1)


# --------------------------------------------------------------------------
# Rosters. MC/DOT numbers are the cross-system identity of a real-world
# carrier: IBRAHIM appears under broker A and broker B, RIO GRANDE under A
# and C. Nothing crosses the broker boundary today, but the identity is there
# for a shared pool later.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Carrier:
    key: str
    name: str
    mc: str
    dot: str
    home: str
    phone: str


CARRIERS: dict[str, Carrier] = {
    c.key: c
    for c in [
        Carrier("ibrahim", "IBRAHIM TRANSPORT INC", "1346382", "3771394", "mesquite", "+15714906959"),
        Carrier("lone_oak", "LONE OAK CARRIERS LLC", "1102938", "3210945", "waxahachie", "+19725550118"),
        Carrier("rio_grande", "RIO GRANDE HAULERS INC", "998271", "2884113", "san_antonio_e", "+12105550177"),
        Carrier("panhandle", "PANHANDLE LOGISTICS LLC", "1450022", "3902117", "fort_worth", "+18175550143"),
        Carrier("bluebonnet", "BLUEBONNET FREIGHT CO", "1500918", "3990441", "katy", "+17135550196"),
        Carrier("trinity", "TRINITY RIVER EXPRESS LLC", "1288440", "3612009", "garland", "+14695550132"),
        Carrier("delta_prime", "DELTA PRIME LLC", "884201", "2551377", "seguin", "+18305550144"),
        Carrier("hill_country", "HILL COUNTRY TRUCKING INC", "1201553", "3455120", "new_braunfels", "+18305550171"),
        Carrier("gulf_breeze", "GULF BREEZE TRANSPORT LLC", "1390221", "3801442", "pasadena", "+17135550188"),
        Carrier("alamo_ridge", "ALAMO RIDGE CARRIERS LLC", "1177342", "3390118", "converse", "+12105550109"),
        Carrier("bayou_city", "BAYOU CITY LOGISTICS LLC", "1420990", "3877221", "baytown", "+18325550155"),
        Carrier("star_of_texas", "STAR OF TEXAS FREIGHT LLC", "1533201", "4010993", "round_rock", "+15125550122"),
    ]
}

CUSTOMERS: dict[str, str] = {
    "lone_star_bev": "Lone Star Beverages",
    "gulf_coast_foods": "Gulf Coast Foods",
    "alamo_building": "Alamo Building Supply",
    "trinity_paper": "Trinity Paper Products",
    "hill_valley_ag": "Hill Valley Agricultural",
    "capital_electronics": "Capital Electronics Group",
    "brazos_chemical": "Brazos Chemical Co",
    "pecan_grove_retail": "Pecan Grove Retail",
}


# --------------------------------------------------------------------------
# Load specs
# --------------------------------------------------------------------------

LIFECYCLE_FULL = ["ACTIVE", "COVERED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]
LIFECYCLE_QUOTED = ["PLANNED", "ACTIVE", "COVERED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]
# A short-haul load can move from booked to delivered inside one 6h window.
LIFECYCLE_FAST = ["ACTIVE", "COVERED", "DELIVERED", "COMPLETED"]


@dataclass
class Correction:
    """A money change that lands after the amount was first recorded.

    Positive delta = accessorial (detention, layover, fuel). Negative = credit
    or a plain data fix. `offset` is an index into the load's appearances.
    """

    offset: int
    delta: float
    code: str
    note: str


@dataclass
class LoadSpec:
    key: str
    pickup: str
    delivery: str
    equipment: str | None
    weight_lbs: float
    customer: str
    carrier: str | None
    lifecycle: list[str]
    commodity: str = "General freight"
    mid_stop: str | None = None
    rate_per_mile: float | None = None
    margin: float = 1.22
    corrections: list[Correction] = field(default_factory=list)
    weight_in_kg: bool = False
    start_slot: int = -1
    miles: float = 0.0
    customer_rate: float = 0.0
    carrier_rate: float = 0.0

    def finalize(self) -> None:
        self.miles = distance_miles(self.pickup, self.delivery)
        if self.mid_stop is not None:
            self.miles = round(self.miles + RNG.uniform(25, 55), 1)
        equip = self.equipment or "DRY_VAN"
        if self.rate_per_mile is not None:
            rpm = self.rate_per_mile
        else:
            # A real lane has spread, so a median over it is a judgement call
            # rather than a lookup. Seeded, so the spread is reproducible.
            rpm = RATE_PER_MILE[equip] * RNG.uniform(0.93, 1.08)
        self.carrier_rate = round(self.miles * rpm / 5) * 5.0
        self.customer_rate = round(self.carrier_rate * self.margin / 5) * 5.0

    @property
    def appearances(self) -> int:
        return len(self.lifecycle)

    def carrier_rate_at(self, offset: int) -> float:
        total = self.carrier_rate
        for corr in self.corrections:
            if corr.offset <= offset:
                total += corr.delta
        return round(total, 2)

    def customer_rate_at(self, offset: int) -> float:
        # Accessorials are usually passed through to the customer; a pure data
        # fix is not. FUEL and ACCESSORIAL bill through, ADJUSTMENT does not.
        total = self.customer_rate
        for corr in self.corrections:
            if corr.offset <= offset and corr.code in ("FUEL", "ACCESSORIAL"):
                total += round(corr.delta * 1.15, 2)
        return round(total, 2)


def broker_a_loads() -> list[LoadSpec]:
    """FreightFlow.

    Shape of the history: DFW->HOU is the deep lane (7 completed loads, three
    different carriers, tight rate spread) so both the ranking and the price
    estimate have something solid to stand on. DFW->AUS is deliberately thin
    (one load) so we can see what a low-confidence answer looks like.
    IBRAHIM is the veteran, TRINITY is strong but only recently active,
    BLUEBONNET has exactly one load ever - the fairness case.
    """
    return [
        # --- deep lane: DFW -> HOU, dry van ---
        LoadSpec("A-H01", "grand_prairie", "katy", "DRY_VAN", 24000, "lone_star_bev", "ibrahim", LIFECYCLE_FULL,
                 commodity="Bottled beverages"),
        LoadSpec("A-H02", "mesquite", "pasadena", "DRY_VAN", 21500, "trinity_paper", "lone_oak", LIFECYCLE_FULL,
                 commodity="Paper goods"),
        LoadSpec("A-H03", "lancaster", "sugar_land", "DRY_VAN", 26200, "pecan_grove_retail", "ibrahim", LIFECYCLE_FAST,
                 commodity="Mixed retail",
                 corrections=[Correction(3, 145.0, "ACCESSORIAL", "Detention at receiver, 2h over")]),
        LoadSpec("A-H04", "garland", "stafford", "DRY_VAN", 19800, "lone_star_bev", "trinity", LIFECYCLE_FULL,
                 commodity="Bottled beverages"),
        LoadSpec("A-H05", "arlington", "baytown", "DRY_VAN", 23100, "brazos_chemical", "ibrahim", LIFECYCLE_FULL,
                 commodity="Drummed lubricants"),
        LoadSpec("A-H06", "grand_prairie", "houston_north", "DRY_VAN", 22400, "trinity_paper", "lone_oak",
                 LIFECYCLE_QUOTED, commodity="Paper goods",
                 corrections=[Correction(4, -85.0, "ADJUSTMENT", "Linehaul was keyed 85 too high at booking")]),
        LoadSpec("A-H07", "plano", "spring", "DRY_VAN", 18600, "pecan_grove_retail", "trinity", LIFECYCLE_FAST,
                 commodity="Mixed retail"),
        # --- reefer, DFW <-> SAT ---
        LoadSpec("A-H08", "fort_worth", "new_braunfels", "REEFER", 27500, "hill_valley_ag", "rio_grande",
                 LIFECYCLE_FULL, commodity="Fresh produce"),
        LoadSpec("A-H09", "waxahachie", "schertz", "REEFER", 25900, "hill_valley_ag", "rio_grande", LIFECYCLE_FAST,
                 commodity="Dairy"),
        # --- flatbed, DFW -> AUS: the thin lane ---
        LoadSpec("A-H10", "alliance", "austin_se", "FLATBED", 31000, "alamo_building", "panhandle", LIFECYCLE_FULL,
                 commodity="Steel coil", rate_per_mile=5.95),
        # --- BLUEBONNET's single load ever ---
        LoadSpec("A-H11", "denton", "rosenberg", "DRY_VAN", 20100, "brazos_chemical", "bluebonnet", LIFECYCLE_FAST,
                 commodity="Packaged chemicals"),
        # --- IBRAHIM's most recent run ends in Houston, right where the
        #     day-7 pickup is not - TRINITY's ends in DFW. Deadhead contrast. ---
        LoadSpec("A-H12", "katy", "mesquite", "DRY_VAN", 21200, "lone_star_bev", "trinity", LIFECYCLE_FAST,
                 commodity="Empty pallets"),
        # --- the answer set: still looking for a carrier on day 7 ---
        LoadSpec("A-N01", "grand_prairie", "katy", "DRY_VAN", 23500, "lone_star_bev", None, ["ACTIVE", "ACTIVE"],
                 commodity="Bottled beverages"),
        LoadSpec("A-N02", "fort_worth", "converse", "REEFER", 26800, "hill_valley_ag", None, ["ACTIVE", "ACTIVE"],
                 commodity="Fresh produce"),
        LoadSpec("A-N03", "arlington", "georgetown", "FLATBED", 29500, "alamo_building", None, ["PLANNED", "ACTIVE"],
                 commodity="Structural steel"),
    ]


def broker_b_loads() -> list[LoadSpec]:
    """HaulDesk. South Texas oriented: SAT->HOU is the deep lane here."""
    return [
        LoadSpec("B-H01", "new_braunfels", "pasadena", "DRY_VAN", 24000, "alamo_building", "delta_prime",
                 LIFECYCLE_FULL, commodity="Building materials"),
        LoadSpec("B-H02", "seguin", "sugar_land", "DRY_VAN", 22800, "gulf_coast_foods", "delta_prime", LIFECYCLE_FAST,
                 commodity="Canned goods"),
        LoadSpec("B-H03", "schertz", "stafford", "DRY_VAN", 25400, "alamo_building", "hill_country", LIFECYCLE_FULL,
                 commodity="Drywall",
                 corrections=[Correction(3, 210.0, "FUEL", "Fuel surcharge billed at delivery")]),
        LoadSpec("B-H04", "converse", "baytown", "DRY_VAN", 21900, "brazos_chemical", "gulf_breeze", LIFECYCLE_FULL,
                 commodity="Packaged chemicals"),
        LoadSpec("B-H05", "san_antonio_e", "katy", "DRY_VAN", 23600, "gulf_coast_foods", "delta_prime",
                 LIFECYCLE_QUOTED, commodity="Canned goods",
                 corrections=[Correction(4, -120.0, "ADJUSTMENT", "Credit: carrier missed the delivery window")]),
        LoadSpec("B-H06", "new_braunfels", "rosenberg", "REEFER", 26100, "hill_valley_ag", "hill_country",
                 LIFECYCLE_FULL, commodity="Fresh produce"),
        LoadSpec("B-H07", "pasadena", "seguin", "DRY_VAN", 20400, "gulf_coast_foods", "gulf_breeze", LIFECYCLE_FAST,
                 commodity="Empty packaging"),
        # IBRAHIM under a second broker: same MC as broker A's veteran, but with
        # thin history *here*. Broker B must not benefit from broker A's data.
        LoadSpec("B-H08", "schertz", "grand_prairie", "DRY_VAN", 22000, "alamo_building", "ibrahim", LIFECYCLE_FAST,
                 commodity="Building materials"),
        LoadSpec("B-N01", "new_braunfels", "pasadena", "DRY_VAN", 24500, "alamo_building", None,
                 ["ACTIVE", "ACTIVE"], commodity="Building materials"),
        LoadSpec("B-N02", "san_antonio_e", "austin_se", "DRY_VAN", 19200, "capital_electronics", None,
                 ["ACTIVE", "ACTIVE"], commodity="Consumer electronics"),
    ]


def broker_c_loads() -> list[LoadSpec]:
    """BrokerOS. Carries the awkward shapes: a three-stop load, a load with
    no equipment type recorded, and one weighed in kg."""
    return [
        LoadSpec("C-H01", "sugar_land", "schertz", "REEFER", 14440, "gulf_coast_foods", "alamo_ridge",
                 LIFECYCLE_FULL, commodity="Packaged foods"),
        LoadSpec("C-H02", "houston_north", "san_antonio_e", "REEFER", 15900, "gulf_coast_foods", "alamo_ridge",
                 LIFECYCLE_FAST, commodity="Frozen foods",
                 corrections=[Correction(2, 175.0, "ACCESSORIAL", "Layover, receiver closed on arrival")]),
        LoadSpec("C-H03", "baytown", "converse", "DRY_VAN", 22600, "brazos_chemical", "bayou_city", LIFECYCLE_FULL,
                 commodity="Packaged chemicals"),
        LoadSpec("C-H04", "stafford", "new_braunfels", "DRY_VAN", 21300, "pecan_grove_retail", "bayou_city",
                 LIFECYCLE_QUOTED, commodity="Mixed retail", mid_stop="rosenberg"),
        LoadSpec("C-H05", "spring", "austin_se", "REEFER", 16800, "gulf_coast_foods", "rio_grande", LIFECYCLE_FULL,
                 commodity="Dairy", weight_in_kg=True),
        LoadSpec("C-H06", "katy", "buda", None, 20500, "capital_electronics", "bayou_city", LIFECYCLE_FAST,
                 commodity="Consumer electronics"),
        # The nastiest correction shape: the carrier rate simply becomes a
        # different number in a later sync, with no marker that it changed.
        LoadSpec("C-H07", "sugar_land", "seguin", "REEFER", 15200, "gulf_coast_foods", "alamo_ridge", LIFECYCLE_FULL,
                 commodity="Packaged foods",
                 corrections=[Correction(4, -240.0, "ADJUSTMENT", "Carrier rate restated at settlement")]),
        LoadSpec("C-H08", "rosenberg", "san_marcos", "FLATBED", 28900, "alamo_building", "star_of_texas",
                 LIFECYCLE_FAST, commodity="Lumber"),
        LoadSpec("C-N01", "sugar_land", "schertz", "REEFER", 15100, "gulf_coast_foods", None, ["ACTIVE", "ACTIVE"],
                 commodity="Packaged foods"),
        LoadSpec("C-N02", "baytown", "georgetown", None, 18700, "capital_electronics", None, ["ACTIVE", "ACTIVE"],
                 commodity="Consumer electronics"),
    ]


# --------------------------------------------------------------------------
# Slot packing: at most MAX_LOADS_PER_SYNC loads per sync file.
# --------------------------------------------------------------------------


def pack(loads: list[LoadSpec]) -> None:
    """Spread loads across the window they belong to, keeping every sync at or
    under the per-sync load cap.

    History loads are spaced evenly over days 1..HISTORY_DAYS and must reach
    COMPLETED inside that window, so "days of history" and "how recently did
    this carrier run for us" both mean something. The answer-day loads are
    pinned to the final day, where they stay ACTIVE.
    """
    occupancy: dict[int, int] = {}

    def fits(start: int, span: int, limit: int) -> bool:
        if start + span > limit:
            return False
        return all(occupancy.get(start + i, 0) < MAX_LOADS_PER_SYNC for i in range(span))

    def place(group: list[LoadSpec], first_slot: int, limit: int) -> None:
        span_room = limit - first_slot - max(spec.appearances for spec in group)
        step = span_room / max(1, len(group) - 1) if len(group) > 1 else 0
        for index, spec in enumerate(group):
            target = first_slot + round(index * step)
            for start in list(range(target, limit)) + list(range(first_slot, target)):
                if fits(start, spec.appearances, limit):
                    spec.start_slot = start
                    break
            else:
                raise RuntimeError(f"could not place {spec.key}: window {first_slot}..{limit} is full")
            for i in range(spec.appearances):
                occupancy[spec.start_slot + i] = occupancy.get(spec.start_slot + i, 0) + 1

    history = [spec for spec in loads if not spec.key.split("-")[1].startswith("N")]
    answer = [spec for spec in loads if spec.key.split("-")[1].startswith("N")]
    place(history, 0, HISTORY_SLOTS)
    place(answer, HISTORY_SLOTS, TOTAL_SLOTS)


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------


def slot_datetime(slot: int) -> datetime:
    day = START_DATE + timedelta(days=slot // SLOTS_PER_DAY)
    return datetime(day.year, day.month, day.day, SYNC_HOURS[slot % SLOTS_PER_DAY])


def slot_filename(slot: int) -> str:
    dt = slot_datetime(slot)
    return f"{dt.date().isoformat()}T{dt.hour:02d}-00_sync.json"


def central(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S-05:00")


def naive(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utc(dt: datetime) -> str:
    return (dt + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def load_dates(spec: LoadSpec) -> tuple[date, date]:
    """Pickup and delivery dates, relative to when the load first appeared."""
    created = slot_datetime(spec.start_slot).date()
    return created + timedelta(days=1), created + timedelta(days=2)


def appearance_context(spec: LoadSpec, offset: int) -> dict:
    """Everything a renderer needs about one appearance of one load."""
    slot = spec.start_slot + offset
    sync_dt = slot_datetime(slot)
    status = spec.lifecycle[offset]
    reached = set(spec.lifecycle[: offset + 1])
    pickup_date, delivery_date = load_dates(spec)
    booked = status in ("COVERED", "IN_TRANSIT", "DELIVERED", "COMPLETED")
    rolling = status in ("IN_TRANSIT", "DELIVERED", "COMPLETED")
    delivered = status in ("DELIVERED", "COMPLETED")
    return {
        "slot": slot,
        "sync_dt": sync_dt,
        "status": status,
        "reached": reached,
        "created_dt": slot_datetime(spec.start_slot) - timedelta(hours=2, minutes=17),
        "modified_dt": sync_dt - timedelta(hours=1, minutes=13),
        "pickup_date": pickup_date,
        "delivery_date": delivery_date,
        "departed_dt": datetime.combine(pickup_date, datetime.min.time()) + timedelta(hours=10, minutes=25),
        "arrived_dt": datetime.combine(delivery_date, datetime.min.time()) + timedelta(hours=9, minutes=40),
        "booked": booked,
        "rolling": rolling,
        "delivered": delivered,
        "carrier": CARRIERS[spec.carrier] if (booked and spec.carrier) else None,
        "carrier_rate": spec.carrier_rate_at(offset) if booked else None,
        "customer_rate": spec.customer_rate_at(offset),
    }


def group_appearances(loads: list[LoadSpec]) -> dict[int, list[tuple[LoadSpec, int]]]:
    by_slot: dict[int, list[tuple[LoadSpec, int]]] = {}
    for spec in loads:
        for offset in range(spec.appearances):
            by_slot.setdefault(spec.start_slot + offset, []).append((spec, offset))
    return by_slot


# --------------------------------------------------------------------------
# TMS A - FreightFlow: nested camelCase REST, US units, text statuses
# --------------------------------------------------------------------------

FF_STATUS = {
    "PLANNED": "Quoting",
    "ACTIVE": "Booking",
    "COVERED": "Dispatched",
    "IN_TRANSIT": "En Route",
    "DELIVERED": "Delivered",
    "COMPLETED": "Completed",
}
FF_EQUIPMENT = {"DRY_VAN": "53 ft Van | Dry", "REEFER": "53 ft Van | Reefer", "FLATBED": "48 ft Flatbed"}


def ff_shipment_id(key: str) -> int:
    return 127472000 + int(key.split("-")[1][1:]) * 397 + (0 if key[2] == "H" else 41)


def ff_stop(place_key: str, stop_type: str, day: date, departed: datetime | None) -> dict:
    city, state, zipcode, _ = PLACES[place_key]
    open_dt = datetime.combine(day, datetime.min.time()) + timedelta(hours=8)
    return {
        "stopType": stop_type,
        "city": city.upper(),
        "state": state,
        "zipCode": zipcode,
        "estimatedReadyDateTime": central(open_dt),
        "estimatedCloseDateTime": central(open_dt + timedelta(hours=8)),
        "actualDepartureDateTime": central(departed) if departed else None,
    }


def render_freightflow(spec: LoadSpec, offset: int) -> dict:
    ctx = appearance_context(spec, offset)
    stops = [
        ff_stop(spec.pickup, "First Pickup", ctx["pickup_date"], ctx["departed_dt"] if ctx["rolling"] else None)
    ]
    if spec.mid_stop:
        stops.append(ff_stop(spec.mid_stop, "Stop Off", ctx["pickup_date"], None))
    stops.append(
        ff_stop(spec.delivery, "Last Drop", ctx["delivery_date"], ctx["arrived_dt"] if ctx["delivered"] else None)
    )
    carrier = ctx["carrier"]
    return {
        "shipmentId": ff_shipment_id(spec.key),
        "status": FF_STATUS[ctx["status"]],
        "mileage": spec.miles,
        "totalSell": ctx["customer_rate"],
        "totalBuy": ctx["carrier_rate"],
        "customer": {
            "customerId": 889000 + stable_hash(spec.customer) % 900,
            "name": CUSTOMERS[spec.customer],
        },
        "carrier": None
        if carrier is None
        else {
            "carrierMasterId": 835000 + int(carrier.mc) % 900,
            "name": carrier.name,
            "mcNumber": carrier.mc,
            "dotNumber": carrier.dot,
            "phoneNumber": carrier.phone,
        },
        "equipment": FF_EQUIPMENT[spec.equipment] if spec.equipment else None,
        "weightTotal": float(spec.weight_lbs),
        "stops": stops,
        "createdDate": central(ctx["created_dt"]),
        "lastModifiedDate": central(ctx["modified_dt"]),
    }


def write_freightflow(loads: list[LoadSpec], out_dir: Path) -> None:
    by_slot = group_appearances(loads)
    for slot in range(TOTAL_SLOTS):
        sync_dt = slot_datetime(slot)
        payload = {
            "syncedAt": central(sync_dt),
            "loads": [render_freightflow(spec, offset) for spec, offset in by_slot.get(slot, [])],
        }
        write_json(out_dir / slot_filename(slot), payload)


# --------------------------------------------------------------------------
# TMS B - HaulDesk: flat table dumps, snake_case, metric, numeric statuses,
# money as append-only line items
# --------------------------------------------------------------------------

HD_STATUS = {"PLANNED": 10, "ACTIVE": 20, "COVERED": 30, "IN_TRANSIT": 40, "DELIVERED": 50, "COMPLETED": 90}
HD_EQUIPMENT = {"DRY_VAN": "V", "REEFER": "R", "FLATBED": "F"}


def hd_load_num(key: str) -> str:
    return f"HD-2026-00{4400 + int(key.split('-')[1][1:]) * 17 + (0 if key[2] == 'H' else 3)}"


def hd_carrier_id(carrier: Carrier) -> int:
    return 66000 + int(carrier.mc) % 900


def render_hauldesk_load(spec: LoadSpec, offset: int) -> dict:
    ctx = appearance_context(spec, offset)
    pu_city, pu_state, pu_zip, _ = PLACES[spec.pickup]
    del_city, del_state, del_zip, _ = PLACES[spec.delivery]
    carrier = ctx["carrier"]
    return {
        "load_num": hd_load_num(spec.key),
        "status_code": HD_STATUS[ctx["status"]],
        "customer_code": f"C-{1 + stable_hash(spec.customer) % 90:04d}",
        "customer_name": CUSTOMERS[spec.customer],
        "carrier_ref": hd_carrier_id(carrier) if carrier else None,
        "equip": HD_EQUIPMENT[spec.equipment] if spec.equipment else None,
        "weight_kg": round(spec.weight_lbs / LBS_PER_KG, 1),
        "dist_km": round(spec.miles / MILES_PER_KM, 1),
        "pu_city": pu_city,
        "pu_state": pu_state,
        "pu_zip": pu_zip,
        "pu_date": ctx["pickup_date"].isoformat(),
        "pu_departed_at": naive(ctx["departed_dt"]) if ctx["rolling"] else None,
        "del_city": del_city,
        "del_state": del_state,
        "del_zip": del_zip,
        "del_date": ctx["delivery_date"].isoformat(),
        "del_arrived_at": naive(ctx["arrived_dt"]) if ctx["delivered"] else None,
        "entered_at": naive(ctx["created_dt"]),
        "updated_at": naive(ctx["modified_dt"]),
    }


def hauldesk_rate_rows(spec: LoadSpec, offset: int, seq: list[int]) -> list[dict]:
    """Rate rows *created* at this appearance. Rows are append-only: the
    linehaul pair lands when the carrier is booked, corrections arrive later
    as their own rows rather than edits."""
    ctx = appearance_context(spec, offset)
    created = naive(ctx["modified_dt"])
    rows: list[dict] = []

    def add(side: str, code: str, amount: float) -> None:
        seq[0] += 1
        rows.append(
            {
                "rate_id": 910000 + seq[0],
                "load_num": hd_load_num(spec.key),
                "side": side,
                "code": code,
                "amount_usd": round(amount, 2),
                "created_at": created,
            }
        )

    # The customer side is agreed when the order is taken; the carrier side only
    # exists once a carrier says yes.
    if offset == 0:
        add("bill", "LINEHAUL", spec.customer_rate)
    became_covered = ctx["status"] == "COVERED" and (offset == 0 or spec.lifecycle[offset - 1] != "COVERED")
    if became_covered:
        add("pay", "LINEHAUL", spec.carrier_rate)
    for corr in spec.corrections:
        if corr.offset == offset:
            add("pay", corr.code, corr.delta)
            if corr.code in ("FUEL", "ACCESSORIAL"):
                add("bill", corr.code, round(corr.delta * 1.15, 2))
    return rows


def write_hauldesk(loads: list[LoadSpec], out_dir: Path) -> None:
    by_slot = group_appearances(loads)
    seen_carriers: set[str] = set()
    seq = [0]
    for slot in range(TOTAL_SLOTS):
        entries = by_slot.get(slot, [])
        load_rows = [render_hauldesk_load(spec, offset) for spec, offset in entries]
        rate_rows = [row for spec, offset in entries for row in hauldesk_rate_rows(spec, offset, seq)]
        carrier_rows = []
        for spec, offset in entries:
            ctx = appearance_context(spec, offset)
            carrier = ctx["carrier"]
            if carrier and carrier.key not in seen_carriers:
                seen_carriers.add(carrier.key)
                home_city, home_state, _, _ = PLACES[carrier.home]
                carrier_rows.append(
                    {
                        "carrier_id": hd_carrier_id(carrier),
                        "carrier_name": carrier.name,
                        "mc_no": carrier.mc,
                        "dot_no": carrier.dot,
                        "home_city": home_city,
                        "home_state": home_state,
                        "phone": f"({carrier.phone[2:5]}) {carrier.phone[5:8]}-{carrier.phone[8:]}",
                    }
                )
        payload = {
            "synced_at": naive(slot_datetime(slot)),
            "loads": load_rows,
            "carriers": carrier_rows,
            "rates": rate_rows,
        }
        write_json(out_dir / slot_filename(slot), payload)


# --------------------------------------------------------------------------
# TMS C - BrokerOS: CRM managed package, opaque IDs, child records
# --------------------------------------------------------------------------

BOS_STATUS = {
    "PLANNED": "Quotes Requested",
    "ACTIVE": "Ready to Book",
    "COVERED": "Booked",
    "IN_TRANSIT": "In Transit",
    "DELIVERED": "Delivered",
    "COMPLETED": "Paid",
}
BOS_EQUIPMENT = {"DRY_VAN": "Dry Van", "REEFER": "Reefer", "FLATBED": "Flatbed"}
_ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def bos_id(prefix: str, seed: str) -> str:
    rng = random.Random(f"{prefix}:{seed}")
    body = "".join(rng.choice(_ID_ALPHABET) for _ in range(18 - len(prefix)))
    return prefix + body


def bos_load_id(key: str) -> str:
    return bos_id("a0j", key)


def bos_load_name(key: str) -> str:
    return f"SHP{6743000 + int(key.split('-')[1][1:]) * 62 + (0 if key[2] == 'H' else 7)}"


def render_brokeros(spec: LoadSpec, offset: int, refs: dict) -> dict:
    ctx = appearance_context(spec, offset)
    carrier = ctx["carrier"]

    def location_ref(place_key: str) -> str:
        rid = bos_id("001", f"loc:{place_key}")
        city, state, zipcode, _ = PLACES[place_key]
        suffix = LOCATION_SUFFIX[stable_hash(place_key) % len(LOCATION_SUFFIX)]
        refs[rid] = {
            "type": "Location",
            "Name": f"{city} {suffix}",
            "bos__City__c": city,
            "bos__State__c": state,
            "bos__Postal_Code__c": zipcode,
        }
        return rid

    def account_ref(name: str, record_type: str, seed: str) -> str:
        rid = bos_id("001", f"acct:{seed}")
        refs[rid] = {"type": "Account", "record_type": record_type, "Name": name}
        return rid

    stop_places = [spec.pickup] + ([spec.mid_stop] if spec.mid_stop else []) + [spec.delivery]
    stops = []
    for index, place_key in enumerate(stop_places):
        is_pickup = index == 0
        is_dropoff = index == len(stop_places) - 1
        scheduled = ctx["pickup_date"] if is_pickup else ctx["delivery_date"]
        arrival = None
        if is_pickup and ctx["rolling"]:
            arrival = utc(ctx["departed_dt"] - timedelta(hours=2))
        elif is_dropoff and ctx["delivered"]:
            arrival = utc(ctx["arrived_dt"])
        stops.append(
            {
                "bos__Number__c": float(index + 1),
                "bos__Is_Pickup__c": is_pickup,
                "bos__Is_Dropoff__c": is_dropoff,
                "bos__Location__c": location_ref(place_key),
                "bos__Scheduled_Date__c": scheduled.isoformat(),
                "bos__Arrival_Time__c": arrival,
            }
        )

    weight = round(spec.weight_lbs / LBS_PER_KG, 1) if spec.weight_in_kg else float(spec.weight_lbs)
    return {
        "Id": bos_load_id(spec.key),
        "Name": bos_load_name(spec.key),
        "bos__Load_Status__c": BOS_STATUS[ctx["status"]],
        "bos__Distance_Miles__c": spec.miles,
        "bos__Customer__c": account_ref(CUSTOMERS[spec.customer], "Customer", spec.customer),
        "bos__Carrier__c": account_ref(carrier.name, "Carrier", carrier.key) if carrier else None,
        "bos__Equipment_Type__c": BOS_EQUIPMENT[spec.equipment] if spec.equipment else None,
        "bos__Customer_Rate__c": ctx["customer_rate"],
        "bos__Carrier_Rate__c": ctx["carrier_rate"],
        "bos__Stops__r": stops,
        "bos__Line_Items__r": [
            {
                "bos__Commodity__c": spec.commodity,
                "bos__Weight__c": weight,
                "bos__Weight_Units__c": "kg" if spec.weight_in_kg else "lbs",
                "bos__Pallet_Count__c": float(round(spec.weight_lbs / 1350)),
            }
        ],
        "CreatedDate": utc(ctx["created_dt"]),
        "LastModifiedDate": utc(ctx["modified_dt"]),
    }


LOCATION_SUFFIX = ("Distribution Ctr", "Cold Storage", "Terminal", "Warehouse")


def write_brokeros(loads: list[LoadSpec], out_dir: Path) -> None:
    by_slot = group_appearances(loads)
    for slot in range(TOTAL_SLOTS):
        refs: dict = {}
        records = [render_brokeros(spec, offset, refs) for spec, offset in by_slot.get(slot, [])]
        payload = {
            "synced_at": utc(slot_datetime(slot)),
            "records": records,
            "referenced_records": refs,
        }
        write_json(out_dir / slot_filename(slot), payload)


# --------------------------------------------------------------------------


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def clear_generated(out_dir: Path) -> None:
    for existing in out_dir.glob("*_sync.json"):
        existing.unlink()


def main() -> None:
    feeds = [
        ("tms_a_freightflow", broker_a_loads(), write_freightflow),
        ("tms_b_hauldesk", broker_b_loads(), write_hauldesk),
        ("tms_c_brokeros", broker_c_loads(), write_brokeros),
    ]
    for name, loads, writer in feeds:
        for spec in loads:
            spec.finalize()
        pack(loads)
        out_dir = DATA_ROOT / name
        clear_generated(out_dir)
        writer(loads, out_dir)
        history = sum(1 for s in loads if "-H" in s.key)
        answer = len(loads) - history
        print(f"{name}: {TOTAL_SLOTS} sync files, {history} history loads, {answer} loads awaiting a carrier")


if __name__ == "__main__":
    main()
