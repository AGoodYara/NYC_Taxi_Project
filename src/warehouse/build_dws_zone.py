
from pathlib import Path
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
from deltalake import DeltaTable, write_deltalake


BASE_DIR = Path(__file__).resolve().parents[2]

FACT_PATH = BASE_DIR / "data/warehouse/facts/fact_taxi_trips"
LOCATION_PATH = BASE_DIR / "data/warehouse/dimensions/dim_location"

DWS_DIR = BASE_DIR / "data/warehouse/dws"
OUTPUT_PATH = DWS_DIR / "dws_zone_trips"
AUDIT_PATH = DWS_DIR / "dws_zone_trips_audit.json"


# ============================================================
# 1. Load source tables
# ============================================================

print("\n========== LOAD SOURCE TABLES ==========")

fact_dt = DeltaTable(str(FACT_PATH))
location_dt = DeltaTable(str(LOCATION_PATH))

fact = fact_dt.to_pandas(
    columns=[
        "pickup_location_key",
        "is_valid_trip",
        "is_valid_revenue",
        "total_amount",
        "trip_distance",
        "trip_duration_minutes",
        "avg_speed_mph",
    ]
)

location = location_dt.to_pandas(
    columns=[
        "location_key",
        "location_id",
        "borough",
        "zone",
    ]
)

print("Fact rows:", len(fact))
print("Location rows:", len(location))

if fact.empty:
    raise ValueError("Fact table is empty")

if location.empty:
    raise ValueError("Location dimension is empty")

if location["location_key"].isna().any():
    raise ValueError("Null location keys in dimension")

if location["location_key"].duplicated().any():
    raise ValueError("Duplicate location keys in dimension")


# ============================================================
# 2. Validate foreign keys
# ============================================================

print("\n========== VALIDATE LOCATION KEYS ==========")

if fact["pickup_location_key"].isna().any():
    raise ValueError("Null pickup location keys in fact")

unknown_keys = (
    set(fact["pickup_location_key"])
    - set(location["location_key"])
)

if unknown_keys:
    raise ValueError(
        f"Unknown pickup location keys: {unknown_keys}"
    )

print("Pickup location foreign keys: PASS")


# ============================================================
# 3. Prepare metrics
# ============================================================

print("\n========== PREPARE ZONE METRICS ==========")

valid_trip = fact["is_valid_trip"].fillna(False).astype(bool)
valid_revenue = fact["is_valid_revenue"].fillna(False).astype(bool)

fact["valid_trip_count"] = valid_trip.astype("int64")
fact["invalid_trip_count"] = (~valid_trip).astype("int64")

fact["valid_revenue_amount"] = (
    pd.to_numeric(fact["total_amount"], errors="coerce")
    .where(valid_revenue, 0.0)
)

for target, source in [
    ("valid_distance", "trip_distance"),
    ("valid_duration", "trip_duration_minutes"),
    ("valid_speed", "avg_speed_mph"),
]:
    fact[target] = (
        pd.to_numeric(fact[source], errors="coerce")
        .where(valid_trip)
    )


# ============================================================
# 4. Aggregate by pickup zone
# ============================================================

print("\n========== AGGREGATE BY PICKUP ZONE ==========")

zone_agg = (
    fact.groupby("pickup_location_key")
    .agg(
        total_trips=("pickup_location_key", "size"),
        valid_trips=("valid_trip_count", "sum"),
        invalid_trips=("invalid_trip_count", "sum"),
        valid_revenue_usd=("valid_revenue_amount", "sum"),
        avg_distance_miles=("valid_distance", "mean"),
        avg_duration_minutes=("valid_duration", "mean"),
        avg_speed_mph=("valid_speed", "mean"),
    )
    .reset_index()
)

print("Observed pickup zones:", len(zone_agg))


# ============================================================
# 5. Include all dimension zones
# ============================================================

print("\n========== COMPLETE ZONE DIMENSION ==========")

zone = location.merge(
    zone_agg,
    left_on="location_key",
    right_on="pickup_location_key",
    how="left",
    validate="one_to_one",
)

zone = zone.drop(columns=["pickup_location_key"])

zone = zone.rename(
    columns={"location_key": "pickup_location_key"}
)

for col in [
    "total_trips",
    "valid_trips",
    "invalid_trips",
]:
    zone[col] = zone[col].fillna(0).astype("int64")

zone["valid_revenue_usd"] = (
    zone["valid_revenue_usd"].fillna(0.0)
)

zone["valid_trip_rate_pct"] = np.where(
    zone["total_trips"] > 0,
    zone["valid_trips"]
    / zone["total_trips"].replace(0, np.nan) * 100,
    0.0,
)

# Average metrics stay NULL for zones without valid trips.
for col in [
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
    "valid_trip_rate_pct",
]:
    zone[col] = zone[col].round(2)

FINAL_COLUMNS = [
    "pickup_location_key",
    "location_id",
    "borough",
    "zone",
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_trip_rate_pct",
    "valid_revenue_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]

zone = (
    zone[FINAL_COLUMNS]
    .sort_values("pickup_location_key")
    .reset_index(drop=True)
)

print("DWS rows:", len(zone))
print("DWS columns:", len(zone.columns))


# ============================================================
# 6. Validate aggregation
# ============================================================

print("\n========== VALIDATE ZONE AGGREGATION ==========")

source_rows = len(fact)
source_valid = int(valid_trip.sum())
source_invalid = source_rows - source_valid

source_revenue = round(
    float(fact["valid_revenue_amount"].sum()), 2
)

zone_revenue = round(
    float(zone["valid_revenue_usd"].sum()), 2
)

revenue_difference = round(
    zone_revenue - source_revenue, 2
)

checks = {
    "row_count_pass": len(zone) == len(location),
    "total_trips_pass": (
        int(zone["total_trips"].sum()) == source_rows
    ),
    "valid_trips_pass": (
        int(zone["valid_trips"].sum()) == source_valid
    ),
    "invalid_trips_pass": (
        int(zone["invalid_trips"].sum()) == source_invalid
    ),
    "zone_key_unique_pass": (
        not zone["pickup_location_key"].duplicated().any()
    ),
    "revenue_pass": (
        abs(revenue_difference) <= 0.01
    ),
    "location_coverage_pass": (
        set(zone["pickup_location_key"])
        == set(location["location_key"])
    ),
}

checks = {
    name: bool(result)
    for name, result in checks.items()
}

for name, passed in checks.items():
    print(f"{name}: {'PASS' if passed else 'FAIL'}")

print("Source revenue:", source_revenue)
print("Zone revenue:", zone_revenue)
print("Revenue difference:", revenue_difference)

if not all(checks.values()):
    raise RuntimeError(f"Validation failed: {checks}")


# ============================================================
# 7. Write Delta Lake table
# ============================================================

print("\n========== WRITE ZONE DELTA TABLE ==========")

DWS_DIR.mkdir(parents=True, exist_ok=True)

write_deltalake(
    str(OUTPUT_PATH),
    zone,
    mode="overwrite",
)

saved_dt = DeltaTable(str(OUTPUT_PATH))
saved = saved_dt.to_pandas()

if len(saved) != len(zone):
    raise RuntimeError("Saved row count mismatch")

if int(saved["total_trips"].sum()) != source_rows:
    raise RuntimeError("Saved trip count mismatch")

print("Delta write: PASS")
print("Delta version:", saved_dt.version())


# ============================================================
# 8. Write audit report
# ============================================================

audit = {
    "table_name": "dws_zone_trips",
    "source_table": "fact_taxi_trips",
    "source_delta_version": int(fact_dt.version()),
    "location_delta_version": int(location_dt.version()),
    "dws_delta_version": int(saved_dt.version()),
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "grain": "One row per pickup location",
    "source_rows": int(source_rows),
    "dws_rows": int(len(saved)),
    "source_valid_trips": int(source_valid),
    "source_valid_revenue_usd": float(source_revenue),
    "dws_valid_revenue_usd": float(zone_revenue),
    "revenue_difference_usd": float(revenue_difference),
    "checks": checks,
    "validation_pass": bool(all(checks.values())),
}

with open(AUDIT_PATH, "w", encoding="utf-8") as f:
    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=4,
    )

print("Audit report: PASS")


# ============================================================
# 9. Business analysis
# ============================================================

print("\n========== TOP 10 PICKUP ZONES ==========")

top_zones = zone.sort_values(
    "total_trips", ascending=False
).head(10)

print(
    top_zones[
        [
            "borough",
            "zone",
            "total_trips",
            "valid_revenue_usd",
        ]
    ].to_string(index=False)
)

print("\n========== BOROUGH SUMMARY ==========")

borough_summary = (
    zone.groupby("borough", dropna=False)
    .agg(
        total_trips=("total_trips", "sum"),
        valid_revenue_usd=("valid_revenue_usd", "sum"),
    )
    .reset_index()
    .sort_values("total_trips", ascending=False)
)

print(borough_summary.to_string(index=False))

print("\nTotal trips:", source_rows)
print("Valid trips:", source_valid)
print("Valid revenue:", source_revenue)
print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("DWS ZONE TABLE CREATED SUCCESSFULLY")
print("========================================")
