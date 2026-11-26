
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 02: Daily Trip and Revenue Trends
-- Source: dws_daily_trips
-- Period: January - February 2026
-- ============================================================

SELECT
    full_date,

    -- Daily trip metrics
    total_trips,
    valid_trips,
    invalid_trips,

    -- Daily revenue
    ROUND(valid_revenue_usd, 2)
        AS valid_revenue_usd,

    -- Rank by daily trip volume
    DENSE_RANK() OVER (
        ORDER BY total_trips DESC
    ) AS trip_volume_rank,

    -- Rank by daily revenue
    DENSE_RANK() OVER (
        ORDER BY valid_revenue_usd DESC
    ) AS revenue_rank,

    -- Seven-day rolling average
    ROUND(
        AVG(total_trips) OVER (
            ORDER BY full_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ),
        2
    ) AS rolling_7day_avg_trips

FROM dws_daily_trips

WHERE full_date >= DATE '2026-01-01'
  AND full_date < DATE '2026-03-01'

ORDER BY full_date;
