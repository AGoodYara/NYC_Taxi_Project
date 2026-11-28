
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

FACT_PATH = BASE_DIR / "data/warehouse/facts/fact_taxi_trips"
DWS_DIR = BASE_DIR / "data/warehouse/dws"

OUTPUT_PATH = DWS_DIR / "dws_monthly_trips"
AUDIT_PATH = DWS_DIR / "dws_monthly_trips_audit.json"

# These are source-file months, not proof of complete
# calendar coverage or exhaustive trip collection.
SOURCE_MONTHS = {(2026, 1), (2026, 2)}


# ============================================================
# 2. Load fact table
# ============================================================

print("\n========== LOAD FACT TABLE ==========")

fact_dt = DeltaTable(str(FACT_PATH))

fact = fact_dt.to_pandas(
    columns=[
        "tpep_pickup_datetime",
        "is_valid_trip",
        "is_valid_revenue",
        "total_amount",
        "trip_distance",
        "trip_duration_minutes",
        "avg_speed_mph",
    ]
)

print("Fact rows:", len(fact))

if fact.empty:
    raise ValueError("Fact table is empty")


# ============================================================
# 3. Prepare month keys and metrics
# ============================================================

print("\n========== PREPARE MONTHLY METRICS ==========")

pickup = pd.to_datetime(
    fact["tpep_pickup_datetime"],
    errors="coerce",
)

if pickup.isna().any():
    raise ValueError("Invalid pickup timestamps")


# ============================================================
# Apply unified analysis date range
# ============================================================

print("\n========== FILTER ANALYSIS PERIOD ==========")

START_DATE = pd.Timestamp("2026-01-01")
END_DATE = pd.Timestamp("2026-03-01")

source_rows_before_filter = len(fact)

analysis_mask = (
    (pickup >= START_DATE)
    & (pickup < END_DATE)
)

fact = fact.loc[analysis_mask].copy()
pickup = pickup.loc[analysis_mask].copy()

source_rows_after_filter = len(fact)

print("Analysis period: 2026-01-01 to 2026-02-28")
print("Fact rows before filter:", source_rows_before_filter)
print("Fact rows after filter:", source_rows_after_filter)
print(
    "Excluded rows:",
    source_rows_before_filter - source_rows_after_filter
)

if len(fact) != 712475:
    raise ValueError(
        f"Unexpected filtered row count: {len(fact)}"
    )


fact["year"] = pickup.dt.year.astype("int32")
fact["month"] = pickup.dt.month.astype("int8")

fact["month_key"] = (
    fact["year"] * 100 + fact["month"]
).astype("int32")

valid_trip = (
    fact["is_valid_trip"].fillna(False).astype(bool)
)

valid_revenue = (
    fact["is_valid_revenue"].fillna(False).astype(bool)
)

fact["valid_trip_count"] = valid_trip.astype("int64")
fact["invalid_trip_count"] = (~valid_trip).astype("int64")
fact["valid_revenue_count"] = valid_revenue.astype("int64")

amount = pd.to_numeric(
    fact["total_amount"],
    errors="coerce",
)

if amount[valid_revenue].isna().any():
    raise ValueError(
        "Valid revenue records have null amounts"
    )

fact["valid_revenue_amount"] = (
    amount.where(valid_revenue, 0.0)
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
# 4. Aggregate by pickup month
# ============================================================

print("\n========== AGGREGATE BY MONTH ==========")

monthly = (
    fact.groupby(["month_key", "year", "month"])
    .agg(
        total_trips=("month_key", "size"),
        valid_trips=("valid_trip_count", "sum"),
        invalid_trips=("invalid_trip_count", "sum"),
        valid_revenue_trips=(
            "valid_revenue_count", "sum"
        ),
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
    .sort_values("month_key")
    .reset_index(drop=True)
)

monthly["month_start_date"] = pd.to_datetime(
    monthly["month_key"].astype(str) + "01",
    format="%Y%m%d",
)

monthly["valid_trip_rate_pct"] = (
    100.0 * monthly["valid_trips"]
    / monthly["total_trips"]
)


# ============================================================
# 5. Coverage status and MoM
# ============================================================

print("\n========== MONTH COVERAGE ==========")

def coverage_status(row):
    ym = (int(row["year"]), int(row["month"]))

    if ym in SOURCE_MONTHS:
        return "coverage_unverified"

    return "boundary_partial"


monthly["coverage_status"] = monthly.apply(
    coverage_status,
    axis=1,
)

# MoM is intentionally NULL until full-month
# coverage is independently verified.
monthly["trips_mom_pct"] = np.nan
monthly["revenue_mom_pct"] = np.nan

print(
    monthly[
        ["month_key", "total_trips", "coverage_status"]
    ].to_string(index=False)
)


# ============================================================
# 6. Finalize schema
# ============================================================

print("\n========== FINALIZE MONTHLY TABLE ==========")

for col in [
    "valid_trip_rate_pct",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]:
    monthly[col] = monthly[col].round(2)

FINAL_COLUMNS = [
    "month_key",
    "year",
    "month",
    "month_start_date",
    "coverage_status",
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_trip_rate_pct",
    "valid_revenue_trips",
    "valid_revenue_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
    "trips_mom_pct",
    "revenue_mom_pct",
]

monthly = monthly[FINAL_COLUMNS]

print("DWS rows:", len(monthly))
print("DWS columns:", len(monthly.columns))


# ============================================================
# 7. Validate monthly aggregation
# ============================================================

print("\n========== VALIDATE MONTHLY AGGREGATION ==========")

source_rows = len(fact)
source_valid = int(valid_trip.sum())
source_invalid = source_rows - source_valid
source_revenue_count = int(valid_revenue.sum())

source_revenue = round(
    float(fact["valid_revenue_amount"].sum()), 2
)

dws_revenue = round(
    float(monthly["valid_revenue_usd"].sum()), 2
)

revenue_difference = round(
    dws_revenue - source_revenue, 2
)

checks = {
    "total_trips_pass": (
        int(monthly["total_trips"].sum())
        == source_rows
    ),
    "valid_trips_pass": (
        int(monthly["valid_trips"].sum())
        == source_valid
    ),
    "invalid_trips_pass": (
        int(monthly["invalid_trips"].sum())
        == source_invalid
    ),
    "valid_revenue_trips_pass": (
        int(monthly["valid_revenue_trips"].sum())
        == source_revenue_count
    ),
    "month_key_unique_pass": (
        not monthly["month_key"].duplicated().any()
    ),
    "revenue_pass": (
        abs(revenue_difference) <= 0.01
    ),
    "month_key_consistency_pass": (
        (
            monthly["month_key"]
            == monthly["year"] * 100 + monthly["month"]
        ).all()
    ),
    "coverage_status_pass": (
        monthly["coverage_status"].notna().all()
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
print("Monthly revenue:", dws_revenue)
print("Revenue difference:", revenue_difference)

if not all(checks.values()):
    raise RuntimeError(
        f"Monthly DWS validation failed: {checks}"
    )


# ============================================================
# 8. Write Delta table
# ============================================================

print("\n========== WRITE MONTHLY DELTA TABLE ==========")

DWS_DIR.mkdir(parents=True, exist_ok=True)

write_deltalake(
    str(OUTPUT_PATH),
    monthly,
    mode="overwrite",
)

saved_dt = DeltaTable(str(OUTPUT_PATH))
saved = saved_dt.to_pandas()

if len(saved) != len(monthly):
    raise RuntimeError("Saved row count mismatch")

if int(saved["total_trips"].sum()) != source_rows:
    raise RuntimeError("Saved total trips mismatch")

print("Delta write: PASS")
print("Delta version:", saved_dt.version())


# ============================================================
# 9. Audit report
# ============================================================

audit = {
    "table_name": "dws_monthly_trips",
    "source_table": "fact_taxi_trips",
    "source_delta_version": int(fact_dt.version()),
    "dws_delta_version": int(saved_dt.version()),
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "grain": "One row per pickup month",
    "source_rows": int(source_rows),
    "dws_rows": int(len(saved)),
    "source_valid_trips": int(source_valid),
    "source_valid_revenue_trips": int(source_revenue_count),
    "source_valid_revenue_usd": float(source_revenue),
    "dws_valid_revenue_usd": float(dws_revenue),
    "revenue_difference_usd": float(revenue_difference),
    "coverage_note": (
        "Source months do not guarantee complete calendar "
        "coverage. MoM remains null until verified."
    ),
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
# 10. Business summary
# ============================================================

print("\n========== MONTHLY SUMMARY ==========")

print(
    monthly[
        [
            "month_key",
            "coverage_status",
            "total_trips",
            "valid_trips",
            "valid_revenue_trips",
            "valid_revenue_usd",
            "avg_distance_miles",
            "avg_duration_minutes",
            "avg_speed_mph",
        ]
    ].to_string(index=False)
)

print("\nTotal trips:", source_rows)
print("Valid trips:", source_valid)
print("Valid revenue records:", source_revenue_count)
print("Valid revenue:", source_revenue)
print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("DWS MONTHLY TABLE CREATED SUCCESSFULLY")
print("========================================")
