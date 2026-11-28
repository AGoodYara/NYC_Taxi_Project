
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
PAYMENT_PATH = BASE_DIR / "data/warehouse/dimensions/dim_payment"

DWS_DIR = BASE_DIR / "data/warehouse/dws"
OUTPUT_PATH = DWS_DIR / "dws_payment_trips"
AUDIT_PATH = DWS_DIR / "dws_payment_trips_audit.json"


# ============================================================
# 2. Load source tables
# ============================================================

print("\n========== LOAD SOURCE TABLES ==========")

fact_dt = DeltaTable(str(FACT_PATH))
payment_dt = DeltaTable(str(PAYMENT_PATH))

fact = fact_dt.to_pandas(
    columns=[
        "payment_key",
        "tpep_pickup_datetime",
        "is_valid_trip",
        "is_valid_revenue",
        "total_amount",
        "trip_distance",
        "trip_duration_minutes",
        "avg_speed_mph",
    ]
)

payment = payment_dt.to_pandas()

print("Fact rows:", len(fact))
print("Payment dimension rows:", len(payment))
print("Payment dimension columns:", payment.columns.tolist())

if fact.empty:
    raise ValueError("Fact table is empty")

if payment.empty:
    raise ValueError("Payment dimension is empty")


# ============================================================
# Apply unified analysis date range
# ============================================================

print("\n========== FILTER ANALYSIS PERIOD ==========")

START_DATE = pd.Timestamp("2026-01-01")
END_DATE = pd.Timestamp("2026-03-01")

pickup = pd.to_datetime(
    fact["tpep_pickup_datetime"],
    errors="coerce",
)

if pickup.isna().any():
    raise ValueError("Invalid pickup timestamps found")

source_rows_before_filter = len(fact)

analysis_mask = (
    (pickup >= START_DATE)
    & (pickup < END_DATE)
)

fact = fact.loc[analysis_mask].copy()

source_rows_after_filter = len(fact)

print("Analysis period: 2026-01-01 to 2026-02-28")
print("Fact rows before filter:", source_rows_before_filter)
print("Fact rows after filter:", source_rows_after_filter)
print(
    "Excluded rows:",
    source_rows_before_filter - source_rows_after_filter
)

if fact.empty:
    raise ValueError("No fact records in analysis period")


if "payment_key" not in payment.columns:
    raise ValueError("payment_key missing from dimension")

if payment["payment_key"].isna().any():
    raise ValueError("Null payment keys in dimension")

if payment["payment_key"].duplicated().any():
    raise ValueError("Duplicate payment keys in dimension")


# ============================================================
# 3. Identify payment label column
# ============================================================

print("\n========== CHECK PAYMENT DIMENSION ==========")

# Different warehouse versions may use different
# descriptive column names. Use an existing column;
# never fabricate payment code descriptions.

label_candidates = [
    "payment_method",
    "payment_method_name",
    "payment_name",
    "payment_description",
    "payment_type_name",
]

label_column = next(
    (
        col for col in label_candidates
        if col in payment.columns
    ),
    None,
)

if label_column is None:
    print(
        "No descriptive payment label column found; "
        "using payment_type code only."
    )
    payment["payment_method"] = (
        "Code " + payment["payment_type"].astype(str)
    )
else:
    payment = payment.rename(
        columns={label_column: "payment_method"}
    )

required_payment_columns = [
    "payment_key",
    "payment_type",
    "payment_method",
]

missing = [
    col for col in required_payment_columns
    if col not in payment.columns
]

if missing:
    raise ValueError(
        f"Missing payment dimension columns: {missing}"
    )

payment = payment[required_payment_columns].copy()

print(
    payment.sort_values("payment_key")
    .to_string(index=False)
)


# ============================================================
# 4. Validate payment foreign keys
# ============================================================

print("\n========== VALIDATE PAYMENT KEYS ==========")

if fact["payment_key"].isna().any():
    raise ValueError("Null payment keys in fact")

unknown_keys = (
    set(fact["payment_key"])
    - set(payment["payment_key"])
)

if unknown_keys:
    raise ValueError(
        f"Unknown payment keys: {unknown_keys}"
    )

print("Payment foreign keys: PASS")


# ============================================================
# 5. Prepare metrics
# ============================================================

print("\n========== PREPARE PAYMENT METRICS ==========")

valid_trip = (
    fact["is_valid_trip"].fillna(False).astype(bool)
)

valid_revenue = (
    fact["is_valid_revenue"].fillna(False).astype(bool)
)

fact["valid_trip_count"] = valid_trip.astype("int64")
fact["invalid_trip_count"] = (~valid_trip).astype("int64")

fact["valid_revenue_count"] = (
    valid_revenue.astype("int64")
)

amount = pd.to_numeric(
    fact["total_amount"],
    errors="coerce",
)

if amount[valid_revenue].isna().any():
    raise ValueError(
        "Valid revenue records contain null amounts"
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
# 6. Aggregate by payment method
# ============================================================

print("\n========== AGGREGATE BY PAYMENT ==========")

payment_agg = (
    fact.groupby("payment_key")
    .agg(
        total_trips=("payment_key", "size"),
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
        avg_speed_mph=(
            "valid_speed", "mean"
        ),
    )
    .reset_index()
)

print("Observed payment methods:", len(payment_agg))


# ============================================================
# 7. Include all payment dimension values
# ============================================================

print("\n========== COMPLETE PAYMENT DIMENSION ==========")

result = payment.merge(
    payment_agg,
    on="payment_key",
    how="left",
    validate="one_to_one",
)

for col in [
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_revenue_trips",
]:
    result[col] = (
        result[col].fillna(0).astype("int64")
    )

result["valid_revenue_usd"] = (
    result["valid_revenue_usd"].fillna(0.0)
)

result["valid_trip_rate_pct"] = np.where(
    result["total_trips"] > 0,
    100.0 * result["valid_trips"]
    / result["total_trips"].replace(0, np.nan),
    0.0,
)

# Denominator is valid revenue records, not
# all trips. This distinction is important.
result["avg_revenue_per_valid_trip_usd"] = (
    result["valid_revenue_usd"]
    / result["valid_revenue_trips"].replace(0, np.nan)
)

for col in [
    "valid_trip_rate_pct",
    "avg_revenue_per_valid_trip_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]:
    result[col] = result[col].round(2)

FINAL_COLUMNS = [
    "payment_key",
    "payment_type",
    "payment_method",
    "total_trips",
    "valid_trips",
    "invalid_trips",
    "valid_trip_rate_pct",
    "valid_revenue_trips",
    "valid_revenue_usd",
    "avg_revenue_per_valid_trip_usd",
    "avg_distance_miles",
    "avg_duration_minutes",
    "avg_speed_mph",
]

result = (
    result[FINAL_COLUMNS]
    .sort_values("payment_key")
    .reset_index(drop=True)
)

print("DWS rows:", len(result))
print("DWS columns:", len(result.columns))


# ============================================================
# 8. Validate aggregation
# ============================================================

print("\n========== VALIDATE PAYMENT AGGREGATION ==========")

source_rows = len(fact)
source_valid = int(valid_trip.sum())
source_invalid = source_rows - source_valid
source_revenue_count = int(valid_revenue.sum())

source_revenue = round(
    float(fact["valid_revenue_amount"].sum()), 2
)

dws_revenue = round(
    float(result["valid_revenue_usd"].sum()), 2
)

revenue_difference = round(
    dws_revenue - source_revenue, 2
)

checks = {
    "row_count_pass": (
        len(result) == len(payment)
    ),
    "total_trips_pass": (
        int(result["total_trips"].sum())
        == source_rows
    ),
    "valid_trips_pass": (
        int(result["valid_trips"].sum())
        == source_valid
    ),
    "invalid_trips_pass": (
        int(result["invalid_trips"].sum())
        == source_invalid
    ),
    "valid_revenue_trips_pass": (
        int(result["valid_revenue_trips"].sum())
        == source_revenue_count
    ),
    "payment_key_unique_pass": (
        not result["payment_key"].duplicated().any()
    ),
    "payment_coverage_pass": (
        set(result["payment_key"])
        == set(payment["payment_key"])
    ),
    "revenue_pass": (
        abs(revenue_difference) <= 0.01
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
print("Payment DWS revenue:", dws_revenue)
print("Revenue difference:", revenue_difference)

if not all(checks.values()):
    raise RuntimeError(
        f"Payment DWS validation failed: {checks}"
    )


# ============================================================
# 9. Write Delta table
# ============================================================

print("\n========== WRITE PAYMENT DELTA TABLE ==========")

DWS_DIR.mkdir(parents=True, exist_ok=True)

write_deltalake(
    str(OUTPUT_PATH),
    result,
    mode="overwrite",
)

saved_dt = DeltaTable(str(OUTPUT_PATH))
saved = saved_dt.to_pandas()

if len(saved) != len(result):
    raise RuntimeError("Saved row count mismatch")

if (
    int(saved["total_trips"].sum())
    != source_rows
):
    raise RuntimeError("Saved total trips mismatch")

print("Delta write: PASS")
print("Delta version:", saved_dt.version())


# ============================================================
# 10. Audit report
# ============================================================

audit = {
    "table_name": "dws_payment_trips",
    "source_table": "fact_taxi_trips",
    "source_delta_version": int(fact_dt.version()),
    "payment_delta_version": int(payment_dt.version()),
    "dws_delta_version": int(saved_dt.version()),
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "grain": "One row per payment method",
    "source_rows": int(source_rows),
    "dws_rows": int(len(saved)),
    "source_valid_trips": int(source_valid),
    "source_valid_revenue_trips": int(source_revenue_count),
    "source_valid_revenue_usd": float(source_revenue),
    "dws_valid_revenue_usd": float(dws_revenue),
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
# 11. Business summary
# ============================================================

print("\n========== PAYMENT METHOD SUMMARY ==========")

summary = result[
    [
        "payment_type",
        "payment_method",
        "total_trips",
        "valid_trips",
        "valid_revenue_trips",
        "valid_revenue_usd",
        "avg_revenue_per_valid_trip_usd",
    ]
].sort_values(
    "total_trips", ascending=False
)

print(summary.to_string(index=False))

print("\nTotal trips:", source_rows)
print("Valid trips:", source_valid)
print("Valid revenue records:", source_revenue_count)
print("Valid revenue:", source_revenue)
print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("DWS PAYMENT TABLE CREATED SUCCESSFULLY")
print("========================================")
