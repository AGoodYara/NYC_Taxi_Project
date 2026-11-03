
SELECT
    DATEPART(HOUR, tpep_pickup_datetime) AS pickup_hour,
    COUNT_BIG(*) AS total_trips,
    SUM(
        CASE WHEN is_valid_trip = 1
        THEN CAST(1 AS BIGINT) ELSE CAST(0 AS BIGINT) END
    ) AS valid_trips,
    ROUND(
        SUM(
            CASE WHEN is_valid_revenue = 1
            THEN total_amount ELSE 0 END
        ),
        2
    ) AS valid_revenue_usd
FROM OPENROWSET(
    BULK 'https://nyctaxidatalake2026.dfs.core.windows.net/taxi-data/dwd/yellow_taxi/year=2026/month=02/*.parquet',
    FORMAT = 'PARQUET'
) AS trips
WHERE tpep_pickup_datetime >= '2026-02-01'
  AND tpep_pickup_datetime < '2026-03-01'
GROUP BY DATEPART(HOUR, tpep_pickup_datetime)
ORDER BY pickup_hour;
