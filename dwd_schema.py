
import pyarrow as pa

# 正式 DWD Schema v1.0
DWD_SCHEMA_VERSION = "1.0"

DWD_SCHEMA = pa.schema([
    pa.field("VendorID", pa.int32()),
    pa.field("tpep_pickup_datetime", pa.timestamp("us")),
    pa.field("tpep_dropoff_datetime", pa.timestamp("us")),
    pa.field("passenger_count", pa.int64()),
    pa.field("trip_distance", pa.float64()),
    pa.field("RatecodeID", pa.int64()),
    pa.field("store_and_fwd_flag", pa.string()),
    pa.field("PULocationID", pa.int32()),
    pa.field("DOLocationID", pa.int32()),
    pa.field("payment_type", pa.int64()),
    pa.field("fare_amount", pa.float64()),
    pa.field("extra", pa.float64()),
    pa.field("mta_tax", pa.float64()),
    pa.field("tip_amount", pa.float64()),
    pa.field("tolls_amount", pa.float64()),
    pa.field("improvement_surcharge", pa.float64()),
    pa.field("total_amount", pa.float64()),
    pa.field("congestion_surcharge", pa.float64()),
    pa.field("Airport_fee", pa.float64()),
    pa.field("cbd_congestion_fee", pa.float64()),
    pa.field("trip_duration_minutes", pa.float64()),
    pa.field("avg_speed_mph", pa.float64()),
    pa.field("missing_passenger_count", pa.bool_()),
    pa.field("missing_ratecode", pa.bool_()),
    pa.field("invalid_duration", pa.bool_()),
    pa.field("invalid_distance", pa.bool_()),
    pa.field("invalid_speed", pa.bool_()),
    pa.field("is_negative_amount", pa.bool_()),
    pa.field("is_zero_amount", pa.bool_()),
    pa.field("is_high_amount", pa.bool_()),
    pa.field("is_valid_trip", pa.bool_()),
    pa.field("is_valid_revenue", pa.bool_()),
    pa.field("quality_rule_version", pa.string()),
])


def validate_dwd_schema(table):
    actual = table.schema.remove_metadata()
    expected = DWD_SCHEMA.remove_metadata()

    if actual.equals(expected, check_metadata=False):
        print("DWD Schema Validation: PASS")
        return True

    print("DWD Schema Validation: FAIL")

    expected_fields = {
        field.name: field for field in expected
    }

    actual_fields = {
        field.name: field for field in actual
    }

    for name in expected_fields:
        if name not in actual_fields:
            print(f"缺失字段：{name}")
        elif expected_fields[name] != actual_fields[name]:
            print(
                f"类型或可空性不一致：{name}\n"
                f"  预期：{expected_fields[name]}\n"
                f"  实际：{actual_fields[name]}"
            )

    for name in actual_fields:
        if name not in expected_fields:
            print(f"额外字段：{name}")

    if list(actual_fields) != list(expected_fields):
        print("字段顺序不一致")

    return False
