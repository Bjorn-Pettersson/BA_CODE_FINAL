"""Combine the 2025 hourly community data with hourly frequency data.

The script keeps all columns from both sources and merges them on the hour in
UTC. The combined dataset already contains two rows per hour, so the frequency
metrics are attached to each matching hourly row.

Usage:
  python3 combine_hourly_2025.py
  python3 combine_hourly_2025.py --combined combined_2025_clean.csv \
      --frequency frequency_activation_factors_2025.csv \
      --output combined_2025_with_frequency.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_COMBINED = BASE_DIR / "combined_2025_clean.csv"
DEFAULT_FREQUENCY = BASE_DIR / "frequency_activation_factors_2025.csv"
DEFAULT_OUTPUT = BASE_DIR / "combined_2025_with_frequency.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge the 2025 combined dataset with hourly frequency data."
    )
    parser.add_argument(
        "--combined",
        type=Path,
        default=DEFAULT_COMBINED,
        help="Path to combined_2025_clean.csv",
    )
    parser.add_argument(
        "--frequency",
        type=Path,
        default=DEFAULT_FREQUENCY,
        help="Path to frequency_activation_factors_2025.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the merged output CSV",
    )
    return parser.parse_args()


def load_and_prepare(combined_path: Path, frequency_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    combined = pd.read_csv(combined_path)
    frequency = pd.read_csv(frequency_path)

    if "hour_utc" not in combined.columns:
        raise ValueError(f"Missing 'hour_utc' in {combined_path}")
    if "timestamp_utc" not in frequency.columns:
        raise ValueError(f"Missing 'timestamp_utc' in {frequency_path}")

    combined = combined.copy()
    frequency = frequency.copy()

    combined["_merge_hour_utc"] = pd.to_datetime(combined["hour_utc"], utc=True).dt.floor("h")
    frequency["_merge_hour_utc"] = pd.to_datetime(frequency["timestamp_utc"], utc=True).dt.floor("h")

    duplicate_frequency_hours = frequency["_merge_hour_utc"].duplicated().sum()
    if duplicate_frequency_hours:
        raise ValueError(
            f"Frequency data contains {duplicate_frequency_hours} duplicate hourly timestamps."
        )

    return combined, frequency


def merge_hourly_data(combined: pd.DataFrame, frequency: pd.DataFrame) -> pd.DataFrame:
    merged = combined.merge(
        frequency,
        on="_merge_hour_utc",
        how="left",
        validate="many_to_one",
        suffixes=("", "_freq"),
    )

    merged = merged.drop(columns=["_merge_hour_utc"])
    merged = merged.sort_values(["hour_utc", "ec_id"], kind="stable").reset_index(drop=True)
    return merged


def main() -> None:
    args = parse_args()

    combined, frequency = load_and_prepare(args.combined, args.frequency)
    merged = merge_hourly_data(combined, frequency)

    missing_frequency_rows = merged["freq_avg_hz"].isna().sum() if "freq_avg_hz" in merged.columns else 0
    if missing_frequency_rows:
        print(f"Warning: {missing_frequency_rows} rows did not find matching frequency data.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)

    print(f"Wrote {len(merged)} rows to {args.output}")
    print(f"Combined rows: {len(combined)}")
    print(f"Frequency rows: {len(frequency)}")


if __name__ == "__main__":
    main()