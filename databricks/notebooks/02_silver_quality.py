# Databricks notebook source
from pyspark.sql import Window, functions as F

CATALOG = "main"
SCHEMA = "private_markets"
VALID_CCY = ["GBP", "USD", "EUR"]

def t(name):
    return spark.table(f"{CATALOG}.{SCHEMA}.bronze_{name}")

def rank_duplicate(df, key):
    return df.withColumn("_dup_rank", F.row_number().over(Window.partitionBy(key).orderBy(F.col("_ingested_at"), F.monotonically_increasing_id())))

def write_split(name, df):
    clean = df.filter(F.col("quarantine_reason").isNull()).drop("_dup_rank", "quarantine_reason")
    bad = df.filter(F.col("quarantine_reason").isNotNull()).drop("_dup_rank")
    clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.silver_{name}")
    return bad.withColumn("entity", F.lit(name))

funds = rank_duplicate(t("funds"), "fund_id").withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_fund_id")
     .when(~F.col("base_currency").isin(VALID_CCY), "invalid_base_currency")
     .when(F.col("target_size") <= 0, "non_positive_target_size"),
)
q_funds = write_split("funds", funds)

investors = rank_duplicate(t("investors"), "investor_id").withColumn(
    "quarantine_reason", F.when(F.col("_dup_rank") > 1, "duplicate_investor_id")
)
q_investors = write_split("investors", investors)

assets = rank_duplicate(t("assets"), "asset_id").withColumn(
    "quarantine_reason", F.when(F.col("_dup_rank") > 1, "duplicate_asset_id")
)
q_assets = write_split("assets", assets)

fx = rank_duplicate(t("fx_rates"), "currency").withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_fx_currency")
     .when(~F.col("currency").isin(VALID_CCY), "invalid_currency")
     .when(F.col("gbp_per_unit") <= 0, "non_positive_fx_rate"),
)
q_fx = write_split("fx_rates", fx)

sf = spark.table(f"{CATALOG}.{SCHEMA}.silver_funds").select("fund_id", "base_currency")
si = spark.table(f"{CATALOG}.{SCHEMA}.silver_investors").select("investor_id")
sa = spark.table(f"{CATALOG}.{SCHEMA}.silver_assets").select("asset_id")

commitments = rank_duplicate(t("commitments"), "commitment_id")
commitments = commitments.join(sf.withColumnRenamed("base_currency", "_fund_ccy"), "fund_id", "left").join(si.withColumn("_investor_ok", F.lit(1)), "investor_id", "left")
commitments = commitments.withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_commitment_id")
     .when(F.col("_fund_ccy").isNull(), "orphan_fund")
     .when(F.col("_investor_ok").isNull(), "orphan_investor")
     .when(~F.col("currency").isin(VALID_CCY), "invalid_currency")
     .when(F.col("currency") != F.col("_fund_ccy"), "fund_currency_mismatch")
     .when(F.col("commitment_amount") <= 0, "non_positive_commitment"),
).drop("_fund_ccy", "_investor_ok")
q_commitments = write_split("commitments", commitments)

# Relationship validity uses the source business-key pair. A bad commitment amount does not
# automatically invalidate an otherwise valid cashflow for that fund/investor pair.
source_pairs = t("commitments").select("fund_id", "investor_id").distinct().withColumn("_pair_ok", F.lit(1))
cashflows = rank_duplicate(t("cashflows"), "cashflow_id")
cashflows = cashflows.join(sf.withColumnRenamed("base_currency", "_fund_ccy"), "fund_id", "left").join(si.withColumn("_investor_ok", F.lit(1)), "investor_id", "left").join(source_pairs, ["fund_id", "investor_id"], "left")
cashflows = cashflows.withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_cashflow_id")
     .when(F.col("_fund_ccy").isNull(), "orphan_fund")
     .when(F.col("_investor_ok").isNull(), "orphan_investor")
     .when(F.col("_pair_ok").isNull(), "missing_fund_investor_commitment")
     .when(~F.col("currency").isin(VALID_CCY), "invalid_currency")
     .when(F.col("currency") != F.col("_fund_ccy"), "fund_currency_mismatch")
     .when(~F.col("cashflow_type").isin(["CONTRIBUTION", "DISTRIBUTION"]), "invalid_cashflow_type")
     .when(F.col("amount") <= 0, "non_positive_amount"),
).drop("_fund_ccy", "_investor_ok", "_pair_ok")
q_cashflows = write_split("cashflows", cashflows)

nav = rank_duplicate(t("nav"), "nav_record_id").join(sf.withColumnRenamed("base_currency", "_fund_ccy"), "fund_id", "left")
nav = nav.withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_nav_record_id")
     .when(F.col("_fund_ccy").isNull(), "orphan_fund")
     .when(~F.col("currency").isin(VALID_CCY), "invalid_currency")
     .when(F.col("currency") != F.col("_fund_ccy"), "fund_currency_mismatch")
     .when(F.col("nav_amount") < 0, "negative_nav")
     .when(F.col("version") < 1, "invalid_version"),
).drop("_fund_ccy")
q_nav = write_split("nav", nav)

positions = rank_duplicate(t("positions"), "position_id").join(sf.withColumnRenamed("base_currency", "_fund_ccy"), "fund_id", "left").join(sa.withColumn("_asset_ok", F.lit(1)), "asset_id", "left")
positions = positions.withColumn(
    "quarantine_reason",
    F.when(F.col("_dup_rank") > 1, "duplicate_position_id")
     .when(F.col("_fund_ccy").isNull(), "orphan_fund")
     .when(F.col("_asset_ok").isNull(), "orphan_asset")
     .when(~F.col("currency").isin(VALID_CCY), "invalid_currency")
     .when(F.col("currency") != F.col("_fund_ccy"), "fund_currency_mismatch")
     .when(F.col("fair_value") < 0, "negative_fair_value"),
).drop("_fund_ccy", "_asset_ok")
q_positions = write_split("positions", positions)

quarantine = q_funds.unionByName(q_investors, allowMissingColumns=True).unionByName(q_assets, allowMissingColumns=True).unionByName(q_fx, allowMissingColumns=True).unionByName(q_commitments, allowMissingColumns=True).unionByName(q_cashflows, allowMissingColumns=True).unionByName(q_nav, allowMissingColumns=True).unionByName(q_positions, allowMissingColumns=True)
quarantine.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.{SCHEMA}.quarantine_all")
