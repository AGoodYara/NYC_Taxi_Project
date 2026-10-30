
from pathlib import Path
import argparse
import json
import pandas as pd
import pyarrow as pa
from dwd_schema import DWD_SCHEMA, validate_dwd_schema

from cleaning_rules import (
    apply_cleaning_rules,
    RULE_VERSION,
    MAX_DURATION_MIN,
    MAX_DISTANCE_MILES,
    MAX_SPEED_MPH,
    MAX_TOTAL_AMOUNT,
)

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="NYC Yellow Taxi DWD 清洗与质量审计"
)

parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)
parser.add_argument(
    "--sample-rate",
    type=float,
    default=1.0,
    help="抽样比例，默认 1.0 表示全量"
)
parser.add_argument(
    "--seed",
    type=int,
    default=42,
    help="随机抽样种子"
)

args = parser.parse_args()

if args.year < 2000 or not 1 <= args.month <= 12:
    parser.error("请输入有效的年份和月份")

if not 0 < args.sample_rate <= 1:
    parser.error("--sample-rate 必须大于 0 且不超过 1")

ym = f"{args.year}-{args.month:02d}"
is_sample = args.sample_rate < 1

input_file = (
    BASE_DIR / "data" / "raw"
    / f"yellow_tripdata_{ym}.parquet"
)

if not input_file.is_file():
    raise FileNotFoundError(
        f"找不到原始数据：{input_file}"
    )

# 样本结果与正式 DWD 分开保存
if is_sample:
    output_dir = (
        BASE_DIR / "data" / "validation" / ym
    )
    suffix = "_sample"
else:
    output_dir = (
        BASE_DIR / "data" / "processed" / "dwd"
    )
    suffix = ""

output_dir.mkdir(parents=True, exist_ok=True)

print(f"\n开始处理：{ym}")
print(f"规则版本：{RULE_VERSION}")
print(f"样本模式：{is_sample}")

# ====================================
# 1. 读取 ODS 原始文件
# ====================================

raw = pd.read_parquet(input_file)
ods_rows = len(raw)

print(f"ODS 原始行数：{ods_rows:,}")

# ====================================
# 2. 抽样
# ====================================

if is_sample:
    source = raw.sample(
        frac=args.sample_rate,
        random_state=args.seed
    ).copy()
else:
    source = raw.copy()

sample_rows = len(source)

print(f"本次处理行数：{sample_rows:,}")

# ====================================
# 3. 去重审计
# ====================================

duplicate_mask = source.duplicated(
    keep="first"
)

duplicate_rows = int(duplicate_mask.sum())

# 当前阶段只统计重复，不实际删除
# 避免在没有唯一行程 ID 的情况下误删
deduplicated = source.copy()

deduplicated_rows = len(deduplicated)

# ====================================
# 4. 应用统一清洗规则
# ====================================

df = apply_cleaning_rules(deduplicated)
# 将 pandas 数据转换为 Arrow 表
# 按正式 DWD Schema 构建 Arrow 表
# safe=True：禁止不安全的数据类型转换
arrow_table = pa.Table.from_pandas(
    df,
    schema=DWD_SCHEMA,
    preserve_index=False,
    safe=True
)

# 严格检查最终 Schema
if not validate_dwd_schema(arrow_table):
    raise RuntimeError(
        "DWD Schema 不符合正式规范，停止写入"
    )

# 严格检查 DWD Schema
if not validate_dwd_schema(arrow_table):
    raise RuntimeError(
        "DWD Schema 不符合正式规范，停止写入"
    )

# ====================================
# 5. 生成异常原因统计
# ====================================

rule_columns = [
    "missing_passenger_count",
    "missing_ratecode",
    "invalid_duration",
    "invalid_distance",
    "invalid_speed",
    "is_negative_amount",
    "is_zero_amount",
    "is_high_amount",
]

rule_report = pd.DataFrame([
    {
        "rule": rule,
        "matched_rows": int(df[rule].sum()),
        "matched_pct": round(
            df[rule].mean() * 100, 4
        )
    }
    for rule in rule_columns
])

# 只计算行程无效规则之间的重叠
trip_rule_columns = [
    "invalid_duration",
    "invalid_distance",
    "invalid_speed",
]

rule_count = df[trip_rule_columns].sum(axis=1)

overlap_report = pd.DataFrame([
    {
        "matched_rule_count": count,
        "rows": int((rule_count == count).sum())
    }
    for count in range(4)
])

# ====================================
# 6. 行数一致性审计
# ====================================

dwd_rows = len(df)

valid_trip_rows = int(
    df["is_valid_trip"].sum()
)

invalid_trip_rows = int(
    (~df["is_valid_trip"]).sum()
)

valid_revenue_rows = int(
    df["is_valid_revenue"].sum()
)

# 目前只标记，不执行实际去重和过滤
removed_duplicate_rows = 0
filtered_rows = 0

row_count_pass = (
    sample_rows
    - removed_duplicate_rows
    - filtered_rows
    == dwd_rows
)

if not row_count_pass:
    raise RuntimeError(
        "行数一致性校验失败，停止写入"
    )

audit = {
    "year_month": ym,
    "rule_version": RULE_VERSION,
    "sample_rate": args.sample_rate,
    "ods_original_rows": ods_rows,
    "processing_input_rows": sample_rows,
    "duplicate_candidates": duplicate_rows,
    "duplicates_removed": removed_duplicate_rows,
    "rows_after_deduplication": deduplicated_rows,
    "rows_filtered": filtered_rows,
    "dwd_expected_rows": dwd_rows,
    "valid_trip_rows": valid_trip_rows,
    "invalid_trip_rows": invalid_trip_rows,
    "valid_revenue_rows": valid_revenue_rows,
    "row_count_pass": row_count_pass,
    "thresholds": {
        "max_duration_minutes": MAX_DURATION_MIN,
        "max_distance_miles": MAX_DISTANCE_MILES,
        "max_speed_mph": MAX_SPEED_MPH,
        "max_total_amount": MAX_TOTAL_AMOUNT
    }
}

# ====================================
# 7. 写入 DWD
# ====================================

output_file = (
    output_dir
    / f"yellow_taxi_dwd_{ym}{suffix}.parquet"
)

import pyarrow.parquet as pq

pq.write_table(arrow_table, output_file)

# 写入后再次检查实际行数
written_rows = len(
    pd.read_parquet(output_file)
)

if written_rows != dwd_rows:
    raise RuntimeError(
        f"DWD 写入校验失败："
        f"预期 {dwd_rows}，实际 {written_rows}"
    )

audit["dwd_actual_written_rows"] = written_rows
audit["write_validation_pass"] = True

# ====================================
# 8. 输出质量报告
# ====================================

rule_report.to_csv(
    output_dir / f"quality_rules_{ym}{suffix}.csv",
    index=False,
    encoding="utf-8-sig"
)

overlap_report.to_csv(
    output_dir / f"quality_overlap_{ym}{suffix}.csv",
    index=False,
    encoding="utf-8-sig"
)

audit_file = (
    output_dir / f"quality_audit_{ym}{suffix}.json"
)

with open(audit_file, "w", encoding="utf-8") as f:
    json.dump(
        audit,
        f,
        ensure_ascii=False,
        indent=2
    )

# 兼容现有上传脚本需要的质量报告文件
if not is_sample:
    quality_metrics = {
        "total_records": dwd_rows,
        "valid_trip_records": valid_trip_rows,
        "invalid_trip_records": invalid_trip_rows,
        "valid_revenue_records": valid_revenue_rows,
        "duplicate_candidates": duplicate_rows,
        "duplicates_removed": removed_duplicate_rows,
        "rows_filtered": filtered_rows,
        "row_count_pass": row_count_pass,
        "write_validation_pass": True
    }

    quality_report = pd.DataFrame([
        {"metric": k, "value": v}
        for k, v in quality_metrics.items()
    ])

    quality_report.to_csv(
        output_dir
        / f"taxi_data_quality_report_{ym}.csv",
        index=False,
        encoding="utf-8-sig"
    )

print("\n========== 清洗结果 ==========")
print(f"ODS 原始行数：{ods_rows:,}")
print(f"本次处理行数：{sample_rows:,}")
print(f"重复候选记录：{duplicate_rows:,}")
print(f"实际删除重复：{removed_duplicate_rows:,}")
print(f"实际过滤记录：{filtered_rows:,}")
print(f"DWD 写入行数：{written_rows:,}")
print(f"有效行程数：{valid_trip_rows:,}")
print(f"无效行程数：{invalid_trip_rows:,}")
print(f"有效收入记录：{valid_revenue_rows:,}")
print(f"写入校验：PASS")
print(f"\n结果目录：{output_dir}")
