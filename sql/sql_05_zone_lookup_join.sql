
WITH taxi_trips AS (
    SELECT
        PULocationID,
        total_amount,
        is_valid_trip,
        is_valid_revenue,
        tpep_pickup_datetime
    FROM OPENROWSET(
        BULK 'https://nyctaxidatalake2026.dfs.core.windows.net/taxi-data/dwd/yellow_taxi/year=2026/month=02/*.parquet',
        FORMAT = 'PARQUET'
    ) AS trips
    WHERE tpep_pickup_datetime >= '2026-02-01'
      AND tpep_pickup_datetime < '2026-03-01'
),
taxi_zones AS (
    SELECT
        LocationID,
        Borough,
        Zone
    FROM OPENROWSET(
        BULK 'https://nyctaxidatalake2026.dfs.core.windows.net/taxi-data/reference/taxi_zone_lookup.csv',
        FORMAT = 'CSV',
        PARSER_VERSION = '2.0',
        HEADER_ROW = TRUE
    )
    WITH (
        LocationID INT,
        Borough VARCHAR(100),
        Zone VARCHAR(200),
        service_zone VARCHAR(100)
    ) AS zones
)
SELECT TOP 10
    z.LocationID AS pickup_zone_id,
    z.Borough AS borough,
    z.Zone AS pickup_zone,
    COUNT_BIG(*) AS total_trips,
    SUM(
        CASE WHEN t.is_valid_trip = 1
        THEN CAST(1 AS BIGINT) ELSE CAST(0 AS BIGINT) END
    ) AS valid_trips,
    ROUND(
        SUM(
            CASE WHEN t.is_valid_revenue = 1
            THEN t.total_amount ELSE 0 END
        ),
        2
    ) AS valid_revenue_usd
FROM taxi_trips AS t
INNER JOIN taxi_zones AS z
    ON t.PULocationID = z.LocationID
GROUP BY
    z.LocationID,
    z.Borough,
    z.Zone
ORDER BY total_trips DESC;
