from pathlib import Path
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd

from deltalake import DeltaTable, write_deltalake


# ============================================================
# 1. Project configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

DWD_PATH = (
    BASE_DIR / "data" / "delta_test"
    / "dwd_v1" / "yellow_taxi_trips"
)

DIMENSION_DIR = BASE_DIR / "data" / "warehouse" / "dimensions"

FACT_PATH = (
    BASE_DIR / "data" / "warehouse"
    / "facts" / "fact_taxi_trips"
)

AUDIT_PATH = (
    BASE_DIR / "data" / "warehouse"
    / "facts" / "fact_taxi_trips_audit.json"
)

SOURCE_COLUMNS = [
    "VendorID",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "RatecodeID",
    "store_and_fwd_flag",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "total_amount",
    "congestion_surcharge",
    "Airport_fee",
    "cbd_congestion_fee",
    "trip_duration_minutes",
    "avg_speed_mph",
    "missing_passenger_count",
    "missing_ratecode",
    "invalid_duration",
    "invalid_distance",
    "invalid_speed",
    "is_negative_amount",
    "is_zero_amount",
    "is_high_amount",
    "is_valid_trip",
    "is_valid_revenue",
    "quality_rule_version",
    "year",
    "month",
]

FOREIGN_KEYS = [
    "pickup_date_key",
    "dropoff_date_key",
    "pickup_location_key",
    "dropoff_location_key",
    "payment_key",
]


# ============================================================
# 2. Load DWD and dimension tables
# ============================================================

print("\n========== LOAD SOURCE TABLES ==========")

for path in [
    DWD_PATH,
    DIMENSION_DIR / "dim_date",
    DIMENSION_DIR / "dim_location",
    DIMENSION_DIR / "dim_payment",
]:
    if not path.exists():
        raise FileNotFoundError(
            f"Required Delta table not found: {path}"
        )

dwd_dt = DeltaTable(str(DWD_PATH))

source = dwd_dt.to_pandas(
    columns=SOURCE_COLUMNS
)

date_dim = DeltaTable(
    str(DIMENSION_DIR / "dim_date")
).to_pandas()

location_dim = DeltaTable(
    str(DIMENSION_DIR / "dim_location")
).to_pandas()

payment_dim = DeltaTable(
    str(DIMENSION_DIR / "dim_payment")
).to_pandas()

print("DWD rows:", len(source))
print("DWD version:", dwd_dt.version())

print("Date dimension:", len(date_dim))
print("Location dimension:", len(location_dim))
print("Payment dimension:", len(payment_dim))

if source.empty:
    raise ValueError("DWD source is empty")


# ============================================================
# 3. Validate dimension primary keys
# ============================================================

print("\n========== VALIDATE DIMENSIONS ==========")

dimension_keys = {
    "dim_date": (date_dim, "date_key"),
    "dim_location": (location_dim, "location_key"),
    "dim_payment": (payment_dim, "payment_key"),
}

for name, (df, pk) in dimension_keys.items():

    if df[pk].isna().any():
        raise ValueError(f"{name}: NULL primary key")

    if df[pk].duplicated().any():
        raise ValueError(f"{name}: Duplicate primary key")

    print(f"{name}: PK PASS")


# ============================================================
# 4. Build dimension lookup mappings
# ============================================================

print("\n========== BUILD DIMENSION MAPPINGS ==========")

# Date mapping
date_keys = set(
    date_dim["date_key"].astype("int64")
)

# Location mapping
location_map = dict(
    zip(
        location_dim["location_id"].astype("int64"),
        location_dim["location_key"].astype("int64")
    )
)

# Payment mapping
payment_map = dict(
    zip(
        payment_dim["payment_type"].astype("int64"),
        payment_dim["payment_key"].astype("int64")
    )
)

print("Date keys:", len(date_keys))
print("Location mappings:", len(location_map))
print("Payment mappings:", len(payment_map))


# ============================================================
# 5. Generate date foreign keys
# ============================================================

print("\n========== MAP DATE DIMENSION ==========")

for source_col, target_col in [
    ("tpep_pickup_datetime", "pickup_date_key"),
    ("tpep_dropoff_datetime", "dropoff_date_key"),
]:

    dates = pd.to_datetime(
        source[source_col],
        errors="coerce"
    )

    if dates.isna().any():
        raise ValueError(
            f"{source_col}: Invalid or missing dates found"
        )

    keys = (
        dates.dt.strftime("%Y%m%d")
        .astype("int32")
    )

    unmatched = ~keys.isin(date_keys)

    if unmatched.any():
        raise ValueError(
            f"{target_col}: "
            f"{int(unmatched.sum())} dates not found"
        )

    source[target_col] = keys

    print(
        f"{target_col}: PASS | "
        f"Unique dates={keys.nunique()}"
    )


# ============================================================
# 6. Generate location foreign keys
# ============================================================

print("\n========== MAP LOCATION DIMENSION ==========")

source["pickup_location_key"] = (
    source["PULocationID"]
    .map(location_map)
)

source["dropoff_location_key"] = (
    source["DOLocationID"]
    .map(location_map)
)

for col in [
    "pickup_location_key",
    "dropoff_location_key",
]:

    unmatched = source[col].isna()

    if unmatched.any():
        raise ValueError(
            f"{col}: {int(unmatched.sum())} "
            "unmatched location records"
        )

    source[col] = source[col].astype("int32")

    print(f"{col}: PASS")


# ============================================================
# 7. Generate payment foreign key
# ============================================================

print("\n========== MAP PAYMENT DIMENSION ==========")

source["payment_key"] = (
    source["payment_type"]
    .map(payment_map)
)

if source["payment_key"].isna().any():
    raise ValueError(
        "Unmatched payment types found"
    )

source["payment_key"] = (
    source["payment_key"].astype("int32")
)

print("payment_key: PASS")


# ============================================================
# 8. Build fact table
# ============================================================

print("\n========== BUILD FACT TABLE ==========")

fact = source.copy()

# The DWD source does not contain a natural trip ID.
# This is a generated surrogate key for this build.

fact.insert(
    0,
    "trip_key",
    np.arange(
        1,
        len(fact) + 1,
        dtype=np.int64
    )
)

fact_columns = [
    "trip_key",
    "pickup_date_key",
    "dropoff_date_key",
    "pickup_location_key",
    "dropoff_location_key",
    "payment_key",
] + SOURCE_COLUMNS

fact = fact[fact_columns]

print("Fact rows:", len(fact))
print("Fact columns:", len(fact.columns))


# ============================================================
# 9. Validate fact table before writing
# ============================================================

print("\n========== PRE-WRITE VALIDATION ==========")

if fact["trip_key"].duplicated().any():
    raise ValueError("Duplicate trip_key found")

if fact["trip_key"].isna().any():
    raise ValueError("NULL trip_key found")

for col in FOREIGN_KEYS:

    null_count = int(fact[col].isna().sum())

    if null_count > 0:
        raise ValueError(
            f"{col}: {null_count} NULL foreign keys"
        )

    print(f"{col}: PASS")

if len(fact) != len(source):
    raise ValueError(
        "Fact row count differs from source row count"
    )

source_valid_trips = int(
    source["is_valid_trip"].sum()
)

source_valid_revenue = int(
    source["is_valid_revenue"].sum()
)

print("Primary key: PASS")
print("Foreign keys: PASS")
print("Row count: PASS")
print("Valid trips:", source_valid_trips)
print("Valid revenue:", source_valid_revenue)


# ============================================================
# 10. Write fact table to Delta Lake
# ============================================================

print("\n========== WRITE FACT TABLE ==========")

FACT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

write_deltalake(
    str(FACT_PATH),
    fact,
    mode="overwrite",
    partition_by=["year", "month"],
)

print("Fact table written successfully")


# ============================================================
# 11. Read back and validate Delta table
# ============================================================

print("\n========== POST-WRITE VALIDATION ==========")

fact_dt = DeltaTable(str(FACT_PATH))

written = fact_dt.to_pandas(
    columns=[
        "trip_key",
        "pickup_date_key",
        "dropoff_date_key",
        "pickup_location_key",
        "dropoff_location_key",
        "payment_key",
        "is_valid_trip",
        "is_valid_revenue",
    ]
)

written_rows = len(written)

row_count_pass = (
    written_rows == len(source)
)

pk_pass = (
    written["trip_key"].notna().all()
    and not written["trip_key"].duplicated().any()
)

fk_pass = all(
    written[col].notna().all()
    for col in FOREIGN_KEYS
)

valid_trip_count = int(
    written["is_valid_trip"].sum()
)

valid_revenue_count = int(
    written["is_valid_revenue"].sum()
)

quality_pass = (
    valid_trip_count == source_valid_trips
    and valid_revenue_count == source_valid_revenue
)

partition_columns = (
    fact_dt.metadata().partition_columns
)

partition_pass = (
    partition_columns == ["year", "month"]
)

checks = {
    "row_count_pass": bool(row_count_pass),
    "primary_key_pass": bool(pk_pass),
    "foreign_key_pass": bool(fk_pass),
    "quality_count_pass": bool(quality_pass),
    "partition_pass": bool(partition_pass),
}

if not all(checks.values()):
    raise RuntimeError(
        f"Fact table validation failed: {checks}"
    )


# ============================================================
# 12. Generate audit report
# ============================================================

audit = {
    "table_name": "fact_taxi_trips",
    "source_table": "dwd_v1/yellow_taxi_trips",
    "source_delta_version": dwd_dt.version(),
    "fact_delta_version": fact_dt.version(),
    "execution_time_utc": datetime.now(
        timezone.utc
    ).isoformat(),

    "fact_grain": "One row per taxi trip",

    "source_rows": len(source),
    "fact_rows": written_rows,
    "fact_columns": len(fact.columns),

    "valid_trip_count": valid_trip_count,
    "valid_revenue_count": valid_revenue_count,

    "partition_columns": partition_columns,

    "checks": checks,
    "validation_pass": all(checks.values()),
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


# ============================================================
# 13. Final summary
# ============================================================

print("\n========== FACT TABLE AUDIT ==========")

print("Source rows:", len(source))
print("Fact rows:", written_rows)
print("Fact columns:", len(fact.columns))

print("Valid trips:", valid_trip_count)
print("Valid revenue:", valid_revenue_count)

print("Partition columns:", partition_columns)

for name, passed in checks.items():

    print(
        f"{name}: "
        f"{'PASS' if passed else 'FAIL'}"
    )

print("Delta version:", fact_dt.version())
print("Audit report:", AUDIT_PATH)

print("\n========================================")
print("FACT TABLE CREATED SUCCESSFULLY")
print("========================================")
