
from pathlib import Path
import argparse
import json
import pyarrow.parquet as pq

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)
args = parser.parse_args()

if args.year < 2000 or not 1 <= args.month <= 12:
    parser.error("年份或月份无效")

ym = f"{args.year}-{args.month:02d}"

ods_file = (
    BASE_DIR / "data" / "raw"
    / f"yellow_tripdata_{ym}.parquet"
)

dwd_file = (
    BASE_DIR / "data" / "validation" / ym
    / f"yellow_taxi_dwd_{ym}_sample.parquet"
)

output_dir = BASE_DIR / "schema_contracts"
output_dir.mkdir(parents=True, exist_ok=True)


def inspect_schema(path):
    if not path.is_file():
        raise FileNotFoundError(f"找不到数据文件：{path}")

    parquet = pq.ParquetFile(path)

    return {
        "source_file": path.name,
        "row_count": parquet.metadata.num_rows,
        "fields": [
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable
            }
            for field in parquet.schema_arrow
        ]
    }


for layer, path in [
    ("ods", ods_file),
    ("dwd", dwd_file)
]:
    print(f"\n========== {layer.upper()} Schema ==========")

    result = inspect_schema(path)

    for field in result["fields"]:
        print(f"{field['name']:<32} {field['type']}")

    output_file = (
        output_dir
        / f"{layer}_yellow_taxi_{ym}_candidate.json"
    )

    if output_file.exists():
        raise FileExistsError(
            f"候选 Schema 已存在，请先检查：{output_file}"
        )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(f"\n已生成：{output_file}")

print("\nSchema 提取完成！")
