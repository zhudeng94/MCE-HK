# Data records and variable dictionary

Main records are UTF-8 CSVs with comma delimiters and a header row. Dates use ISO 8601.
Missing numeric fields are empty, never implicit zero. Emissions are combustion CO₂ estimates;
1 ktCO₂ = 1,000 tonnes CO₂; 1 MtCO₂ = 1,000 ktCO₂. All principal estimates are labelled `Modelled estimate`.

## `outputs/uncertainty/sector_monthly_uncertainty.csv`

Unique key: (`date`, `sector`), with the same rows, point estimates and missingness as the main sector table.
These are **central 95% model-based uncertainty intervals**, conditional on configured input distributions
and structural priors. Frequentist coverage has not been empirically calibrated.
Methods and alternatives are defined in [the uncertainty report](../outputs/uncertainty/report.md).

| Column | Meaning |
|---|---|
| date, sector, ktCO2, method, estimate_label, as_of | Copied from the main sector table |
| lower_95_ktCO2, upper_95_ktCO2 | Simulated 2.5th and 97.5th percentiles |
| median_ktCO2, mean_ktCO2, std_ktCO2 | Simulated median, mean and sample standard deviation; separate from published point |
| lower_deviation_pct, upper_deviation_pct | Signed 100 × (bound / point − 1); point is not forcibly included or centered |
| relative_half_width_95_pct | 100 × (upper − lower) / (2 × point); not a symmetric interval about the point |
| mc_endpoint_change_pct | Maximum endpoint difference between independent halves of draws, as percent of point |
| coverage_probability | 0.95, conditional model probability, not demonstrated frequentist coverage |
| draws | Number of Monte Carlo draws; zero for missing months |
| status | model_based_95pct_interval or no_estimate |
| interval_interpretation | Explicit conditional interpretation |

Relative metrics are blank when the point estimate is zero or missing. Bounds remain blank for missing months.
`latest_common_month.csv` extracts the latest month with all eight point estimates.
`sector_summary.csv` has unique key `sector` and reports coverage and median/maximum monthly
relative half-widths. These summaries are not uncertainties of annual sums.
`input_parameters.csv` lists distribution bounds, units and whether the basis is a reference or an assumption.
`scenario_probabilities.csv` lists structural prior weights and sampled counts; named choices need not
produce distinct values in every month. `checks.csv` records reconstruction and numerical convergence.
Industry has one probability-one production method and a single shared 2021 CO2/TJ coefficient.
Annual non-electric fuel activity errors are propagated as target/base-year ratios; the 2021
calibration error is shared across months. Extrapolation drift applies after 2024. The older industrial endpoint
and calendar alternatives remain sensitivity diagnostics only.
`manifest.json` includes the entire uncertainty configuration, provenance hashes and package versions.
Original scenario envelopes and their old fields remain separately in `scenario_sensitivity/`;
they are not Monte Carlo samples or probabilistic bounds.

`total_monthly_uncertainty.csv` has key (`date`, `scope`), and `total_annual_uncertainty.csv`
has key (`year`, `scope`). Both retain published totals and missingness. Annual rows include
`months` and `full_year`; partial years are not annualized. `sector_annual_uncertainty.csv`
uses key (`year`, `sector`) and each sector's own available months.
`annual_change_uncertainty.csv` has key (`year`, `scope`); its `ktCO2` and interval columns
refer to the net change from the previous year's identical `compared_months`.
All aggregate intervals use aligned Monte Carlo draws, summed (and for changes, differenced)
before quantiles are taken. They are not sums or differences of marginal interval endpoints.
These tables contain `lower_95_ktCO2`, `median_ktCO2`, `upper_95_ktCO2`, and `coverage_probability`.
Main monthly figures shade the intervals; annual net-change figures use capped interval bars.

`outputs/official_inventory_comparison/annual_total_comparison.csv` retains all available
local model years, including years beyond official coverage and partial years. Key: `year`.
Emissions and bounds are in ktCO2 (official columns in ktCO2e); `months`, `full_year`,
`first_month`, `last_month` describe model coverage. Climate TRACE is the existing total
excluding forestry and international aviation/shipping; it still includes additional sources.
`climate_trace_months` counts available observations within the exact model months, and the
TRACE total is blank unless all those months are available. Official annual values remain
blank beyond source coverage and for partial model years. The figure plots complete-year
curves and a separate latest partial-year panel, without annualization. Inputs and script hash
are recorded in `annual_total_comparison_manifest.json`.

## `outputs/hong_kong_sector_monthly.csv`

Unique key: (`date`, `sector`). 2,112 rows = 264 indexed months × 8 sectors, including missing estimates.

| Column | Meaning |
|---|---|
| date | First day of the represented calendar month; 2005-01 through 2026-12 index |
| sector | Industry, Power, Road Transport, Domestic Navigation, Residential, Commercial, International Aviation, International Shipping |
| ktCO2 | Estimated monthly CO₂ in kilotonnes; blank when unavailable |
| method | Selected method identifier or description; early reconstruction is separately labelled |
| estimate_label | Modelled estimate; input observations do not make the final estimates measured emissions |
| as_of | Configured recent-observation cutoff, not the retrieval date of every historical source |
| activity_method | Underlying activity/allocation method before official-baseline calibration |
| baseline_year | Common baseline year, 2021; 2005 and 2020 are validation years |
| calibration_scale | Fixed new scale applied to the prior sector model; 1 for already calibrated Industry/Road Transport/Domestic Navigation |

Industry covers fuel combustion in manufacturing/construction, not industrial processes.
Road Transport includes road plus residual transport; Domestic Navigation is CRT 1.A.3.d. Together they preserve full 1.A.3.
Road coverage starts in 2005; navigation starts in 2008; both extend through 2026-08. Values after 2024 use fixed marine intensity extrapolation, explicitly identified in `method`.
Road-only input is `outputs/diagnostics/road_monthly_proxy.csv` and must not be added to totals separately. International Aviation and International Shipping represent fuel supplied in Hong Kong,
not emissions geographically released in Hong Kong.

## `outputs/hong_kong_total_monthly.csv`

Unique key: (`date`, `scope`). 528 rows = 264 months × 2 scopes.

| Column | Meaning |
|---|---|
| date | First day of calendar month |
| scope | Aggregation boundary defined below |
| ktCO2 | Sum only when every required sector is available; otherwise blank |
| available_sectors | Number of nonmissing sector estimates in that scope/month |
| required_sectors | 6 for local scope, 8 for scope including international bunkers |
| complete | Boolean: all required sectors available |
| estimate_label | Modelled estimate |
| as_of | Configured recent-observation cutoff |
| yoy_pct | `(current month / same month last year - 1) × 100`; blank without comparable data |

`covered_local_sectors`: Power + Industry + Road Transport + Domestic Navigation + Residential + Commercial.
`covered_sectors_plus_international_bunkers`: those six + International Aviation + International Shipping.
Neither scope is a complete territorial inventory: town-gas manufacture, industrial processes and other omitted sources are not included.

## `outputs/hong_kong_total_annual.csv`

Unique key: (`year`, `scope`). 44 rows = 22 years × 2 scopes.

| Column | Meaning |
|---|---|
| year | Calendar year |
| scope | Same scope definitions as monthly totals |
| ktCO2 | Sum of complete months only; blank if no valid month |
| months | Number of complete months used |
| full_year | True only if all 12 months are included |
| first_month, last_month | First and last included month (not a guarantee of no internal gaps) |
| yoy_same_months_pct | Change against the identical months of the preceding year; blank if unavailable |

For this method version, both totals cover 2008-01 through 2026-06. In 2005–2007,
transport has no annual marine benchmark: totals are missing, annual `months=0`, `full_year=false`.
2025 is a complete year; 2026 totals contain January–June only. Transport itself extends through July,
but power and international bunker coverage limit aggregate availability. Annual comparisons use identical
months in the prior year, without annualizing. The original row grids are retained.

Transport extension records: `monthly_transport_proxy.csv` has `extrapolated` (boolean),
`extrapolation_reference_year` (2024 for extrapolated rows), `status` and allocation labels.
The annual benchmark table `annual_transport_proxy.csv` intentionally stops at 2024.
`annual_transport_monthly_summary.csv` contains all available monthly estimates aggregated by year,
with `months`, `full_year`, `extrapolated_months`, `first_month`, `last_month` and `yoy_same_months_pct`.
Transport's 2026 summary is January–July and must not be mixed with January–June total summaries.

## Supporting records

| Location | Purpose |
|---|---|
| `outputs/diagnostics/industry_proxy_calibration.csv` | CRT anchors in ktCO₂; gas/electricity activity in TJ; coefficients in ktCO₂ per proxy TJ |
| `outputs/diagnostics/industry_proxy_components.csv` | Monthly industrial components, proxy TJ, coefficients, anchor years and interpolation status |
| `outputs/diagnostics/historical_coverage.csv` | Nonmissing start/end/count by sector |
| `outputs/diagnostics/consistency_checks.csv` | Model conservation and benchmark checks, not independent validation |
| `outputs/diagnostics/*scenarios.csv` | Component/road model alternatives; Road is road-only, not the published Transport. Ranges are not confidence intervals |
| `outputs/diagnostics/road_monthly_proxy.csv` | Uncalibrated road-only input; unique date, ktCO2, sector=Road, method, role |
| `outputs/transport_extension/` | Adopted full-transport annual/monthly components and explicit allocation sensitivity; see monthly_report.md |
| `outputs/diagnostics/data_gaps.csv` | Gaps recorded during estimation |
| `data/processed/` | Regenerable normalized activity and benchmark tables; source-specific units retained in the columns |
| `outputs/provenance/` | Config, dependency versions, selected methods, source cells and checksums |
| `outputs/*_comparison/` | Supporting comparisons; heed CO₂/CO₂e and inventory-boundary differences in each report |

The dictionary covers all main release variables. Before publishing additional processed or diagnostic tables as independent data records,
add a complete variable-level dictionary for those tables as well.

## Website power-system indicators

The website exporter creates additional download records. These are supporting
indicators and do not change the production emission estimates.

### `local/web/public/data/power-intensity.csv`

One row per complete year from 2008, matched to the annual electricity balance.

| Column | Definition |
|---|---|
| year | Calendar year; complete power-emission years only |
| power_ktCO2 | Hong Kong Carbon Atlas annual Power combustion CO₂ estimate, ktCO₂ |
| local_generation_TWh | C&SD gross local electricity generation; original TJ divided by 3,600 |
| intensity_gCO2_per_kWh | `power_ktCO2 / local_generation_TWh`, in gCO₂/kWh |

The denominator is local **gross generation**, not electricity supplied to end users.
Imports are excluded. The ratio is a model-derived local-generation intensity,
not an official consumer electricity emission factor. No uncertainty interval is
provided for this derived ratio.

### `local/web/public/data/power-fuel-output.csv`

Calculated from the verified raw worksheets of `data/raw/power/HK_power_generation_2010_2025.xlsx`
by `src/cmhk/sources/power_workbook.py`. Common complete years are 2021–2025.
The formula summary sheet is not used; missing formula caches are never treated as zero.

| Column | Definition |
|---|---|
| year | Calendar year |
| gas_GWh | Black Point C+D whole-plant sent-out output + HK Electric gas output, GWh |
| coal_class_GWh | Castle Peak A+B whole-plant sent-out output + HK Electric coal-and-oil output, GWh |
| selected_thermal_total_GWh | Sum of the two selected output categories, GWh |
| gas_share_of_selected_thermal_pct | `100 * gas_GWh / selected_thermal_total_GWh` |
| coal_class_note | Explicit qualification that the coal category includes oil |

CLP plant classification follows the primary fuel and retains auxiliary fuels; output
is not reduced by ownership shares. Imported nuclear, Penny's Bay diesel, other
renewable output and overseas assets are excluded. These categories are not an
exhaustive Hong Kong electricity-supply mix. Sent-out generation is distinct from
the gross generation denominator used for the intensity indicator.

### `local/web/public/data/power-company-output.csv`

One row per company and verified net-output year: CLP 2011–2025 and HK Electric
2021–2025. Missing company years are absent records, not zero generation.

| Column | Definition |
|---|---|
| year | Complete calendar year |
| company | CLP or HK Electric |
| gas_GWh | Whole-plant gas-class net electricity sent out, GWh |
| coal_class_GWh | CLP coal-plant net output or HK Electric combined coal-and-oil output, GWh |
| basis | Net-output basis and coal/oil qualification |
| source_urls | Original source URLs from workbook raw rows, separated by a vertical bar |

CLP 2011–2019 uses Black Point and Castle Peak totals; 2020–2025 sums C+D and A+B.
Negative Castle Peak A net output is preserved before aggregation. CLP's 2010
annual-report generation is not confirmed as net sent out, so it remains only in
the downloadable source workbook. HK Electric fuel input (TJ) is not converted into
output (GWh). H1 and H2 must both be present before HKE annual sums are accepted.
The downloadable `HK_power_generation_2010_2025.xlsx` retains these distinct bases,
missing-data notes and original source links. Its SHA-256 is recorded in snapshot metadata.

## Power-station lifecycle map

`plant-unit-history.csv` contains one record per reviewed unit in the four main
utility thermal stations. It describes asset history, not generation or observed
ON/OFF state. The timeline is limited to 2010–2025; no planned retirements are
substituted for confirmed retirement dates.

| Field | Meaning |
|---|---|
| plant | Station name |
| unit | Unit identifier; Penny's Bay uses PG1–PG3 |
| primary_fuel | `coal`, `gas` (natural gas), or `oil` (including diesel), for this timeline |
| in_2010_baseline | Unit already represented in the 2010 starting inventory |
| verified_commissioning_year | Confirmed year, or blank where an early exact year is unverified; GT57 is the 2002 combined-cycle block, converted to natural gas in 2008 |
| retirement_year | Confirmed lifecycle retirement year; blank means none documented through 2025 |
| reference_location_verified | Whether reference-point identity was checked against engineering plans; not a surveyed coordinate or evidence of operation |
| source_urls | Supporting primary-source URLs separated by ` | ` |

`plant-history.json` also contains source references, image paths and unit marker
positions (`xy`: percent of image width and height from the upper-left corner).
Missing positions remain null. GT1 and GT57 appear in the list only. Aerial images
are fixed reference maps retrieved on 2026-10-14, with unknown capture dates.
The map reports unit counts, not capacity shares; it does not backcast current MW
ratings or infer shutdown from absent satellite plumes.

## Official-baseline diagnostics

`outputs/diagnostics/official_baseline_calibration.csv` has one row per published sector:
`year`, `official_ktCO2`, `proxy_baseline_ktCO2`, dimensionless `scale`, `role`, and source workbook/sheet/cell/SHA-256.
The scale is an activity calibration coefficient, not a physical fuel emission factor.
`sector_monthly_before_baseline_calibration.csv` contains date/sector/ktCO2 from the previous activity model, regenerated from the same inputs.
It is a diagnostic, not the new published estimate; Industry and Transport already include their original CRT calibrations.
`baseline_calibration_comparison.csv` has year/sector (including both total scopes), observed months/full_year,
before/after ktCO2, level_change_pct, before/after_yoy_same_months_pct and yoy_difference_pp.
Partial years use identical observed months on both sides and identical prior-year months for each year-on-year comparison.
Baseline provenance and policy are in `outputs/provenance/point_estimate_manifest.json` and `configs/model.json:official_baseline`.

## Near-real-time fields and diagnostics

The current snapshot extends Power and international bunkers to September 2026 and complete totals to August 2026 (road/navigation coverage limits the total).
Sector `temporal_status` is `statistically_constrained`, `fuel_activity_extrapolation`, `intensity_nowcast`, `activity_nowcast`, `activity_model`, or `no_estimate`.
`activity_model` includes the sector activity estimates and does not mean observed emissions.
`prediction_model` identifies the selected activity window and/or intensity method; `reference_period` identifies the last statistical reference.
`nowcast_log_sigma` is the selection-period RMS log forecast error for a missing quarter, shared across that quarter's months;
`intensity_log_sigma` is the annual power-intensity RMS log error, shared within a year, scaled by square root of horizon.
Total `nowcast_sectors` counts the new activity/intensity nowcasts, not all existing extrapolations; `temporal_status=contains_nowcast` flags a complete total containing them.
Annual `nowcast_months` counts included months containing a new activity/intensity nowcast.

`outputs/near_realtime/quarterly_backtest.csv` stores target/prediction, proxy, reference window, selection/evaluation/monitoring split and last training period.
`quarterly_scores.csv` reports MAPE and signed relative bias as fractions, with identical quarter samples across candidates.
`power_intensity_backtest.csv` compares hold and damped-trend annual predictions; `power_intensity_update.csv` records applied values and company references.
`company_intensity_inputs.csv` records company fuel-output mix indices and fixed company weights; these are proxy intensities, not measured emission factors.
`history/` holds content-addressed monthly snapshots and per-version revision tables; `latest.json` identifies the current snapshot.
Revision tables include old/new estimate and temporal status, delta and percentage; initial method changes are not forecast accuracy observations.

## Transport split (2026-11-16)

`Road Transport` includes road and residual domestic transport. `Domestic Navigation` is CRT 1.A.3.d. Their sum preserves full 1.A.3. The main table contains eight sectors; `Transport` remains an aggregate in comparison diagnostics only.

Industrial `temporal_status`: `annual_fuel_constrained` through 2024, `fuel_activity_extrapolated` thereafter.
