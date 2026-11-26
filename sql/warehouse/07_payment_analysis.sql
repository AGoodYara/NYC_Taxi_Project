
-- ============================================================
-- NYC Taxi Data Warehouse
-- SQL 07: Payment Method Analysis
-- Source: dws_payment_trips
-- ============================================================

WITH payment_metrics AS (
    SELECT
        payment_type,
        payment_method,

        SUM(total_trips) AS payment_total_trips,
        SUM(valid_trips) AS payment_valid_trips,
        SUM(valid_revenue_usd) AS payment_revenue

    FROM dws_payment_trips

    GROUP BY
        payment_type,
        payment_method
)

SELECT
    payment_type,
    payment_method,

    payment_total_trips AS total_trips,
    payment_valid_trips AS valid_trips,

    ROUND(payment_revenue, 2)
        AS valid_revenue_usd,

    ROUND(
        100.0 * payment_total_trips /
        NULLIF(SUM(payment_total_trips) OVER (), 0),
        2
    ) AS trip_share_pct,

    ROUND(
        100.0 * payment_revenue /
        NULLIF(SUM(payment_revenue) OVER (), 0),
        2
    ) AS revenue_share_pct,

    DENSE_RANK() OVER (
        ORDER BY payment_revenue DESC
    ) AS revenue_rank

FROM payment_metrics

ORDER BY revenue_rank;
