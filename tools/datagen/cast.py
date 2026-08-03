from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from .models import Broker, Carrier, Customer, Place

CENTRAL = timezone(timedelta(hours=-5))
BASE_DATE = date(2026, 7, 6)
SYNC_HOURS = (0, 6, 12, 18)
HISTORY_DAYS = 10
DAY11_SLOTS = 3
TOTAL_SLOTS = HISTORY_DAYS * len(SYNC_HOURS) + DAY11_SLOTS


def slot_datetime(slot: int) -> datetime:
    day_offset, hour_index = divmod(slot, len(SYNC_HOURS))
    return datetime.combine(BASE_DATE + timedelta(days=day_offset), time(SYNC_HOURS[hour_index]), CENTRAL)


def slot_filename(slot: int, suffix: str = "sync") -> str:
    dt = slot_datetime(slot)
    return f"{dt:%Y-%m-%d}T{dt:%H-%M}_{suffix}.json"


# Coordinates come from the same vendored Census ZCTA table the ranker uses, so the
# generator cannot invent a geography that only its own consumer agrees with.
ZCTA_REFERENCE = Path(__file__).resolve().parents[2] / "backend/src/carrier_pool/reference/zcta_centroids.csv"


@lru_cache(maxsize=1)
def _zcta_centroids() -> dict[str, tuple[float, float]]:
    with ZCTA_REFERENCE.open(newline="", encoding="utf-8") as handle:
        return {row["zip"]: (float(row["lat"]), float(row["lon"])) for row in csv.DictReader(handle)}


def _place(key: str, city: str, zip_code: str, metro: str) -> Place:
    lat, lon = _zcta_centroids()[zip_code]
    return Place(key, city, "TX", zip_code, metro, lat, lon)


# Each place needs its own ZCTA: two places sharing one ZIP would be a single point
# to any ZIP-keyed consumer. Schertz and Selma genuinely share 78154, so the roster
# uses Cibolo (78108), a distinct neighbouring ZCTA in the same metro.
PLACES: dict[str, Place] = {
    "grand_prairie": _place("grand_prairie", "Grand Prairie", "75050", "DFW"),
    "arlington": _place("arlington", "Arlington", "76010", "DFW"),
    "irving": _place("irving", "Irving", "75062", "DFW"),
    "plano": _place("plano", "Plano", "75074", "DFW"),
    "fort_worth": _place("fort_worth", "Fort Worth", "76102", "DFW"),
    "denton": _place("denton", "Denton", "76201", "DFW"),
    "waxahachie": _place("waxahachie", "Waxahachie", "75165", "DFW"),
    "katy": _place("katy", "Katy", "77449", "HOU"),
    "pasadena": _place("pasadena", "Pasadena", "77502", "HOU"),
    "sugar_land": _place("sugar_land", "Sugar Land", "77478", "HOU"),
    "baytown": _place("baytown", "Baytown", "77520", "HOU"),
    "pearland": _place("pearland", "Pearland", "77581", "HOU"),
    "conroe": _place("conroe", "Conroe", "77301", "HOU"),
    "new_braunfels": _place("new_braunfels", "New Braunfels", "78130", "SA"),
    "schertz": _place("schertz", "Schertz", "78154", "SA"),
    "seguin": _place("seguin", "Seguin", "78155", "SA"),
    "cibolo": _place("cibolo", "Cibolo", "78108", "SA"),
    "san_marcos": _place("san_marcos", "San Marcos", "78666", "SA"),
}


CUSTOMERS: dict[str, Customer] = {
    "a_bev": Customer(Broker.FREIGHTFLOW, "a_bev", "Lone Star Beverages"),
    "a_retail": Customer(Broker.FREIGHTFLOW, "a_retail", "Trinity Retail Group"),
    "a_food": Customer(Broker.FREIGHTFLOW, "a_food", "Bluebonnet Foods"),
    "b_build": Customer(Broker.HAULDESK, "b_build", "Alamo Building Supply"),
    "b_parts": Customer(Broker.HAULDESK, "b_parts", "Metroplex Auto Parts"),
    "b_cold": Customer(Broker.HAULDESK, "b_cold", "Hill Country Cold Chain"),
    "c_food": Customer(Broker.BROKEROS, "c_food", "Gulf Coast Foods"),
    "c_med": Customer(Broker.BROKEROS, "c_med", "Bexar Medical Supply"),
    "c_home": Customer(Broker.BROKEROS, "c_home", "Triangle Home Goods"),
}


def _carrier(broker: Broker, key: str, name: str, mc: str, dot: str, home: str, phone: str) -> Carrier:
    return Carrier(broker, key, name, mc, dot, home, phone)


CARRIERS: dict[str, Carrier] = {
    # FreightFlow
    "a_veteran_1": _carrier(Broker.FREIGHTFLOW, "a_veteran_1", "Ibrahim Transport Inc", "1346382", "3771394", "grand_prairie", "+15714906959"),
    "a_veteran_2": _carrier(Broker.FREIGHTFLOW, "a_veteran_2", "Blue Route Carriers", "550218", "1603301", "katy", "+12815550121"),
    "a_mid_1": _carrier(Broker.FREIGHTFLOW, "a_mid_1", "Cedar Hill Freight", "902441", "2419988", "arlington", "+18175550188"),
    "a_mid_2": _carrier(Broker.FREIGHTFLOW, "a_mid_2", "River City Haulage", "771204", "3001552", "new_braunfels", "+18305550144"),
    "a_mid_3": _carrier(Broker.FREIGHTFLOW, "a_mid_3", "Delta Prime, LLC", "884201", "2551377", "seguin", "+18305550144"),
    "a_thin_1": _carrier(Broker.FREIGHTFLOW, "a_thin_1", "Pecan Valley Trucking", "420018", "1997331", "fort_worth", "+16825550155"),
    "a_thin_2": _carrier(Broker.FREIGHTFLOW, "a_thin_2", "Mockingbird Logistics", "615880", "2100987", "plano", "+19725550190"),
    "a_thin_3": _carrier(Broker.FREIGHTFLOW, "a_thin_3", "Bayou Bend Express", "740221", "3099101", "baytown", "+17135550110"),
    "a_thin_4": _carrier(Broker.FREIGHTFLOW, "a_thin_4", "Mission City Freight", "631145", "2881440", "schertz", "+12105550133"),
    "a_thin_5": _carrier(Broker.FREIGHTFLOW, "a_thin_5", "Lariat Linehaul", "501004", "1800442", "denton", "+19405550177"),
    # HaulDesk
    "b_veteran_1": _carrier(Broker.HAULDESK, "b_veteran_1", "DELTA PRIME LLC", "884201", "2551377", "seguin", "(830) 555-0144"),
    "b_veteran_2": _carrier(Broker.HAULDESK, "b_veteran_2", "BRAZOS CARRIER GROUP", "700441", "3102245", "pasadena", "(713) 555-0150"),
    "b_mid_1": _carrier(Broker.HAULDESK, "b_mid_1", "ALAMO LINEHAUL", "620488", "2440101", "new_braunfels", "(210) 555-0172"),
    "b_mid_2": _carrier(Broker.HAULDESK, "b_mid_2", "NORTHSTAR TEXAS", "560333", "2239011", "irving", "(972) 555-0112"),
    "b_mid_3": _carrier(Broker.HAULDESK, "b_mid_3", "COASTAL COOL CARRIERS", "909311", "4000122", "pearland", "(281) 555-0189"),
    "b_thin_1": _carrier(Broker.HAULDESK, "b_thin_1", "COMAL CREEK FREIGHT", "720411", "3301140", "schertz", "(830) 555-0131"),
    "b_thin_2": _carrier(Broker.HAULDESK, "b_thin_2", "PRAIRIE DOG LOGISTICS", "518420", "1811441", "denton", "(940) 555-0198"),
    "b_thin_3": _carrier(Broker.HAULDESK, "b_thin_3", "GULFWAY FLATBED", "715902", "3101990", "baytown", "(832) 555-0184"),
    "b_thin_4": _carrier(Broker.HAULDESK, "b_thin_4", "TRINITY SPUR TRUCKING", "640991", "2540109", "waxahachie", "(469) 555-0137"),
    "b_thin_5": _carrier(Broker.HAULDESK, "b_thin_5", "LIVE OAK TRANSPORT", "799120", "3450112", "cibolo", "(210) 555-0109"),
    # BrokerOS
    "c_veteran_1": _carrier(Broker.BROKEROS, "c_veteran_1", "Lone Pine Logistics", "930114", "4102221", "sugar_land", "+17135550123"),
    "c_veteran_2": _carrier(Broker.BROKEROS, "c_veteran_2", "Hill Country Refrigerated", "830225", "3980102", "san_marcos", "+15125550191"),
    "c_mid_1": _carrier(Broker.BROKEROS, "c_mid_1", "Guadalupe Freight Co", "740305", "2880100", "seguin", "+18305550162"),
    "c_mid_2": _carrier(Broker.BROKEROS, "c_mid_2", "MetroLink Van Lines", "682190", "2721880", "plano", "+19725550163"),
    "c_mid_3": _carrier(Broker.BROKEROS, "c_mid_3", "Pearland Produce Express", "609871", "2509441", "pearland", "+12815550165"),
    "c_thin_1": _carrier(Broker.BROKEROS, "c_thin_1", "Oak Cliff Cartage", "580201", "2311772", "irving", "+14695550168"),
    "c_thin_2": _carrier(Broker.BROKEROS, "c_thin_2", "Bastion Flatbeds", "765992", "3314780", "fort_worth", "+18175550169"),
    "c_thin_3": _carrier(Broker.BROKEROS, "c_thin_3", "Cibolo Shuttle", "713400", "3188220", "cibolo", "+12105550170"),
    "c_thin_4": _carrier(Broker.BROKEROS, "c_thin_4", "Conroe Cold Start", "888130", "3601720", "conroe", "+19365550171"),
    "c_thin_5": _carrier(Broker.BROKEROS, "c_thin_5", "Waxahachie Way", "593810", "2107780", "waxahachie", "+19725550172"),
}


# Hours added to the planned midpoint of each appointment. Negative/low values
# create consistently punctual carriers; high values create visible late actuals.
RELIABILITY_BIAS_HOURS: dict[str, float] = {
    "a_veteran_1": -1.0,
    "a_veteran_2": 0.0,
    "a_mid_1": 0.5,
    "a_mid_2": -0.5,
    "a_mid_3": 2.5,
    "a_thin_1": 3.5,
    "a_thin_2": 1.5,
    "a_thin_3": 2.0,
    "a_thin_4": 1.0,
    "a_thin_5": 0.5,
    "b_veteran_1": -0.5,
    "b_veteran_2": 0.0,
    "b_mid_1": 0.5,
    "b_mid_2": 1.0,
    "b_mid_3": -0.25,
    "b_thin_1": 3.0,
    "b_thin_2": 2.0,
    "b_thin_3": 2.5,
    "b_thin_4": 1.5,
    "b_thin_5": 1.0,
    "c_veteran_1": -0.75,
    "c_veteran_2": -0.25,
    "c_mid_1": 1.0,
    "c_mid_2": 1.5,
    "c_mid_3": 0.5,
    "c_thin_1": 2.0,
    "c_thin_2": 3.0,
    "c_thin_3": 1.5,
    "c_thin_4": 2.5,
    "c_thin_5": 1.0,
}


def road_miles(origin_key: str, destination_key: str) -> float:
    origin = PLACES[origin_key]
    destination = PLACES[destination_key]
    radius_miles = 3958.8
    lat1 = radians(origin.lat)
    lat2 = radians(destination.lat)
    dlat = radians(destination.lat - origin.lat)
    dlon = radians(destination.lon - origin.lon)
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    straight = 2 * radius_miles * asin(sqrt(a))
    return round(max(straight * 1.18, 8.0), 1)
