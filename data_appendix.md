# Appendix: Data Sources and Preprocessing

This appendix provides step-by-step documentation sufficient to reconstruct the
input dataset from raw downloads.  All processing code lives under
\texttt{data/data\_processing/}.  The final model input is
\texttt{data/data\_out/combined\_2025\_with\_frequency.csv}.

---

## A.1 Nordic System Frequency

### Source

| Field | Value |
|-------|-------|
| Provider | Fingrid (Finnish TSO, Nordic control area) |
| Dataset name | "Frequency measurement" |
| Dataset ID | 339 |
| URL | \texttt{https://data.fingrid.fi/en/datasets/339} |
| Download method | Manual bulk export (daily CSV files) |
| Download date | Not recorded in code comments |
| Geographic scope | Nordic synchronous area (same frequency applies to DK2) |

### Raw file format

- One CSV per day; filename convention: \texttt{TaajuusdataYYYY-MM-DD.csv}
  (Finnish: \emph{taajuus} = frequency)
- Files stored at \texttt{data/data\_in/data\_freq/2025-MM/} (12 monthly subfolders)
- Total: 365 daily files
- Columns: \texttt{Time} (ISO-8601 timestamp, no timezone suffix -- treated as UTC),
  \texttt{Value} (Hz, \texttt{float64})
- Resolution: 0.1 s (10 Hz sampling); approximately 863,952 readings per day
  (theoretical maximum $24\times3600\times10 = 864{,}000$; small shortfalls observed)
- January 2025 alone contains 26,775,841 readings

### Preprocessing: \texttt{1\_process\_frequency.py}

**Step 1 -- folder discovery** (\texttt{discover\_month\_folders()}, line~42):
Monthly subfolders are matched by trailing numeric suffix (\texttt{re.search(r'(\textbackslash{}d\{1,2\})\$')}).
The result is a sorted list of \texttt{(month\_num, Path)} pairs.

**Step 2 -- timezone detection** (\texttt{detect\_timezone()}, line~98):
The first row of the first file is sampled.  If the timestamp string contains \texttt{+00},
\texttt{Z}, or \texttt{UTC} it is marked \texttt{UTC}; if it contains \texttt{+02}/\texttt{EET}
or \texttt{+03}/\texttt{EEST} the \texttt{Europe/Helsinki} offset is applied; otherwise
(the actual 2025 case) it is treated as \texttt{naive\_assumed\_utc} -- the naive timestamp is
tz-localised to UTC directly.

**Step 3 -- chunked reading and accumulation** (\texttt{process\_chunk()}, line~154):
Files are read in chunks of 50,000 rows (\texttt{CHUNKSIZE}). Per chunk:
  1. Parse \texttt{Time} column and floor to the clock hour (\texttt{dt.floor("h")}).
  2. Apply vectorised activation formulas (see below) to the \texttt{Value} array.
  3. Group by hour; accumulate running sums of all activation factors and a row count
     into a Python dict keyed by the UTC hour timestamp.

**Step 4 -- activation formulas** (\texttt{fcrd\_up\_activation()} etc., lines~121--146):

Piecewise-linear activation factor per 0.1-s reading, following Crowley et al.\ (2025):

\[
  a_{\tau}^{\mathrm{FCRD}\uparrow}(f) =
  \begin{cases}
    1 & f < 49.5\text{ Hz}\\
    \dfrac{49.9-f}{0.4} & 49.5 \le f \le 49.9\text{ Hz}\\
    0 & f > 49.9\text{ Hz}
  \end{cases}
\]

\[
  a_{\tau}^{\mathrm{FCRD}\downarrow}(f) =
  \begin{cases}
    0 & f < 50.1\text{ Hz}\\
    \dfrac{f-50.1}{0.4} & 50.1 \le f \le 50.5\text{ Hz}\\
    1 & f > 50.5\text{ Hz}
  \end{cases}
\]

FCR-N: dead-band $[49.9, 50.0)$ Hz (up) and $(50.0, 50.1]$ Hz (down), both linear over a
0.1 Hz range.

**Step 5 -- hourly aggregation** (\texttt{build\_output()}, line~211):

\[
  y_t^{\mathrm{actFCRD}\uparrow} = \frac{\sum_{\tau\in t} a_\tau^{\mathrm{FCRD}\uparrow}}{n_t}
\]

where $n_t$ is the count of 0.1-s readings in hour $t$.  The hourly value is thus the
\emph{time-averaged activation fraction} (between 0 and 1), not a binary threshold count.

**Step 6 -- full-year index and quality flag** (\texttt{build\_output()}, line~211):
A complete 8,760-hour UTC index is generated (\texttt{pd.date\_range("2025-01-01 00:00:00", periods=8760)}),
and the accumulator is left-joined onto it (missing hours become NaN).
A \texttt{data\_quality\_flag} is set to 1 for any hour with $n_t < 18{,}000$
(fewer than half the expected 36,000 readings).

**Output**: \texttt{data/data\_processing/data/processed/frequency\_activation\_factors\_2025.csv}
(8,760 rows).
Columns: \texttt{timestamp\_utc}, \texttt{freq\_avg\_hz},
\texttt{y\_act\_fcrd\_up}, \texttt{y\_act\_fcrd\_down},
\texttt{y\_act\_fcrn\_up}, \texttt{y\_act\_fcrn\_down}, \texttt{data\_quality\_flag}.

### Descriptive statistics (b-type EC rows, 8,756 non-flagged hours)

| Variable | Mean | Std | Min | Max |
|----------|------|-----|-----|-----|
| \texttt{freq\_avg\_hz} (Hz) | 50.0000 | 0.0151 | 49.9065 | 50.1244 |
| \texttt{y\_act\_fcrd\_up} | 0.000270 | 0.00173 | 0.0 | 0.0439 |
| \texttt{y\_act\_fcrd\_down} | 0.000243 | 0.00198 | 0.0 | 0.0718 |

FCR-D up is nonzero in 1,811 hours (20.7\%); FCR-D down in 1,545 hours (17.6\%).
Full activation ($y\ge 0.99$) is extremely rare.

**Discrepancy note:** The thesis Eq.~(2.1.4) writes
$y_t^{\mathrm{actFCRD}\uparrow} = \#\{\tau\in t: f_\tau < 49.9\,\text{Hz}\}/\#\{\tau\in t\}$,
which is a binary threshold count.  The code uses the continuous piecewise-linear formula
above; the two agree only when the frequency is either above 49.9 Hz (activation = 0) or
below 49.5 Hz (activation = 1).  In the intermediate band the proportional formula is used.

---

## A.2 Day-Ahead Spot Prices

### Sources

| Field | Source 1 | Source 2 |
|-------|----------|----------|
| Product | \texttt{Elspotprices} | \texttt{DayAheadPrices} |
| URL | \texttt{https://www.energidataservice.dk/tso-electricity/Elspotprices} | \texttt{https://energidataservice.dk/tso-electricity/DayAheadPrices} |
| Period covered (DK2) | 2024-12-31 23:00 -- 2025-09-30 21:00 UTC | 2025-09-30 22:00 -- 2025-12-31 22:45 UTC |
| DK2 row count | 6,551 | 8,836 |
| Resolution | Hourly | 15-minute |

### Raw file format

Both files use semicolon delimiters and Danish locale (comma as decimal separator).
Column names and price units:

- \texttt{Elspotprices.csv}: \texttt{HourUTC;HourDK;PriceArea;SpotPriceDKK;SpotPriceEUR}
  -- \texttt{SpotPriceDKK} in DKK/MWh
- \texttt{DayAheadPrices.csv}: \texttt{TimeUTC;TimeDK;PriceArea;DayAheadPriceEUR;DayAheadPriceDKK}
  -- \texttt{DayAheadPriceDKK} in DKK/MWh

Both files contain multiple price areas; only DK2 rows are retained.

### Preprocessing: \texttt{0\_process\_spot\_ec.ipynb} (cell \texttt{bcba2c88})

Implemented in \texttt{helpers.\_load\_hourly()} (helpers.py, line~6):

1. Read CSV with \texttt{sep=";"}, strip column names, coerce commas to dots in price column.
2. Parse timestamp column (\texttt{HourUTC} or \texttt{TimeUTC}), floor to clock hour.
3. Group by (\texttt{PriceArea}, \texttt{timestamp\_utc}), take \textbf{mean} -- this averages
   the four 15-minute prices within each hour for \texttt{DayAheadPrices}.

Merge procedure (notebook cell \texttt{bcba2c88}):

1. Tag each source: \texttt{spot} $\rightarrow$ priority 0, \texttt{dayahead} $\rightarrow$ priority 1.
2. Filter to \texttt{PriceArea == "DK2"}.
3. Sort by (\texttt{timestamp\_utc}, priority); drop duplicates keeping first -- so
   \texttt{Elspotprices} wins for any overlapping hours near the transition (approximately
   2025-10-01).
4. Re-index onto full 8,760-hour grid (\texttt{pd.date\_range("2025-01-01", "2025-12-31 23:00")}).
5. Forward-fill then back-fill \texttt{spot\_price\_dkk\_per\_mwh} -- fills the one missing
   terminal hour (2025-12-31 23:00 UTC).

**Warning in notebook output:** "missing 1 hourly price points for 2025: 2025-12-31 23:00:00".
This is handled by \texttt{ffill().bfill()}.

**Unit conversion:** DKK/MWh $\div$ 10 $=$ \o{}re/kWh.

### Price-stack calculation (\texttt{0\_process\_spot\_ec.ipynb}, cell \texttt{bcba2c88})

Tariff values from \texttt{config.py}.

**DSO network tariff** (Radius, 2026 schedule, \o{}re/kWh excl.\ VAT):

| Season | Hours | Block name | \o{}re/kWh |
|--------|-------|-----------|------------|
| Winter (Oct--Mar) | 00--06 | lavlast | 9.76 |
| Winter | 06--17 | hojlast\_day | 29.29 |
| Winter | 17--21 | spidslast | 87.88 |
| Winter | 21--24 | hojlast\_night | 29.29 |
| Summer (Apr--Sep) | 00--06 | lavlast | 9.76 |
| Summer | 06--17 | hojlast\_day | 14.65 |
| Summer | 17--21 | spidslast | 38.08 |
| Summer | 21--24 | hojlast\_night | 14.65 |

Applied via \texttt{helpers.get\_dso\_tariff(ts, DSO\_TARIFFS)} (helpers.py, line~28),
which maps each UTC timestamp to its block.

**State fees** (\o{}re/kWh excl.\ VAT): \texttt{elafgift} = 0.80,
\texttt{transmission} = 5.80, \texttt{system\_fee} = 5.40 (total fixed = 12.00).

**Buy price** (consumer, incl.\ VAT):
\[
  \lambda_t^{\mathrm{buy}} = (\lambda_t^{\mathrm{spot}} + \tau_t^{\mathrm{DSO}} + 12.00)\times 1.25
  \quad\text{[\o{}re/kWh]}
\]

**Sell price** (prosumer, incl.\ VAT):
\[
  \lambda_t^{\mathrm{sell}} = \lambda_t^{\mathrm{spot}} - 0.59
  \quad\text{[\o{}re/kWh]}
\]

where 0.59 \o{}re/kWh is \texttt{FEEDIN\_TARIFF\_INKL} (incl.\ VAT).
The sell price can be negative during negative-price hours.

**Note:** config.py labels the tariffs as "Radius DSO network tariffs 2026" while the study
covers 2025.  The 2026 schedule is applied throughout.

**Output**: \texttt{data\_out/spot\_prices\_2025\_complete.csv} (8,760 rows).
Columns include \texttt{timestamp\_utc}, \texttt{spot\_price\_dkk\_per\_mwh},
\texttt{spot\_exkl\_vat\_ore\_kwh}, \texttt{dso\_tariff\_exkl\_vat\_ore\_kwh},
\texttt{buy\_price\_inkl\_vat\_ore\_kwh}, \texttt{sell\_price\_inkl\_vat\_ore\_kwh}.

### Descriptive statistics (8,760 hourly observations)

| Variable | Mean | Std | Min | Max |
|----------|------|-----|-----|-----|
| \texttt{spot\_exkl\_vat\_ore\_kwh} (\o{}re/kWh) | 61.57 | 38.65 | $-$18.91 | 435.27 |
| \texttt{buy\_price\_inkl\_vat\_ore\_kwh} (\o{}re/kWh) | 124.13 | 61.36 | 9.67 | 595.70 |
| \texttt{sell\_price\_inkl\_vat\_ore\_kwh} (\o{}re/kWh) | 60.98 | 38.65 | $-$19.50 | 434.68 |

Negative spot (and hence negative sell) prices occurred in 2025 (minimum $-18.9$ \o{}re/kWh).

---

## A.3 Energy Community Smart-Meter Data

### Source

| Field | Value |
|-------|-------|
| Provider | Enyday.com (industry collaboration) |
| Files | \texttt{data\_in/data\_ec/b\_data.csv}, \texttt{data\_in/data\_ec/s\_data.csv} |
| Data type | Cumulative energy register (odometer-style), kWh |

### Raw file format

Both files: comma-separated with an anonymous index column.
Columns: \texttt{[index], reading\_time, Serial, Consumption}.

- \texttt{reading\_time}: ISO timestamp string (local/UTC ambiguous -- rounded to nearest
  hour by preprocessing code).
- \texttt{Serial}: integer meter ID.  Negative serial identifies the PV production meter
  (\texttt{Serial}$=-1$ for b-type, \texttt{Serial}$=-2$ for s-type).
- \texttt{Consumption}: cumulative register reading in kWh (monotonically increasing for
  load meters; increases for production meter too, representing cumulative generation).

| File | Total rows | Unique serials | Load meters | PV meter |
|------|-----------|----------------|------------|---------|
| \texttt{b\_data.csv} | 496,121 | 57 | 56 (Serial 1--57, excl.\ 15) | Serial $-1$ |
| \texttt{s\_data.csv} | 547,852 | 63 | 62 (Serial 58--120, excl.\ 107) | Serial $-2$ |

Date range: 2025-01-01 00:00:00 to 2026-01-01 00:00:00 (inclusive).

### Preprocessing: \texttt{0\_process\_spot\_ec.ipynb}, function \texttt{build\_cleaned\_cumulative()} (cell \texttt{118122cb})

1. **Load and column normalisation**: read CSV, drop unnamed index column, rename
   \texttt{reading\_time} $\to$ \texttt{timestamp}, \texttt{Consumption} $\to$
   \texttt{consumption\_cumulative\_kwh}.
2. **Timestamp rounding**: \texttt{pd.to\_datetime(...).dt.round("h")} -- sub-hourly readings
   are snapped to the nearest clock hour.
3. **Hourly grid construction**: cross-join serial list with full 8,760-hour grid
   (\texttt{pd.date\_range("2025-01-01", "2026-01-01", freq="h", inclusive="left")}).
4. **Left merge**: attach actual readings onto the grid; duplicates at the same
   \texttt{(Serial, timestamp)} are resolved by keeping the last.
5. **Linear interpolation of cumulative values** per serial:
   \texttt{groupby("Serial")["consumption\_cumulative\_kwh"].transform(lambda s: s.interpolate(method="linear", limit\_direction="both"))}.
   Filled positions are flagged with \texttt{corrected\_consumption\_value}$=1$.
   Corrected counts: b-type 3,299/499,320 (0.66\%), s-type 4,123/551,880 (0.75\%).
6. **Hourly delta**: \texttt{groupby("Serial")["consumption\_cumulative\_kwh\_interpolated"].diff()}.
   The first row per serial (no prior value) is back-filled from the second row.
7. **Output**: \texttt{data\_out/b\_data\_cumulative\_cleaned\_2025.csv} and
   \texttt{s\_data\_cumulative\_cleaned\_2025.csv}, each with 8,760 rows per serial.
   Columns: \texttt{Serial, timestamp, time, consumption\_cumulative\_kwh\_interpolated,
   corrected\_consumption\_value}.

### Combination step: same notebook cell \texttt{e9207dae}

Using \texttt{helpers.\_build\_hourly\_consumption()} (helpers.py, line~212)
and \texttt{helpers.\_build\_hourly\_production()} (line~226):

- **Consumption**: sum \texttt{hourly\_consumption\_kwh} across all non-PV serials per hour.
  The hourly diff is recomputed from the interpolated cumulative via \texttt{.diff()}.
- **PV production**: take \texttt{hourly\_consumption\_kwh} for the PV serial only
  (identical logic -- the register increases as energy is generated).
- Resulting dataset: 8,760 rows per EC type, columns \texttt{timestamp, ec\_id, consumption,
  pv\_production\_kwh}.
- \texttt{ec\_id}: \texttt{"b"} for b-type, \texttt{"s"} for s-type.
- Combined: \texttt{data\_out/combined\_2025.csv} (17,520 rows = 8,760 $\times$ 2 EC types).

### Descriptive statistics (b-type hourly, 8,760 observations)

| Variable | Mean | Std | Min | Max |
|----------|------|-----|-----|-----|
| \texttt{consumption} (kWh) | 13.27 | 4.64 | 0.00 | 28.50 |
| \texttt{pv\_production\_kwh} (kWh) | 3.95 | 6.55 | 0.00 | 28.01 |

s-type has slightly higher mean consumption (community-level total, summed across all load meters).
PV production peaks in summer (solar noon, up to $\approx$28 kWh/h), zero for all winter nights.

### EC type characteristics

The b-type community represents a large multi-unit residential block with high base load
and moderate solar generation; the s-type represents a community where the PV capacity is
larger relative to total consumption.  Both exhibit the classic Danish demand profile
(morning/evening peaks) with a strong solar injection around 12:00--14:00 in summer months.
The distinction between b-type and s-type maps directly to the two empirical communities
provided by Enyday; they are not constructed analytically.

---

## A.4 FCR-D and FCR-N Reservation Prices

### Source

| Field | Value |
|-------|-------|
| Provider | Energidataservice (Energinet) |
| Dataset name | \texttt{FcrNdDK2} — FCR-N and FCR-D clearing prices for DK2 |
| URL | \texttt{https://www.energidataservice.dk/tso-electricity/FcrNdDK2} |
| File | \texttt{data/data\_in/data\_FCRD/FcrNdDK2.csv} |
| 2025 row count | 78,840 (3 products × 3 auction types × 8,760 hours) |
| Date range | 2025-01-01 00:00 -- 2025-12-31 23:00 UTC |

### Raw file format

Semicolon-separated, Danish locale (comma decimal).
Columns: \texttt{HourUTC; HourDK; PriceArea; ProductName; AuctionType; PurchasedVolumeLocal;
PurchasedVolumeTotal; PriceTotalEUR}.

- \texttt{ProductName}: \texttt{"FCR-D ned"} (down), \texttt{"FCR-D upp"} (up), \texttt{"FCR-N"}
- \texttt{AuctionType}: \texttt{"D-1 early"}, \texttt{"D-1 late"}, \texttt{"Total"}
  (volume-weighted combined of early+late)
- \texttt{PriceTotalEUR}: clearing price in \textbf{EUR/MW/h} (capacity reservation price)
- \texttt{PurchasedVolumeLocal}: MW purchased in DK2 local auction
- \texttt{PurchasedVolumeTotal}: MW purchased across full Nordic area

The naming convention \emph{ned}/\emph{upp} (Swedish/Norwegian for down/up) reflects the
Nordic TSO terminology used in the Nordic MMS bidding portal.

### Preprocessing (unit conversion)

The price column \texttt{PriceTotalEUR} is in EUR/MW/h (euros per MW of reserved capacity per
hour).  The model requires \o{}re/kWh.  The conversion uses a \textbf{fixed EUR/DKK exchange
rate of 7.46}:

\[
  \texttt{price\_ore\_kwh} = \texttt{PriceTotalEUR} \times \frac{7.46}{10}
  = \texttt{PriceTotalEUR} \times 0.746
\]

Derivation: $1\,\text{EUR/MW/h} = 1\,\text{EUR}/\text{MWh}
= 7.46\,\text{DKK}/\text{MWh} = 0.746\,\text{\o{}re/kWh}$.

Example (first 2025 hour, FCR-D Down, early auction):
$8.00\,\text{EUR/MW} \times 0.746 = 5.968\,\text{\o{}re/kWh}$,
which exactly matches \texttt{price\_ore\_kwh\_fcr\_d\_ned\_\_d\_1\_early}
in \texttt{combined\_2025\_with\_frequency.csv}.

The pivot step reshapes the long format (product × auction type) to one row per hour with
nine wide columns:

| Raw \texttt{ProductName} + \texttt{AuctionType} | Target column |
|-------------------------------------------------|---------------|
| FCR-D ned + D-1 early | \texttt{price\_ore\_kwh\_fcr\_d\_ned\_\_d\_1\_early} |
| FCR-D ned + D-1 late  | \texttt{price\_ore\_kwh\_fcr\_d\_ned\_\_d\_1\_late} |
| FCR-D ned + Total     | \texttt{price\_ore\_kwh\_fcr\_d\_ned\_\_total} |
| FCR-D upp + D-1 early | \texttt{price\_ore\_kwh\_fcr\_d\_upp\_\_d\_1\_early} |
| FCR-D upp + D-1 late  | \texttt{price\_ore\_kwh\_fcr\_d\_upp\_\_d\_1\_late} |
| FCR-D upp + Total     | \texttt{price\_ore\_kwh\_fcr\_d\_upp\_\_total} |
| FCR-N + D-1 early     | \texttt{price\_ore\_kwh\_fcr\_n\_\_d\_1\_early} |
| FCR-N + D-1 late      | \texttt{price\_ore\_kwh\_fcr\_n\_\_d\_1\_late} |
| FCR-N + Total         | \texttt{price\_ore\_kwh\_fcr\_n\_\_total} |

This preprocessing step was performed by the now-deleted \texttt{0\_CREATE\_2025\_DATA.ipynb};
no active script currently reproduces it.

### How FCR-D prices are used in the model

In \texttt{01\_Back\_test.ipynb} (cell~8) the columns are loaded, clipped to
$\ge 0$, and converted from \o{}re/kWh to DKK/kWh (divide by 100):
```python
df_raw['fcrd_up_early_dkk'] = df_raw['price_ore_kwh_fcr_d_upp__d_1_early'].fillna(0.0).clip(lower=0) / 100.0
```

The buy-back price in the late-auction objective is the maximum of early and late clearing
prices per hour, computed in \texttt{build\_late()} (cell~14):
```python
t: max(early_clearing_up[t-1], day_late['fcrd_up_price_late'][t-1]) for t in T
```

Only FCR-D Up and Down are bid; FCR-N prices (\texttt{price\_ore\_kwh\_fcr\_n\_\_\*}) are
present in the dataset but not used in any constraint or objective in the reported experiments.

### Descriptive statistics (8,760 hourly observations, DK2 2025)

| Variable | Mean (\o{}re/kWh) | Std | Min | Max |
|----------|-------------------|-----|-----|-----|
| FCR-D Up, early clearing | 4.38 | 5.14 | 0.74 | 100.71 |
| FCR-D Up, late clearing | 4.75 | 11.65 | 0.07 | 208.88 |
| FCR-D Down, early clearing | 3.67 | 3.64 | 0.75 | 44.76 |
| FCR-D Down, late clearing | 6.10 | 59.23 | 0.07 | 2006.74 |

The late FCR-D Down series has extreme outliers (max 2,007~\o{}re/kWh); these likely
correspond to stress events.  Zero-price or near-zero values are handled by the
\texttt{.clip(lower=0).fillna(0)} guard in the data loading cell.

---

## A.5 Synthetic Portfolio Construction

Implemented in \texttt{01\_Back\_test.ipynb}, cells 2 (configuration) and 5 (construction).

### Parameters (from cell 2)

| Parameter | Code name | Value |
|-----------|-----------|-------|
| Number of ECs | \texttt{N\_ECS} | 10 |
| Battery power limit per EC | \texttt{B\_MAX\_EC} | 100 kW |
| Battery energy capacity per EC | \texttt{S\_MAX\_EC} | 200 kWh |
| Round-trip efficiency | \texttt{ETA\_MEAN} | 0.95 |
| Efficiency spread | \texttt{ETA\_SIGMA} | 0.0 (all identical) |
| Required sustain duration | \texttt{T\_SUSTAIN} | 0.5 h |
| Minimum bid size | \texttt{P\_MIN} | 100 kW |
| Initial / terminal SOC fraction | \texttt{SOC\_INIT\_FRAC} | 0.5 |
| b-type probability | \texttt{P\_B\_CHANCE} | 0.60 |
| s-type probability | \texttt{P\_S\_CHANCE} | 0.40 |
| Scale factor mean $\mu$ | \texttt{SCALE\_MU} | 1.0 |
| Scale factor std $\sigma$ | \texttt{SCALE\_SIGMA} | 1.0 |
| Random seed | \texttt{rng} | 42 (\texttt{np.random.default\_rng(42)}) |

### Sampling procedure (cell 5)

```python
rng = np.random.default_rng(42)
for i in range(N_ECS):
    base = 'b' if rng.random() < P_B_CHANCE else 's'
    scale = -1.0
    while scale <= 0:               # truncated normal: re-draw until positive
        scale = float(rng.normal(SCALE_MU, SCALE_SIGMA))
    eta_e = ETA_MEAN                # ETA_SIGMA == 0, no spread
    EC_LIST.append({'id': f'ec{i:02d}', 'base': base,
                    'scale': scale, 'b_max': B_MAX_EC,
                    's_max': S_MAX_EC, 'eta': eta_e})
```

The scale factor is applied multiplicatively to both the consumption and PV production
curves of the assigned base type (\texttt{base = 'b'} or \texttt{'s'}).  All ECs have
identical hardware parameters; the only EC-level variation is the profile type and
scale factor.

Aggregated portfolio: $10 \times 100\,\text{kW} = 1{,}000\,\text{kW}$ /
$10 \times 200\,\text{kWh} = 2{,}000\,\text{kWh}$.

The seed-42 draw with the above parameters produces 6 b-type and 4 s-type ECs
(consistent with $P_b = 0.6$).  Scale factors: min $\approx 0.03$,
mean $\approx 1.0$, max $\approx 2.2$ (exact values vary with the NumPy version).

**Cross-check with thesis Table~2:** The table lists the same hardware parameters.
The random seed (42) is not stated in the thesis text but is hard-coded in cell 5.

---

## A.6 Final Dataset Assembly

### Step 1: \texttt{0\_process\_spot\_ec.ipynb}

Produces \texttt{data\_out/combined\_2025.csv} (17,520 rows): columns
\texttt{timestamp, ec\_id, consumption, pv\_production\_kwh,
spot\_exkl\_vat\_ore\_kwh, buy\_price\_inkl\_vat\_ore\_kwh,
sell\_price\_inkl\_vat\_ore\_kwh} plus weather columns.

### Step 2: intermediate merge (TODO -- missing script)

An undocumented step adds FCR-D/FCR-N reservation price columns and renames/reshapes
the timestamp column to \texttt{hour\_utc} (timezone-aware UTC), producing
\texttt{combined\_2025\_clean.csv}.  The \texttt{2\_combine\_hourly\_2025.py} script
expects this file at its default input path.

### Step 3: \texttt{1\_process\_frequency.py --full}

Produces \texttt{frequency\_activation\_factors\_2025.csv} (8,760 rows).

### Step 4: \texttt{2\_combine\_hourly\_2025.py}

Left-joins the frequency file onto \texttt{combined\_2025\_clean.csv} on the
UTC clock hour (\texttt{validate="many\_to\_one"} -- two EC rows per hour each
receive the same frequency value).  Output:
\texttt{combined\_2025\_with\_frequency.csv} (17,520 rows).
Columns: all 34 fields including \texttt{hour\_utc}, \texttt{ec\_id},
\texttt{consumption}, \texttt{pv\_production\_kwh}, spot and tariff prices,
FCR-D/FCR-N prices, weather variables, \texttt{freq\_avg\_hz},
\texttt{y\_act\_fcrd\_up}, \texttt{y\_act\_fcrd\_down}, \texttt{y\_act\_fcrn\_up},
\texttt{y\_act\_fcrn\_down}, \texttt{data\_quality\_flag}.

### Step 5: \texttt{3\_check\_combined\_frequency.ipynb}

Validation notebook: loads \texttt{combined\_2025\_with\_frequency.csv}, plots
frequency and activation fractions for a sample week, confirms alignment.

---

## A.7 Weather Data (Downloaded but Not Used)

| Field | Value |
|-------|-------|
| Provider | Open-Meteo |
| Actual API | \texttt{https://archive-api.open-meteo.com/v1/archive} |
| Forecast API | \texttt{https://historical-forecast-api.open-meteo.com/v1/forecast} |
| Location | 55.676°N, 12.568°E (Copenhagen / DK2) |
| Period | 2025-01-01 to 2026-01-01 |
| Variables | \texttt{temperature\_2m} (°C), \texttt{shortwave\_radiation} (W/m²), \texttt{wind\_speed\_10m} (km/h), \texttt{relative\_humidity\_2m} (\%), \texttt{precipitation} (mm) |
| Rows | 8,784 (includes hourly DST handling by Open-Meteo UTC output) |

Processing in \texttt{0\_process\_spot\_ec.ipynb} (cell \texttt{fb0f9148}) via
\texttt{helpers.\_fetch\_open\_meteo()} and \texttt{helpers.\_build\_weather\_df()}.
Output files: \texttt{data\_out/weather\_data\_2025\_historical.csv} (actuals) and
\texttt{data\_out/weather\_actuals\_vs\_forecasts\_2025.csv} (merged actuals + forecasts,
8,784 rows).  Both files are merged into \texttt{combined\_2025.csv} and hence into the
final dataset, but no weather variable is referenced by any constraint or objective in
\texttt{01\_Back\_test.ipynb} or \texttt{02\_Sensitivity.ipynb}.
