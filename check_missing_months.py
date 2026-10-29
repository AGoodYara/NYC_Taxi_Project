
import argparse
from datetime import date

from azure.identity import InteractiveBrowserCredential
from azure.storage.blob import BlobServiceClient


STORAGE_ACCOUNT = "nyctaxidatalake2026"
CONTAINER_NAME = "taxi-data"

ACCOUNT_URL = (
    f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
)


def month_range(start_year, start_month, end_year, end_month):
    """生成开始月份到结束月份的所有年月。"""
    year, month = start_year, start_month

    while (year, month) <= (end_year, end_month):
        yield year, month

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def expected_blob_paths(year, month):
    """返回一个月份应有的三个 Azure Blob 路径。"""
    ym = f"{year}-{month:02d}"
    partition = f"year={year}/month={month:02d}"

    return {
        "ODS": (
            f"ods/yellow_taxi/{partition}/"
            f"yellow_tripdata_{ym}.parquet"
        ),
        "DWD": (
            f"dwd/yellow_taxi/{partition}/"
            f"yellow_taxi_dwd_{ym}.parquet"
        ),
        "Quality": (
            f"quality/yellow_taxi/{partition}/"
            f"taxi_data_quality_report_{ym}.csv"
        ),
    }


def check_missing_months(
    start_year=2026,
    start_month=1,
    end_year=2026,
    end_month=8
):
    print("正在连接 Azure Blob Storage...", flush=True)

    credential = InteractiveBrowserCredential()

    service = BlobServiceClient(
        account_url=ACCOUNT_URL,
        credential=credential
    )

    container = service.get_container_client(CONTAINER_NAME)

    print("正在读取云端文件列表...", flush=True)

    # 一次列出 Yellow Taxi 相关文件，
    # 避免每个月单独发送多个网络请求。
    existing_blobs = set()

    for prefix in (
        "ods/yellow_taxi/",
        "dwd/yellow_taxi/",
        "quality/yellow_taxi/"
    ):
        for blob in container.list_blobs(name_starts_with=prefix):
            existing_blobs.add(blob.name)

    missing_months = []
    complete_months = []
    partial_months = []

    print("\n" + "=" * 55)
    print("NYC TAXI AZURE MONTHLY COMPLETENESS REPORT")
    print("=" * 55)

    for year, month in month_range(
        start_year,
        start_month,
        end_year,
        end_month
    ):
        ym = f"{year}-{month:02d}"
        expected = expected_blob_paths(year, month)

        found = [
            layer
            for layer, path in expected.items()
            if path in existing_blobs
        ]

        missing = [
            layer
            for layer in expected
            if layer not in found
        ]

        if len(found) == 3:
            status = "COMPLETE"
            complete_months.append(ym)

        elif len(found) == 0:
            status = "MISSING"
            missing_months.append(ym)

        else:
            status = "PARTIAL"
            partial_months.append(ym)
            missing_months.append(ym)

        print(
            f"{ym} | {status:8} | "
            f"已有: {','.join(found) or '-'} | "
            f"缺少: {','.join(missing) or '-'}"
        )

    print("\n" + "=" * 55)
    print("检查汇总")
    print("=" * 55)

    print(f"完整月份：{len(complete_months)}")
    print(f"部分完成：{len(partial_months)}")
    print(f"需要补齐：{len(missing_months)}")

    if missing_months:
        print("\n待补齐月份：")
        for ym in missing_months:
            print(f"  {ym}")
    else:
        print("\n所有检查月份均已完整上传！")

    return missing_months


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--start-year", type=int, default=2026)
    parser.add_argument("--start-month", type=int, default=1)

    parser.add_argument(
        "--end-year",
        type=int,
        default=date.today().year
    )

    parser.add_argument(
        "--end-month",
        type=int,
        default=date.today().month
    )

    args = parser.parse_args()

    if not 1 <= args.start_month <= 12:
        parser.error("--start-month 必须在 1 到 12 之间")

    if not 1 <= args.end_month <= 12:
        parser.error("--end-month 必须在 1 到 12 之间")

    if (args.start_year, args.start_month) > (
        args.end_year, args.end_month
    ):
        parser.error("开始月份不能晚于结束月份")

    check_missing_months(
        start_year=args.start_year,
        start_month=args.start_month,
        end_year=args.end_year,
        end_month=args.end_month
    )
