"""
Process raw FCR-D/FCR-N auction price data for DK2 2025.

Reads  : data_in/data_FCRD/FcrNdDK2.csv  (EUR/MW/h, semi-colon delimited)
Reads  : data_out/combined_2025.csv       (hourly EC + spot + weather, output of step 0)
Writes : data_out/combined_2025_clean.csv (adds FCRD price columns in øre/kWh)

Unit conversion:  EUR/MW/h  ×  EUR_DKK_RATE  ÷ 10  =  øre/kWh
EUR/DKK rate is the 2025 annual fixed rate used throughout this study.

The combined_2025_clean.csv produced here is the input for step 2
(2_combine_hourly_2025.py), which merges the frequency activation data.
"""

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR  = Path(__file__).resolve().parent
DATA_IN   = BASE_DIR.parent / "data_in"
DATA_OUT  = BASE_DIR.parent / "data_out"

INPUT_FCRD     = DATA_IN  / "data_FCRD" / "FcrNdDK2.csv"
INPUT_COMBINED = DATA_OUT / "combined_2025.csv"
OUTPUT_CLEAN   = DATA_OUT / "combined_2025_clean.csv"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PRICE_AREA    = "DK2"
EUR_DKK_RATE  = 7.46   # fixed annual rate used throughout this study

# Maps (ProductName, AuctionType) → output column suffix
PRODUCT_MAP = {
    "FCR-D ned": "fcr_d_ned",
    "FCR-D upp": "fcr_d_upp",
    "FCR-N":     "fcr_n",
}
AUCTION_MAP = {
    "D-1 early": "d_1_early",
    "D-1 late":  "d_1_late",
    "Total":     "total",
}


def col_name(product: str, auction: str) -> str:
    return f"price_ore_kwh_{PRODUCT_MAP[product]}__{AUCTION_MAP[auction]}"


# ---------------------------------------------------------------------------
# Step 1: Load and clean raw FCRD prices
# ---------------------------------------------------------------------------
def load_fcrd(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    df.columns = df.columns.str.strip()

    for col in ["PurchasedVolumeLocal", "PurchasedVolumeTotal", "PriceTotalEUR"]:
        df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["HourUTC"] = pd.to_datetime(df["HourUTC"])
    df["HourDK"]  = pd.to_datetime(df["HourDK"])

    # Filter to DK-year 2025 and DK2 price area
    df = df[(df["HourDK"].dt.year == 2025) & (df["PriceArea"].str.strip() == PRICE_AREA)].copy()

    return df


# ---------------------------------------------------------------------------
# Step 2: Convert EUR/MW/h → øre/kWh and pivot to wide format
# ---------------------------------------------------------------------------
def build_fcrd_hourly(df: pd.DataFrame) -> pd.DataFrame:
    # EUR/MW/h = EUR/MWh; ×EUR_DKK_RATE → DKK/MWh; ÷10 → øre/kWh
    df = df.copy()
    df["price_ore_kwh"] = df["PriceTotalEUR"] * EUR_DKK_RATE / 10.0

    df["col"] = df.apply(lambda r: col_name(r["ProductName"], r["AuctionType"]), axis=1)

    wide = df.pivot_table(
        index="HourUTC",
        columns="col",
        values="price_ore_kwh",
        aggfunc="mean",
    ).reset_index()
    wide.columns.name = None

    # Ensure all 9 expected columns are present (fill missing with NaN)
    expected_cols = [
        col_name(p, a)
        for p in PRODUCT_MAP
        for a in AUCTION_MAP
    ]
    for c in expected_cols:
        if c not in wide.columns:
            wide[c] = float("nan")

    # Align column order
    wide = wide[["HourUTC"] + expected_cols]

    # Left-join onto the full 2025 UTC hourly grid so every hour has a row
    grid = pd.DataFrame({
        "HourUTC": pd.date_range("2025-01-01", periods=8760, freq="h", tz=None)
    })
    wide = grid.merge(wide, on="HourUTC", how="left")

    # Forward-fill isolated gaps (DST fallback hour on 2025-10-26 and year-end boundary)
    price_cols = [c for c in wide.columns if c != "HourUTC"]
    wide[price_cols] = wide[price_cols].ffill()

    return wide


# ---------------------------------------------------------------------------
# Step 3: Merge FCRD prices onto combined_2025.csv
# ---------------------------------------------------------------------------
def merge_fcrd(fcrd_wide: pd.DataFrame, combined_path: Path) -> pd.DataFrame:
    df = pd.read_csv(combined_path)

    # Normalise the time column — step 0 outputs 'timestamp'; rename to 'hour_utc'
    if "timestamp" in df.columns and "hour_utc" not in df.columns:
        df = df.rename(columns={"timestamp": "hour_utc"})

    df["_merge_key"] = pd.to_datetime(df["hour_utc"], utc=False).dt.tz_localize(None).dt.floor("h")
    fcrd_wide["_merge_key"] = pd.to_datetime(fcrd_wide["HourUTC"]).dt.floor("h")

    merged = df.merge(
        fcrd_wide.drop(columns=["HourUTC"]),
        on="_merge_key",
        how="left",
        validate="many_to_one",
    ).drop(columns=["_merge_key"])

    merged = merged.sort_values(["hour_utc", "ec_id"], kind="stable").reset_index(drop=True)
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 65)
    print("FCRD price processor — EUR/MW/h → øre/kWh")
    print("=" * 65)

    print(f"\n[1] Loading raw FCRD data from {INPUT_FCRD.name} …")
    df_fcrd = load_fcrd(INPUT_FCRD)
    print(f"    Rows after filter (DK2, 2025): {len(df_fcrd):,}")

    print("\n[2] Converting units and pivoting to wide format …")
    fcrd_wide = build_fcrd_hourly(df_fcrd)
    print(f"    Wide table: {len(fcrd_wide)} hourly rows × {len(fcrd_wide.columns) - 1} price columns")

    missing = fcrd_wide.iloc[:, 1:].isna().sum()
    if missing.any():
        print("    NaN counts per column (expected for D-1 late on some hours):")
        for col, n in missing[missing > 0].items():
            print(f"      {col}: {n}")

    print(f"\n[3] Loading combined_2025.csv from {INPUT_COMBINED} …")
    if not INPUT_COMBINED.exists():
        raise FileNotFoundError(
            f"{INPUT_COMBINED} not found. Run 0_process_spot_ec.ipynb first."
        )

    merged = merge_fcrd(fcrd_wide, INPUT_COMBINED)
    print(f"    Merged rows: {len(merged)}")

    # Quick sanity check: count rows that got no FCRD price at all
    fcrd_cols = [c for c in merged.columns if c.startswith("price_ore_kwh_fcr")]
    fully_missing = merged[fcrd_cols].isna().all(axis=1).sum()
    if fully_missing:
        print(f"    Warning: {fully_missing} rows have all FCRD prices as NaN "
              "(likely the last UTC hour of 2025 which falls outside DK-2025).")

    OUTPUT_CLEAN.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUTPUT_CLEAN, index=False)
    print(f"\n[4] Saved → {OUTPUT_CLEAN}")
    print(f"    Rows: {len(merged)}  |  Columns: {len(merged.columns)}")
    print("\nDone. Run 2_combine_hourly_2025.py next to merge frequency data.")


if __name__ == "__main__":
    main()
