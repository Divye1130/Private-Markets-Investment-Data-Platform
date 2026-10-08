# Data dictionary

## Core business entities

| Entity | Business key | Purpose |
|---|---|---|
| Fund | `fund_id` | Private-markets investment vehicle |
| Investor | `investor_id` | Institution committing capital to funds |
| Asset | `asset_id` | Underlying portfolio company / debt / real asset |
| Commitment | `commitment_id` | Investor commitment to a fund |
| Cashflow | `cashflow_id` | Contribution or distribution between investor and fund |
| NAV | `nav_record_id` | Fund valuation snapshot; restatements have higher versions |
| Position | `position_id` | Fund holding in an underlying asset at a point in time |
| Capital-call document | `document_id` | Synthetic PDF notice linked to a contribution cashflow |

## Fund-performance metrics

- **DPI** = distributions / paid-in capital.
- **RVPI** = latest NAV / paid-in capital.
- **TVPI** = (distributions + latest NAV) / paid-in capital.
- **Unfunded commitment** = total commitment - paid-in capital, floored at zero.

These are synthetic portfolio demonstration metrics. Fund-level ratios are calculated within each fund's base currency. Cross-fund monetary totals and exposure marts use the generated `fx_rates` table (`gbp_per_unit`) to normalise GBP, USD and EUR values to GBP. Those FX rates are deterministic synthetic inputs, not market data.
