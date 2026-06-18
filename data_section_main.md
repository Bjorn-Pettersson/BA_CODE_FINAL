# Data

The model is calibrated and back-tested on five categories of hourly time-series data for the DK2
bidding zone, covering the full calendar year 2025.  All inputs are aligned to UTC and
presented to the optimiser at hourly resolution.  Table~\ref{tab:datasets} summarises the
sources; the following subsections describe each in turn.

## Frequency Measurements

System-frequency measurements for the Nordic synchronous area (Finland, Sweden, Norway, and DK2
share a single synchronous grid) were obtained from the Fingrid open-data
portal~\cite{fingrid339}.  The raw data consist of instantaneous frequency readings sampled at
\textbf{10 Hz} (one value every 0.1 s), yielding approximately 864,000 observations per day.
Data are stored as one CSV file per day, organised in monthly subfolders, covering
all 365 days of 2025.

From these sub-second recordings the script \texttt{1\_process\_frequency.py} derives four
hourly \emph{activation fractions} -- for FCR-D up and down and FCR-N up and down -- following
the proportional piecewise-linear activation function of Crowley et al.\ (2025):

\begin{align}
y_t^{\mathrm{actFCRD}\uparrow} &= \frac{1}{n_t}\sum_{\tau\in t}
  \begin{cases}1 & f_\tau < 49.5\text{ Hz}\\
  \frac{49.9-f_\tau}{0.4} & 49.5\le f_\tau\le 49.9\text{ Hz}\\
  0 & f_\tau > 49.9\text{ Hz}\end{cases}
\end{align}

and analogously for FCR-D down (activating above 50.1 Hz, saturating at 50.5 Hz) and FCR-N
(dead-band $\pm$0.1 Hz).  The hourly value is the \emph{mean activation factor} across all
$n_t \approx 36{,}000$ readings within hour $t$.  A data-quality flag is set for any hour with
fewer than 18,000 readings; 15 flagged hours are excluded from model runs.

**Note:** the thesis notation in Eq.~(2.1.4) presents the simpler threshold-counting form
($\#\{\tau: f_\tau < 49.9\}/\#\{\tau\}$); the code implements the proportional Crowley formula.
In practice the two differ only when the frequency lies in the partial-activation band
(49.5--49.9 Hz / 50.1--50.5 Hz), which is infrequent, so the numerical impact is small.

The hourly activation fractions entering the model as $y_t^{\mathrm{actFCRD}\uparrow}$ and
$y_t^{\mathrm{actFCRD}\downarrow}$ have annual means of $2.7\times10^{-4}$ and
$2.4\times10^{-4}$, respectively, confirming that full-activation hours are rare.

## Spot Prices

Day-ahead electricity prices for DK2 were obtained from the Energidataservice
API~\cite{energidataservice_spot,energidataservice_dap}.  During 2025 the API migrated from
an hourly product (\texttt{Elspotprices}, covering January--September in \texttt{SpotPriceDKK}
in DKK/MWh) to a 15-minute product (\texttt{DayAheadPrices}, covering October--December in
\texttt{DayAheadPriceDKK} in DKK/MWh).  The two series are merged in
\texttt{0\_process\_spot\_ec.ipynb}: the 15-minute prices are averaged within each clock hour,
the hourly \texttt{Elspotprices} series takes priority for any overlap, and the single missing
terminal hour (2025-12-31 23:00 UTC) is forward-filled, yielding exactly 8,760 hourly
observations.  Prices are converted from DKK/MWh to \o{}re/kWh (divide by 10) for all
downstream calculations.

## Consumer and Producer Tariffs

The consumer buy-price and prosumer sell-price are derived from the spot price by applying
Danish network tariffs and state fees.  Tariffs are sourced from the Radius DSO (2026 schedule,
applicable to the Copenhagen/DK2 area) and held fixed across the year.  The buy price is:

\[
  \lambda_t^{\mathrm{im}} = \bigl(\lambda_t^{\mathrm{spot}} +
  \tau_t^{\mathrm{DSO}} + 5.80 + 5.40 + 0.80\bigr)\times 1.25
\]

where $\lambda^{\mathrm{spot}}$ is the spot price in \o{}re/kWh (excl.\ VAT),
$\tau_t^{\mathrm{DSO}}$ is the time-of-use DSO tariff, the fixed terms are the transmission
tariff (5.80), system fee (5.40), and electricity duty \emph{elafgift} (0.80) all in
\o{}re/kWh excl.\ VAT, and 1.25 is the VAT multiplier.  The peak DSO tariff is
87.88~\o{}re/kWh (winter peak, 17:00--21:00), creating a strong evening buy-price premium.
The sell price is $\lambda_t^{\mathrm{ex}} = \lambda_t^{\mathrm{spot}} - 0.59$
(\o{}re/kWh incl.\ VAT), where 0.59 is the statutory feed-in handling fee; the sell price
can therefore become negative during hours of very low or negative spot prices.

## Energy Community Profiles

Per-meter smart-meter data for two real Danish energy communities were provided by Enyday.com.
The raw data are cumulative energy register reads (\texttt{Serial}, \texttt{reading\_time},
\texttt{Consumption} in kWh) with irregular sub-hourly observations.

\textbf{b-type community} (\texttt{b\_data.csv}): 56 load meters and one solar-PV production
meter (identified by \texttt{Serial}$=-1$), covering a large multi-unit residential block with
relatively flat, high daytime consumption and moderate solar production.

\textbf{s-type community} (\texttt{s\_data.csv}): 62 load meters and one PV production meter
(\texttt{Serial}$=-2$), representing a setup with stronger solar PV relative to base load, with
a more pronounced midday production peak.  Both communities exhibit the characteristic daily
profile visible in Figure~1: morning and evening consumption peaks, solar noon production peak
(April--September), and near-zero production in winter.

Missing meter readings are filled by linear interpolation on the cumulative register (3,299
corrected values for b-type, 4,123 for s-type out of 8,760 hourly observations per meter).
Hourly consumption is obtained by differencing the interpolated cumulative series; the PV
production meter is treated analogously.

## FCR-D Reservation Prices

Hourly day-ahead clearing prices for FCR-D Up, FCR-D Down, and FCR-N -- separately for the
early (GCT D-1 00:30) and late (GCT D-1 18:00) auctions -- are sourced from the
Energidataservice \texttt{FcrNdDK2} dataset~\cite{energidataservice_fcr}.  The raw prices
are in EUR/MW/h and converted to \o{}re/kWh using a fixed EUR/DKK rate of 7.46
(i.e.\ multiplied by 0.746); see Appendix~A.4.  The mean early-clearing FCR-D Up price for
2025 is 4.38~\o{}re/kWh; FCR-D Down averages 3.67~\o{}re/kWh early and 6.10~\o{}re/kWh
late, with occasional extreme spikes in the late market (max 2,007~\o{}re/kWh).  The
buy-back price entering the late-auction objective is
$\max(\lambda_t^{\mathrm{FCRD}\uparrow\mathrm{early}},\,\lambda_t^{\mathrm{FCRD}\uparrow\mathrm{late}})$
per hour, computed in \texttt{build\_late()} in \texttt{01\_Back\_test.ipynb}.

## Synthetic Portfolio

The optimisation is evaluated on a synthetic portfolio of $N=10$ energy communities whose
load and PV curves are scaled versions of the two empirical profiles.  Each simulated EC is
assigned type b with probability $P_b=0.60$ and type s with probability $P_s=0.40$, with
a scale factor $X\sim\mathcal{N}(\mu=1,\,\sigma=1)$ truncated to positive values (re-drawn
until $X>0$).  Battery parameters are identical across ECs: $\bar{b}_e=100$\,kW,
$\bar{S}_e=200$\,kWh, $\eta_e=0.95$, with initial and terminal SOC fixed at 50\%.  The
minimum bid size is $p^{\min}=100$\,kW and the required sustain duration is
$T_{\mathrm{sustain}}=0.5$\,h.  The aggregated portfolio therefore presents up to
1,000\,kW / 2,000\,kWh to the FCR-D market.  Construction uses \texttt{numpy} random seed
42 (\texttt{np.random.default\_rng(42)}).

## Weather Data

Hourly weather actuals and historical forecasts (temperature, shortwave radiation, wind speed,
humidity, precipitation) for Copenhagen (55.676°N, 12.568°E) were retrieved from the
Open-Meteo archive API for the full year 2025.  These data are present in the combined
dataset but are \textbf{not consumed by the MILP model} in any of the reported experiments;
they were obtained for potential use in load and PV forecasting modules.

---

\begin{table}[ht]
\centering
\caption{Dataset summary}
\label{tab:datasets}
\begin{tabular}{lllll}
\hline
\textbf{Dataset} & \textbf{Source} & \textbf{Native resolution} & \textbf{Coverage} & \textbf{Model variable(s)} \\
\hline
Nordic frequency & Fingrid API (id 339) & 0.1 s & Full year 2025 & $y_t^{\mathrm{actFCRD}\uparrow}$, $y_t^{\mathrm{actFCRD}\downarrow}$ \\
Spot prices (hourly) & Energidataservice \texttt{Elspotprices} & 1 h & Jan--Sep 2025 & $\lambda_t^{\mathrm{spot}}$ \\
Spot prices (15-min) & Energidataservice \texttt{DayAheadPrices} & 15 min & Oct--Dec 2025 & $\lambda_t^{\mathrm{spot}}$ \\
EC load + PV (b-type) & Enyday.com (smart meters) & Irregular cumul.\ & Full year 2025 & $D_{e,t}$, $\mathrm{PV}_{e,t}$ \\
EC load + PV (s-type) & Enyday.com (smart meters) & Irregular cumul.\ & Full year 2025 & $D_{e,t}$, $\mathrm{PV}_{e,t}$ \\
FCR-D/FCR-N prices & Energidataservice \texttt{FcrNdDK2} & 1 h & Full year 2025 & $\lambda_t^{\mathrm{FCRD}\uparrow}$, $\lambda_t^{\mathrm{FCRD}\downarrow}$ \\
Weather & Open-Meteo archive API & 1 h & Full year 2025 & (unused) \\
\hline
\end{tabular}
\end{table}
