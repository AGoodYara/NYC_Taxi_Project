
import numpy as np
import pandas as pd

# 候选业务阈值
# 来源：原有清洗脚本
# 状态：已进行样本敏感性分析，仍待业务确认
MAX_DURATION_MIN = 180
MAX_DISTANCE_MILES = 100
MAX_SPEED_MPH = 100
MAX_TOTAL_AMOUNT = 500

RULE_VERSION = "v1.0-candidate"


def apply_cleaning_rules(df):
    """
    对出租车数据增加质量标记。

    不删除原始记录。
    不修改 ODS。
    返回带有质量标记的 DataFrame。
    """
    df = df.copy()
        # 保留整数语义，同时允许缺失值
    df["passenger_count"] = pd.to_numeric(
        df["passenger_count"], errors="raise"
    ).astype("Int64")

    df["RatecodeID"] = pd.to_numeric(
        df["RatecodeID"], errors="raise"
    ).astype("Int64")

    # 统一字符串字段
    df["store_and_fwd_flag"] = df[
        "store_and_fwd_flag"
    ].astype("string")

    pickup = pd.to_datetime(
        df["tpep_pickup_datetime"],
        errors="coerce"
    )

    dropoff = pd.to_datetime(
        df["tpep_dropoff_datetime"],
        errors="coerce"
    )

    duration = (
        dropoff - pickup
    ).dt.total_seconds() / 60

    distance = pd.to_numeric(
        df["trip_distance"],
        errors="coerce"
    )

    amount = pd.to_numeric(
        df["total_amount"],
        errors="coerce"
    )

    speed = (
        distance / (duration / 60)
    ).where(duration > 0)

    df["trip_duration_minutes"] = duration
    df["avg_speed_mph"] = speed

    # 结构化缺失
    df["missing_passenger_count"] = (
        df["passenger_count"].isna()
    )

    df["missing_ratecode"] = (
        df["RatecodeID"].isna()
    )

    # 行程时长
    df["invalid_duration"] = (
        duration.isna()
        | duration.le(0)
        | duration.gt(MAX_DURATION_MIN)
    )

    # 行程距离
    df["invalid_distance"] = (
        distance.isna()
        | distance.le(0)
        | distance.gt(MAX_DISTANCE_MILES)
    )

    # 行驶速度
    df["invalid_speed"] = (
        speed.isna()
        | speed.le(0)
        | speed.gt(MAX_SPEED_MPH)
    )

    # 金额质量
    df["is_negative_amount"] = amount.lt(0)
    df["is_zero_amount"] = amount.eq(0)
    df["is_high_amount"] = amount.gt(
        MAX_TOTAL_AMOUNT
    )

    df["is_valid_trip"] = ~(
        df["invalid_duration"]
        | df["invalid_distance"]
        | df["invalid_speed"]
    )

    df["is_valid_revenue"] = (
        df["is_valid_trip"]
        & amount.gt(0)
        & amount.le(MAX_TOTAL_AMOUNT)
    )

    # 记录规则版本，支持后续追溯
    df["quality_rule_version"] = RULE_VERSION

    return df
