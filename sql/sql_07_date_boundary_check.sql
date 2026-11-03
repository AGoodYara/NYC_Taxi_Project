
SELECT
    COUNT_BIG(*) AS total_rows,
    SUM(
        CASE
            WHEN tpep_pickup_datetime >= '2026-02-01'
             AND tpep_pickup_datetime < '2026-03-01'
            THEN CAST(1 AS BIGINT)
            ELSE CAST(0 AS BIGINT)
        END
    ) AS february_rows,
    SUM(
        CASE
            WHEN tpep_pickup_datetime < '2026-02-01'
              OR tpep_pickup_datetime >= '2026-03-01'
              OR tpep_pickup_datetime IS NULL
            THEN CAST(1 AS BIGINT)
            ELSE CAST(0 AS BIGINT)
        END
    ) AS outside_february_rows
FROM OPENROWSET(
    BULK 'https://nyctaxidatalake2026.dfs.core.windows.net/taxi-data/dwd/yellow_taxi/year=2026/month=02/*.parquet',
    FORMAT = 'PARQUET'
) AS trips;
