
from pathlib import Path
import argparse
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent

# 当前脚本的阈值，仅用于审计，不代表已经验证合理
MAX_DURATION_MIN = 180
MAX_DISTANCE_MILES = 100
MAX_SPEED_MPH = 100
MAX_TOTAL_AMOUNT = 500

SAMPLE_RATE = 0.10
RANDOM_SEED = 42


def count_true(condition):
    return int(condition.fillna(False).sum())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=1)
    args = parser.parse_args()

    if args.year < 2000 or not 1 <= args.month <= 12:
        parser.error("请输入有效的年份和月份")

    ym = f"{args.year}-{args.month:02d}"

    input_file = (
        BASE_DIR / "data" / "raw"
        / f"yellow_tripdata_{ym}.parquet"
    )

    output_dir = BASE_DIR / "data" / "validation" / ym
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"读取原始数据：{ym}", flush=True)
    raw = pd.read_parquet(input_file)

    # 仅在内存中抽样，不修改 ODS 文件
    sample = raw.sample(
        frac=SAMPLE_RATE,
        random_state=RANDOM_SEED
    ).copy()

    print(f"ODS 原始行数：{len(raw):,}")
    print(f"10% 样本行数：{len(sample):,}")

    # 不直接去重：先统计完全相同的行
    duplicate_mask = sample.duplicated(keep="first")
    duplicate_count = int(duplicate_mask.sum())

    # 模拟完全重复行去重
    # 仅用于审计，不改变正式 DWD
    df = sample.loc[~duplicate_mask].copy()

    duration = (
        pd.to_datetime(
            df["tpep_dropoff_datetime"],
            errors="coerce"
        )
        - pd.to_datetime(
            df["tpep_pickup_datetime"],
            errors="coerce"
        )
    ).dt.total_seconds() / 60

    distance = pd.to_numeric(
        df["trip_distance"], errors="coerce"
    )

    amount = pd.to_numeric(
        df["total_amount"], errors="coerce"
    )

    speed = (
        distance / (duration / 60)
    ).where(duration > 0)

    # 各规则分别统计，允许同一行命中多条规则
    rules = {
        "missing_pickup_time":
            df["tpep_pickup_datetime"].isna(),

        "missing_dropoff_time":
            df["tpep_dropoff_datetime"].isna(),

        "missing_passenger_count":
            df["passenger_count"].isna(),

        "missing_ratecode":
            df["RatecodeID"].isna(),

        "missing_duration":
            duration.isna(),

        "zero_duration":
            duration.eq(0),

        "negative_duration":
            duration.lt(0),

        "long_duration":
            duration.gt(MAX_DURATION_MIN),

        "missing_distance":
            distance.isna(),

        "zero_distance":
            distance.eq(0),

        "negative_distance":
            distance.lt(0),

        "high_distance":
            distance.gt(MAX_DISTANCE_MILES),

        "high_speed":
            speed.gt(MAX_SPEED_MPH),

        "missing_amount":
            amount.isna(),

        "negative_amount":
            amount.lt(0),

        "zero_amount":
            amount.eq(0),

        "high_amount":
            amount.gt(MAX_TOTAL_AMOUNT)
    }

    # 与当前 clean_taxi.py 的有效行程条件保持一致
    valid_trip = (
        duration.between(
            0, MAX_DURATION_MIN, inclusive="right"
        )
        & distance.between(
            0, MAX_DISTANCE_MILES, inclusive="right"
        )
        & speed.between(
            0, MAX_SPEED_MPH, inclusive="right"
        )
    ).fillna(False)

    valid_revenue = (
        valid_trip
        & amount.gt(0)
        & amount.le(MAX_TOTAL_AMOUNT)
    ).fillna(False)

    
    # ====================================
    # 距离阈值敏感性分析
    # ====================================

    print("\n========== 距离阈值敏感性分析 ==========")

    sensitivity_rows = []

    for threshold in [30, 50, 75, 100, 150]:
        # 固定时长与速度条件，只改变距离上限
        candidate_valid = (
            duration.between(
                0, MAX_DURATION_MIN,
                inclusive="right"
            )
            & distance.between(
                0, threshold,
                inclusive="right"
            )
            & speed.between(
                0, MAX_SPEED_MPH,
                inclusive="right"
            )
        ).fillna(False)

        selected = distance.loc[candidate_valid]

        sensitivity_rows.append({
            "distance_limit_miles": threshold,
            "valid_rows": int(candidate_valid.sum()),
            "retention_pct": round(
                candidate_valid.mean() * 100, 4
            ),
            "mean_distance": selected.mean(),
            "median_distance": selected.median(),
            "p99_distance": selected.quantile(0.99)
        })

    sensitivity_report = pd.DataFrame(sensitivity_rows)

    print(sensitivity_report.to_string(index=False))

    sensitivity_report.to_csv(
        output_dir / "distance_threshold_sensitivity.csv",
        index=False,
        encoding="utf-8-sig"
    )

    
    # ====================================
    # 异常原因归因分析
    # ====================================

    print("\n========== 异常原因归因 ==========")

    trip_rules = {
        "invalid_duration": (
            duration.isna()
            | duration.le(0)
            | duration.gt(MAX_DURATION_MIN)
        ),
        "invalid_distance": (
            distance.isna()
            | distance.le(0)
            | distance.gt(MAX_DISTANCE_MILES)
        ),
        "invalid_speed": (
            speed.isna()
            | speed.le(0)
            | speed.gt(MAX_SPEED_MPH)
        )
    }

    # 每条记录命中了多少条行程无效规则
    rule_flags = pd.DataFrame(trip_rules, index=df.index)
    rule_count = rule_flags.sum(axis=1)

    attribution_rows = []

    for rule_name in trip_rules:
        matched = rule_flags[rule_name]

        attribution_rows.append({
            "rule": rule_name,
            "total_matched": int(matched.sum()),
            "only_this_rule": int(
                (matched & rule_count.eq(1)).sum()
            ),
            "overlap_with_other_rules": int(
                (matched & rule_count.gt(1)).sum()
            )
        })

    attribution_report = pd.DataFrame(attribution_rows)

    print(attribution_report.to_string(index=False))

    print("\n异常规则重叠情况：")
    print(
        rule_count.value_counts()
        .sort_index()
        .to_string()
    )

    # 分析被排除行程的距离贡献
    excluded = df.loc[~valid_trip].copy()

    excluded["duration_minutes"] = duration.loc[
        excluded.index
    ]

    excluded["avg_speed_mph"] = speed.loc[
        excluded.index
    ]

    print("\n被排除行程距离统计：")
    print(
        excluded["trip_distance"].describe(
            percentiles=[0.5, 0.9, 0.99, 0.999]
        )
    )

    print("\n距离最大的 10 条被排除记录：")
    columns = [
        "trip_distance",
        "duration_minutes",
        "avg_speed_mph",
        "total_amount"
    ]

    print(
        excluded[columns]
        .sort_values("trip_distance", ascending=False)
        .head(10)
        .to_string(index=False)
    )

    attribution_report.to_csv(
        output_dir / "invalid_reason_attribution.csv",
        index=False,
        encoding="utf-8-sig"
    )

    
    # 统计每条规则的命中数量
    rule_rows = []

    for name, condition in rules.items():
        hits = count_true(condition)

        rule_rows.append({
            "rule": name,
            "matched_rows": hits,
            "matched_pct": round(
                hits / len(df) * 100, 4
            ) if len(df) else 0
        })

    rule_report = pd.DataFrame(rule_rows)

    # 清洗前后对比：
    # before = 抽样后的全部记录
    # after = 完全去重后，满足当前有效行程规则的记录
    # 这是模拟分析视图，不是实际 DWD 写入结果
    before = sample
    after = df.loc[valid_trip]

    def summarize(frame):
        d = (
            pd.to_datetime(
                frame["tpep_dropoff_datetime"],
                errors="coerce"
            )
            - pd.to_datetime(
                frame["tpep_pickup_datetime"],
                errors="coerce"
            )
        ).dt.total_seconds() / 60

        return {
            "rows": len(frame),
            "mean_distance": frame["trip_distance"].mean(),
            "median_distance": frame["trip_distance"].median(),
            "mean_duration_minutes": d.mean(),
            "total_amount_sum": frame["total_amount"].sum(),
            "missing_passenger_pct":
                frame["passenger_count"].isna().mean() * 100
        }

    before_stats = summarize(before)
    after_stats = summarize(after)

    comparison = pd.DataFrame([
        {
            "metric": metric,
            "before": before_stats[metric],
            "after": after_stats[metric]
        }
        for metric in before_stats
    ])

    # 行数审计：各阶段实际减少的行数必须对应
    sample_rows = len(sample)
    deduplicated_rows = len(df)
    valid_view_rows = int(valid_trip.sum())

    audit = {
        "ods_total_rows": len(raw),
        "sample_rows": sample_rows,
        "sample_duplicate_rows": duplicate_count,
        "sample_deduplicated_rows": deduplicated_rows,
        "sample_invalid_trip_rows":
            int((~valid_trip).sum()),
        "sample_valid_trip_rows": valid_view_rows,
        "sample_valid_revenue_rows":
            int(valid_revenue.sum()),
        "dedup_balance_pass":
            sample_rows - duplicate_count == deduplicated_rows,
        "valid_view_balance_pass":
            deduplicated_rows
            - int((~valid_trip).sum())
            == valid_view_rows
    }

    audit_report = pd.DataFrame(
        [{"metric": k, "value": v} for k, v in audit.items()]
    )

    rule_report.to_csv(
        output_dir / "rule_report.csv",
        index=False,
        encoding="utf-8-sig"
    )

    comparison.to_csv(
        output_dir / "before_after_comparison.csv",
        index=False,
        encoding="utf-8-sig"
    )

    audit_report.to_csv(
        output_dir / "row_count_audit.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print("\n========== 规则命中统计 ==========")
    print(rule_report.to_string(index=False))

    print("\n========== 清洗前后对比 ==========")
    print(comparison.to_string(index=False))

    print("\n========== 行数审计 ==========")
    print(audit_report.to_string(index=False))

    if not (
        audit["dedup_balance_pass"]
        and audit["valid_view_balance_pass"]
    ):
        raise RuntimeError("样本行数审计失败")

    print(f"\n样本审计完成，报告目录：{output_dir}")


if __name__ == "__main__":
    main()
