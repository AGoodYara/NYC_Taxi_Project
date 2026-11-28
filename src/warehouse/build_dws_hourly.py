
from pathlib import Path
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
from deltalake import DeltaTable, write_deltalake


# ============================================================
# 1. Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

FACT_PATH = (
    BASE_DIR / "data/warehouse/facts/fact_taxi_trips"
)

DATE_PATH = (
    BASE_DIR / "data/warehouse/dimensions/dim_date"
)

DWS_DIR = BASE_DIR / "data/warehouse/dws"

OUTPUT_PATH = DWS_DIR / "dws_hourly_trips"
AUDIT_PATH = DWS_DIR / "dws_hourly_trips_audit.json"

# Candidate business definitions
MORNING_PEAK_HOURS = {7, 8, 9}
EVENING_PEAK_HOURS = {16, 17, 18}


def get_peak_period(hour):
    if hour in MORNING_PEAK_HOURS:
        return "Morning Peak"
    if hour in EVENING_PEAK_HOURS:
        return "Evening Peak"
    return "Off-Peak"


# ============================================================
# 2. Load fact and date dimension
# ============================================================

print("\n========== LOAD SOURCE TABLES ==========")

fact_dt = DeltaTable(str(FACT_PATH))
date_dt = DeltaTable(str(DATE_PATH))

fact = fact_dt.to_pandas(
    columns=[
        "pickup_date_key",
        "tpep_pickup_datetime",
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
        "month",
        "day_of_week",
        "is_weekend",
    ]
)

print("Fact rows:", len(fact))
print("Date dimension rows:", len(dim_date))

if fact.empty:
    raise ValueError("Fact table is empty")

if dim_date["date_key"].duplicated().any():
    raise ValueError("Duplicate date keys")


# ============================================================
# 3. Prepare hourly attributes
# ============================================================

print("\n========== PREPARE HOURLY DATA ==========")

pickup = pd.to_datetime(
    fact["tpep_pickup_datetime"],
    errors="coerce",
)

if pickup.isna().any():
    raise ValueError("Invalid pickup timestamps found")


# ============================================================
# Apply unified analysis date range
# ============================================================

START_DATE = pd.Timestamp("2026-01-01")
END_DATE = pd.Timestamp("2026-03-01")

analysis_mask = (
    (pickup >= START_DATE)
    & (pickup < END_DATE)
)

source_rows_before_filter = len(fact)

fact = fact.loc[analysis_mask].copy()
pickup = pickup.loc[analysis_mask].copy()

source_rows_after_filter = len(fact)

print("Analysis period:", START_DATE.date(), "to",
      (END_DATE - pd.Timedelta(days=1)).date())
print("Fact rows before filter:", source_rows_before_filter)
print("Fact rows after filter:", source_rows_after_filter)
print("Excluded rows:", source_rows_before_filter - source_rows_after_filter)

if len(fact) != 712475:
    raise ValueError(
        f"Unexpected filtered row count: {len(fact)}"
    )


fact["pickup_hour"] = pickup.dt.hour.astype("int8")

# Verify date key agrees with pickup timestamp.
calculated_date_keys = (
    pickup.dt.strftime("%Y%m%d").astype("int32")
)

if not calculated_date_keys.equals(
    fact["pickup_date_key"].astype("int32")
):
    raise ValueError("Pickup date key mismatch")

fact["valid_trip_count"] = (
    fact["is_valid_trip"].astype("int64")
)

fact["invalid_trip_count"] = (
    (~fact["is_valid_trip"]).astype("int64")
)

fact["valid_revenue_amount"] = (
    fact["total_amount"].where(
        fact["is_valid_revenue"], 0.0
    )
)

for output_col, source_col in [
    ("valid_distance", "trip_distance"),
    ("valid_duration", "trip_duration_minutes"),
    ("valid_speed", "avg_speed_mph"),
]:
    fact[output_col] = fact[source_col].where(
        fact["is_valid_trip"]
    )


# ============================================================
# 4. Aggregate by date and hour
# ============================================================

print("\n========== CALCULATE HOURLY METRICS ==========")

hourly = (
    fact.groupby(
        ["pickup_date_key", "pickup_hour"]
    )
    .agg(
        total_trips=("pickup_hour", "size"),
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
        avg_speed_mph=("valid_speed", "mean"),
    )
    .reset_index()
    .rename(
        columns={"pickup_date_key": "date_key"}
    )
)

print("Observed date-hour groups:", len(hourly))


# ============================================================
# 5. Create complete date-hour grid
# ============================================================

print("\n========== COMPLETE DATE-HOUR GRID ==========")

# Filter date dimension to the analysis period.
dim_date["full_date"] = pd.to_datetime(
    dim_date["full_date"],
    errors="coerce"
)

dim_date = dim_date[
    (dim_date["full_date"] >= pd.Timestamp("2026-01-01"))
    & (dim_date["full_date"] < pd.Timestamp("2026-03-01"))
].copy()

print("Analysis date dimension rows:", len(dim_date))


date_hours = pd.MultiIndex.from_product(
    [
        dim_date["date_key"].tolist(),
        range(24),
    ],
    names=["date_key", "pickup_hour"],
).to_frame(index=False)

hourly = date_hours.merge(
    hourly,
    on=["date_key", "pickup_hour"],
    how="left",
    validate="one_to_one",
)

hourly = hourly.merge(
    dim_date,
    on="date_key",
    how="left",
    validate="many_to_one",
)

for col in [
    "total_trips",
    "valid_trips",
    "invalid_trips",
]:
    hourly[col] = (
        hourly[col].fillna(0).astype("int64")
    )

hourly["valid_revenue_usd"] = (
    hourly["valid_revenue_usd"].fillna(0.0)
)

# Keep average metrics NULL when there are no
# valid trips; zero would be misleading.

hourly["valid_trip_rate_pct"] = np.where(
    hourly["total_trips"] > 0,
    100.0 * hourly["valid_trips"]
    / hourly["total_trips"].replace(0, np.nan),
    0.0,
)

hourly["peak_period"] = (
    hourly["pickup_hour"].map(get_peak_period)
)

# Round only for final presentation.

for col in [
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
    "valid_trip_rate_pct",
]:
    hourly[col] = hourly[col].round(2)

hourly = hourly.sort_values(
    ["date_key", "pickup_hour"]
).reset_index(drop=True)

FINAL_COLUMNS = [
    "date_key",
    "full_date",
    "year",
    "month",
    "day_of_week",
    "is_weekend",
    "pickup_hour",
    "peak_period",
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_trip_rate_pct",
    "valid_revenue_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]

hourly = hourly[FINAL_COLUMNS]

print("DWS rows:", len(hourly))
print("DWS columns:", len(hourly.columns))


# ============================================================
# 6. Validate aggregation
# ============================================================

print("\n========== VALIDATE HOURLY AGGREGATION ==========")

source_rows = len(fact)
source_valid = int(fact["is_valid_trip"].sum())
source_invalid = source_rows - source_valid

source_revenue = round(
    float(
        fact.loc[
            fact["is_valid_revenue"],
            "total_amount",
        ].sum()
    ),
    2,
)

hourly_revenue = round(
    float(hourly["valid_revenue_usd"].sum()),
    2,
)

# Revenue may differ by a few cents when
# individual hourly groups are rounded.
revenue_difference = round(
    hourly_revenue - source_revenue, 2
)

checks = {
    "row_count_pass": (
        len(hourly) == len(dim_date) * 24
    ),
    "total_trips_pass": (
        int(hourly["total_trips"].sum())
        == source_rows
    ),
    "valid_trips_pass": (
        int(hourly["valid_trips"].sum())
        == source_valid
    ),
    "invalid_trips_pass": (
        int(hourly["invalid_trips"].sum())
        == source_invalid
    ),
    "date_hour_unique_pass": (
        not hourly.duplicated(
            ["date_key", "pickup_hour"]
        ).any()
    ),
    "revenue_pass": (
        abs(revenue_difference) <= 0.05
    ),
    "date_coverage_pass": (
        hourly["date_key"].nunique()
        == len(dim_date)
    ),
}

checks = {
    name: bool(value)
    for name, value in checks.items()
}

for name, passed in checks.items():
    print(
        f"{name}: {'PASS' if passed else 'FAIL'}"
    )

print("Source revenue:", source_revenue)
print("Hourly revenue:", hourly_revenue)
print("Revenue difference:", revenue_difference)

if not all(checks.values()):
    raise RuntimeError(
        f"Hourly validation failed: {checks}"
    )


# ============================================================
# 7. Write Delta table
# ============================================================

print("\n========== WRITE DWS HOURLY TABLE ==========")

DWS_DIR.mkdir(parents=True, exist_ok=True)

write_deltalake(
    str(OUTPUT_PATH),
    hourly,
    mode="overwrite",
)

saved_dt = DeltaTable(str(OUTPUT_PATH))
saved = saved_dt.to_pandas()

if len(saved) != len(hourly):
    raise RuntimeError("Delta row count mismatch")

if (
    int(saved["total_trips"].sum())
    != source_rows
):
    raise RuntimeError("Delta trip count mismatch")

print("Delta write: PASS")
print("Delta version:", saved_dt.version())


# ============================================================
# 8. Audit report
# ============================================================

audit = {
    "table_name": "dws_hourly_trips",
    "source_table": "fact_taxi_trips",
    "source_delta_version": int(fact_dt.version()),
    "dws_delta_version": int(saved_dt.version()),
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "grain": "One row per pickup date and hour",
    "source_rows": int(source_rows),
    "dws_rows": int(len(saved)),
    "source_valid_trips": int(source_valid),
    "source_valid_revenue_usd": float(source_revenue),
    "dws_valid_revenue_usd": float(hourly_revenue),
    "revenue_difference_usd": float(revenue_difference),
    "peak_definition": {
        "morning_hours": sorted(MORNING_PEAK_HOURS),
        "evening_hours": sorted(EVENING_PEAK_HOURS),
    },
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
# 9. Summary
# ============================================================

print("\n========== HOURLY DEMAND SUMMARY ==========")

summary = (
    hourly.groupby("pickup_hour")["total_trips"]
    .sum()
    .reset_index()
)

print(summary.to_string(index=False))

print("\n========== PEAK PERIOD SUMMARY ==========")

peak_summary = (
    hourly.groupby("peak_period")["total_trips"]
    .sum()
    .reset_index()
)

peak_summary["share_pct"] = (
    100.0 * peak_summary["total_trips"]
    / source_rows
).round(2)

print(peak_summary.to_string(index=False))

print("\nTotal trips:", source_rows)
print("Valid trips:", source_valid)
print("Valid revenue:", source_revenue)
print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("DWS HOURLY TABLE CREATED SUCCESSFULLY")
print("========================================")
