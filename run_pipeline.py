
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from detect_latest_month import detect_latest
from check_missing_months import check_missing_months


BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# 1. Run a single script
# ============================================================

def run_script(script_name, year, month, extra_args=None):
    script_path = BASE_DIR / script_name

    if not script_path.is_file():
        raise RuntimeError(f"Script not found: {script_path}")

    command = [
        sys.executable,
        str(script_path),
        "--year", str(year),
        "--month", str(month)
    ]

    if extra_args:
        command.extend(extra_args)

    print("\n" + "=" * 55, flush=True)
    print(f"RUNNING: {script_name}", flush=True)
    print("COMMAND:", " ".join(command), flush=True)
    print("=" * 55, flush=True)

    start = time.perf_counter()

    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        check=False
    )

    duration = time.perf_counter() - start

    if result.returncode != 0:
        print(f"\n[FAILED] {script_name}", flush=True)
        print(f"Exit code: {result.returncode}", flush=True)
        print(f"Duration: {duration:.2f}s", flush=True)

        raise RuntimeError(
            f"{script_name} failed with exit code "
            f"{result.returncode}"
        )

    print(f"\n[PASS] {script_name}", flush=True)
    print(f"Duration: {duration:.2f}s", flush=True)

    return duration


# ============================================================
# 2. Original Azure ADLS pipeline
# ============================================================

def process_month_azure(year, month, cleanup=False):
    print("\n" + "=" * 55, flush=True)
    print(f"AZURE PIPELINE: {year}-{month:02d}", flush=True)
    print("=" * 55, flush=True)

    durations = {}

    durations["download"] = run_script(
        "download_taxi.py",
        year,
        month
    )

    durations["clean"] = run_script(
        "clean_taxi.py",
        year,
        month
    )

    durations["upload"] = run_script(
        "upload_to_adls.py",
        year,
        month
    )

    if cleanup:
        durations["cleanup"] = run_script(
            "cleanup_local.py",
            year,
            month,
            ["--confirm"]
        )

    print(f"\nAZURE PIPELINE SUCCESS: {year}-{month:02d}")
    print(f"Step durations: {durations}")

    return durations


# ============================================================
# 3. Local Delta Lake pipeline
# ============================================================

def process_month_local_delta(
    year,
    month,
    sample_rate=0.1,
    seed=42
):
    print("\n" + "=" * 55, flush=True)
    print(f"LOCAL DELTA PIPELINE: {year}-{month:02d}", flush=True)
    print(f"Sample rate: {sample_rate}", flush=True)
    print(f"Random seed: {seed}", flush=True)
    print("=" * 55, flush=True)

    raw_path = (
        BASE_DIR
        / "data"
        / "raw"
        / f"yellow_tripdata_{year}-{month:02d}.parquet"
    )

    if not raw_path.is_file():
        raise RuntimeError(
            "Local raw data not found: "
            f"{raw_path}\n"
            "Local Delta mode does not download data."
        )

    durations = {}

    # STEP 1: DWD cleaning and schema validation
    durations["clean"] = run_script(
        "clean_taxi.py",
        year,
        month,
        [
            "--sample-rate", str(sample_rate),
            "--seed", str(seed)
        ]
    )

    # STEP 2: Verify the expected sample file
    sample_path = (
        BASE_DIR
        / "data"
        / "validation"
        / f"{year}-{month:02d}"
        / f"yellow_taxi_dwd_{year}-{month:02d}_sample.parquet"
    )

    if not sample_path.is_file():
        raise RuntimeError(
            "DWD sample not found after cleaning: "
            f"{sample_path}"
        )

    print("\n[PASS] DWD sample file exists", flush=True)
    print(f"Sample path: {sample_path}", flush=True)

    # STEP 3: Delta Lake partition write and audit
    durations["delta"] = run_script(
        "write_delta_v1.py",
        year,
        month
    )

    print("\n" + "=" * 55, flush=True)
    print("LOCAL DELTA PIPELINE SUCCESS", flush=True)
    print(f"Processing month: {year}-{month:02d}", flush=True)
    print(f"Step durations: {durations}", flush=True)
    print("=" * 55, flush=True)

    return durations


# ============================================================
# 4. Pipeline dispatcher
# ============================================================

def process_month(year, month, args):
    if args.local_delta:
        return process_month_local_delta(
            year,
            month,
            sample_rate=args.sample_rate,
            seed=args.seed
        )

    return process_month_azure(
        year,
        month,
        cleanup=args.cleanup
    )


# ============================================================
# 5. Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="NYC Taxi Automated Data Pipeline"
    )

    # Month selection
    parser.add_argument("--year", type=int)
    parser.add_argument("--month", type=int)

    # Automatic processing
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--allow-unknown", action="store_true")
    parser.add_argument("--backfill", action="store_true")

    # Azure cleanup
    parser.add_argument("--cleanup", action="store_true")

    # Backfill range
    parser.add_argument(
        "--start-year",
        type=int,
        default=2026
    )

    parser.add_argument(
        "--start-month",
        type=int,
        default=1
    )

    # Local Delta Lake mode
    parser.add_argument(
        "--local-delta",
        action="store_true",
        help="Run local DWD cleaning and Delta Lake writing"
    )

    parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.1,
        help="Sampling rate for local Delta mode (default: 0.1)"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for local sampling (default: 42)"
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Parameter validation
    # --------------------------------------------------------

    if args.backfill and not args.auto:
        parser.error("--backfill requires --auto")

    if args.allow_unknown and not args.auto:
        parser.error("--allow-unknown requires --auto")

    if args.auto and (
        args.year is not None or args.month is not None
    ):
        parser.error(
            "--auto cannot be combined with --year/--month"
        )

    if (args.year is None) != (args.month is None):
        parser.error(
            "--year and --month must be provided together"
        )

    if not 1 <= args.start_month <= 12:
        parser.error("--start-month must be between 1 and 12")

    if args.start_year < 2000:
        parser.error("--start-year must be >= 2000")

    if not 0 < args.sample_rate <= 1:
        parser.error(
            "--sample-rate must be greater than 0 and <= 1"
        )

    if args.local_delta and args.cleanup:
        parser.error(
            "--cleanup is not supported in local Delta mode"
        )

    if args.local_delta and args.backfill:
        parser.error(
            "--backfill is not supported in local Delta mode yet"
        )

    if args.local_delta and args.auto:
        parser.error(
            "--auto is not supported in local Delta mode yet; "
            "specify --year and --month"
        )

    if not args.local_delta and (
        args.sample_rate != 0.1 or args.seed != 42
    ):
        parser.error(
            "--sample-rate and --seed are for local Delta mode"
        )

    # --------------------------------------------------------
    # Start pipeline
    # --------------------------------------------------------

    start_time = datetime.now()
    start_perf = time.perf_counter()

    mode = (
        "LOCAL DELTA"
        if args.local_delta
        else "AZURE ADLS"
    )

    print("\n" + "=" * 60, flush=True)
    print("NYC TAXI DATA PIPELINE", flush=True)
    print("=" * 60, flush=True)
    print(f"Mode: {mode}", flush=True)
    print(f"Start time: {start_time}", flush=True)

    processed_months = []

    try:
        if args.auto:
            latest_year, latest_month = detect_latest(
                max_months=12,
                allow_unknown=args.allow_unknown
            )

            if args.backfill:
                missing_months = check_missing_months(
                    start_year=args.start_year,
                    start_month=args.start_month,
                    end_year=latest_year,
                    end_month=latest_month
                )

                if not missing_months:
                    print(
                        "\nAll months already uploaded. "
                        "Nothing to backfill.",
                        flush=True
                    )
                else:
                    print("\nMissing months:", missing_months)

                    for ym in missing_months:
                        year, month = map(int, ym.split("-"))

                        process_month(year, month, args)
                        processed_months.append(ym)

            else:
                process_month(
                    latest_year,
                    latest_month,
                    args
                )

                processed_months.append(
                    f"{latest_year}-{latest_month:02d}"
                )

        else:
            year = (
                args.year
                if args.year is not None
                else 2026
            )

            month = (
                args.month
                if args.month is not None
                else 1
            )

            if year < 2000 or not 1 <= month <= 12:
                parser.error("Invalid year or month")

            process_month(year, month, args)

            processed_months.append(
                f"{year}-{month:02d}"
            )

        total_duration = time.perf_counter() - start_perf

        print("\n" + "=" * 60, flush=True)
        print("PIPELINE SUMMARY", flush=True)
        print("=" * 60, flush=True)
        print("Status: SUCCESS", flush=True)
        print(f"Mode: {mode}", flush=True)
        print(f"Processed months: {processed_months}", flush=True)
        print(f"Total duration: {total_duration:.2f}s", flush=True)
        print(f"End time: {datetime.now()}", flush=True)
        print("=" * 60, flush=True)

    except (
        RuntimeError,
        subprocess.CalledProcessError,
        OSError,
        ValueError
    ) as error:
        print(
            f"\nPIPELINE FAILED: {error}",
            file=sys.stderr,
            flush=True
        )
        sys.exit(1)

    finally:
        print(
            f"\nTotal elapsed: {datetime.now() - start_time}",
            flush=True
        )


if __name__ == "__main__":
    main()
