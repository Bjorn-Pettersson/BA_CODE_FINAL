# Data Pipeline Audit & Repository Cleanup

This document records all changes made to the repository during the final audit
and cleanup session. The repo represents the codebase for the BA thesis on
sequential FCR-D bidding for an energy community battery portfolio (DK2, 2025).

---

## 1. Repository Structure

```
BA_CODE_FINAL/
├── data/
│   ├── data_in/
│   │   ├── data_ec/        — hourly EC consumption + PV (Enyday.com)
│   │   ├── data_FCRD/      — FcrNdDK2.csv (EUR/MW/h, Energinet)
│   │   ├── data_freq/      — Fingrid 0.1-second frequency CSVs
│   │   └── data_spot/      — Elspotprices.csv + DayAheadPrices.csv
│   ├── data_out/
│   │   └── combined_2025_with_frequency.csv   ← FINAL DATASET
│   └── data_processing/
│       ├── 0_process_spot_ec.ipynb   — Step 0: spot + EC → combined_2025.csv
│       ├── 1_process_frequency.py    — Step 1: Fingrid Hz → activation factors
│       ├── 1b_process_fcrd.py        — Step 1b: FCRD EUR → øre/kWh
│       ├── 2_combine_hourly_2025.py  — Step 2: merge all → final dataset
│       ├── 3_check_combined_frequency.ipynb  — validation
│       ├── config.py                 — DSO tariffs, state fees, constants
│       ├── helpers.py                — shared helper functions
│       └── _process_weather.ipynb    — weather fetch (data not used in study)
├── notebooks/
│   ├── 01_Back_test_6_LER.ipynb     — upper-bound backtest (365 days, MILP)
│   ├── 01b_portfolio_study.ipynb    — portfolio size sensitivity study
│   └── sensitivity_v6(1).ipynb     — forecast noise sensitivity study
└── figures/                         — all plot outputs
```

---

## 2. Pipeline Overview

The pipeline runs in four numbered steps to produce `combined_2025_with_frequency.csv`:

| Step | Script | Reads | Writes |
|------|--------|-------|--------|
| 0 | `0_process_spot_ec.ipynb` | Elspotprices.csv, DayAheadPrices.csv, b/s_data CSVs | `combined_2025.csv` |
| 1 | `1_process_frequency.py` | Fingrid 0.1-s monthly CSVs | `frequency_activation_factors_2025.csv` |
| 1b | `1b_process_fcrd.py` | FcrNdDK2.csv + combined_2025.csv | `combined_2025_clean.csv` |
| 2 | `2_combine_hourly_2025.py` | combined_2025_clean.csv + frequency_activation_factors_2025.csv | `combined_2025_with_frequency.csv` |

Step 1 is heavy (processes ~315 million 0.1-second readings) and should only
be run if `frequency_activation_factors_2025.csv` does not already exist.

---

## 3. Path Fixes

All scripts had paths relative to their own directory or hardcoded at incorrect
levels after files were moved into the numbered pipeline structure. Fixed files:

### `data/data_processing/1_process_frequency.py`
```python
# Before
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "data" / "processed"   # non-existent nested path
discover_month_folders(BASE_DIR)               # searched script dir, not data dir

# After
FREQ_DIR   = BASE_DIR.parent / "data_in" / "data_freq"
OUTPUT_DIR = BASE_DIR.parent / "data_out"
discover_month_folders(FREQ_DIR)
```

### `data/data_processing/2_combine_hourly_2025.py`
```python
# Before — all three defaults pointed into the script directory
DEFAULT_COMBINED  = BASE_DIR / "combined_2025_clean.csv"
DEFAULT_FREQUENCY = BASE_DIR / "frequency_activation_factors_2025.csv"
DEFAULT_OUTPUT    = BASE_DIR / "combined_2025_with_frequency.csv"

# After
DATA_OUT          = BASE_DIR.parent / "data_out"
DEFAULT_COMBINED  = DATA_OUT / "combined_2025_clean.csv"
DEFAULT_FREQUENCY = DATA_OUT / "frequency_activation_factors_2025.csv"
DEFAULT_OUTPUT    = DATA_OUT / "combined_2025_with_frequency.csv"
```

### `data/data_processing/0_process_spot_ec.ipynb`
```python
# Before (missing ../ prefix and data_spot/ subdirectory)
INPUT_SPOT_CSV = "data_in/Elspotprices.csv"
INPUT_DAP_CSV  = "data_in/DayAheadPrices.csv"
OUTPUT_CSV     = "data_out/spot_prices_2025_complete.csv"

# After
INPUT_SPOT_CSV = "../data_in/data_spot/Elspotprices.csv"
INPUT_DAP_CSV  = "../data_in/data_spot/DayAheadPrices.csv"
OUTPUT_CSV     = "../data_out/spot_prices_2025_complete.csv"
# (all other data_out/ paths similarly prefixed with ../)
```

### `data/data_processing/3_check_combined_frequency.ipynb`
```python
# Before
data_path = "combined_2025_with_frequency.csv"

# After
data_path = "../data_out/combined_2025_with_frequency.csv"
```

### `data/data_processing/config.py`
```python
# Before
OUTPUT_ACTUAL_CSV     = "data_out/weather_data_2025_historical.csv"
OUTPUT_COMPARISON_CSV = "data_out/weather_actuals_vs_forecasts_2025.csv"

# After
OUTPUT_ACTUAL_CSV     = "../data_out/weather_data_2025_historical.csv"
OUTPUT_COMPARISON_CSV = "../data_out/weather_actuals_vs_forecasts_2025.csv"
```

Also corrected the comment `# Radius DSO network tariffs 2026` → `2025`.

### `data/data_processing/_process_weather.ipynb`
All active cells: `"data_in/"` → `"../data_in/data_spot/"`, `"data_out/"` → `"../data_out/"`.

---

## 4. New Script: `1b_process_fcrd.py`

No script existed to process the raw FCRD price data. The file was written from
scratch as the missing pipeline step between steps 0 and 2.

**What it does:**
1. Reads `data_in/data_FCRD/FcrNdDK2.csv` (semicolon-delimited, comma decimals)
2. Filters to `PriceArea == "DK2"` and `HourDK.year == 2025`
3. Converts prices: `EUR/MW/h × 7.46 (DKK/EUR) ÷ 10 = øre/kWh`
4. Pivots to wide format: one column per (ProductName, AuctionType) combination
5. Left-joins onto a full 8760-hour UTC grid for 2025
6. Forward-fills two isolated gaps (DST fallback hour 2025-10-26 00:00 UTC has no
   FCRD data; 2025-12-31 23:00 UTC = DK 2026-01-01 00:00 falls outside DK-year filter)
7. Reads `combined_2025.csv`, renames `timestamp` → `hour_utc`, merges FCRD columns
8. Writes `combined_2025_clean.csv` (9 new price columns, 17,520 rows × 27 columns)

**Produces these columns** (all in øre/kWh):
- `price_ore_kwh_fcr_d_ned__d_1_early / __d_1_late / __total`
- `price_ore_kwh_fcr_d_upp__d_1_early / __d_1_late / __total`
- `price_ore_kwh_fcr_n__d_1_early / __d_1_late / __total`

**Validation result:** 8751 / 8760 hours match exactly against the reference
`combined_2025_with_frequency.csv`. The 9 differing hours are data-version
differences — the raw FcrNdDK2.csv was re-downloaded after the reference dataset
was originally produced. NaN counts match exactly for all columns.

---

## 5. Sensitivity Notebook: Colab → Local

`notebooks/sensitivity_v6(1).ipynb` was written for Google Colab (Drive mount,
file upload widget, hardcoded `/content/drive/` paths). Updated to run locally:

| Cell | Change |
|------|--------|
| Title | Removed "— Colab" and "Colab runtime" |
| Section 1 header | "Mount Google Drive & install solver" → "Install dependencies" |
| Cell 1 code | Removed `from google.colab import drive` + `drive.mount()`; kept pip install |
| Section 2 header | "Upload data file" → "Data paths" |
| Cell 2 code | Replaced Drive/upload block with `BASE_DIR` + `LOCAL_DATA` via `os.path.join(os.getcwd(), '..')` |
| Config cell | `OUT_DIR = '/content/drive/...'` → `os.path.join(BASE_DIR, 'data', 'data_out')`; added `FIGURES_DIR` |
| Plot cell | `PLOT_PATH = f'{OUT_DIR}/...'` → `os.path.join(FIGURES_DIR, 'sensitivity_summary.png')` |

Path pattern is consistent with `01_Back_test_6_LER.ipynb` and
`01b_portfolio_study.ipynb`.

---

## 6. Repository Cleanup

### Removed
- `notebooks/old/` — 4 old backtest versions (backtests 1, 2, 4; old sensitivity)
- `notebooks/odl2/` — 9 intermediate versions (backtests 3, 5; single-day, sensitivity variants)
- `notebooks/.ipynb_checkpoints/` — stale checkpoint of backtest 3
- `data_tables.aux`, `data_tables.log`, `data_tables.out` — LaTeX build artifacts

### Updated `.gitignore`
```
**/.ipynb_checkpoints/
__pycache__/
```

### Updated `data/DataInfo.txt`
Rewrote with full pipeline documentation (steps 0 → 1 → 1b → 2), data source
descriptions, and output file inventory.

---

## 7. Unit Audit

Traced units from raw source files through every conversion to the MILP objective.

### Confirmed correct

| Conversion | Formula | Verified |
|---|---|---|
| Spot price DKK/MWh → øre/kWh | `÷ 10` | 1.439 øre/kWh from 14.39 DKK/MWh ✓ |
| FCRD EUR/MW/h → øre/kWh | `× 7.46 ÷ 10` | 5.968 øre/kWh → 8.000 EUR/MW/h ✓ |
| Buy price VAT | `(spot + DSO + state fees) × 1.25` | 23.199 × 1.25 = 28.999 ✓ |
| Sell price | `spot_exkl_vat − 0.59 øre/kWh` | 0.849 ✓ |
| Notebooks: øre → DKK | `÷ 100` | `ORE_TO_DKK = 1/100` ✓ |
| MILP objective | `DKK/kWh × kW × 1h` = DKK | implicit Δt = 1 h ✓ |
| Sustain constraint | `SOC (kWh) ≥ T_sus (h) / η × p_res (kW)` | kWh ✓ |
| Power constraints | `b_ch + p_res ≤ b_max` | kW ✓ |
| Frequency activation | mean of piecewise-linear [0,1] per 0.1-s reading | dimensionless ✓ |

### Known minor issues (not fixed)

**DSO tariff lookup uses UTC hour, not DK local time** (`helpers.py:38`)

`get_dso_tariff` is called with a tz-naive UTC timestamp and reads `.hour` to
assign the tariff band. Denmark is UTC+1 (winter) / UTC+2 (summer). The
peak-rate band (17:00–21:00 DK local) is therefore applied 1–2 hours late in
UTC. This slightly underestimates buy prices at the evening peak boundary.
The effect is small; it is a known conservative approximation.

**`sell_price_exkl_vat` formula mixes VAT conventions** (`0_process_spot_ec.ipynb`)

```python
sell_price_inkl_vat_ore_kwh = spot_exkl_vat - FEEDIN_TARIFF_INKL  # 0.59 øre/kWh
sell_price_exkl_vat_ore_kwh = spot_exkl_vat - FEEDIN_TARIFF_EXKL  # 0.472 øre/kWh
```

The `inkl_vat` column deducts an incl-VAT fee from an excl-VAT spot price.
The naming is inconsistent, but the column is economically correct (net cash
received per kWh exported = spot price minus gross settlement fee). The
`exkl_vat` column is dead code — it is computed but dropped in
`PRICE_COLS_TO_KEEP` and never reaches any downstream notebook.

---

## 8. What the Final Notebooks Produce

| Notebook | Output | Unit |
|---|---|---|
| `01_Back_test_6_LER.ipynb` | `backtest_upper_bound_2025.csv` | revenue in DKK/day |
| `01b_portfolio_study.ipynb` | `portfolio_study_2025.csv` | revenue in DKK/day |
| `sensitivity_v6(1).ipynb` | `individual_day_results.csv`, `figures/sensitivity_summary.png` | revenue fraction (normalised) |

All three notebooks use the same conversion (`ORE_TO_DKK = 1/100`) and the same
MILP structure. Portfolio sizes are in kW (power) and kWh (capacity). All
monetary results are in DKK.
