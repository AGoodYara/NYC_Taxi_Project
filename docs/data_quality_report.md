# NYC Yellow Taxi — Data Quality Validation Report

## 1. Overview

This report evaluates the data quality of NYC Yellow Taxi trip records for January and February 2026.

The validation is based on 10% samples of the original ODS datasets, processed through the DWD cleaning pipeline.

- **Rule version:** `v1.0-candidate`
- **Processing strategy:** Preserve records and add quality flags
- **Storage validation:** Delta Lake
- **Validation scope:** January and February 2026 samples

## 2. Data Volume and Validation Results

| Metric | January 2026 | February 2026 |
|---|---:|---:|
| Original ODS rows | 3,724,889 | 3,399,866 |
| Sampled DWD rows | 372,489 | 339,987 |
| Valid trip rows | 355,323 | 323,465 |
| Invalid trip rows | 17,166 | 16,522 |
| Valid trip rate | 95.39% | 95.14% |
| Valid revenue rows | 351,506 | 320,895 |
| Duplicates removed | 0 | 0 |
| Rows filtered | 0 | 0 |
| Row count validation | PASS | PASS |
| Write validation | PASS | PASS |

## 3. Data Quality Rules

The pipeline applies three categories of quality checks:

**Missing-value checks**
- Missing passenger count
- Missing rate code

**Trip validity checks**
- Invalid trip duration
- Invalid trip distance
- Invalid average speed

**Revenue validity checks**
- Negative total amount
- Zero total amount
- Excessively high total amount

The current candidate thresholds are:

| Parameter | Threshold |
|---|---|
| Maximum trip duration | 180 minutes |
| Maximum trip distance | 100 miles |
| Maximum average speed | 100 mph |
| Maximum total amount | $500 |

These thresholds are provisional and require further business validation.

## 4. Cross-Month Quality Comparison

| Quality rule | January | February |
|---|---:|---:|
| Missing passenger count | 29.1778% | 30.0829% |
| Missing rate code | 29.1778% | 30.0829% |
| Invalid duration | 1.2615% | 1.2336% |
| Invalid distance | 3.3708% | 3.6451% |
| Invalid speed | 4.5647% | 4.8225% |
| Negative amount | 1.0991% | 0.8153% |
| Zero amount | 0.0132% | 0.0135% |
| High amount | 0.0021% | 0.0024% |

Passenger count and rate code missingness are the most frequent quality issues. Invalid speed is the most common trip-validity flag.

The invalid trip rate increased slightly from January to February, but two sampled months are insufficient to establish a long-term trend.

## 5. Rule Overlap Analysis

| Number of matched trip-validity rules | January | February |
|---|---:|---:|
| 0 | 355,323 | 323,465 |
| 1 | 219 | 179 |
| 2 | 16,802 | 16,225 |
| 3 | 145 | 118 |

The overlap report includes only invalid duration, distance and speed rules.

Missing-value and revenue-related flags are excluded from this overlap calculation.

## 6. Validation Conclusions

The January and February sample pipelines passed row-count and write-validation checks.

The February Delta Lake audit additionally confirmed:

- Correct year/month partitioning
- Schema consistency
- Input/output row-count consistency
- Delta transaction-log validation
- Successful partition overwrite

The pipeline preserves sampled records rather than removing invalid trips, supporting traceability and downstream analysis.

## 7. Limitations and Follow-Up Actions

- Results represent 10% samples, not full-dataset quality certification.
- Business thresholds remain provisional.
- Missing-value patterns require further investigation.
- Negative amounts may represent legitimate adjustment transactions.
- Full-volume processing and cloud orchestration remain to be validated.

**Overall status:** Sample-level data quality and write-integrity checks passed. Business-rule approval and production-level acceptance remain pending.