
from pathlib import Path
import argparse
import json
import pyarrow.parquet as pq

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)
args = parser.parse_args()

ym = f"{args.year}-{args.month:02d}"


def validate_schema(data_path, contract_path):
    if not data_path.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_path}")

    if not contract_path.is_file():
        raise FileNotFoundError(f"Schema 契约不存在：{contract_path}")

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    actual_schema = pq.ParquetFile(data_path).schema_arrow

    actual_fields = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable
        }
        for field in actual_schema
    ]

    expected_fields = contract["fields"]

    print(f"\n检查文件：{data_path.name}")

    if actual_fields == expected_fields:
        print("Schema Validation: PASS")
        print(f"字段数量：{len(actual_fields)}")
        return True

    print("Schema Validation: FAIL")

    expected = {field["name"]: field for field in expected_fields}
    actual = {field["name"]: field for field in actual_fields}

    for name in expected.keys() - actual.keys():
        print(f"缺失字段：{name}")

    for name in actual.keys() - expected.keys():
        print(f"额外字段：{name}")

    for name in expected.keys() & actual.keys():
        if expected[name] != actual[name]:
            print(
                f"字段不匹配：{name}\n"
                f"  预期：{expected[name]}\n"
                f"  实际：{actual[name]}"
            )

    if list(expected) != list(actual):
        print("字段顺序不一致")

    return False


ods_file = (
    BASE_DIR / "data" / "raw"
    / f"yellow_tripdata_{ym}.parquet"
)

dwd_file = (
    BASE_DIR / "data" / "validation" / ym
    / f"yellow_taxi_dwd_{ym}_sample.parquet"
)

contract_dir = BASE_DIR / "schema_contracts"

ods_pass = validate_schema(
    ods_file,
    contract_dir / f"ods_yellow_taxi_{ym}_candidate.json"
)

dwd_pass = validate_schema(
    dwd_file,
    contract_dir / f"dwd_yellow_taxi_{ym}_candidate.json"
)

if not (ods_pass and dwd_pass):
    raise SystemExit("Schema 校验失败，停止后续处理")

print("\nODS 和 DWD Schema 校验全部通过！")
