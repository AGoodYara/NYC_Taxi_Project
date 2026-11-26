
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 08: Trip Performance Analysis
-- Source: dws_zone_trips
-- ============================================================

WITH zone_performance AS (

    SELECT
        location_id,
        borough,
        zone,

        total_trips,
        valid_trips,
        invalid_trips,

        valid_trip_rate_pct,

        avg_distance_miles,
        avg_duration_minutes,
        avg_speed_mph

    FROM dws_zone_trips

    WHERE total_trips >= 100
)

SELECT
    location_id,
    borough,
    zone,

    total_trips,
    valid_trips,

    ROUND(valid_trip_rate_pct, 2)
        AS valid_trip_rate_pct,

    ROUND(avg_distance_miles, 2)
        AS avg_distance_miles,

    ROUND(avg_duration_minutes, 2)
        AS avg_duration_minutes,

    ROUND(avg_speed_mph, 2)
        AS avg_speed_mph,

    DENSE_RANK() OVER (
        ORDER BY avg_speed_mph DESC NULLS LAST
    ) AS speed_rank

FROM zone_performance

WHERE avg_speed_mph IS NOT NULL

ORDER BY speed_rank, total_trips DESC

LIMIT 20;
