"""
Nordic system frequency data processor.
Computes hourly FCR-D and FCR-N activation factors from 0.1-second Fingrid data
following Crowley et al. (2024).  Entirely chunked — never loads a full day
into memory at once.

Usage:
  python3 process_frequency.py --trial   # process first month only
  python3 process_frequency.py --full    # process full year
"""

import argparse
import gc
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV_TRIAL = OUTPUT_DIR / "frequency_activation_factors_2025_TRIAL.csv"
OUTPUT_CSV_FULL  = OUTPUT_DIR / "frequency_activation_factors_2025.csv"

# ---------------------------------------------------------------------------
# Column names (hardcoded after first-file inspection)
# ---------------------------------------------------------------------------
COL_TIME  = "Time"
COL_VALUE = "Value"
CHUNKSIZE = 50_000


# ---------------------------------------------------------------------------
# Step 0: Discover and sort month folders
# ---------------------------------------------------------------------------
def discover_month_folders(base: Path):
    """Return sorted list of (month_num, Path) for month folders."""
    month_map = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    folders = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        # Numeric suffix: "01", "1", "2025-01", "2025_01"
        m = re.search(r'(\d{1,2})$', name)
        if m:
            month_num = int(m.group(1))
            if 1 <= month_num <= 12:
                folders.append((month_num, p))
            continue
        # Named: "January", "january_2025", etc.
        low = name.lower()
        for month_name, num in month_map.items():
            if month_name in low:
                folders.append((num, p))
                break
    folders.sort(key=lambda x: x[0])
    return folders


# ---------------------------------------------------------------------------
# Step 0b: Sort daily CSV files within a month folder
# ---------------------------------------------------------------------------
def sorted_csv_files(folder: Path):
    """Return CSV files sorted by filename (ISO date in filename sorts lexically)."""
    return sorted(folder.glob("*.csv"), key=lambda p: p.name)


# ---------------------------------------------------------------------------
# Step 3: Timestamp parsing
# ---------------------------------------------------------------------------
def parse_and_utc(series: pd.Series, tz_info: str) -> pd.Series:
    """
    Parse timestamps; convert to UTC-aware if necessary.
    tz_info: 'UTC', 'EET', 'EEST', or 'naive_assumed_utc'
    """
    if tz_info == "UTC":
        ts = pd.to_datetime(series, utc=True)
    else:
        ts = pd.to_datetime(series)          # parse as naive
        if tz_info in ("EET", "EEST"):
            ts = ts.dt.tz_localize("Europe/Helsinki").dt.tz_convert("UTC")
        else:  # naive_assumed_utc
            ts = ts.dt.tz_localize("UTC")
    return ts


def detect_timezone(first_file: Path) -> str:
    """
    Read a small sample and determine the timezone convention.
    Returns one of: 'UTC', 'EET', 'EEST', 'naive_assumed_utc'
    """
    sample = pd.read_csv(first_file, nrows=5)
    raw = str(sample[COL_TIME].iloc[0])
    print(f"\n  [TZ detection] Sample timestamp: {raw!r}")
    if "+00" in raw or raw.endswith("Z") or "UTC" in raw:
        tz = "UTC"
    elif "+02" in raw or "EET" in raw:
        tz = "EET"
    elif "+03" in raw or "EEST" in raw:
        tz = "EEST"
    else:
        tz = "naive_assumed_utc"
    print(f"  [TZ detection] Detected: {tz!r} — treating all timestamps as UTC")
    return tz


# ---------------------------------------------------------------------------
# Steps 4 & 5: Vectorised activation formulas
# ---------------------------------------------------------------------------
def fcrd_up_activation(f: np.ndarray) -> np.ndarray:
    """FCR-D up activation factor per reading (Crowley et al. 2024 eq. 7)."""
    return np.where(f < 49.5, 1.0,
           np.where(f > 49.9, 0.0,
                    (49.9 - f) / 0.4))


def fcrd_down_activation(f: np.ndarray) -> np.ndarray:
    """FCR-D down activation factor per reading (Nordic TSO / ENTSO-E 2023)."""
    return np.where(f > 50.5, 1.0,
           np.where(f < 50.1, 0.0,
                    (f - 50.1) / 0.4))


def fcrn_up_activation(f: np.ndarray) -> np.ndarray:
    """FCR-N up-regulation activation factor."""
    return np.where(f < 49.9, 1.0,
           np.where(f >= 50.0, 0.0,
                    (50.0 - f) / 0.1))


def fcrn_down_activation(f: np.ndarray) -> np.ndarray:
    """FCR-N down-regulation activation factor."""
    return np.where(f > 50.1, 1.0,
           np.where(f <= 50.0, 0.0,
                    (f - 50.0) / 0.1))


# ---------------------------------------------------------------------------
# Step 2: Chunked accumulator
# ---------------------------------------------------------------------------
# accumulator[hour_ts] = [sum_freq, sum_fcrd_up, sum_fcrd_down, sum_fcrn_up, sum_fcrn_down, count]

def process_chunk(chunk: pd.DataFrame, tz_info: str, accumulator: dict) -> int:
    """Process one chunk, merge into accumulator, return chunk row count."""
    ts        = parse_and_utc(chunk[COL_TIME], tz_info)
    hour_keys = ts.dt.floor("h")

    freq              = chunk[COL_VALUE].to_numpy(dtype=np.float64)
    act_fcrd_up       = fcrd_up_activation(freq)
    act_fcrd_down     = fcrd_down_activation(freq)
    act_fcrn_up       = fcrn_up_activation(freq)
    act_fcrn_down     = fcrn_down_activation(freq)

    tmp = pd.DataFrame({
        "hour":       hour_keys.values,
        "freq":       freq,
        "fcrd_up":    act_fcrd_up,
        "fcrd_down":  act_fcrd_down,
        "fcrn_up":    act_fcrn_up,
        "fcrn_down":  act_fcrn_down,
    })

    grouped = tmp.groupby("hour", sort=False).agg(
        sum_freq       = ("freq",      "sum"),
        sum_fcrd_up    = ("fcrd_up",   "sum"),
        sum_fcrd_down  = ("fcrd_down", "sum"),
        sum_fcrn_up    = ("fcrn_up",   "sum"),
        sum_fcrn_down  = ("fcrn_down", "sum"),
        count          = ("freq",      "count"),
    )

    for hour, row in grouped.iterrows():
        if hour in accumulator:
            acc = accumulator[hour]
            acc[0] += row["sum_freq"]
            acc[1] += row["sum_fcrd_up"]
            acc[2] += row["sum_fcrd_down"]
            acc[3] += row["sum_fcrn_up"]
            acc[4] += row["sum_fcrn_down"]
            acc[5] += row["count"]
        else:
            accumulator[hour] = [
                row["sum_freq"],
                row["sum_fcrd_up"],
                row["sum_fcrd_down"],
                row["sum_fcrn_up"],
                row["sum_fcrn_down"],
                row["count"],
            ]

    n = len(chunk)
    del tmp, grouped, ts, hour_keys, freq, act_fcrd_up, act_fcrd_down, act_fcrn_up, act_fcrn_down
    gc.collect()
    return n


# ---------------------------------------------------------------------------
# Step 6: Build final DataFrame from accumulator
# ---------------------------------------------------------------------------
def build_output(accumulator: dict, year_start: str, n_hours: int) -> pd.DataFrame:
    rows = []
    for hour_ts, vals in accumulator.items():
        sum_freq, sum_fcrd_up, sum_fcrd_down, sum_fcrn_up, sum_fcrn_down, count = vals
        rows.append({
            "timestamp_utc":  hour_ts,
            "sum_freq":       sum_freq,
            "sum_fcrd_up":    sum_fcrd_up,
            "sum_fcrd_down":  sum_fcrd_down,
            "sum_fcrn_up":    sum_fcrn_up,
            "sum_fcrn_down":  sum_fcrn_down,
            "count":          count,
        })

    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    full_index = pd.date_range(year_start, periods=n_hours, freq="h", tz="UTC")
    df_full = pd.DataFrame({"timestamp_utc": full_index})
    df_full = df_full.merge(df, on="timestamp_utc", how="left")

    df_full["freq_avg_hz"]        = df_full["sum_freq"]      / df_full["count"]
    df_full["y_act_fcrd_up"]      = df_full["sum_fcrd_up"]   / df_full["count"]
    df_full["y_act_fcrd_down"]    = df_full["sum_fcrd_down"] / df_full["count"]
    df_full["y_act_fcrn_up"]      = df_full["sum_fcrn_up"]   / df_full["count"]
    df_full["y_act_fcrn_down"]    = df_full["sum_fcrn_down"] / df_full["count"]
    df_full["data_quality_flag"]  = (
        (df_full["count"] < 18_000) | df_full["count"].isna()
    ).astype(int)

    df_full["timestamp_utc"] = df_full["timestamp_utc"].dt.strftime("%Y-%m-%d %H:%M:%S")

    return df_full[[
        "timestamp_utc", "freq_avg_hz",
        "y_act_fcrd_up", "y_act_fcrd_down", "y_act_fcrn_up", "y_act_fcrn_down",
        "data_quality_flag",
    ]]


# ---------------------------------------------------------------------------
# Step 8: Validation printout
# ---------------------------------------------------------------------------
def print_validation(df_out: pd.DataFrame, total_readings: int, max_chunk_seen: int,
                     label: str = ""):
    print(f"\n{'='*70}")
    print(f"VALIDATION SUMMARY{' — ' + label if label else ''}")
    print(f"{'='*70}")

    print(f"\nTotal raw 0.1-s readings processed : {total_readings:>15,}")
    print(f"Max readings held in memory at once: {max_chunk_seen:>15,}  (target: ≤50,000)")

    fcrd_up   = df_out["y_act_fcrd_up"].dropna()
    fcrd_down = df_out["y_act_fcrd_down"].dropna()
    fcrn_up   = df_out["y_act_fcrn_up"].dropna()
    fcrn_down = df_out["y_act_fcrn_down"].dropna()
    freq_col  = df_out["freq_avg_hz"].dropna()

    print(f"\nFrequency (hourly mean Hz):")
    print(f"  Mean freq_avg_hz                  : {freq_col.mean():.6f}  (expect ≈50.0)")
    print(f"  Max  freq_avg_hz                  : {freq_col.max():.6f}")
    print(f"  Min  freq_avg_hz                  : {freq_col.min():.6f}")

    print(f"\nFCR-D up (activates below 49.9 Hz):")
    print(f"  Hours with y_act_fcrd_up > 0      : {(fcrd_up > 0).sum():>6}")
    print(f"  Hours with y_act_fcrd_up >= 0.99  : {(fcrd_up >= 0.99).sum():>6}")
    print(f"  Mean y_act_fcrd_up                : {fcrd_up.mean():.6f}")
    print(f"  Max  y_act_fcrd_up                : {fcrd_up.max():.6f}")

    print(f"\nFCR-D down (activates above 50.1 Hz):")
    print(f"  Hours with y_act_fcrd_down > 0    : {(fcrd_down > 0).sum():>6}")
    print(f"  Hours with y_act_fcrd_down >= 0.99: {(fcrd_down >= 0.99).sum():>6}")
    print(f"  Mean y_act_fcrd_down              : {fcrd_down.mean():.6f}")
    print(f"  Max  y_act_fcrd_down              : {fcrd_down.max():.6f}")

    print(f"\nFCR-N up-regulation:")
    print(f"  Mean y_act_fcrn_up                : {fcrn_up.mean():.6f}")
    print(f"  Max  y_act_fcrn_up                : {fcrn_up.max():.6f}")

    print(f"\nFCR-N down-regulation:")
    print(f"  Mean y_act_fcrn_down              : {fcrn_down.mean():.6f}")
    print(f"  Max  y_act_fcrn_down              : {fcrn_down.max():.6f}")

    print(f"\nData quality:")
    print(f"  Hours with data_quality_flag=1: {df_out['data_quality_flag'].sum():>6}")

    # Monthly mean frequency
    tmp = df_out.copy()
    tmp["month"] = pd.to_datetime(tmp["timestamp_utc"]).dt.month
    monthly = tmp.groupby("month")["freq_avg_hz"].mean().reset_index()
    monthly.columns = ["month", "mean_freq_hz"]
    print(f"\nMonthly mean frequency (Hz):")
    for _, r in monthly.iterrows():
        print(f"  Month {int(r['month']):02d}: {r['mean_freq_hz']:.5f} Hz")

    # FCR-D histograms
    bins_labels = ["== 0", "(0, 0.01]", "(0.01, 0.1]", "(0.1, 0.5]", "(0.5, 1.0]"]

    def hist_counts(series):
        s = series.fillna(0)
        return [
            (s == 0).sum(),
            ((s > 0)    & (s <= 0.01)).sum(),
            ((s > 0.01) & (s <= 0.10)).sum(),
            ((s > 0.10) & (s <= 0.50)).sum(),
            ((s > 0.50) & (s <= 1.00)).sum(),
        ]

    print(f"\ny_act_fcrd_up histogram (hourly means):")
    for lbl, cnt in zip(bins_labels, hist_counts(df_out["y_act_fcrd_up"])):
        print(f"  {lbl:>12} : {cnt:>5} hours")

    print(f"\ny_act_fcrd_down histogram (hourly means):")
    for lbl, cnt in zip(bins_labels, hist_counts(df_out["y_act_fcrd_down"])):
        print(f"  {lbl:>12} : {cnt:>5} hours")

    print(f"\n{'='*70}")


# ---------------------------------------------------------------------------
# Core loop: process a list of month folders into an accumulator
# ---------------------------------------------------------------------------
def run_months(month_folders: list, tz_info: str):
    """Process the given month folders; return (accumulator, total_readings, max_chunk)."""
    accumulator   = {}
    total_readings = 0
    max_chunk_seen = 0

    for month_num, month_path in month_folders:
        csv_files = sorted_csv_files(month_path)
        month_readings = 0

        print(f"\n{'─'*60}")
        print(f"Month {month_num:02d}  ({month_path.name})  —  {len(csv_files)} daily file(s)")
        print(f"{'─'*60}")

        for csv_file in csv_files:
            file_readings = 0
            try:
                reader = pd.read_csv(
                    csv_file,
                    chunksize=CHUNKSIZE,
                    usecols=[COL_TIME, COL_VALUE],
                    dtype={COL_VALUE: np.float64},
                    engine="c",
                )
                for chunk in reader:
                    n = process_chunk(chunk, tz_info, accumulator)
                    file_readings += n
                    if n > max_chunk_seen:
                        max_chunk_seen = n
                    del chunk
                    gc.collect()

            except Exception as exc:
                print(f"  [WARNING] Failed to read {csv_file.name}: {exc}")
                continue

            total_readings += file_readings
            month_readings += file_readings
            print(f"  {csv_file.name}  ->  {file_readings:>10,} readings  "
                  f"(total so far: {total_readings:>12,})")

        print(f"\n  Month {month_num:02d} complete: {month_readings:>10,} readings  |  "
              f"Accumulator size: {len(accumulator):>5} hours  |  "
              f"Total readings: {total_readings:>12,}")

    return accumulator, total_readings, max_chunk_seen


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Nordic frequency activation factor processor")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--trial", action="store_true",
                       help="Process first month only and save to _TRIAL.csv")
    group.add_argument("--full",  action="store_true",
                       help="Process full year and save to _2025.csv")
    args = parser.parse_args()

    print("=" * 70)
    print("Nordic frequency data processor — FCR-D & FCR-N activation factors")
    print("=" * 70)

    # --- Step 0: Discover folders ---
    month_folders = discover_month_folders(BASE_DIR)
    if not month_folders:
        raise RuntimeError(f"No month folders found under {BASE_DIR}")

    print(f"\nFound {len(month_folders)} month folder(s):")
    for num, p in month_folders:
        print(f"  month={num:02d}  {p.name}")

    # --- Inspect first file ---
    first_csv = sorted_csv_files(month_folders[0][1])[0]
    print(f"\nInspecting first CSV: {first_csv.name}")
    preview = pd.read_csv(first_csv, nrows=3)
    print(f"  Columns : {list(preview.columns)}")
    print(f"  First 3 rows:\n{preview.to_string(index=False)}")
    tz_info = detect_timezone(first_csv)

    # -----------------------------------------------------------------------
    # TRIAL RUN — first month only
    # -----------------------------------------------------------------------
    if args.trial:
        print(f"\n{'='*70}")
        print("TRIAL RUN — processing first month only")
        print(f"{'='*70}")

        accumulator, total_readings, max_chunk_seen = run_months(
            month_folders[:1], tz_info
        )

        # First month has 31 days × 24 hours = 744 hours
        first_month_num = month_folders[0][0]
        month_start = f"2025-{first_month_num:02d}-01 00:00:00"
        # Count hours in first month by looking at the accumulator span
        n_trial_hours = 31 * 24  # January; build_output will fill missing hours

        df_out = build_output(accumulator, month_start, n_trial_hours)
        df_out.to_csv(OUTPUT_CSV_TRIAL, index=False, float_format="%.8f")
        print(f"\nSaved trial output: {OUTPUT_CSV_TRIAL}")
        print(f"  Row count: {len(df_out)}  (expect 744 for January)")

        print_validation(df_out, total_readings, max_chunk_seen, label="TRIAL (January)")

        print("\n*** Trial run complete. Inspect the output above. ***")
        print("*** Run with --full to process the entire year.    ***")
        return

    # -----------------------------------------------------------------------
    # FULL YEAR
    # -----------------------------------------------------------------------
    print(f"\n{'='*70}")
    print("FULL YEAR — processing all 12 months")
    print(f"{'='*70}")

    accumulator, total_readings, max_chunk_seen = run_months(month_folders, tz_info)

    # Step 6: Finalise
    print(f"\n{'='*70}")
    print("Finalising hourly output ...")

    df_out = build_output(accumulator, "2025-01-01 00:00:00", 8760)
    df_out.to_csv(OUTPUT_CSV_FULL, index=False, float_format="%.8f")
    print(f"\nSaved: {OUTPUT_CSV_FULL}")

    n_rows = len(df_out)
    if n_rows != 8760:
        print(f"  [WARNING] Expected 8760 rows, got {n_rows}")
    else:
        print(f"  Row count: {n_rows} (8760 hours = full year 2025)")

    print_validation(df_out, total_readings, max_chunk_seen, label="FULL YEAR 2025")
    print("Done.")


if __name__ == "__main__":
    main()
