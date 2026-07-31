"""Turning a street address into something you can group history by.

The hard part of this problem is what counts as "the same lane". City names are
too fine (Grand Prairie and Mesquite are both just "Dallas" to a trucker) and
states are far too coarse (Dallas->Houston is 240 miles, El Paso->Houston is
750). So the unit here is the **metro market**: a group of towns close enough
that a carrier who runs to one will happily run to another.

Markets are resolved from the ZIP prefix rather than the city name, because ZIP
prefixes already encode geography - which is exactly what fixes the
NYC/Newark problem the README raises. Newark's 07xxx and Manhattan's 100xx
would be assigned to one metro here, despite differing in both city and state.

This is deliberately a lookup table, not a geocoder. It is the right shape but
the wrong resolution: see `docs` note in DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass

UNKNOWN_MARKET = "UNKNOWN"


@dataclass(frozen=True)
class Market:
    code: str
    label: str
    # Approximate centroid, used only for the deadhead estimate.
    lat: float
    lon: float


MARKETS: dict[str, Market] = {
    "DFW": Market("DFW", "Dallas–Fort Worth", 32.78, -96.97),
    "HOU": Market("HOU", "Houston", 29.76, -95.37),
    "SAT": Market("SAT", "San Antonio", 29.46, -98.43),
    "AUS": Market("AUS", "Austin", 30.27, -97.74),
    UNKNOWN_MARKET: Market(UNKNOWN_MARKET, "Unknown market", 0.0, 0.0),
}

# ZIP3 ranges, inclusive. Ordered most specific first is unnecessary here
# because the ranges do not overlap.
_ZIP3_RANGES: tuple[tuple[int, int, str], ...] = (
    (750, 767, "DFW"),
    (770, 779, "HOU"),
    (780, 785, "SAT"),
    (786, 789, "AUS"),
)

# Straight-line distances would understate real driving distance, so these are
# rough road miles between market centroids. Used for the deadhead signal, and
# as a fallback when a TMS does not give us mileage.
MARKET_DISTANCE_MILES: dict[frozenset[str], float] = {
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


# Some records carry a city but no ZIP (carrier home bases, mostly). ZIP is the
# primary resolver; this is the fallback, and it only knows the towns that
# actually appear in this dataset. A real deployment resolves this by geocoding
# rather than by growing this table.
_CITY_MARKETS: dict[str, str] = {
    **{
        city: "DFW"
        for city in ("dallas", "fort worth", "grand prairie", "mesquite", "lancaster", "garland",
                     "waxahachie", "plano", "arlington", "denton", "irving", "seagoville")
    },
    **{
        city: "HOU"
        for city in ("houston", "katy", "pasadena", "sugar land", "baytown", "stafford", "spring",
                     "rosenberg", "conroe")
    },
    **{
        city: "SAT"
        for city in ("san antonio", "new braunfels", "schertz", "seguin", "converse")
    },
    **{
        city: "AUS"
        for city in ("austin", "round rock", "san marcos", "buda", "georgetown", "kyle")
    },
}


def market_for_city(city: str | None, state: str | None = None) -> str:
    if not city:
        return UNKNOWN_MARKET
    if state and state.strip().upper() not in ("TX", ""):
        return UNKNOWN_MARKET
    return _CITY_MARKETS.get(city.strip().lower(), UNKNOWN_MARKET)


def market_for_zip(postal_code: str | None) -> str:
    if not postal_code:
        return UNKNOWN_MARKET
    digits = "".join(ch for ch in postal_code if ch.isdigit())
    if len(digits) < 3:
        return UNKNOWN_MARKET
    zip3 = int(digits[:3])
    for low, high, code in _ZIP3_RANGES:
        if low <= zip3 <= high:
            return code
    return UNKNOWN_MARKET


def resolve_market(postal_code: str | None, city: str | None = None, state: str | None = None) -> str:
    """ZIP first, city name only if the ZIP is missing or unrecognised."""
    market = market_for_zip(postal_code)
    if market == UNKNOWN_MARKET:
        market = market_for_city(city, state)
    return market


def market_label(code: str) -> str:
    market = MARKETS.get(code)
    return market.label if market else code


def lane_code(origin_market: str, destination_market: str) -> str:
    return f"{origin_market}->{destination_market}"


def lane_label(origin_market: str, destination_market: str) -> str:
    return f"{market_label(origin_market)} → {market_label(destination_market)}"


def market_distance_miles(a: str, b: str) -> float | None:
    """Rough road miles between two markets, or None if either is unknown."""
    if a == UNKNOWN_MARKET or b == UNKNOWN_MARKET:
        return None
    return MARKET_DISTANCE_MILES.get(frozenset({a, b}))
