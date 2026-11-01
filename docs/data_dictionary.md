# NYC Yellow Taxi — DWD Data Dictionary

**Schema Version:** 1.0  
**Quality Rule Version:** v1.0-candidate  
**Data Layer:** DWD (Data Warehouse Detail)  
**Source:** NYC TLC Yellow Taxi Trip Records  
**Storage Format:** Apache Parquet / Delta Lake

## 1. Overview

The DWD layer contains cleaned and standardized NYC Yellow Taxi trip records.

The dataset preserves source records while adding derived metrics and quality flags. Invalid records are marked rather than automatically removed, supporting data traceability and downstream analytical filtering.

The DWD schema contains 33 fields.

## 2. Trip Information

| Field | Data Type | Description |
|---|---|---|
| `VendorID` | int32 | Identifier of the taxi technology provider |
| `tpep_pickup_datetime` | timestamp(us) | Trip pickup date and time |
| `tpep_dropoff_datetime` | timestamp(us) | Trip drop-off date and time |
| `passenger_count` | int64 | Number of passengers |
| `trip_distance` | float64 | Trip distance in miles |
| `RatecodeID` | int64 | Applied rate code |
| `store_and_fwd_flag` | string | Indicates whether the trip record was stored before forwarding |
| `PULocationID` | int32 | Pickup taxi zone identifier |
| `DOLocationID` | int32 | Drop-off taxi zone identifier |
| `payment_type` | int64 | Payment method code |

## 3. Fare and Revenue Information

| Field | Data Type | Description |
|---|---|---|
| `fare_amount` | float64 | Metered trip fare |
| `extra` | float64 | Additional charges |
| `mta_tax` | float64 | MTA tax |
| `tip_amount` | float64 | Recorded tip amount |
| `tolls_amount` | float64 | Toll charges |
| `improvement_surcharge` | float64 | Improvement surcharge |
| `total_amount` | float64 | Recorded total trip amount |
| `congestion_surcharge` | float64 | Congestion surcharge |
| `Airport_fee` | float64 | Airport-related fee |
| `cbd_congestion_fee` | float64 | Central Business District congestion fee |

## 4. Derived Metrics

| Field | Data Type | Description |
|---|---|---|
| `trip_duration_minutes` | float64 | Trip duration calculated from drop-off and pickup timestamps, in minutes |
| `avg_speed_mph` | float64 | Average trip speed calculated from distance and duration, in miles per hour |

### Calculation Logic

**Trip duration**

`trip_duration_minutes = (dropoff_datetime - pickup_datetime) / 60 seconds`

**Average speed**

`avg_speed_mph = trip_distance / (trip_duration_minutes / 60)`

Average speed is calculated only when the trip duration is greater than zero. Otherwise, the calculated speed is missing and the trip is flagged as invalid.

## 5. Data Quality Flags

| Field | Data Type | Description |
|---|---|---|
| `missing_passenger_count` | bool | Passenger count is missing |
| `missing_ratecode` | bool | Rate code is missing |
| `invalid_duration` | bool | Duration is missing, non-positive, or exceeds 180 minutes |
| `invalid_distance` | bool | Distance is missing, non-positive, or exceeds 100 miles |
| `invalid_speed` | bool | Average speed is missing, non-positive, or exceeds 100 mph |
| `is_negative_amount` | bool | Total amount is negative |
| `is_zero_amount` | bool | Total amount equals zero |
| `is_high_amount` | bool | Total amount exceeds $500 |
| `is_valid_trip` | bool | Trip passes duration, distance and speed validation |
| `is_valid_revenue` | bool | Trip is valid and total amount is greater than zero and at most $500 |

### Valid Trip Definition

A trip is considered valid when:

- `invalid_duration = False`
- `invalid_distance = False`
- `invalid_speed = False`

Missing passenger counts and missing rate codes do not automatically invalidate a trip.

### Valid Revenue Definition

A record is eligible for the current positive-revenue analysis when:

- `is_valid_trip = True`
- `total_amount > 0`
- `total_amount <= 500`

Negative amounts may represent legitimate adjustments or refunds and should not automatically be interpreted as erroneous transactions.

## 6. Data Lineage and Rule Versioning

| Field | Data Type | Description |
|---|---|---|
| `quality_rule_version` | string | Version identifier of the cleaning and validation rules |

Current rule version: `v1.0-candidate`.

The candidate status indicates that the thresholds have been evaluated on sample data but have not yet received final business approval.

## 7. Nullability and Data Types

The schema is defined using PyArrow.

All 33 fields are nullable at the schema level because `nullable=False` has not been explicitly specified.

The following distinctions apply:

- **Schema nullability:** A field can contain null values without violating the declared Arrow schema.
- **Business validity:** A record may be marked invalid according to the quality rules even if its schema is valid.
- **Missing-value flags:** The pipeline explicitly tracks missing passenger counts and rate codes.

Schema validation checks field names, data types, nullability and field ordering against the expected DWD schema.

## 8. Delta Lake Partitioning

The local Delta Lake writer uses:

- `year`
- `month`

These two partition columns are added during Delta writing and are not part of the 33-field DWD schema.

The resulting Delta table therefore contains 35 fields when both partition columns are included.

Partition-based overwrites support reprocessing an individual month without intentionally replacing other monthly partitions.

## 9. Downstream Analytical Usage

The DWD dataset supports:

- Trip volume and demand analysis
- Trip duration and distance analysis
- Revenue and fare analysis
- Pickup and drop-off zone analysis
- Peak-hour and temporal demand analysis
- Data quality monitoring

Downstream analytical queries should apply `is_valid_trip` or `is_valid_revenue` according to the metric being calculated, rather than indiscriminately excluding all flagged records.

## 10. Known Limitations

1. Data quality thresholds remain provisional.
2. Sample-level validation does not establish full-volume production acceptance.
3. Arrow schema nullability does not guarantee business-level completeness.
4. Payment and rate-code values require source codebook mappings for readable business labels.
5. Derived average speed is an analytical estimate, not a measured instantaneous vehicle speed.

**Document Status:** DWD Schema v1.0 documented; business-rule approval and production acceptance pending.