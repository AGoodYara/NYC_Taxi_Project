
import duckdb

print("========== CONNECT DUCKDB ==========")

con = duckdb.connect()

print("========== LOAD DELTA EXTENSION ==========")

con.execute("LOAD delta")

print("Delta extension: PASS")

print("========== QUERY FACT TABLE ==========")

result = con.execute(
    """
    SELECT COUNT(*)
    FROM delta_scan(
        'data/warehouse/facts/fact_taxi_trips'
    )
    """
).fetchall()

print("Fact row count:", result)

con.close()
