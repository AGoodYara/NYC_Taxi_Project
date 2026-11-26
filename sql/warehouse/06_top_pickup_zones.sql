
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 06: Top Pickup Zones Analysis
-- Source: dws_zone_trips
-- Period: January - February 2026
-- ============================================================

WITH zone_metrics AS (

    SELECT
        location_id,
        borough,
        zone,

        total_trips,
        valid_trips,
        invalid_trips,

        valid_revenue_usd,

        valid_trip_rate_pct

    FROM dws_zone_trips
)

SELECT
    location_id,

    borough,

    zone,

    total_trips,

    valid_trips,

    invalid_trips,

    ROUND(valid_revenue_usd, 2)
        AS valid_revenue_usd,

    ROUND(valid_trip_rate_pct, 2)
        AS valid_trip_rate_pct,

    ROUND(
        100.0 * total_trips /
        NULLIF(
            SUM(total_trips) OVER (), 0
        ),
        2
    ) AS trip_share_pct,

    DENSE_RANK() OVER (
        ORDER BY total_trips DESC
    ) AS trip_volume_rank

FROM zone_metrics

ORDER BY trip_volume_rank

LIMIT 10;
