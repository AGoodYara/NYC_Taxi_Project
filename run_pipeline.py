
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from detect_latest_month import detect_latest
from check_missing_months import check_missing_months

BASE_DIR = Path(__file__).resolve().parent


def run_script(script_name, year, month, extra_args=None):
    command = [
        sys.executable,
        str(BASE_DIR / script_name),
        "--year", str(year),
        "--month", str(month)
    ]

    if extra_args:
        command.extend(extra_args)

    print(f"\n正在执行：{script_name}", flush=True)

    subprocess.run(
        command,
        cwd=BASE_DIR,
        check=True
    )


def process_month(year, month, cleanup=False):
    print("\n" + "=" * 50)
    print(f"开始处理：{year}-{month:02d}")
    print("=" * 50)

    run_script("download_taxi.py", year, month)
    run_script("clean_taxi.py", year, month)
    run_script("upload_to_adls.py", year, month)

    if cleanup:
        run_script(
            "cleanup_local.py",
            year,
            month,
            ["--confirm"]
        )

    print(f"月份 {year}-{month:02d} 处理完成！")


def main():
    parser = argparse.ArgumentParser(
        description="NYC Taxi 自动数据流水线"
    )

    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--allow-unknown", action="store_true")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--cleanup", action="store_true")

    parser.add_argument(
        "--start-year",
        type=int,
        default=2026
    )

    parser.add_argument(
        "--start-month",
        type=int,
        default=1
    )

    args = parser.parse_args()

    if args.backfill and not args.auto:
        parser.error("--backfill 需要同时使用 --auto")

    if args.allow_unknown and not args.auto:
        parser.error("--allow-unknown 需要同时使用 --auto")

    if args.auto and (
        args.year is not None or args.month is not None
    ):
        parser.error("--auto 不能与 --year/--month 同时使用")

    if not 1 <= args.start_month <= 12:
        parser.error("--start-month 必须在 1 到 12 之间")

    start_time = datetime.now()

    print("NYC TAXI DATA PIPELINE")
    print(f"开始时间：{start_time}")

    try:
        if args.auto:
            latest_year, latest_month = detect_latest(
                max_months=12,
                allow_unknown=args.allow_unknown
            )

            if args.backfill:
                missing_months = check_missing_months(
                    start_year=args.start_year,
                    start_month=args.start_month,
                    end_year=latest_year,
                    end_month=latest_month
                )

                if not missing_months:
                    print("\n所有月份已完整上传，无需补齐。")
                    return

                print("\n准备补齐以下月份：")
                for ym in missing_months:
                    print(f"  {ym}")

                for ym in missing_months:
                    year, month = map(int, ym.split("-"))
                    process_month(
                        year,
                        month,
                        cleanup=args.cleanup
                    )

            else:
                process_month(
                    latest_year,
                    latest_month,
                    cleanup=args.cleanup
                )

        else:
            if (args.year is None) != (args.month is None):
                parser.error(
                    "--year 和 --month 必须同时提供"
                )

            year = args.year if args.year is not None else 2026
            month = args.month if args.month is not None else 1

            if year < 2000 or not 1 <= month <= 12:
                parser.error("年份或月份无效")

            process_month(
                year,
                month,
                cleanup=args.cleanup
            )

        print("\n所有任务执行成功！")

    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\n流水线执行失败：{error}", file=sys.stderr)
        sys.exit(1)

    finally:
        print(f"\n总耗时：{datetime.now() - start_time}")


if __name__ == "__main__":
    main()
