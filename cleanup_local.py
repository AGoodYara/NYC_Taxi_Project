from pathlib import Path
import argparse

BASE_DIR = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(
    description="清理已上传的 NYC Taxi 本地文件"
)
parser.add_argument("--year", type=int, required=True)
parser.add_argument("--month", type=int, required=True)
parser.add_argument(
    "--confirm",
    action="store_true",
    help="确认执行删除；不提供时只预览"
)
args = parser.parse_args()

if args.year < 2000 or not 1 <= args.month <= 12:
    parser.error("请输入有效的年份和月份")

year_month = f"{args.year}-{args.month:02d}"

files = [
    BASE_DIR / "data" / "raw" /
    f"yellow_tripdata_{year_month}.parquet",

    BASE_DIR / "data" / "processed" / "dwd" /
    f"yellow_taxi_dwd_{year_month}.parquet",

    BASE_DIR / "data" / "processed" / "dwd" /
    f"taxi_data_quality_report_{year_month}.csv"
]

print(f"准备清理月份：{year_month}")

for file_path in files:
    if not file_path.is_file():
        print(f"文件不存在，跳过：{file_path.name}")
        continue

    size_mb = file_path.stat().st_size / 1024**2

    if args.confirm:
        file_path.unlink()
        print(f"已删除：{file_path.name} ({size_mb:.2f} MB)")
    else:
        print(
            f"待删除：{file_path.name} "
            f"({size_mb:.2f} MB)"
        )

if not args.confirm:
    print("\n当前为预览模式，没有删除任何文件。")
else:
    print("\n本地清理完成。")
