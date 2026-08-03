from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from carrier_pool.geo import GeoIndex

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def geo():
    return GeoIndex.bundled()


def test_reference_is_the_full_census_zcta_table(geo):
    # The 2020 Gazetteer publishes 33,144 ZCTAs; a partial or hand-authored file would
    # silently shrink this and reintroduce the coverage gaps the vendored table removes.
    assert len(geo.centroids) == 33144
    assert {"07102", "10001", "90210", "99501", "00601"} <= set(geo.centroids)


def test_distances_match_real_world_geography(geo):
    assert geo.miles("75201", "77002") == pytest.approx(225.9, abs=1.0)
    # The README's motivating example: different cities, different states, same market.
    assert geo.miles("07102", "10001") == pytest.approx(9.3, abs=1.0)


def test_generator_and_ranker_share_one_coordinate_authority():
    from tools.datagen.cast import PLACES

    geo = GeoIndex.bundled()
    for place in PLACES.values():
        centroid = geo.centroid(place.zip_code)
        assert (place.lat, place.lon) == (centroid.lat, centroid.lon)


def test_every_place_has_a_distinct_zcta():
    from tools.datagen.cast import PLACES

    zips = [place.zip_code for place in PLACES.values()]
    assert len(zips) == len(set(zips))


def test_point_zip_falls_back_to_zip3_centroid(geo):
    # 77299 is a Houston PO-box ZIP with no ZCTA of its own.
    assert geo.resolution("77299") == "zip3"
    assert geo.miles("77299", "77002") < 15.0


def test_zip_with_no_zcta_in_its_prefix_is_unlocatable(geo):
    # 73301 is the IRS in Austin; the entire 733 prefix is point-ZIPs.
    assert geo.resolution("73301") == "unknown"
    assert geo.locate("73301") is None


def test_unlocatable_zip_yields_infinite_distance_rather_than_raising(geo):
    assert math.isinf(geo.miles("73301", "75201"))
    assert math.exp(-geo.miles("73301", "75201") / 35.0) == 0.0


def test_reference_csv_is_sorted_and_well_formed():
    path = ROOT / "backend/src/carrier_pool/reference/zcta_centroids.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["zip"] for row in rows] == sorted(row["zip"] for row in rows)
    for row in rows:
        assert len(row["zip"]) == 5 and row["zip"].isdigit()
        assert -180.0 <= float(row["lon"]) <= 180.0
        assert -90.0 <= float(row["lat"]) <= 90.0
