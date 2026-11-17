# MCE-HK monthly emissions

One UTF-8 CSV: [MCE_HK_monthly.csv](MCE_HK_monthly.csv). Emissions are in kt CO₂ (1 kt = 1,000 tonnes).

| Column | Description |
|---|---|
| `date` | Calendar month, YYYYMM. |
| `sector` | Eight sector accounts or `Local_total`. |
| `ktco2` | Monthly combustion CO₂ estimate. |
| `ktco2_lower`, `ktco2_upper` | Lower and upper bounds of the central 95% model interval. |

## Coverage

| Account | First month | Last month | Records |
|---|---|---|---:|
| Commercial | 200501 | 202609 | 261 |
| Domestic Navigation | 200801 | 202608 | 224 |
| Industry | 200501 | 202609 | 261 |
| International Aviation | 200501 | 202609 | 261 |
| International Shipping | 200501 | 202609 | 261 |
| Local_total | 200801 | 202608 | 224 |
| Power | 200501 | 202609 | 261 |
| Residential | 200501 | 202609 | 261 |
| Road Transport | 200501 | 202608 | 260 |

All eight sectors and the local total are available from 200801 to 202608.

`Local_total` sums Power, Industry, Road Transport, Domestic Navigation, Residential and Commercial. International aviation and shipping are separate accounts for fuel supplied in Hong Kong. Road Transport includes the remaining domestic transport categories after subtracting domestic navigation.

Unavailable observations are omitted; an absent row is not zero. Local totals require all six sectors. Their interval bounds are calculated from aligned joint draws and are not sums of sector bounds.

The 95% intervals are conditional on the configured input-error distributions and structural assumptions. Recent observations may use activity nowcasts or extrapolated fuel intensities. The local total covers the included combustion sectors, rather than the complete territorial greenhouse-gas inventory.

The snapshot date, per-account coverage, model-configuration checksums and CSV checksum are recorded in [manifest.json](manifest.json).
