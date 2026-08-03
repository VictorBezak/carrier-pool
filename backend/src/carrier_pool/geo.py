from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from importlib import resources
from math import asin, cos, radians, sin, sqrt


@dataclass(frozen=True)
class ZipCentroid:
    zip_code: str
    lat: float
    lon: float


class GeoIndex:
    """ZIP-to-coordinate lookup backed by US Census ZCTA interior points.

    ZCTAs approximate USPS ZIP delivery areas but are not identical to them: ZIPs that
    exist only as PO boxes or single-building business codes have no ZCTA at all. Those
    resolve to the centroid of their ZIP3 prefix, which keeps a shipment locatable to
    within a sectional center rather than dropping it from the ranking entirely.
    """

    def __init__(self, centroids: dict[str, ZipCentroid]):
        self.centroids = centroids
        self._prefixes: dict[str, ZipCentroid | None] = {}

    @classmethod
    def bundled(cls) -> "GeoIndex":
        with resources.files("carrier_pool.reference").joinpath("zcta_centroids.csv").open(newline="", encoding="utf-8") as handle:
            rows = csv.DictReader(handle)
            return cls({row["zip"]: ZipCentroid(row["zip"], float(row["lat"]), float(row["lon"])) for row in rows})

    def locate(self, zip_code: str) -> ZipCentroid | None:
        exact = self.centroids.get(zip_code)
        if exact is not None:
            return exact
        return self._prefix_centroid(zip_code)

    def centroid(self, zip_code: str) -> ZipCentroid:
        located = self.locate(zip_code)
        if located is None:
            raise KeyError(f"No ZCTA or ZIP3 centroid available for {zip_code!r}")
        return located

    def resolution(self, zip_code: str) -> str:
        if zip_code in self.centroids:
            return "zcta"
        return "zip3" if self._prefix_centroid(zip_code) else "unknown"

    def _prefix_centroid(self, zip_code: str) -> ZipCentroid | None:
        prefix = zip_code[:3]
        if prefix in self._prefixes:
            return self._prefixes[prefix]
        members = [c for z, c in self.centroids.items() if z.startswith(prefix)]
        # A handful of ZIP3 prefixes are entirely point-ZIPs (73301, the IRS in Austin,
        # is the classic case) and have no ZCTA anywhere in the sectional center.
        centroid = None
        if members:
            centroid = ZipCentroid(
                prefix,
                sum(c.lat for c in members) / len(members),
                sum(c.lon for c in members) / len(members),
            )
        self._prefixes[prefix] = centroid
        return centroid

    def miles(self, origin_zip: str, destination_zip: str) -> float:
        """Great-circle miles, or infinity when either endpoint cannot be located.

        Infinity is deliberate: every consumer feeds this into an exp(-d/k) decay, so an
        unlocatable ZIP contributes no lane credit instead of aborting the whole ranking.
        """
        origin = self.locate(origin_zip)
        destination = self.locate(destination_zip)
        if origin is None or destination is None:
            return math.inf
        return haversine_miles(origin.lat, origin.lon, destination.lat, destination.lon)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius_miles * asin(sqrt(a))
