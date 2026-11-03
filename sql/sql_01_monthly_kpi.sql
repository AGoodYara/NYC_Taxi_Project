
SELECT
    COUNT_BIG(*) AS total_trips,

    SUM(
        CASE WHEN is_valid_trip = 1
        THEN CAST(1 AS BIGINT) ELSE CAST(0 AS BIGINT) END
    ) AS valid_trips,

    SUM(
        CASE WHEN is_valid_trip = 0
        THEN CAST(1 AS BIGINT) ELSE CAST(0 AS BIGINT) END
    ) AS invalid_trips,

    ROUND(
        100.0 * SUM(
            CASE WHEN is_valid_trip = 1 THEN 1 ELSE 0 END
        ) / NULLIF(COUNT_BIG(*), 0),
        2
    ) AS valid_trip_rate_pct,

    ROUND(
        SUM(
            CASE WHEN is_valid_revenue = 1
            THEN total_amount ELSE 0 END
        ),
        2
    ) AS valid_revenue_usd,

    ROUND(
        AVG(
            CASE WHEN is_valid_trip = 1
            THEN trip_distance END
        ),
        2
    ) AS avg_distance_miles

FROM OPENROWSET(
    BULK 'https://nyctaxidatalake2026.dfs.core.windows.net/taxi-data/dwd/yellow_taxi/year=2026/month=02/*.parquet',
    FORMAT = 'PARQUET'
) AS trips;
