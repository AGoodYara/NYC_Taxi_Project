
from pathlib import Path
import argparse
import json
import sys
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake

from dwd_schema import DWD_SCHEMA, validate_dwd_schema


# ============================================================
# 1. 路径与参数配置
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="NYC Yellow Taxi DWD Delta Lake v1 写入与验证"
)

parser.add_argument(
    "--year",
    type=int,
    default=2026,
    help="数据年份"
)

parser.add_argument(
    "--month",
    type=int,
    default=1,
    help="数据月份"
)

args = parser.parse_args()

year = args.year
month = args.month

if year < 2000 or not 1 <= month <= 12:
    parser.error("年份或月份无效")

ym = f"{year}-{month:02d}"

INPUT_FILE = (
    BASE_DIR
    / "data"
    / "validation"
    / ym
    / f"yellow_taxi_dwd_{ym}_sample.parquet"
)

DELTA_DIR = (
    BASE_DIR
    / "data"
    / "delta_test"
    / "dwd_v1"
    / "yellow_taxi_trips"
)

AUDIT_FILE = (
    BASE_DIR
    / "data"
    / "validation"
    / ym
    / f"delta_write_audit_v1_{ym}.json"
)

PARTITION_COLUMNS = ["year", "month"]

PARTITION_FILTERS = [
    ("year", "=", year),
    ("month", "=", month)
]

PARTITION_PREDICATE = (
    f"year = {year} AND month = {month}"
)


# ============================================================
# 2. Schema 比较与差异诊断
# ============================================================


def to_pyarrow_schema(schema):
    """
    将 arro3 Schema 转换为 PyArrow Schema。
    PyArrow Schema 则直接返回。
    """
    if isinstance(schema, pa.Schema):
        return schema

    # arro3 实现了 Arrow C Data Interface
    if hasattr(schema, "__arrow_c_schema__"):
        return pa.Schema._import_from_c_capsule(
            schema.__arrow_c_schema__()
        )

    raise TypeError(
        f"不支持的 Schema 类型：{type(schema)}"
    )


def same_schema(actual, expected):
    """
    严格比较字段名称、类型、顺序及可空性。
    忽略 Schema 元数据。
    """
    actual = to_pyarrow_schema(actual)
    expected = to_pyarrow_schema(expected)

    return actual.equals(
        expected,
        check_metadata=False
    )


def print_schema_difference(actual, expected):
    """
    打印真正的 Schema 差异。
    """
    actual = to_pyarrow_schema(actual)
    expected = to_pyarrow_schema(expected)

    print("\n========== Schema 差异诊断 ==========")

    actual_fields = {
        field.name: field
        for field in actual
    }

    expected_fields = {
        field.name: field
        for field in expected
    }

    differences = 0

    for name in sorted(
        set(actual_fields) | set(expected_fields)
    ):
        a = actual_fields.get(name)
        e = expected_fields.get(name)

        if a is None:
            differences += 1
            print(f"缺少字段：{name}")

        elif e is None:
            differences += 1
            print(f"多余字段：{name}")

        elif not a.equals(e, check_metadata=False):
            differences += 1
            print(f"\n字段：{name}")
            print(f"实际：{a}")
            print(f"预期：{e}")

    if actual.names != expected.names:
        differences += 1
        print("\n字段顺序不一致")
        print("实际：", actual.names)
        print("预期：", expected.names)

    print(f"\n差异数量：{differences}")

    """
    详细打印 Schema 差异，便于排查。
    """

    print("\n========== Schema 差异诊断 ==========")

    actual_fields = {
        field.name: field
        for field in actual
    }

    expected_fields = {
        field.name: field
        for field in expected
    }

    differences = 0

    for name in sorted(
        set(actual_fields) | set(expected_fields)
    ):

        actual_field = actual_fields.get(name)
        expected_field = expected_fields.get(name)

        if actual_field is None:
            differences += 1
            print(f"\n缺少字段：{name}")

        elif expected_field is None:
            differences += 1
            print(f"\n多余字段：{name}")

        elif (
            str(actual_field.type) != str(expected_field.type)
            or actual_field.nullable != expected_field.nullable
        ):
            differences += 1

            print(f"\n字段：{name}")
            print(f"实际：{actual_field}")
            print(f"预期：{expected_field}")

    actual_names = [
        field.name for field in actual
    ]

    expected_names = [
        field.name for field in expected
    ]

    if actual_names != expected_names:
        differences += 1

        print("\n字段顺序不一致")
        print("实际字段顺序：", actual_names)
        print("预期字段顺序：", expected_names)

    print(f"\n差异数量：{differences}")


def require_schema(actual, expected, stage):
    """
    Schema 不一致时停止写入。
    """

    if not same_schema(actual, expected):

        print(f"\n{stage}：FAIL")

        print_schema_difference(
            actual,
            expected
        )

        raise RuntimeError(
            f"{stage}：Schema 不一致"
        )

    print(f"{stage}：PASS")


# ============================================================
# 3. 读取 DWD Parquet 样本
# ============================================================

print("\n========== 读取 DWD 样本 ==========")

print(f"处理月份：{ym}")
print(f"输入文件：{INPUT_FILE}")

if not INPUT_FILE.is_file():
    raise FileNotFoundError(
        f"找不到输入文件：{INPUT_FILE}"
    )

table = pq.read_table(INPUT_FILE)

input_rows = table.num_rows

print(f"输入样本行数：{input_rows:,}")
print(f"输入字段数量：{len(table.schema)}")

# 正式 DWD Schema 检查
if not validate_dwd_schema(table):
    raise RuntimeError(
        "输入 DWD Schema 不符合正式规范"
    )


# ============================================================
# 4. 添加年月分区字段
# ============================================================

print("\n========== 构建分区字段 ==========")

table = table.append_column(
    "year",
    pa.array(
        [year] * input_rows,
        type=pa.int32()
    )
)

table = table.append_column(
    "month",
    pa.array(
        [month] * input_rows,
        type=pa.int32()
    )
)

EXPECTED_DELTA_SCHEMA = (
    DWD_SCHEMA
    .append(pa.field("year", pa.int32()))
    .append(pa.field("month", pa.int32()))
)

require_schema(
    table.schema,
    EXPECTED_DELTA_SCHEMA,
    "输入 Delta Schema 校验"
)

print(f"Delta 字段数量：{len(table.schema)}")
print(f"分区字段：{PARTITION_COLUMNS}")


# ============================================================
# 5. 检查已有 Delta 表
# ============================================================

print("\n========== 写入前检查 ==========")

delta_exists = (
    DELTA_DIR / "_delta_log"
).is_dir()

if DELTA_DIR.exists() and not delta_exists:
    raise RuntimeError(
        "目标目录已存在，但不是有效的 Delta 表目录"
    )

previous_version = None
previous_month_rows = 0

if delta_exists:

    print("检测到已有 Delta 表")

    dt = DeltaTable(str(DELTA_DIR))

    previous_version = dt.version()

    existing_partitions = (
        dt.metadata().partition_columns
    )

    if existing_partitions != PARTITION_COLUMNS:
        raise RuntimeError(
            "已有 Delta 表的分区定义不一致："
            f"{existing_partitions}"
        )

    existing_schema = dt.schema().to_arrow()

    # 严格比较已有 Delta 表 Schema
    require_schema(
        existing_schema,
        EXPECTED_DELTA_SCHEMA,
        "已有 Delta 表 Schema 校验"
    )

    previous_month_rows = (
        dt.to_pyarrow_table(
            filters=PARTITION_FILTERS
        ).num_rows
    )

else:
    print("Delta 表不存在，将创建新表")

print(f"Delta 表路径：{DELTA_DIR}")
print(f"Delta 表已存在：{delta_exists}")
print(f"目标月份原有行数：{previous_month_rows:,}")
print(f"分区条件：{PARTITION_PREDICATE}")
print(f"上一个 Delta 版本：{previous_version}")


# ============================================================
# 6. 写入 Delta Lake
# ============================================================

print("\n========== 开始写入 Delta Lake ==========")

if not delta_exists:

    write_deltalake(
        str(DELTA_DIR),
        table,
        mode="error",
        partition_by=PARTITION_COLUMNS
    )

    print("首次创建 Delta 表成功")

else:

    write_deltalake(
        str(DELTA_DIR),
        table,
        mode="overwrite",
        predicate=PARTITION_PREDICATE
    )

    print("目标月份分区覆盖成功")


# ============================================================
# 7. 写入后回读验证
# ============================================================

print("\n========== 写入后验证 ==========")

dt = DeltaTable(str(DELTA_DIR))

current_version = dt.version()

actual_partitions = (
    dt.metadata().partition_columns
)

partition_pass = (
    actual_partitions == PARTITION_COLUMNS
)

actual_schema = dt.schema().to_arrow()

schema_pass = same_schema(
    actual_schema,
    EXPECTED_DELTA_SCHEMA
)

if not schema_pass:
    print_schema_difference(
        actual_schema,
        EXPECTED_DELTA_SCHEMA
    )

written_table = dt.to_pyarrow_table(
    filters=PARTITION_FILTERS
)

written_rows = written_table.num_rows

row_count_pass = (
    written_rows == input_rows
)

delta_log_pass = (
    DELTA_DIR / "_delta_log"
).is_dir()

validation_pass = all([
    partition_pass,
    schema_pass,
    row_count_pass,
    delta_log_pass
])


# ============================================================
# 8. 保存审计报告
# ============================================================

audit = {
    "year_month": ym,
    "schema_version": "1.0",
    "execution_time_utc": (
        datetime.now(timezone.utc).isoformat()
    ),
    "input_file": str(INPUT_FILE),
    "delta_path": str(DELTA_DIR),
    "mode": "sample_test",
    "input_rows": input_rows,
    "previous_month_rows": previous_month_rows,
    "delta_month_rows": written_rows,
    "previous_delta_version": previous_version,
    "current_delta_version": current_version,
    "partition_columns": actual_partitions,
    "partition_pass": partition_pass,
    "schema_pass": schema_pass,
    "row_count_pass": row_count_pass,
    "delta_log_pass": delta_log_pass,
    "validation_pass": validation_pass
}

AUDIT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

with open(
    AUDIT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=2
    )


# ============================================================
# 9. 输出最终结果
# ============================================================

print("\n========== Delta Lake v1 审计 ==========")

print(f"处理月份：{ym}")
print(f"输入样本行数：{input_rows:,}")
print(f"Delta 月份行数：{written_rows:,}")

print(
    f"Schema："
    f"{'PASS' if schema_pass else 'FAIL'}"
)

print(
    f"分区："
    f"{'PASS' if partition_pass else 'FAIL'}"
)

print(
    f"行数："
    f"{'PASS' if row_count_pass else 'FAIL'}"
)

print(
    f"事务日志："
    f"{'PASS' if delta_log_pass else 'FAIL'}"
)

print(f"Delta 版本：{current_version}")
print(f"审计报告：{AUDIT_FILE}")

if not validation_pass:

    raise RuntimeError(
        "Delta Lake 写入后校验失败，"
        "请检查上面的 Schema 差异和审计报告"
    )

print("\nDelta Lake v1 写入验证成功！")
