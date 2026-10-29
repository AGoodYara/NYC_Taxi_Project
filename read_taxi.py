
import pandas as pd
from pathlib import Path

# 获取当前 Python 文件所在的项目目录
BASE_DIR = Path(__file__).resolve().parent

# 原始数据路径
input_path = BASE_DIR / "data" / "raw" / "yellow_tripdata_2026-01.parquet"

# 读取 Parquet 文件
df = pd.read_parquet(input_path)

# 提取前 10000 条记录
sample = df.head(10000)

# 输出文件路径
output_path = BASE_DIR / "data" / "processed" / "yellow_taxi_sample_2026-01.csv"

# 保存为 CSV
sample.to_csv(output_path, index=False)

print("CSV 文件生成成功！")
print("保存位置：", output_path)
print("数据行数：", len(sample))
