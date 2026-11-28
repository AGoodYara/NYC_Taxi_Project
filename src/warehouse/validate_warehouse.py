
from pathlib import Path
from datetime import datetime, timezone
import json

import pandas as pd
from deltalake import DeltaTable


BASE_DIR = Path(__file__).resolve().parents[2]

WAREHOUSE = BASE_DIR / "data/warehouse"
REPORT_PATH = (
    BASE_DIR / "data/validation/warehouse_validation_report.json"
)

TABLE_PATHS = {
    "dim_date": WAREHOUSE / "dimensions/dim_date",
    "dim_location": WAREHOUSE / "dimensions/dim_location",
    "dim_payment": WAREHOUSE / "dimensions/dim_payment",
    "fact_taxi_trips": WAREHOUSE / "facts/fact_taxi_trips",
    "dws_daily_trips": WAREHOUSE / "dws/dws_daily_trips",
    "dws_hourly_trips": WAREHOUSE / "dws/dws_hourly_trips",
    "dws_zone_trips": WAREHOUSE / "dws/dws_zone_trips",
    "dws_payment_trips": WAREHOUSE / "dws/dws_payment_trips",
    "dws_monthly_trips": WAREHOUSE / "dws/dws_monthly_trips",
}

# Load only columns needed for validation.
COLUMNS = {
    "dim_date": ["date_key"],
    "dim_location": ["location_key"],
    "dim_payment": ["payment_key"],
    "fact_taxi_trips": [
        "pickup_date_key",
        "dropoff_date_key",
        "pickup_location_key",
        "dropoff_location_key",
        "payment_key",
        "tpep_pickup_datetime",
        "is_valid_trip",
        "is_valid_revenue",
        "total_amount",
    ],
    "dws_daily_trips": [
        "date_key", "total_trips", "valid_trips",
        "invalid_trips", "valid_revenue_usd",
    ],
    "dws_hourly_trips": [
        "date_key", "pickup_hour", "total_trips",
        "valid_trips", "invalid_trips",
        "valid_revenue_usd",
    ],
    "dws_zone_trips": [
        "pickup_location_key", "total_trips",
        "valid_trips", "invalid_trips",
        "valid_revenue_usd",
    ],
    "dws_payment_trips": [
        "payment_key", "total_trips", "valid_trips",
        "invalid_trips", "valid_revenue_usd",
    ],
    "dws_monthly_trips": [
        "month_key", "total_trips", "valid_trips",
        "invalid_trips", "valid_revenue_usd",
    ],
}


print("\n========== LOAD WAREHOUSE TABLES ==========")

tables = {}
versions = {}
checks = {}
details = {}


def check(name, condition):
    passed = bool(condition)
    checks[name] = passed
    print(f"{name}: {'PASS' if passed else 'FAIL'}")


for name, path in TABLE_PATHS.items():
    dt = DeltaTable(str(path))
    tables[name] = dt.to_pandas(columns=COLUMNS[name])
    versions[name] = int(dt.version())
    print(
        f"{name}: {len(tables[name]):,} rows, "
        f"Delta version {versions[name]}"
    )


print("\n========== DIMENSION PRIMARY KEYS ==========")

dimension_keys = {
    "dim_date": "date_key",
    "dim_location": "location_key",
    "dim_payment": "payment_key",
}

for name, key in dimension_keys.items():
    df = tables[name]
    check(
        f"{name}_primary_key",
        df[key].notna().all()
        and df[key].is_unique,
    )


print("\n========== FACT FOREIGN KEYS ==========")

fact = tables["fact_taxi_trips"]

foreign_keys = {
    "pickup_date_key": ("dim_date", "date_key"),
    "dropoff_date_key": ("dim_date", "date_key"),
    "pickup_location_key": (
        "dim_location", "location_key"
    ),
    "dropoff_location_key": (
        "dim_location", "location_key"
    ),
    "payment_key": ("dim_payment", "payment_key"),
}

for fact_col, (dim_name, dim_col) in foreign_keys.items():
    valid_keys = set(tables[dim_name][dim_col].dropna())

    check(
        f"fact_{fact_col}_foreign_key",
        fact[fact_col].notna().all()
        and fact[fact_col].isin(valid_keys).all(),
    )


print("\n========== FACT BASELINE METRICS ==========")

valid_trip = fact["is_valid_trip"].fillna(False).astype(bool)
valid_revenue = (
    fact["is_valid_revenue"].fillna(False).astype(bool)
)

amount = pd.to_numeric(
    fact["total_amount"], errors="coerce"
)

check(
    "valid_revenue_amount_not_null",
    amount[valid_revenue].notna().all(),
)



# ============================================================
# Original Fact baseline
# ============================================================

original_source_rows = int(len(fact))

# ============================================================
# Analysis period baseline: Jan-Feb 2026
# ============================================================

pickup = pd.to_datetime(
    fact["tpep_pickup_datetime"],
    errors="coerce",
)

if pickup.isna().any():
    raise ValueError("Invalid pickup timestamps found")

START_DATE = pd.Timestamp("2026-01-01")
END_DATE = pd.Timestamp("2026-03-01")

analysis_mask = (
    (pickup >= START_DATE)
    & (pickup < END_DATE)
)

analysis_fact = fact.loc[analysis_mask].copy()

analysis_valid_trip = (
    analysis_fact["is_valid_trip"]
    .fillna(False)
    .astype(bool)
)

analysis_valid_revenue = (
    analysis_fact["is_valid_revenue"]
    .fillna(False)
    .astype(bool)
)

analysis_amount = pd.to_numeric(
    analysis_fact["total_amount"],
    errors="coerce",
)

if analysis_amount[analysis_valid_revenue].isna().any():
    raise ValueError("Valid revenue records have null amounts")

source_rows = int(len(analysis_fact))
source_valid = int(analysis_valid_trip.sum())
source_invalid = source_rows - source_valid

source_revenue = round(
    float(
        analysis_amount.where(
            analysis_valid_revenue, 0.0
        ).sum()
    ),
    2,
)

details["fact_baseline"] = {
    "original_fact_rows": original_source_rows,
    "analysis_period": "2026-01-01 to 2026-02-28",
    "analysis_rows": source_rows,
    "excluded_rows": original_source_rows - source_rows,
    "total_trips": source_rows,
    "valid_trips": source_valid,
    "invalid_trips": source_invalid,
    "valid_revenue_usd": source_revenue,
}

print(details["fact_baseline"])




check(
    "fact_original_row_count",
    original_source_rows == 712476,
)

check(
    "analysis_period_row_count",
    source_rows == 712475,
)

check(
    "analysis_period_excluded_rows",
    original_source_rows - source_rows == 1,
)

print("\n========== DWS CROSS-TABLE RECONCILIATION ==========")

dws_names = [
    "dws_daily_trips",
    "dws_hourly_trips",
    "dws_zone_trips",
    "dws_payment_trips",
    "dws_monthly_trips",
]

for name in dws_names:
    df = tables[name]

    total = int(df["total_trips"].sum())
    valid = int(df["valid_trips"].sum())
    invalid = int(df["invalid_trips"].sum())
    revenue = round(
        float(df["valid_revenue_usd"].sum()), 2
    )

    details[name] = {
        "total_trips": total,
        "valid_trips": valid,
        "invalid_trips": invalid,
        "valid_revenue_usd": revenue,
    }

    check(f"{name}_total_trips", total == source_rows)
    check(f"{name}_valid_trips", valid == source_valid)
    check(
        f"{name}_invalid_trips",
        invalid == source_invalid,
    )
    check(
        f"{name}_valid_revenue",
        abs(revenue - source_revenue) <= 0.01,
    )


print("\n========== DWS GRAIN UNIQUENESS ==========")

grain_keys = {
    "dws_daily_trips": ["date_key"],
    "dws_hourly_trips": ["date_key", "pickup_hour"],
    "dws_zone_trips": ["pickup_location_key"],
    "dws_payment_trips": ["payment_key"],
    "dws_monthly_trips": ["month_key"],
}

for name, keys in grain_keys.items():
    df = tables[name]
    check(
        f"{name}_grain_unique",
        df[keys].notna().all().all()
        and not df.duplicated(keys).any(),
    )


print("\n========== DAILY VS MONTHLY ==========")

print("\n========== ANALYSIS PERIOD VALIDATION ==========")

analysis_dates = pd.to_datetime(
    fact["tpep_pickup_datetime"],
    errors="coerce",
)

analysis_start = pd.Timestamp("2026-01-01")
analysis_end = pd.Timestamp("2026-03-01")

check(
    "daily_date_range",
    (
        tables["dws_daily_trips"]["date_key"].between(
            20260101, 20260228
        ).all()
        and len(tables["dws_daily_trips"]) == 59
    ),
)

check(
    "hourly_date_range",
    (
        tables["dws_hourly_trips"]["date_key"].between(
            20260101, 20260228
        ).all()
        and len(tables["dws_hourly_trips"]) == 1416
    ),
)

check(
    "monthly_date_range",
    set(tables["dws_monthly_trips"]["month_key"])
    == {202601, 202602},
)

daily = tables["dws_daily_trips"].copy()
monthly = tables["dws_monthly_trips"].copy()

daily["month_key"] = (
    daily["date_key"].astype("int64") // 100
)

daily_month = (
    daily.groupby("month_key", as_index=False)
    .agg(
        total_trips=("total_trips", "sum"),
        valid_trips=("valid_trips", "sum"),
        invalid_trips=("invalid_trips", "sum"),
        valid_revenue_usd=("valid_revenue_usd", "sum"),
    )
)

comparison = daily_month.merge(
    monthly,
    on="month_key",
    how="outer",
    suffixes=("_daily", "_monthly"),
    indicator=True,
    validate="one_to_one",
)

check(
    "daily_monthly_month_coverage",
    comparison["_merge"].eq("both").all(),
)

for metric in [
    "total_trips",
    "valid_trips",
    "invalid_trips",
]:
    check(
        f"daily_monthly_{metric}",
        (
            comparison[f"{metric}_daily"]
            == comparison[f"{metric}_monthly"]
        ).all(),
    )

check(
    "daily_monthly_revenue",
    (
        comparison["valid_revenue_usd_daily"]
        - comparison["valid_revenue_usd_monthly"]
    ).abs().le(0.01).all(),
)


print("\n========== WRITE VALIDATION REPORT ==========")

report = {
    "report_name": "NYC Taxi Warehouse Validation",
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "delta_versions": versions,
    "checks": checks,
    "details": details,
    "total_checks": len(checks),
    "passed_checks": sum(checks.values()),
    "failed_checks": [
        name for name, passed in checks.items()
        if not passed
    ],
    "validation_pass": all(checks.values()),
}

REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=4)

print("Report saved:", REPORT_PATH)

print("\n========== FINAL RESULT ==========")
print(
    f"Checks passed: "
    f"{report['passed_checks']}/{report['total_checks']}"
)

if not report["validation_pass"]:
    raise RuntimeError(
        "Warehouse validation failed. "
        "Check the report for details."
    )

print("\n========================================")
print("WAREHOUSE VALIDATION PASSED")
print("========================================")
