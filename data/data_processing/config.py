
PRICE_AREA       = "DK2"

# Radius DSO network tariffs 2026 (excl. VAT, øre/kWh)
DSO_TARIFFS = {
    "winter": {                        # Oct–Mar
        "months": [10, 11, 12, 1, 2, 3],
        "lavlast":        {"hours": (0,  6),  "price": 9.76},
        "hoejlast_day":   {"hours": (6,  17), "price": 29.29},
        "spidslast":      {"hours": (17, 21), "price": 87.88},
        "hoejlast_night": {"hours": (21, 24), "price": 29.29},
    },
    "summer": {                        # Apr–Sep
        "months": [4, 5, 6, 7, 8, 9],
        "lavlast":        {"hours": (0,  6),  "price": 9.76},
        "hoejlast_day":   {"hours": (6,  17), "price": 14.65},
        "spidslast":      {"hours": (17, 21), "price": 38.08},
        "hoejlast_night": {"hours": (21, 24), "price": 14.65},
    },
}

# State fees (excl. VAT, øre/kWh)
STATE_FEES = {
    "elafgift":    0.80,
    "transmission": 5.80,
    "system_fee":   5.40,
}

VAT_MULTIPLIER       = 1.25
FEEDIN_TARIFF_INKL   = 0.59          # øre/kWh incl. VAT
FEEDIN_TARIFF_EXKL   = FEEDIN_TARIFF_INKL / VAT_MULTIPLIER


# WEATHER

OUTPUT_ACTUAL_CSV      = "data_out/weather_data_2025_historical.csv"
OUTPUT_COMPARISON_CSV  = "data_out/weather_actuals_vs_forecasts_2025.csv"

# Keep the notebook aligned with the original time window
START_DATE             = "2025-01-01"
END_DATE               = "2026-01-01"

# Copenhagen / DK2
LATITUDE               = 55.676
LONGITUDE              = 12.568

ACTUAL_API_URL         = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_API_URL       = "https://historical-forecast-api.open-meteo.com/v1/forecast"

WEATHER_VARS = [
    "temperature_2m",
    "shortwave_radiation",
    "wind_speed_10m",
    "relative_humidity_2m",
    "precipitation",
]
