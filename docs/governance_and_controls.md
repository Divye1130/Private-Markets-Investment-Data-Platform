# Governance and control design

## Data-quality gates

The local pipeline checks uniqueness, referential integrity, valid currency domains, fund/base-currency consistency, positive monetary values, supported FX rates and accepted transaction types. Invalid rows are not silently corrected: they are routed to entity-specific quarantine files with an explicit reason.

## Historical corrections

NAV restatements are deliberately generated. The Silver layer keeps the versioned records, the Data Vault satellite preserves the history, and the Gold NAV fact selects the latest valid version for a fund/date. This separates audit history from consumption semantics.

## Reconciliation

Two independent reconciliations are produced:

1. **Position-to-NAV**: compares the sum of latest fund positions with the latest fund NAV and places material breaks in a review queue.
2. **Capital-call document-to-ledger**: extracts typed fields from generated PDF notices and checks the referenced ledger cashflow, fund, investor, currency and amount.

## Document intelligence

The verified local build uses deterministic PDF text extraction because the source notices are synthetic and structured. A Databricks Model Serving adapter seam is included for a future LLM extraction step. Any model output must still pass deterministic schema/master-data/reconciliation controls before acceptance.

## Responsible use

All source records, documents, institutions and financial values in this repository are synthetic. Nothing should be interpreted as investment advice, audited fund performance or a production control framework.


## Portfolio currency control
Cross-fund monetary aggregation is performed only after joining the validated synthetic FX-rate table. Fund-level investment ratios are left in each fund's base currency, avoiding accidental addition of unlike currencies.
