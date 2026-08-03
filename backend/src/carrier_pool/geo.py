from __future__ import annotations

import csv
from dataclasses import dataclass
from importlib import resources
from math import asin, cos, radians, sin, sqrt


@dataclass(frozen=True)
class ZipCentroid:
    zip_code: str
    lat: float
    lon: float


class GeoIndex:
    def __init__(self, centroids: dict[str, ZipCentroid]):
        self.centroids = centroids

    @classmethod
    def bundled(cls) -> "GeoIndex":
        with resources.files("carrier_pool.reference").joinpath("zcta_centroids.csv").open(newline="", encoding="utf-8") as handle:
            rows = csv.DictReader(handle)
            return cls({row["zip"]: ZipCentroid(row["zip"], float(row["lat"]), float(row["lon"])) for row in rows})

    def miles(self, origin_zip: str, destination_zip: str) -> float:
        origin = self.centroids[origin_zip]
        destination = self.centroids[destination_zip]
        return haversine_miles(origin.lat, origin.lon, destination.lat, destination.lon)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius_miles * asin(sqrt(a))
