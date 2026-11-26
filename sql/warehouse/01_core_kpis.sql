
-- NYC Taxi Warehouse
-- 01: Core Operational KPIs
-- Source: dws_daily_trips
-- Grain: Entire available dataset

SELECT
    SUM(total_trips) AS total_trips,
    SUM(valid_trips) AS valid_trips,
    SUM(invalid_trips) AS invalid_trips,

    ROUND(
        100.0 * SUM(valid_trips)
        / NULLIF(SUM(total_trips), 0),
        2
    ) AS valid_trip_rate_pct,

    ROUND(
        SUM(valid_revenue_usd),
        2
    ) AS valid_revenue_usd

FROM dws_daily_trips;
