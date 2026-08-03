from __future__ import annotations

import argparse
from pathlib import Path

from .geo import GeoIndex
from .ingest import ingest_data
from .pricing import estimate_price
from .ranking import active_loads, rank_carriers


def main() -> None:
    parser = argparse.ArgumentParser(description="Print price estimates and ranked carriers for active loads.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Path to generated TMS sync data")
    parser.add_argument("--limit", type=int, default=5, help="Ranked carriers to show per load")
    args = parser.parse_args()

    store = ingest_data(args.data_dir)
    geo = GeoIndex.bundled()
    loads = active_loads(store)

    print(f"Active loads: {len(loads)}")
    for load in loads:
        estimate = estimate_price(store, load, geo)
        print()
        print(f"{load.broker_id} / {load.raw_load_id}")
        print(f"  Lane: {load.pickup.city}, {load.pickup.state} {load.pickup.zip_code} -> {load.delivery.city}, {load.delivery.state} {load.delivery.zip_code}")
        print(f"  Equipment: {load.equipment.value}  Distance: {load.distance_miles:.1f} mi")
        print(
            "  Expected carrier cost: "
            f"${estimate.point_usd:,.0f} "
            f"(${estimate.low_usd:,.0f}-${estimate.high_usd:,.0f}, "
            f"{estimate.point_ppm:.2f}/mi, {estimate.confidence}, {estimate.basis})"
        )
        for reason in estimate.reasons:
            print(f"    - {reason}")
        for limitation in estimate.limitations:
            print(f"    ! {limitation}")

        print("  Ranked carriers:")
        for index, ranking in enumerate(rank_carriers(store, load, geo)[: args.limit], start=1):
            price = next(component for component in ranking.components if component.name == "price")
            print(
                f"    {index}. {ranking.carrier_name} "
                f"score={ranking.score:.3f} confidence={ranking.confidence} "
                f"expected=${price.evidence['point_usd']:,.0f}"
            )
            for reason in ranking.reasons[:3]:
                print(f"       - {reason}")
            for limitation in ranking.limitations[:2]:
                print(f"       ! {limitation}")


if __name__ == "__main__":
    main()
