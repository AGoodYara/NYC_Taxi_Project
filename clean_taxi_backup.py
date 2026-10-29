
from pathlib import Path
import argparse
import pandas as pd
import numpy as np

# ============================
# 1. 接收年月参数
# ============================

parser = argparse.ArgumentParser(
    description="NYC Yellow Taxi 数据清洗"
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

YEAR = args.year
MONTH = args.month

if YEAR < 2000 or not 1 <= MONTH <= 12:
    parser.error("请输入有效的年份和月份")

YEAR_MONTH = f"{YEAR}-{MONTH:02d}"

print(f"正在处理数据月份：{YEAR_MONTH}")

# ============================
# 2. 设置文件路径
# ============================

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = (
    BASE_DIR / "data" / "raw" /
    f"yellow_tripdata_{YEAR_MONTH}.parquet"
)

OUTPUT_DIR = BASE_DIR / "data" / "processed" / "dwd"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not INPUT_FILE.is_file():
    raise FileNotFoundError(
        f"找不到原始数据文件：{INPUT_FILE}"
    )

# ============================
# 3. 读取原始数据
# ============================

df = pd.read_parquet(INPUT_FILE)

print(f"原始记录数：{len(df)}")

# ============================
# 4. 计算行程时长与速度
# ============================

df["trip_duration_minutes"] = (
    df["tpep_dropoff_datetime"] -
    df["tpep_pickup_datetime"]
).dt.total_seconds() / 60

df["avg_speed_mph"] = np.where(
    df["trip_duration_minutes"] > 0,
    df["trip_distance"] /
    (df["trip_duration_minutes"] / 60),
    np.nan
)

# ============================
# 5. 数据质量标记
# ============================

df["is_valid_trip"] = (
    df["trip_duration_minutes"].between(
        0, 180, inclusive="right"
    )
    & df["trip_distance"].between(
        0, 100, inclusive="right"
    )
    & df["avg_speed_mph"].between(
        0, 100, inclusive="right"
    )
)

df["is_negative_amount"] = df["total_amount"] < 0
df["is_zero_amount"] = df["total_amount"] == 0
df["is_high_amount"] = df["total_amount"] > 500

df["is_valid_revenue"] = (
    df["is_valid_trip"]
    & (df["total_amount"] > 0)
    & (df["total_amount"] <= 500)
)

# ============================
# 6. 保存 DWD Parquet
# ============================

output_file = (
    OUTPUT_DIR /
    f"yellow_taxi_dwd_{YEAR_MONTH}.parquet"
)

df.to_parquet(output_file, index=False)

print(f"DWD 文件保存成功：{output_file}")
print(f"有效行程数：{df['is_valid_trip'].sum()}")
print(f"有效收入记录：{df['is_valid_revenue'].sum()}")

# ============================
# 7. 自动生成数据质量报告
# ============================

quality_metrics = {
    "total_records": len(df),
    "valid_trip_records": int(df["is_valid_trip"].sum()),
    "invalid_trip_records": int((~df["is_valid_trip"]).sum()),
    "valid_revenue_records": int(df["is_valid_revenue"].sum()),
    "negative_duration": int(
        (df["trip_duration_minutes"] < 0).sum()
    ),
    "zero_duration": int(
        (df["trip_duration_minutes"] == 0).sum()
    ),
    "zero_distance": int(
        (df["trip_distance"] == 0).sum()
    ),
    "high_speed": int(
        (df["avg_speed_mph"] > 100).sum()
    ),
    "negative_amount": int(
        df["is_negative_amount"].sum()
    ),
    "zero_amount": int(
        df["is_zero_amount"].sum()
    ),
    "high_amount": int(
        df["is_high_amount"].sum()
    )
}

quality_report = pd.DataFrame(
    [
        {"metric": key, "value": value}
        for key, value in quality_metrics.items()
    ]
)

report_file = (
    OUTPUT_DIR /
    f"taxi_data_quality_report_{YEAR_MONTH}.csv"
)

quality_report.to_csv(
    report_file,
    index=False,
    encoding="utf-8-sig"
)

print(f"数据质量报告保存成功：{report_file}")
print(f"月份 {YEAR_MONTH} 清洗完成！")
