import pandas as pd
import requests

# PRICE

def _load_hourly(path, ts_col_candidates, price_col, price_alias):
    """Load a CSV and aggregate to hourly prices using the mean within each hour."""
    df = pd.read_csv(path, sep=";", encoding="utf-8")
    df.columns = df.columns.str.strip()

    ts_col = next(c for c in ts_col_candidates if c in df.columns)
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df[price_col] = pd.to_numeric(df[price_col].astype(str).str.replace(",", "."), errors="coerce")

    df = df[["PriceArea", ts_col, price_col]].dropna(subset=[ts_col, price_col]).copy()
    df["timestamp_utc"] = df[ts_col].dt.floor("h")

    df_hourly = (
        df.groupby(["PriceArea", "timestamp_utc"], as_index=False)[price_col]
        .mean()
    )

    return df_hourly.rename(
        columns={"PriceArea": "price_area", price_col: price_alias}
    )


def get_dso_tariff(ts, DSO_TARIFFS):
    """Return the DSO network tariff (excl. VAT, øre/kWh) for a given UTC timestamp."""
    if pd.isna(ts):
        return pd.NA
    for season in DSO_TARIFFS.values():
        if ts.month in season["months"]:
            for block_name, block in season.items():
                if block_name == "months":
                    continue
                start, end = block["hours"]
                if start <= ts.hour < end:
                    return block["price"]
    return pd.NA

# WEATHER


def _fetch_open_meteo(url, params, label):
    """Fetch hourly Open-Meteo data and return the JSON payload."""
    print(f"Fetching {label} …")
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    if "hourly" not in payload or "time" not in payload["hourly"]:
        raise ValueError(f"Unexpected response for {label}: missing hourly time series")

    return payload


def _build_weather_df(hourly_payload, column_map):
    """Convert an Open-Meteo hourly payload into a notebook-compatible DataFrame."""
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly_payload["time"], utc=True).tz_localize(None),
    })

    for api_name, output_name in column_map.items():
        values = hourly_payload.get(api_name)
        if values is None:
            df[output_name] = pd.NA
        else:
            df[output_name] = pd.to_numeric(values, errors="coerce")

    return df


def get_nan_stat(df, col):
    """Return NaN statistics for a single dataframe column."""
    if col not in df.columns:
        return {
            "column": col,
            "total_rows": len(df),
            "missing_count": pd.NA,
            "missing_pct": pd.NA,
            "non_missing_count": pd.NA,
            "non_missing_pct": pd.NA,
            "exists_in_df": False,
        }

    total_rows = len(df)
    missing_count = int(df[col].isna().sum())
    non_missing_count = total_rows - missing_count

    missing_pct = round((missing_count / total_rows * 100), 3) if total_rows > 0 else 0.0
    non_missing_pct = round((non_missing_count / total_rows * 100), 3) if total_rows > 0 else 0.0

    return {
        "column": col,
        "total_rows": total_rows,
        "missing_count": missing_count,
        "missing_pct": missing_pct,
        "non_missing_count": non_missing_count,
        "non_missing_pct": non_missing_pct,
        "exists_in_df": True,
    }


def get_nan_stats_for_files(file_paths, columns):
    """Return simple NaN statistics for selected columns across multiple CSV files."""
    stats_rows = []

    for path in file_paths:
        df = pd.read_csv(path)
        dataset_name = path.split("/")[-1]

        for col in columns:
            row = get_nan_stat(df, col)
            row["dataset"] = dataset_name
            row["path"] = path
            stats_rows.append(row)

    ordered_cols = [
        "dataset",
        "path",
        "column",
        "total_rows",
        "missing_count",
        "missing_pct",
        "non_missing_count",
        "non_missing_pct",
        "exists_in_df",
    ]
    return pd.DataFrame(stats_rows)[ordered_cols]




# CONSUMPTION AND COMBINE

def _load_and_transform_consumption(path):
    """Load meter data and return standardized columns: Serial, timestamp, hourly_consumption_kwh.

    Supported input formats:
    1) Raw cumulative data: reading_time + Consumption (+ Serial)
    2) Cleaned cumulative data: timestamp + consumption_cumulative_kwh_interpolated (+ Serial)
    3) Already-hourly data: timestamp + one of [hourly_consumption_kwh, consumption] (+ Serial)
    """
    df_raw = pd.read_csv(path).drop(columns=["Unnamed: 0"], errors="ignore")
    df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()].copy()

    if "Serial" not in df_raw.columns:
        raise ValueError(
            f"Input file '{path}' is missing required column 'Serial'. "
            "Include Serial in cleaned exports so load and PV meters can be separated."
        )

    # Case 1: raw cumulative readings
    if {"reading_time", "Consumption"}.issubset(df_raw.columns):
        df_raw = df_raw.rename(
            columns={
                "reading_time": "timestamp",
                "Consumption": "consumption_cumulative_kwh",
            }
        )
        timestamp_series = df_raw["timestamp"]
        if isinstance(timestamp_series, pd.DataFrame):
            timestamp_series = timestamp_series.iloc[:, 0]
        df_raw["timestamp"] = pd.to_datetime(timestamp_series, errors="coerce").dt.round("h")
        df_raw["consumption_cumulative_kwh"] = pd.to_numeric(
            df_raw["consumption_cumulative_kwh"], errors="coerce"
        )
        df_raw = df_raw.dropna(subset=["Serial", "timestamp", "consumption_cumulative_kwh"]).copy()
        df_raw = df_raw.sort_values(["Serial", "timestamp"]).reset_index(drop=True)
        df_raw["hourly_consumption_kwh"] = df_raw.groupby("Serial")["consumption_cumulative_kwh"].diff()
        df_raw.loc[df_raw.groupby("Serial").cumcount() == 0, "hourly_consumption_kwh"] = None
        return df_raw

    # Case 2: cleaned cumulative readings
    if {"timestamp", "consumption_cumulative_kwh_interpolated"}.issubset(df_raw.columns):
        timestamp_series = df_raw["timestamp"]
        if isinstance(timestamp_series, pd.DataFrame):
            timestamp_series = timestamp_series.iloc[:, 0]
        df_raw["timestamp"] = pd.to_datetime(timestamp_series, errors="coerce").dt.round("h")
        df_raw["consumption_cumulative_kwh_interpolated"] = pd.to_numeric(
            df_raw["consumption_cumulative_kwh_interpolated"], errors="coerce"
        )
        df_raw = df_raw.dropna(subset=["Serial", "timestamp"]).copy()
        df_raw = df_raw.sort_values(["Serial", "timestamp"]).reset_index(drop=True)
        df_raw["hourly_consumption_kwh"] = df_raw.groupby("Serial")["consumption_cumulative_kwh_interpolated"].diff()
        df_raw.loc[df_raw.groupby("Serial").cumcount() == 0, "hourly_consumption_kwh"] = None
        return df_raw

    # Case 3: already-hourly readings
    if "timestamp" in df_raw.columns:
        hourly_candidates = ["hourly_consumption_kwh", "consumption"]
        hourly_col = next((col for col in hourly_candidates if col in df_raw.columns), None)
        if hourly_col is not None:
            timestamp_series = df_raw["timestamp"]
            if isinstance(timestamp_series, pd.DataFrame):
                timestamp_series = timestamp_series.iloc[:, 0]
            df_raw["timestamp"] = pd.to_datetime(timestamp_series, errors="coerce").dt.round("h")
            df_raw["hourly_consumption_kwh"] = pd.to_numeric(df_raw[hourly_col], errors="coerce")
            df_raw = df_raw.dropna(subset=["Serial", "timestamp"]).copy()
            df_raw = df_raw.sort_values(["Serial", "timestamp"]).reset_index(drop=True)
            return df_raw

    raise ValueError(
        f"Unsupported schema in '{path}'. "
        "Expected raw [Serial, reading_time, Consumption], cleaned cumulative "
        "[Serial, timestamp, consumption_cumulative_kwh_interpolated], or hourly "
        "[Serial, timestamp, hourly_consumption_kwh/consumption]."
    )


def _build_hourly_consumption(df_raw, ec_id, pv_serial):
    """Aggregate transformed consumption to one hourly series per energy community id."""
    df_cons = df_raw[df_raw["Serial"] != pv_serial].copy()
    df_hourly = (
        df_cons
        .groupby("timestamp")
        ["hourly_consumption_kwh"]
        .sum()
        .reset_index(name="consumption")
    )
    df_hourly["ec_id"] = ec_id
    return df_hourly[["timestamp", "ec_id", "consumption"]]


def _build_hourly_production(df_raw, ec_id, pv_serial):
    """Aggregate PV production (Serial == pv_serial) per hour for one EC."""
    df_pv = df_raw[df_raw["Serial"] == pv_serial].copy()
    df_pv_hourly = (
        df_pv
        .groupby("timestamp")
        ["hourly_consumption_kwh"]
        .sum()
        .reset_index(name="pv_production_kwh")
    )
    df_pv_hourly["ec_id"] = ec_id
    return df_pv_hourly[["timestamp", "ec_id", "pv_production_kwh"]]
