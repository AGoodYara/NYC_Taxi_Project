from pathlib import Path
import argparse

from azure.identity import InteractiveBrowserCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import AzureError

# ============================
# 1. 动态年月参数
# ============================

parser = argparse.ArgumentParser(
    description="上传 NYC Taxi ODS、DWD 和质量报告"
)

parser.add_argument("--year", type=int, default=2026)
parser.add_argument("--month", type=int, default=1)

args = parser.parse_args()

YEAR = args.year
MONTH = args.month

if YEAR < 2000 or not 1 <= MONTH <= 12:
    parser.error("请输入有效的年份和月份")

YEAR_MONTH = f"{YEAR}-{MONTH:02d}"
PARTITION = f"year={YEAR}/month={MONTH:02d}"

# ============================
# 2. 本地文件路径
# ============================

BASE_DIR = Path(__file__).resolve().parent

RAW_DIR = BASE_DIR / "data" / "raw"
DWD_DIR = BASE_DIR / "data" / "processed" / "dwd"

ODS_FILE = (
    RAW_DIR / f"yellow_tripdata_{YEAR_MONTH}.parquet"
)

DWD_FILE = (
    DWD_DIR / f"yellow_taxi_dwd_{YEAR_MONTH}.parquet"
)

QUALITY_FILE = (
    DWD_DIR / f"taxi_data_quality_report_{YEAR_MONTH}.csv"
)

# ============================
# 3. Azure 配置
# ============================

STORAGE_ACCOUNT = "nyctaxidatalake2026"
CONTAINER_NAME = "taxi-data"

# 文件清单：本地路径 → Azure 路径
FILES_TO_UPLOAD = [
    (
        ODS_FILE,
        f"ods/yellow_taxi/{PARTITION}/{ODS_FILE.name}"
    ),
    (
        DWD_FILE,
        f"dwd/yellow_taxi/{PARTITION}/{DWD_FILE.name}"
    ),
    (
        QUALITY_FILE,
        f"quality/yellow_taxi/{PARTITION}/{QUALITY_FILE.name}"
    )
]

# 上传前检查三个文件是否存在
for local_path, _ in FILES_TO_UPLOAD:
    if not local_path.is_file():
        raise FileNotFoundError(
            f"找不到本地文件：{local_path}"
        )

# ============================
# 4. Azure 身份认证
# ============================

credential = InteractiveBrowserCredential()

service_client = BlobServiceClient(
    account_url=(
        f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
    ),
    credential=credential,
    connection_timeout=60,
    read_timeout=120
)

container_client = service_client.get_container_client(
    CONTAINER_NAME
)

# ============================
# 5. 上传 + 校验
# ============================

def upload_and_verify(local_path, remote_path):
    local_size = local_path.stat().st_size

    print(f"\n开始上传：{local_path.name}", flush=True)
    print(
        f"本地大小：{local_size / 1024**2:.2f} MB",
        flush=True
    )

    blob_client = container_client.get_blob_client(
        remote_path
    )

    with local_path.open("rb") as data:
        blob_client.upload_blob(
            data,
            overwrite=True,
            max_concurrency=1,
            timeout=600
        )

    # 上传完成后读取云端属性
    properties = blob_client.get_blob_properties()
    cloud_size = properties.size

    if cloud_size != local_size:
        raise RuntimeError(
            f"文件大小不一致：{local_path.name}，"
            f"本地={local_size}，云端={cloud_size}"
        )

    print(f"上传并校验成功：{remote_path}", flush=True)


# ============================
# 6. 执行上传
# ============================

try:
    print(f"正在处理月份：{YEAR_MONTH}")

    for local_path, remote_path in FILES_TO_UPLOAD:
        upload_and_verify(local_path, remote_path)

    print("\n三个文件全部上传并校验成功！")

except (AzureError, RuntimeError, OSError) as error:
    print(f"\n上传或校验失败：{error}")
    raise

finally:
    service_client.close()
    credential.close()
