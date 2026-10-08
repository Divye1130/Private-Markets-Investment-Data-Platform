# Databricks runbook

1. Create or use an accessible catalog/schema and a volume for input files.
2. Run the local generator once and upload `data/raw/*.csv` plus `data/documents/*.pdf` to the workspace volume.
3. Import the files under `databricks/notebooks/` and follow the numeric run order.
4. Confirm Bronze row counts against `reports/run_summary.json`.
5. Complete/extend the Silver quality notebook for all entities, then compare quarantined counts with the local reference run.
6. Run the Data Vault SQL and verify that 18 synthetic NAV restatements remain in the historical satellite for the default dataset.
7. Run the Kimball/semantic SQL and reconcile fund counts, fund-performance logic and review queues.
8. Only after successful live execution should the CV wording be upgraded from “Databricks-ready implementation” to “implemented on Databricks”.

The repository intentionally separates **verified local execution evidence** from **cloud deployment assets** so portfolio claims stay defensible.
