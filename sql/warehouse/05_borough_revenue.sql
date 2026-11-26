
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 05: Borough Revenue Analysis
-- Source: dws_zone_trips
-- Period: January - February 2026
-- ============================================================

WITH borough_metrics AS (

    SELECT
        borough,

        SUM(total_trips) AS borough_total_trips,

        SUM(valid_trips) AS borough_valid_trips,

        SUM(invalid_trips) AS borough_invalid_trips,

        SUM(valid_revenue_usd) AS borough_revenue

    FROM dws_zone_trips

    GROUP BY borough
)

SELECT
    b.borough,

    b.borough_total_trips AS total_trips,

    b.borough_valid_trips AS valid_trips,

    b.borough_invalid_trips AS invalid_trips,

    ROUND(b.borough_revenue, 2)
        AS valid_revenue_usd,

    ROUND(
        b.borough_revenue /
        NULLIF(b.borough_valid_trips, 0),
        2
    ) AS avg_revenue_per_valid_trip_usd,

    ROUND(
        100.0 * b.borough_revenue /
        NULLIF(
            SUM(b.borough_revenue) OVER (), 0
        ),
        2
    ) AS revenue_share_pct,

    DENSE_RANK() OVER (
        ORDER BY b.borough_revenue DESC
    ) AS revenue_rank

FROM borough_metrics AS b

ORDER BY revenue_rank;
