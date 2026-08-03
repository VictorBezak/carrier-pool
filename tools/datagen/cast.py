from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

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


PLACES: dict[str, Place] = {
    "grand_prairie": Place("grand_prairie", "Grand Prairie", "TX", "75050", "DFW", 32.7459, -96.9978),
    "arlington": Place("arlington", "Arlington", "TX", "76010", "DFW", 32.7357, -97.1081),
    "irving": Place("irving", "Irving", "TX", "75062", "DFW", 32.8140, -96.9489),
    "plano": Place("plano", "Plano", "TX", "75074", "DFW", 33.0198, -96.6989),
    "fort_worth": Place("fort_worth", "Fort Worth", "TX", "76102", "DFW", 32.7555, -97.3308),
    "denton": Place("denton", "Denton", "TX", "76201", "DFW", 33.2148, -97.1331),
    "waxahachie": Place("waxahachie", "Waxahachie", "TX", "75165", "DFW", 32.3865, -96.8483),
    "katy": Place("katy", "Katy", "TX", "77449", "HOU", 29.7858, -95.8244),
    "pasadena": Place("pasadena", "Pasadena", "TX", "77502", "HOU", 29.6911, -95.2091),
    "sugar_land": Place("sugar_land", "Sugar Land", "TX", "77478", "HOU", 29.6197, -95.6349),
    "baytown": Place("baytown", "Baytown", "TX", "77520", "HOU", 29.7355, -94.9774),
    "pearland": Place("pearland", "Pearland", "TX", "77581", "HOU", 29.5636, -95.2860),
    "conroe": Place("conroe", "Conroe", "TX", "77301", "HOU", 30.3119, -95.4561),
    "new_braunfels": Place("new_braunfels", "New Braunfels", "TX", "78130", "SA", 29.7030, -98.1245),
    "schertz": Place("schertz", "Schertz", "TX", "78154", "SA", 29.5522, -98.2697),
    "seguin": Place("seguin", "Seguin", "TX", "78155", "SA", 29.5688, -97.9647),
    "selma": Place("selma", "Selma", "TX", "78154", "SA", 29.5844, -98.3053),
    "san_marcos": Place("san_marcos", "San Marcos", "TX", "78666", "SA", 29.8833, -97.9414),
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
    "b_thin_5": _carrier(Broker.HAULDESK, "b_thin_5", "LIVE OAK TRANSPORT", "799120", "3450112", "selma", "(210) 555-0109"),
    # BrokerOS
    "c_veteran_1": _carrier(Broker.BROKEROS, "c_veteran_1", "Lone Pine Logistics", "930114", "4102221", "sugar_land", "+17135550123"),
    "c_veteran_2": _carrier(Broker.BROKEROS, "c_veteran_2", "Hill Country Refrigerated", "830225", "3980102", "san_marcos", "+15125550191"),
    "c_mid_1": _carrier(Broker.BROKEROS, "c_mid_1", "Guadalupe Freight Co", "740305", "2880100", "seguin", "+18305550162"),
    "c_mid_2": _carrier(Broker.BROKEROS, "c_mid_2", "MetroLink Van Lines", "682190", "2721880", "plano", "+19725550163"),
    "c_mid_3": _carrier(Broker.BROKEROS, "c_mid_3", "Pearland Produce Express", "609871", "2509441", "pearland", "+12815550165"),
    "c_thin_1": _carrier(Broker.BROKEROS, "c_thin_1", "Oak Cliff Cartage", "580201", "2311772", "irving", "+14695550168"),
    "c_thin_2": _carrier(Broker.BROKEROS, "c_thin_2", "Bastion Flatbeds", "765992", "3314780", "fort_worth", "+18175550169"),
    "c_thin_3": _carrier(Broker.BROKEROS, "c_thin_3", "Selma Shuttle", "713400", "3188220", "selma", "+12105550170"),
    "c_thin_4": _carrier(Broker.BROKEROS, "c_thin_4", "Conroe Cold Start", "888130", "3601720", "conroe", "+19365550171"),
    "c_thin_5": _carrier(Broker.BROKEROS, "c_thin_5", "Waxahachie Way", "593810", "2107780", "waxahachie", "+19725550172"),
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
