from pathlib import Path
import json
from datetime import datetime, timezone

import pandas as pd
from deltalake import DeltaTable, write_deltalake


# ============================================================
# 1. Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

FACT_PATH = (
    BASE_DIR / "data" / "warehouse"
    / "facts" / "fact_taxi_trips"
)

DATE_DIM_PATH = (
    BASE_DIR / "data" / "warehouse"
    / "dimensions" / "dim_date"
)

DWS_DIR = (
    BASE_DIR / "data" / "warehouse"
    / "dws"
)

OUTPUT_PATH = DWS_DIR / "dws_daily_trips"

AUDIT_PATH = (
    DWS_DIR / "dws_daily_trips_audit.json"
)


# ============================================================
# 2. Load source tables
# ============================================================

print("\n========== LOAD SOURCE TABLES ==========")

for path in [FACT_PATH, DATE_DIM_PATH]:
    if not path.exists():
        raise FileNotFoundError(path)

fact_dt = DeltaTable(str(FACT_PATH))
date_dt = DeltaTable(str(DATE_DIM_PATH))

fact = fact_dt.to_pandas(
    columns=[
        "pickup_date_key",
        "is_valid_trip",
        "is_valid_revenue",
        "total_amount",
        "trip_distance",
        "trip_duration_minutes",
        "avg_speed_mph",
    ]
)

dim_date = date_dt.to_pandas(
    columns=[
        "date_key",
        "full_date",
        "year",
        "quarter",
        "month",
        "day",
        "day_of_week",
        "day_name",
        "is_weekend",
    ]
)

print("Fact rows:", len(fact))
print("Date dimension rows:", len(dim_date))


# ============================================================
# 3. Prepare fact data
# ============================================================

print("\n========== PREPARE FACT DATA ==========")

fact["is_valid_trip"] = (
    fact["is_valid_trip"].astype(bool)
)

fact["is_valid_revenue"] = (
    fact["is_valid_revenue"].astype(bool)
)

# Use pickup date as the daily reporting date.
fact["pickup_date_key"] = (
    fact["pickup_date_key"].astype("int32")
)


# ============================================================
# 4. Calculate daily metrics
# ============================================================

print("\n========== CALCULATE DAILY METRICS ==========")

fact["valid_trip_count"] = (
    fact["is_valid_trip"].astype("int64")
)

fact["invalid_trip_count"] = (
    (~fact["is_valid_trip"]).astype("int64")
)

fact["valid_revenue_amount"] = (
    fact["total_amount"].where(
        fact["is_valid_revenue"], 0
    )
)

valid_distance = fact["trip_distance"].where(
    fact["is_valid_trip"]
)

valid_duration = fact["trip_duration_minutes"].where(
    fact["is_valid_trip"]
)

valid_speed = fact["avg_speed_mph"].where(
    fact["is_valid_trip"]
)

fact["valid_distance"] = valid_distance
fact["valid_duration"] = valid_duration
fact["valid_speed"] = valid_speed

daily = (
    fact.groupby("pickup_date_key")
    .agg(
        total_trips=("pickup_date_key", "size"),
        valid_trips=("valid_trip_count", "sum"),
        invalid_trips=("invalid_trip_count", "sum"),
        valid_revenue_usd=(
            "valid_revenue_amount", "sum"
        ),
        avg_distance_miles=(
            "valid_distance", "mean"
        ),
        avg_duration_minutes=(
            "valid_duration", "mean"
        ),
        avg_speed_mph=(
            "valid_speed", "mean"
        ),
    )
    .reset_index()
    .rename(
        columns={
            "pickup_date_key": "date_key"
        }
    )
)

daily["valid_trip_rate_pct"] = (
    daily["valid_trips"]
    / daily["total_trips"]
    * 100
)

daily["invalid_trip_rate_pct"] = (
    daily["invalid_trips"]
    / daily["total_trips"]
    * 100
)

daily["valid_revenue_usd"] = (
    daily["valid_revenue_usd"].round(2)
)

for col in [
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
    "valid_trip_rate_pct",
    "invalid_trip_rate_pct",
]:
    daily[col] = daily[col].round(2)


# ============================================================
# 5. Join date dimension
# ============================================================

print("\n========== JOIN DATE DIMENSION ==========")

# Check all aggregated dates exist in dim_date
if not daily["date_key"].isin(
    dim_date["date_key"]
).all():
    raise ValueError(
        "Some daily records cannot match dim_date"
    )

# One row per calendar date, including dates
# without pickup trips.
daily = dim_date.merge(
    daily,
    on="date_key",
    how="left",
    validate="one_to_one",
)

count_columns = [
    "total_trips",
    "valid_trips",
    "invalid_trips",
]

for col in count_columns:
    daily[col] = (
        daily[col].fillna(0).astype("int64")
    )

daily["valid_revenue_usd"] = (
    daily["valid_revenue_usd"].fillna(0.0)
)

daily["valid_trip_rate_pct"] = (
    daily["valid_trip_rate_pct"].fillna(0.0)
)

daily["invalid_trip_rate_pct"] = (
    daily["invalid_trip_rate_pct"].fillna(0.0)
)

daily = daily.sort_values(
    "date_key"
).reset_index(drop=True)


# ============================================================
# 6. Arrange final columns
# ============================================================

FINAL_COLUMNS = [
    "date_key",
    "full_date",
    "year",
    "quarter",
    "month",
    "day",
    "day_of_week",
    "day_name",
    "is_weekend",
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_trip_rate_pct",
    "invalid_trip_rate_pct",
    "valid_revenue_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]

daily = daily[FINAL_COLUMNS]

print("DWS rows:", len(daily))
print("DWS columns:", len(daily.columns))


# ============================================================
# 7. Validate aggregation
# ============================================================

print("\n========== VALIDATE DAILY AGGREGATION ==========")

source_rows = len(fact)

daily_total = int(daily["total_trips"].sum())

source_valid = int(fact["is_valid_trip"].sum())

daily_valid = int(daily["valid_trips"].sum())

source_invalid = source_rows - source_valid

daily_invalid = int(daily["invalid_trips"].sum())

source_revenue = round(
    fact.loc[
        fact["is_valid_revenue"],
        "total_amount"
    ].sum(),
    2
)

daily_revenue = round(
    daily["valid_revenue_usd"].sum(),
    2
)

checks = {
    "total_trips_pass": daily_total == source_rows,
    "valid_trips_pass": daily_valid == source_valid,
    "invalid_trips_pass": daily_invalid == source_invalid,
    "revenue_pass": daily_revenue == source_revenue,
    "date_key_unique_pass": (
        not daily["date_key"].duplicated().any()
    ),
    "date_dimension_coverage_pass": (
        len(daily) == len(dim_date)
    ),
}

for name, passed in checks.items():
    print(
        f"{name}: {'PASS' if passed else 'FAIL'}"
    )

if not all(checks.values()):
    raise RuntimeError(
        f"DWS validation failed: {checks}"
    )

print("Source revenue:", source_revenue)
print("DWS revenue:", daily_revenue)


# ============================================================
# 8. Write DWS Delta table
# ============================================================

print("\n========== WRITE DWS TABLE ==========")

DWS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

write_deltalake(
    str(OUTPUT_PATH),
    daily,
    mode="overwrite",
)

dws_dt = DeltaTable(str(OUTPUT_PATH))

saved = dws_dt.to_pandas()

if len(saved) != len(daily):
    raise RuntimeError(
        "DWS write row count mismatch"
    )

print("DWS Delta write: PASS")
print("Delta version:", dws_dt.version())



# ============================================================
# 9. Generate audit report
# ============================================================

audit = {
    "table_name": "dws_daily_trips",
    "source_table": "fact_taxi_trips",

    "source_delta_version": int(fact_dt.version()),
    "dws_delta_version": int(dws_dt.version()),

    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),

    "source_rows": int(source_rows),
    "dws_rows": int(len(saved)),

    "source_valid_trips": int(source_valid),
    "dws_valid_trips": int(daily_valid),

    "source_valid_revenue_usd": float(source_revenue),
    "dws_valid_revenue_usd": float(daily_revenue),

    # Convert NumPy/Pandas bool to native Python bool
    "checks": {
        name: bool(passed)
        for name, passed in checks.items()
    },

    "validation_pass": bool(
        all(checks.values())
    ),
}

with open(
    AUDIT_PATH,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=4
    )

print("Audit report: PASS")


# ============================================================
# 10. Final summary
# ============================================================

print("\n========== DWS DAILY SUMMARY ==========")

print(
    daily[
        [
            "full_date",
            "total_trips",
            "valid_trips",
            "valid_revenue_usd",
        ]
    ].head(10).to_string(index=False)
)

print("\nTotal daily trips:", daily_total)
print("Total valid trips:", daily_valid)
print("Total valid revenue:", daily_revenue)

print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("DWS DAILY TABLE CREATED SUCCESSFULLY")
print("========================================")
