
-- ============================================================
-- NYC Taxi Data Warehouse
-- Investigation: Anomalous Daily Trip Counts
-- Source: dws_hourly_trips
-- ============================================================

SELECT
    full_date,
    pickup_hour,
    total_trips,
    valid_trips,
    invalid_trips,
    valid_revenue_usd

FROM dws_hourly_trips

WHERE full_date IN (
    DATE '2026-01-25',
    DATE '2026-01-26',
    DATE '2026-02-22',
    DATE '2026-02-23'
)

ORDER BY
    full_date,
    pickup_hour;


-- ============================================================
-- DAILY HOURLY COVERAGE SUMMARY
-- ============================================================

SELECT
    full_date,

    COUNT(*) AS hour_records,

    COUNT(DISTINCT pickup_hour)
        AS distinct_hours,

    SUM(total_trips)
        AS total_trips,

    SUM(valid_trips)
        AS valid_trips,

    SUM(invalid_trips)
        AS invalid_trips,

    ROUND(SUM(valid_revenue_usd), 2)
        AS valid_revenue_usd,

    SUM(
        CASE
            WHEN total_trips = 0 THEN 1
            ELSE 0
        END
    ) AS zero_trip_hours,

    MIN(total_trips) AS min_hourly_trips,

    MAX(total_trips) AS max_hourly_trips

FROM dws_hourly_trips

WHERE full_date IN (
    DATE '2026-01-25',
    DATE '2026-01-26',
    DATE '2026-02-22',
    DATE '2026-02-23'
)

GROUP BY full_date

ORDER BY full_date;

