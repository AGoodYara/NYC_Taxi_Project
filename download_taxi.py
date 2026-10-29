
from pathlib import Path
import argparse
import time
import requests
import pyarrow.parquet as pq

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser(
    description="下载 NYC TLC Yellow Taxi 月度数据"
)
parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)
args = parser.parse_args()

if args.year < 2000 or not 1 <= args.month <= 12:
    parser.error("请输入有效的年份和月份")

year_month = f"{args.year}-{args.month:02d}"
filename = f"yellow_tripdata_{year_month}.parquet"

url = (
    "https://d37ci6vzurychx.cloudfront.net/"
    f"trip-data/{filename}"
)

target = RAW_DIR / filename
temp_file = RAW_DIR / f"{filename}.part"


def validate_parquet(path):
    metadata = pq.ParquetFile(path).metadata

    if metadata.num_rows <= 0:
        raise ValueError("Parquet 文件没有数据")

    return metadata.num_rows


# 已存在有效文件就跳过下载
if target.exists():
    try:
        rows = validate_parquet(target)
    except Exception as error:
        raise RuntimeError(
            f"本地文件校验失败：{target}，请人工检查"
        ) from error

    print(f"文件已存在，跳过下载：{target}")
    print(f"记录数：{rows}")
    raise SystemExit(0)


print(f"下载月份：{year_month}")
print(f"下载地址：{url}")

for attempt in range(1, 4):
    try:
        print(f"下载尝试：{attempt}/3")

        with requests.get(
            url,
            stream=True,
            timeout=(15, 60)
        ) as response:

            if response.status_code == 404:
                raise FileNotFoundError(
                    f"官方尚未提供 {year_month} 数据"
                )

            response.raise_for_status()

            downloaded = 0

            with temp_file.open("wb") as file:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if chunk:
                        file.write(chunk)
                        downloaded += len(chunk)

                        if downloaded % (20 * 1024 * 1024) < len(chunk):
                            print(
                                f"已下载：{downloaded / 1024**2:.1f} MB",
                                flush=True
                            )

        rows = validate_parquet(temp_file)
        temp_file.replace(target)

        print(f"下载成功：{target}")
        print(f"记录数：{rows}")
        break

    except FileNotFoundError:
        temp_file.unlink(missing_ok=True)
        raise

    except Exception as error:
        temp_file.unlink(missing_ok=True)
        print(f"下载失败：{error}")

        if attempt == 3:
            raise RuntimeError(
                "连续三次下载失败，请检查网络"
            ) from error

        time.sleep(5)
