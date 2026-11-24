from pathlib import Path

import pandas as pd
from deltalake import DeltaTable, write_deltalake


# ============================================================
# 1. Project configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

SOURCE_DELTA = (
    BASE_DIR / "data" / "delta_test"
    / "dwd_v1" / "yellow_taxi_trips"
)

ZONE_FILE = (
    BASE_DIR / "data" / "reference"
    / "taxi_zone_lookup.csv"
)

OUTPUT_DIR = BASE_DIR / "data" / "warehouse" / "dimensions"

TABLES = {
    "dim_date": OUTPUT_DIR / "dim_date",
    "dim_location": OUTPUT_DIR / "dim_location",
    "dim_payment": OUTPUT_DIR / "dim_payment",
}


# ============================================================
# 2. Read source data
# ============================================================

print("\n========== LOAD DWD SOURCE ==========")

if not SOURCE_DELTA.exists():
    raise FileNotFoundError(SOURCE_DELTA)

if not ZONE_FILE.is_file():
    raise FileNotFoundError(ZONE_FILE)

dt = DeltaTable(str(SOURCE_DELTA))

source = dt.to_pandas(
    columns=[
        "tpep_pickup_datetime",
        "tpep_dropoff_datetime",
        "payment_type",
    ]
)

print("DWD rows:", len(source))
print("DWD version:", dt.version())


# ============================================================
# 3. Build dim_date
# ============================================================

print("\n========== BUILD DIM_DATE ==========")

date_values = pd.concat(
    [
        pd.to_datetime(source["tpep_pickup_datetime"]),
        pd.to_datetime(source["tpep_dropoff_datetime"]),
    ],
    ignore_index=True
).dropna()

min_date = date_values.min().normalize()
max_date = date_values.max().normalize()

dates = pd.date_range(
    start=min_date,
    end=max_date,
    freq="D"
)

dim_date = pd.DataFrame({
    "full_date": dates
})

dim_date["date_key"] = (
    dim_date["full_date"].dt.strftime("%Y%m%d").astype("int32")
)

dim_date["year"] = dim_date["full_date"].dt.year.astype("int16")
dim_date["quarter"] = dim_date["full_date"].dt.quarter.astype("int8")
dim_date["month"] = dim_date["full_date"].dt.month.astype("int8")
dim_date["day"] = dim_date["full_date"].dt.day.astype("int8")

dim_date["day_of_week"] = (
    dim_date["full_date"].dt.isocalendar().day.astype("int8")
)

dim_date["day_name"] = (
    dim_date["full_date"].dt.day_name()
)

dim_date["is_weekend"] = (
    dim_date["day_of_week"] >= 6
)

dim_date["full_date"] = pd.to_datetime(
    dim_date["full_date"]
)

# Reorder columns
dim_date = dim_date[
    [
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
]

print("Date range:", min_date, "to", max_date)
print("dim_date rows:", len(dim_date))


# ============================================================
# 4. Build dim_location
# ============================================================

print("\n========== BUILD DIM_LOCATION ==========")

zones = pd.read_csv(ZONE_FILE)

if zones["LocationID"].isna().any():
    raise ValueError("LocationID contains missing values")

if zones["LocationID"].duplicated().any():
    raise ValueError("Duplicate LocationID found")

zones["LocationID"] = zones["LocationID"].astype("int32")

for col in ["Borough", "Zone", "service_zone"]:
    zones[col] = (
        zones[col]
        .fillna("Unknown")
        .astype("string")
    )

zones = zones.sort_values("LocationID").reset_index(drop=True)

dim_location = pd.DataFrame({
    "location_key": range(1, len(zones) + 1),
    "location_id": zones["LocationID"],
    "borough": zones["Borough"],
    "zone": zones["Zone"],
    "service_zone": zones["service_zone"],
})

dim_location["location_key"] = (
    dim_location["location_key"].astype("int32")
)

print("dim_location rows:", len(dim_location))


# ============================================================
# 5. Build dim_payment
# ============================================================

print("\n========== BUILD DIM_PAYMENT ==========")

if source["payment_type"].isna().any():
    raise ValueError("payment_type contains missing values")

payment_codes = sorted(
    source["payment_type"].unique()
)

# Code 0 is retained separately.
# Its business meaning should be confirmed against
# the applicable source data dictionary.

payment_names = {
    0: "Code 0 - Verify",
    1: "Credit card",
    2: "Cash",
    3: "No charge",
    4: "Dispute",
    5: "Unknown",
    6: "Voided trip",
}

dim_payment = pd.DataFrame({
    "payment_key": range(1, len(payment_codes) + 1),
    "payment_type": payment_codes,
})

dim_payment["payment_key"] = (
    dim_payment["payment_key"].astype("int32")
)

dim_payment["payment_name"] = (
    dim_payment["payment_type"]
    .map(payment_names)
    .fillna(
        dim_payment["payment_type"].map(
            lambda x: f"Unmapped code {x}"
        )
    )
)

print(dim_payment.to_string(index=False))


# ============================================================
# 6. Validate dimensions
# ============================================================

print("\n========== DIMENSION VALIDATION ==========")

dimensions = {
    "dim_date": (dim_date, "date_key"),
    "dim_location": (dim_location, "location_key"),
    "dim_payment": (dim_payment, "payment_key"),
}

for name, (df, pk) in dimensions.items():

    if df[pk].isna().any():
        raise ValueError(f"{name}: NULL primary key")

    if df[pk].duplicated().any():
        raise ValueError(f"{name}: Duplicate primary key")

    print(
        f"{name}: PASS | "
        f"Rows={len(df):,} | "
        f"Unique PK={df[pk].nunique():,}"
    )


# ============================================================
# 7. Write Delta dimension tables
# ============================================================

print("\n========== WRITE DELTA DIMENSIONS ==========")

for name, (df, pk) in dimensions.items():

    output_path = TABLES[name]

    write_deltalake(
        str(output_path),
        df,
        mode="overwrite",
    )

    saved = DeltaTable(str(output_path))

    saved_rows = saved.to_pyarrow_table().num_rows

    if saved_rows != len(df):
        raise RuntimeError(
            f"{name}: Row count mismatch "
            f"{saved_rows} != {len(df)}"
        )

    print(
        f"{name}: WRITE PASS | "
        f"Rows={saved_rows:,} | "
        f"Version={saved.version()}"
    )


print("\n========================================")
print("ALL DIMENSION TABLES CREATED SUCCESSFULLY")
print("========================================")
