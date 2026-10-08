# Databricks deployment path

The verified reference build in this repository runs locally with Python/pandas/SQLite so it can be tested without cloud credentials. The files in `databricks/notebooks/` mirror the same architecture for Databricks and are intended to be imported into a Databricks workspace.

Suggested run order:

1. `00_setup.sql`
2. Upload generated CSV/PDF inputs to a Unity Catalog volume or workspace-accessible storage path.
3. `01_bronze_ingestion.py`
4. `02_silver_quality.py`
5. `03_data_vault.sql`
6. `04_gold_kimball.sql`
7. `05_document_intelligence.py`
8. `06_semantic_queries.sql`

The Databricks implementation uses Delta tables and PySpark patterns. It was source-reviewed and Python-syntax checked in the build environment, but it was **not executed against a live Databricks workspace** because no workspace or credentials were available. Do not describe it as a deployed Databricks solution until the notebooks have been run successfully in your own workspace.
