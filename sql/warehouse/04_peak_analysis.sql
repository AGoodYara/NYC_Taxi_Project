
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 04: Peak Period Analysis
-- Source: dws_hourly_trips
-- Period: January - February 2026
-- ============================================================

WITH hourly_metrics AS (

    SELECT
        pickup_hour,

        SUM(total_trips) AS total_trips,

        SUM(valid_trips) AS valid_trips,

        SUM(invalid_trips) AS invalid_trips,

        SUM(valid_revenue_usd) AS valid_revenue_usd

    FROM dws_hourly_trips

    WHERE full_date >= DATE '2026-01-01'
      AND full_date < DATE '2026-03-01'

    GROUP BY pickup_hour
),

peak_classification AS (

    SELECT
        *,

        CASE
            WHEN pickup_hour BETWEEN 7 AND 9
                THEN 'Morning Peak'

            WHEN pickup_hour BETWEEN 17 AND 19
                THEN 'Evening Peak'

            ELSE 'Off-Peak'
        END AS peak_period

    FROM hourly_metrics
)

SELECT
    peak_period,

    SUM(total_trips) AS total_trips,

    SUM(valid_trips) AS valid_trips,

    SUM(invalid_trips) AS invalid_trips,

    ROUND(
        SUM(valid_revenue_usd), 2
    ) AS valid_revenue_usd,

    ROUND(
        100.0 * SUM(total_trips)
        / NULLIF(SUM(SUM(total_trips)) OVER (), 0),
        2
    ) AS trip_share_pct

FROM peak_classification

GROUP BY peak_period

ORDER BY
    CASE peak_period
        WHEN 'Morning Peak' THEN 1
        WHEN 'Evening Peak' THEN 2
        WHEN 'Off-Peak' THEN 3
    END;
