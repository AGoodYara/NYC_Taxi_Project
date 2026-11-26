
from pathlib import Path
import sys

import duckdb


BASE_DIR = Path(__file__).resolve().parents[2]

DWS_DIR = BASE_DIR / "data/warehouse/dws"
SQL_DIR = BASE_DIR / "sql/warehouse"

DWS_TABLES = [
    "dws_daily_trips",
    "dws_hourly_trips",
    "dws_zone_trips",
    "dws_payment_trips",
    "dws_monthly_trips",
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python src/warehouse/run_sql.py "
            "01_core_kpis.sql"
        )

    sql_name = sys.argv[1]

    # Restrict execution to SQL files in sql/warehouse.
    if Path(sql_name).name != sql_name:
        raise ValueError("Provide a SQL filename only")

    sql_path = SQL_DIR / sql_name

    if not sql_path.is_file():
        raise FileNotFoundError(sql_path)

    con = duckdb.connect()

    try:
        con.execute("LOAD delta")

        print("\n========== REGISTER DWS VIEWS ==========")

        for table_name in DWS_TABLES:
            delta_path = DWS_DIR / table_name

            if not delta_path.exists():
                raise FileNotFoundError(delta_path)

            # Escape SQL string literals safely.
            delta_path_sql = str(delta_path).replace("'", "''")

            con.execute(
                f"""
                CREATE VIEW {table_name} AS
                SELECT *
                FROM delta_scan('{delta_path_sql}')
                """
            )


            print(f"{table_name}: READY")

        print("\n========== EXECUTE SQL ==========")
        print("SQL file:", sql_path.name)

        sql = sql_path.read_text(encoding="utf-8")
        result = con.execute(sql)

        print("\n========== QUERY RESULT ==========")
        print(result.df().to_string(index=False))

    finally:
        con.close()


if __name__ == "__main__":
    main()
