# Databricks notebook source
from pyspark.sql import functions as F

CATALOG = "main"
SCHEMA = "private_markets"
BASE = f"/Volumes/{CATALOG}/{SCHEMA}/raw_inputs"

TABLES = ["funds", "investors", "assets", "fx_rates", "commitments", "cashflows", "nav", "positions", "document_manifest"]

for name in TABLES:
    df = (
        spark.read.option("header", True).option("inferSchema", True).csv(f"{BASE}/{name}.csv")
        .withColumn("_source_file", F.input_file_name())
        .withColumn("_ingested_at", F.current_timestamp())
    )
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_{name}")
    )
