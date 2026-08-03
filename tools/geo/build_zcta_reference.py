"""Rebuild the vendored ZCTA centroid reference from the US Census Gazetteer.

Source: 2020 Census Gazetteer Files, ZIP Code Tabulation Areas (national).
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html

The Gazetteer is a work of the US federal government and is in the public domain,
so the trimmed output can be committed directly into this repository.

Usage:
    python3 -m tools.geo.build_zcta_reference
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from pathlib import Path

GAZETTEER_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_zcta_national.zip"
OUTPUT = Path(__file__).resolve().parents[2] / "backend/src/carrier_pool/reference/zcta_centroids.csv"


def fetch_rows() -> list[tuple[str, float, float]]:
    with urllib.request.urlopen(GAZETTEER_URL, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    member = next(name for name in archive.namelist() if name.endswith(".txt"))
    text = archive.read(member).decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    # The Gazetteer pads its header names with trailing spaces.
    reader.fieldnames = [name.strip() for name in reader.fieldnames or []]

    rows = []
    for row in reader:
        rows.append((row["GEOID"].strip(), float(row["INTPTLAT"].strip()), float(row["INTPTLONG"].strip())))
    return sorted(rows)


def main() -> None:
    rows = fetch_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["zip", "lat", "lon"])
        for zip_code, lat, lon in rows:
            writer.writerow([zip_code, f"{lat:.6f}", f"{lon:.6f}"])
    print(f"Wrote {len(rows)} ZCTA centroids to {OUTPUT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
