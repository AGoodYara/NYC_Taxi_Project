
from pathlib import Path
import argparse
import json

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="NYC Taxi DWD Delta Lake 样本写入测试"
)
parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)
args = parser.parse_args()

if args.year < 2000 or not 1 <= args.month <= 12:
    parser.error("年份或月份无效")

ym = f"{args.year}-{args.month:02d}"

# 只使用验证样本，不读取正式 DWD
input_file = (
    BASE_DIR / "data" / "validation" / ym
    / f"yellow_taxi_dwd_{ym}_sample.parquet"
)

contract_file = (
    BASE_DIR / "schema_contracts"
    / f"dwd_yellow_taxi_{ym}_candidate.json"
)

# 测试 Delta 表与生产数据完全隔离
delta_dir = (
    BASE_DIR / "data" / "delta_test"
    / "dwd" / "yellow_taxi_trips"
)

if not input_file.is_file():
    raise FileNotFoundError(input_file)

if not contract_file.is_file():
    raise FileNotFoundError(contract_file)

# 防止覆盖以前的 Delta 测试结果
if delta_dir.exists():
    raise FileExistsError(
        f"Delta 测试目录已存在，停止写入：{delta_dir}"
    )

with open(contract_file, "r", encoding="utf-8") as f:
    contract = json.load(f)

table = pq.read_table(input_file)

def field_info(schema):
    return [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable
        }
        for field in schema
    ]

if field_info(table.schema) != contract["fields"]:
    raise ValueError("输入 DWD Schema 与候选契约不一致")

input_rows = table.num_rows

# 添加分区字段
year_array = pa.array(
    [args.year] * input_rows,
    type=pa.int32()
)

month_array = pa.array(
    [args.month] * input_rows,
    type=pa.int32()
)

table = table.append_column("year", year_array)
table = table.append_column("month", month_array)

print(f"输入样本行数：{input_rows}")
print(f"准备写入 Delta：{delta_dir}")

write_deltalake(
    str(delta_dir),
    table,
    mode="error",
    partition_by=["year", "month"],
)

# 使用 Delta API 读取，确认它是真正的 Delta 表
dt = DeltaTable(str(delta_dir))

if not (delta_dir / "_delta_log").is_dir():
    raise RuntimeError("未找到 Delta 事务日志")

# 读取指定年月分区
written = dt.to_pyarrow_table(
    partitions=[
        ("year", "=", str(args.year)),
        ("month", "=", str(args.month)),
    ]
)

written_rows = written.num_rows

# 分区字段不属于原始 DWD Schema
written_schema = written.schema
for name in ("year", "month"):
    index = written_schema.get_field_index(name)
    if index < 0:
        raise RuntimeError(f"Delta 缺少分区字段：{name}")
    written_schema = written_schema.remove(index)

schema_pass = (
    field_info(written_schema) == contract["fields"]
)
row_count_pass = (written_rows == input_rows)

audit = {
    "year_month": ym,
    "input_rows": input_rows,
    "delta_written_rows": written_rows,
    "schema_pass": schema_pass,
    "row_count_pass": row_count_pass,
    "delta_version": dt.version(),
    "partition_columns": dt.metadata().partition_columns,
}

audit_file = (
    BASE_DIR / "data" / "validation" / ym
    / f"delta_write_audit_{ym}.json"
)

with open(audit_file, "w", encoding="utf-8") as f:
    json.dump(audit, f, indent=2, ensure_ascii=False)

print("\n========== Delta Lake 审计 ==========")
print(f"输入行数：{input_rows}")
print(f"Delta 行数：{written_rows}")
print(f"Schema 校验：{'PASS' if schema_pass else 'FAIL'}")
print(f"行数校验：{'PASS' if row_count_pass else 'FAIL'}")
print(f"Delta 版本：{dt.version()}")

if not schema_pass or not row_count_pass:
    raise RuntimeError("Delta Lake 写入校验失败")

print("\nDelta Lake 样本写入成功！")
