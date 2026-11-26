
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 03: Hourly Demand Analysis
-- Source: dws_hourly_trips
-- Period: January - February 2026
-- ============================================================

SELECT
    pickup_hour,

    -- Trip metrics
    SUM(total_trips) AS total_trips,
    SUM(valid_trips) AS valid_trips,
    SUM(invalid_trips) AS invalid_trips,

    -- Revenue metrics
    ROUND(
        SUM(valid_revenue_usd), 2
    ) AS valid_revenue_usd,

    -- Trip volume percentage
    ROUND(
        100.0 * SUM(total_trips)
        / NULLIF(SUM(SUM(total_trips)) OVER (), 0),
        2
    ) AS trip_share_pct,

    -- Ranking by trip volume
    DENSE_RANK() OVER (
        ORDER BY SUM(total_trips) DESC
    ) AS demand_rank

FROM dws_hourly_trips

WHERE full_date >= DATE '2026-01-01'
  AND full_date < DATE '2026-03-01'

GROUP BY pickup_hour

ORDER BY pickup_hour;
