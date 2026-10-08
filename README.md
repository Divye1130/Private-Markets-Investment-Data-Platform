Link to live dashboard -- https://divye1130.github.io/Private-Markets-Investment-Data-Platform/

# Private Markets Investment Data Lakehouse & Document Intelligence Platform

A portfolio-grade data-engineering project modelling how fragmented private-markets data can be ingested, quality-controlled, historised, transformed into trusted investment marts, and reconciled against capital-call documents.

**Core themes:** Python, SQL, private-markets data, Bronze/Silver/Gold architecture, Data Vault 2.0, Kimball modelling, data quality, reconciliation, document extraction, Databricks/PySpark deployment assets, CI and a GitHub Pages dashboard.

## Run output

- **24 funds**, **180 investors** and **240 underlying assets**.
- **793 raw commitments**, **4,592 raw cashflow rows**, **438 raw NAV records** and **279 raw positions**.
- **63 deliberately invalid rows quarantined**, including duplicates, invalid currencies, orphan keys, and invalid values.
- **18 NAV restatements retained** in the Data Vault historical satellite rather than overwritten.
- **4,547 valid cashflows** and **272 valid positions** in the Gold analytical model.
- **60 synthetic capital-call PDFs parsed**, with all 60 passing the typed extraction schema.
- **52 document-to-ledger matches** and **8 deliberately created mismatches** correctly routed to review.
- **18/24 funds** pass position-to-NAV reconciliation after quality filtering; **6** enter a review queue.
- **37/37 automated tests pass**.

The synthetic portfolio has a median TVPI of **1.089x**, median DPI of **0.620x**, and median computed fund-level XIRR of approximately **6.4%** in the generated demo data. Fund-level ratios remain in each fund's base currency, while portfolio monetary totals and exposure charts use an explicit synthetic FX layer to normalise GBP, USD and EUR values to GBP for comparability.

## Architecture

```text
Fund-admin CSVs + capital-call PDFs
               |
               v
            BRONZE
 immutable raw + load metadata
               |
       quality / validation
        /             \
       v               v
    SILVER         QUARANTINE
       |               |
       v               |
 DATA VAULT 2.0        |
 hubs/links/sats        |
 historical NAV        |
       |                |
       +-------+--------+
               v
         GOLD / KIMBALL
 dimensions + facts + latest valid NAV
               |
     +---------+-----------+
     |                     |
     v                     v
fund KPI / exposure   document + NAV
semantic marts        reconciliation
     |                     |
     +----------+----------+
                v
       GitHub Pages dashboard
```

See `docs/architecture.md` for the design rationale.

## Data model

### Data Vault 2.0 layer

**Hubs:** Fund, Investor, Asset  
**Links:** Fund-Investor, Fund-Asset  
**Satellites:** Fund attributes and versioned NAV history

The vault's purpose is historical traceability: an NAV restatement becomes another satellite record rather than replacing the earlier reported value.

### Kimball Gold layer

**Dimensions:** Fund, Investor, Asset, Date  
**Facts:** Cashflow, Commitment, Position, NAV

Gold marts calculate DPI, RVPI, TVPI, unfunded commitments, sector/region exposure, NAV reconciliation and document review queues.

## Document intelligence

The generator creates 60 synthetic capital-call PDFs. The verified local parser uses `pypdf` to extract typed fields:

- fund/investor IDs;
- notice and due dates;
- currency;
- call amount;
- ledger reference.

The extracted record is reconciled to the referenced contribution cashflow. Eight notices are deliberately generated with amount mismatches, and the control layer routes them to review.

A `DatabricksModelServingExtractor` seam plus a Databricks notebook show where an approved LLM/Mosaic AI extraction endpoint can be inserted. The model step is **optional and unexecuted** here; deterministic validation remains mandatory after any model output.

## Databricks path

`databricks/notebooks/` contains a mirror implementation using Databricks SQL/PySpark patterns:

1. setup / Unity Catalog volume;
2. Bronze CSV ingestion to Delta;
3. Silver quality controls and quarantine;
4. Data Vault 2.0 hubs/links/satellites;
5. Kimball/semantic marts;
6. optional model-serving seam for documents.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python scripts/run_pipeline.py
python scripts/build_dashboard.py
pytest -q
```

Or:

```bash
make run
make test
```

## Repository layout

```text
src/                 data generation, controls, vault/gold build, PDF extraction
scripts/             reproducible local run + dashboard build
tests/               automated data-model/control tests
sql/                 modelling and control design SQL
databricks/          PySpark / Databricks SQL deployment path
data/                 reproducibly generated raw/processed/quarantine/documents
docs/                 architecture, runbook and GitHub Pages dashboard
reports/              run summary and analytical/reconciliation outputs
warehouse/            generated SQLite reference warehouse
.github/workflows/    CI and Pages deployment
```


## Limitations

- All data is synthetic.
- Portfolio-level monetary totals and exposure charts use deterministic synthetic FX rates to normalise GBP, USD and EUR to GBP; the rates are demonstration inputs rather than market data.
- The local reference implementation uses pandas/SQLite rather than a distributed engine.
- Databricks, Delta and model-serving assets were not live-executed in this environment.
- The Data Vault implementation is intentionally compact and educational; a production vault would usually include effectivity/record-source conventions, more satellites and incremental loading strategy.
- Fund-level XIRR is calculated from each fund's generated base-currency cashflows plus terminal NAV. It is a synthetic engineering demonstrationonly.  
