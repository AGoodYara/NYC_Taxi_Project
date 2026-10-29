import argparse
from datetime import date
import requests

BASE_URL = (
    "https://d37ci6vzurychx.cloudfront.net/"
    "trip-data"
)


def previous_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def check_month(year, month, session):
    filename = f"yellow_tripdata_{year}-{month:02d}.parquet"
    url = f"{BASE_URL}/{filename}"

    try:
        response = session.head(
            url,
            timeout=(10, 20),
            allow_redirects=True
        )

        if response.status_code == 200:
            return "available"

        if response.status_code == 404:
            return "missing"

        if response.status_code == 403:
            return "unknown"

        response.raise_for_status()

        raise RuntimeError(
            f"意外 HTTP 状态码：{response.status_code}"
        )

    except requests.RequestException as error:
        raise RuntimeError(
            f"检查 {year}-{month:02d} 失败：{error}"
        ) from error


def detect_latest(max_months=12, allow_unknown=False):
    today = date.today()
    year, month = previous_month(today.year, today.month)

    unknown_months = []

    with requests.Session() as session:
        for _ in range(max_months):
            month_str = f"{year}-{month:02d}"
            print(f"正在检查：{month_str}", flush=True)

            status = check_month(year, month, session)

            if status == "available":
                if unknown_months:
                    print(
                        "警告：以下较新月份无法确认："
                        + ", ".join(unknown_months),
                        flush=True
                    )

                if unknown_months and not allow_unknown:
                    raise RuntimeError(
                        "存在状态未知的较新月份，"
                        "无法严格确认最新发布月份。"
                        "如需继续，请使用 --allow-unknown。"
                    )

                print(
                    f"最新可访问月份：{month_str}",
                    flush=True
                )
                return year, month

            if status == "unknown":
                unknown_months.append(month_str)
                print(
                    f"{month_str} 返回 403，状态未知",
                    flush=True
                )

            year, month = previous_month(year, month)

    raise RuntimeError(
        f"最近 {max_months} 个月未找到可访问文件"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-months",
        type=int,
        default=12
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true"
    )

    args = parser.parse_args()

    if args.max_months < 1:
        parser.error("--max-months 必须大于 0")

    detect_latest(
        max_months=args.max_months,
        allow_unknown=args.allow_unknown
    )
