from __future__ import annotations

from .models import Broker, Equipment, LoadSpec, Scenario


def _load(
    key: str,
    broker: Broker,
    customer: str,
    carrier: str | None,
    pickup: str,
    delivery: str,
    equipment: Equipment,
    sell: float,
    buy: float | None,
    start_slot: int,
    *,
    lifecycle: str = "compressed",
    scenario_ids: tuple[str, ...] = (),
    notes: str = "",
    intermediate_stops: tuple[str, ...] = (),
    weight_lbs: float | None = None,
    commodity: str | None = None,
    pallet_count: float | None = None,
    correction_delta_usd: float = 0.0,
    brokeros_weight_units: str = "lbs",
    brokeros_null_equipment: bool = False,
    hauldesk_carrier_rename_slot: int | None = None,
    reassigned_carrier: str | None = None,
) -> LoadSpec:
    commodities = ("General freight", "Packaged foods", "Building materials", "Retail goods", "Medical supplies")
    variant = sum(ord(char) for char in key)
    return LoadSpec(
        key=key,
        broker=broker,
        customer=customer,
        carrier=carrier,
        pickup=pickup,
        delivery=delivery,
        equipment=equipment,
        weight_lbs=weight_lbs if weight_lbs is not None else float(18000 + (variant % 9) * 2500),
        sell_usd=sell,
        buy_usd=buy,
        start_slot=start_slot,
        lifecycle=lifecycle,
        scenario_ids=scenario_ids,
        notes=notes,
        intermediate_stops=intermediate_stops,
        commodity=commodity or commodities[variant % len(commodities)],
        pallet_count=pallet_count if pallet_count is not None else float(10 + variant % 17),
        correction_delta_usd=correction_delta_usd,
        brokeros_weight_units=brokeros_weight_units,
        brokeros_null_equipment=brokeros_null_equipment,
        hauldesk_carrier_rename_slot=hauldesk_carrier_rename_slot,
        reassigned_carrier=reassigned_carrier,
    )


def build_load_specs() -> list[LoadSpec]:
    specs: list[LoadSpec] = []

    # FreightFlow: rich DFW->Houston lane, a near-miss suburb case, deadhead isolation, and the bad half of the MC/DOT twin.
    for i, slot in enumerate(range(0, 20, 2), start=1):
        specs.append(
            _load(
                f"ff-rich-dfw-hou-{i:02d}",
                Broker.FREIGHTFLOW,
                "a_bev",
                "a_veteran_1",
                "grand_prairie",
                "katy",
                Equipment.DRY_VAN,
                1450 + i * 8,
                1160 + i * 6,
                slot,
                lifecycle="full" if i == 1 else "compressed",
                scenario_ids=("sanity", "near_miss_lane"),
                notes="Dense Grand Prairie to Katy history for the FreightFlow veteran.",
            )
        )

    for i, slot in enumerate((20, 22), start=1):
        specs.append(
            _load(
                f"ff-twin-bad-{i}",
                Broker.FREIGHTFLOW,
                "a_retail",
                "a_mid_3",
                "grand_prairie",
                "katy",
                Equipment.DRY_VAN,
                1500,
                1395 + i * 30,
                slot,
                scenario_ids=("cross_broker_twin",),
                notes="Same MC/DOT twin as HaulDesk, but poor FreightFlow economics.",
            )
        )

    specs.extend(
        [
            _load("ff-deadhead-close", Broker.FREIGHTFLOW, "a_food", "a_mid_2", "schertz", "pasadena", Equipment.REEFER, 1540, 1210, 24, scenario_ids=("deadhead_isolation",), notes="Ends near the day-11 pickup."),
            _load("ff-deadhead-far", Broker.FREIGHTFLOW, "a_food", "a_thin_3", "schertz", "pasadena", Equipment.REEFER, 1540, 1210, 26, scenario_ids=("deadhead_isolation",), notes="Same lane economics, but ends far from the day-11 pickup."),
            _load("ff-intra-dfw-1", Broker.FREIGHTFLOW, "a_retail", "a_thin_1", "fort_worth", "plano", Equipment.DRY_VAN, 540, 430, 28, scenario_ids=("state_grouping_trap",)),
            _load("ff-intra-dfw-2", Broker.FREIGHTFLOW, "a_retail", "a_thin_2", "denton", "waxahachie", Equipment.DRY_VAN, 610, 485, 30, scenario_ids=("state_grouping_trap",)),
            _load("ff-correction-rate", Broker.FREIGHTFLOW, "a_bev", "a_veteran_2", "irving", "sugar_land", Equipment.DRY_VAN, 1510, 1190, 25, lifecycle="full", correction_delta_usd=175, scenario_ids=("correction_moves_answer",), reassigned_carrier="a_mid_1"),
            _load("ff-thin-sa-dfw", Broker.FREIGHTFLOW, "a_food", "a_thin_4", "cibolo", "arlington", Equipment.FLATBED, 1260, 1085, 34, lifecycle="covered_only"),
            _load("ff-thin-dfw-sa", Broker.FREIGHTFLOW, "a_food", "a_thin_5", "plano", "new_braunfels", Equipment.FLATBED, 1320, 1110, 36),
            _load("ff-tail-slot", Broker.FREIGHTFLOW, "a_retail", "a_mid_1", "waxahachie", "baytown", Equipment.DRY_VAN, 1330, 1105, 38),
        ]
    )

    specs.extend(
        [
            _load("ff-day11-sanity-nearmiss", Broker.FREIGHTFLOW, "a_bev", None, "arlington", "sugar_land", Equipment.DRY_VAN, 1490, None, 40, lifecycle="day11", scenario_ids=("sanity", "near_miss_lane"), notes="Day-11 ACTIVE load that should borrow strength from Grand Prairie/Katy history."),
            _load("ff-day11-deadhead", Broker.FREIGHTFLOW, "a_food", None, "new_braunfels", "pasadena", Equipment.REEFER, 1560, None, 41, lifecycle="day11", scenario_ids=("deadhead_isolation",)),
            _load("ff-day11-twin-isolation", Broker.FREIGHTFLOW, "a_retail", None, "grand_prairie", "katy", Equipment.DRY_VAN, 1510, None, 42, lifecycle="day11", scenario_ids=("cross_broker_twin",)),
        ]
    )

    # HaulDesk: the good half of the twin, a small-sample trap, equipment filtering, and append-only corrections.
    for i, slot in enumerate(range(0, 16, 2), start=1):
        specs.append(
            _load(
                f"hd-twin-good-{i:02d}",
                Broker.HAULDESK,
                "b_build",
                "b_veteran_1",
                "new_braunfels",
                "pasadena",
                Equipment.DRY_VAN,
                1325 + i * 5,
                1015 + i * 4,
                slot,
                scenario_ids=("cross_broker_twin",),
                notes="Same MC/DOT twin as FreightFlow, but strong HaulDesk results.",
            )
        )

    specs.append(_load("hd-small-one-great", Broker.HAULDESK, "b_parts", "b_thin_1", "irving", "schertz", Equipment.DRY_VAN, 1400, 890, 16, scenario_ids=("small_sample_trap",), notes="One excellent result that should be shrunk toward the prior."))
    for i, slot in enumerate((18, 20, 22, 24, 26, 28, 30, 32), start=1):
        specs.append(_load(f"hd-small-many-solid-{i}", Broker.HAULDESK, "b_parts", "b_veteran_2", "irving", "schertz", Equipment.DRY_VAN, 1400 + i * 4, 980 + i * 3, slot, scenario_ids=("small_sample_trap",)))

    specs.extend(
        [
            _load("hd-flatbed-history-1", Broker.HAULDESK, "b_build", "b_thin_3", "seguin", "baytown", Equipment.FLATBED, 1320, 1060, 27, lifecycle="full", scenario_ids=("equipment_constraint",), correction_delta_usd=-85, hauldesk_carrier_rename_slot=38),
            _load("hd-flatbed-history-2", Broker.HAULDESK, "b_build", "b_thin_3", "seguin", "baytown", Equipment.FLATBED, 1340, 1075, 36, scenario_ids=("equipment_constraint",)),
            _load("hd-tail-slot", Broker.HAULDESK, "b_parts", "b_mid_1", "san_marcos", "pearland", Equipment.DRY_VAN, 1350, 1095, 38),
            _load("hd-day11-small-sample", Broker.HAULDESK, "b_parts", None, "plano", "new_braunfels", Equipment.DRY_VAN, 1420, None, 40, lifecycle="day11", scenario_ids=("small_sample_trap",)),
            _load("hd-day11-equipment", Broker.HAULDESK, "b_cold", None, "seguin", "baytown", Equipment.REEFER, 1560, None, 41, lifecycle="day11", scenario_ids=("equipment_constraint",)),
            _load("hd-day11-maintenance", Broker.HAULDESK, "b_build", "b_thin_2", "fort_worth", "plano", Equipment.DRY_VAN, 560, 455, 42, lifecycle="covered_only", notes="A day-11 historical update so the third HaulDesk sync is non-empty without adding another active ask."),
        ]
    )

    # BrokerOS: directionality, cold lane, UTC/null equipment/kg quirks, and silent rate restatement.
    for i, slot in enumerate(range(0, 16, 2), start=1):
        specs.append(_load(f"bo-direction-hou-dfw-{i:02d}", Broker.BROKEROS, "c_food", "c_veteran_1", "pasadena", "fort_worth", Equipment.REEFER, 1680 + i * 7, 1290 + i * 5, slot, scenario_ids=("directionality",), brokeros_weight_units="kg" if i == 3 else "lbs"))

    for i, slot in enumerate((16, 18, 20, 22, 24, 26), start=1):
        specs.append(_load(f"bo-sa-hou-{i}", Broker.BROKEROS, "c_med", "c_veteran_2", "san_marcos", "sugar_land", Equipment.REEFER, 1500 + i * 8, 1190 + i * 6, slot, scenario_ids=("correction_moves_answer",)))

    specs.extend(
        [
            _load("bo-silent-restatement", Broker.BROKEROS, "c_home", "c_mid_2", "plano", "pearland", Equipment.DRY_VAN, 1490, 1180, 28, lifecycle="full", correction_delta_usd=140, scenario_ids=("correction_moves_answer",), intermediate_stops=("baytown",), reassigned_carrier="c_mid_3"),
            _load("bo-null-equipment", Broker.BROKEROS, "c_home", "c_mid_1", "schertz", "katy", Equipment.UNKNOWN, 1340, 1090, 30, brokeros_null_equipment=True),
            _load("bo-intra-texas", Broker.BROKEROS, "c_home", "c_thin_5", "fort_worth", "plano", Equipment.DRY_VAN, 520, 410, 32, scenario_ids=("state_grouping_trap",)),
            _load("bo-thin-flatbed", Broker.BROKEROS, "c_med", "c_thin_2", "baytown", "cibolo", Equipment.FLATBED, 1370, 1130, 34),
            _load("bo-thin-reefer", Broker.BROKEROS, "c_med", "c_thin_4", "pearland", "new_braunfels", Equipment.REEFER, 1420, 1165, 36),
            _load("bo-tail-slot", Broker.BROKEROS, "c_food", "c_mid_3", "sugar_land", "san_marcos", Equipment.REEFER, 1440, 1175, 38),
            _load("bo-day11-cold", Broker.BROKEROS, "c_med", None, "conroe", "cibolo", Equipment.REEFER, 1280, None, 40, lifecycle="day11", scenario_ids=("cold_lane",)),
            _load("bo-day11-direction", Broker.BROKEROS, "c_food", None, "grand_prairie", "katy", Equipment.REEFER, 1700, None, 41, lifecycle="day11", scenario_ids=("directionality",)),
            _load("bo-day11-correction", Broker.BROKEROS, "c_home", None, "plano", "pearland", Equipment.DRY_VAN, 1515, None, 42, lifecycle="day11", scenario_ids=("correction_moves_answer",)),
        ]
    )

    return specs


SCENARIOS: dict[str, Scenario] = {
    "sanity": Scenario("sanity", "Rich-lane sanity check", "FreightFlow has dense Grand Prairie to Katy dry-van history.", "The day-11 Arlington to Sugar Land load should rank the FreightFlow veteran first with high confidence."),
    "near_miss_lane": Scenario("near_miss_lane", "Near-miss lane", "Historical cities differ from the day-11 cities, but both endpoints sit in the same metros.", "Exact city matching should be sparse; metro/zip clustering should recover the history."),
    "small_sample_trap": Scenario("small_sample_trap", "Small-sample trap", "One HaulDesk carrier has a single excellent DFW to SA load; another has many solid loads.", "A shrunk score should prefer the experienced carrier over the one-load outlier."),
    "deadhead_isolation": Scenario("deadhead_isolation", "Deadhead isolation", "Two FreightFlow carriers have matching lane economics but different recent delivery positions.", "The closer recent delivery should explain any ranking separation."),
    "equipment_constraint": Scenario("equipment_constraint", "Equipment constraint", "HaulDesk has flatbed history on a lane that becomes a reefer request on day 11.", "The ranker should not treat deep flatbed history as a clean reefer match."),
    "cold_lane": Scenario("cold_lane", "Cold lane", "BrokerOS has no Conroe to Cibolo history.", "The price estimate should fall back geographically and show low confidence."),
    "correction_moves_answer": Scenario("correction_moves_answer", "Correction moves answer", "FreightFlow and BrokerOS restate buy rates; HaulDesk appends a negative adjustment.", "Ingesting the correction file should change downstream estimates without hidden stale aggregates."),
    "directionality": Scenario("directionality", "Directionality", "BrokerOS has repeated Houston to DFW history, then a DFW to Houston day-11 load.", "Reverse-lane history may earn partial credit but should not be treated as identical."),
    "cross_broker_twin": Scenario("cross_broker_twin", "Cross-broker MC/DOT twin", "Delta Prime appears in FreightFlow and HaulDesk with the same MC/DOT but divergent performance.", "FreightFlow rankings must use only FreightFlow history when the broker already knows that carrier."),
    "state_grouping_trap": Scenario("state_grouping_trap", "State grouping trap", "All loads are TX to TX, including short intra-metro moves and long triangle moves.", "A state-level lane definition is visibly too broad."),
}
