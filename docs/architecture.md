# Architecture

```text
Synthetic fund-admin CSVs + generated capital-call PDFs
                         |
                         v
                    BRONZE / RAW
     immutable source rows + ingestion metadata
                         |
              validation / profiling
                         |
             +-----------+-----------+
             |                       |
             v                       v
          SILVER                 QUARANTINE
  standardised valid data     rejected rows + reason
             |
             +---------------------------+
             |                           |
             v                           v
       DATA VAULT 2.0               DOCUMENT CONTROL
 hubs / links / satellites       PDF -> typed fields ->
 restatement history retained    ledger reconciliation
             |                           |
             +-------------+-------------+
                           v
                       GOLD / KIMBALL
           dimensions + transaction/snapshot facts
                           |
              semantic / analytical marts
                           |
          GitHub Pages dashboard + review queues
```

## Why both Data Vault and Kimball?

The raw-vault layer prioritises auditability and change history. In particular, NAV restatements are retained rather than overwritten. The Gold layer prioritises consumption: simple dimensions and facts support reporting, reconciliation and fund-performance metrics.

## Local vs Databricks implementation

The verified reference path runs with Python, pandas and SQLite. The `databricks/` folder contains equivalent Delta/PySpark/Databricks SQL assets so the same design can be moved to a live lakehouse. Those assets were not executed in the build environment because no Databricks workspace or credentials were available.
