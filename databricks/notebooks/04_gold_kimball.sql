-- Databricks notebook source
USE CATALOG main;
USE SCHEMA private_markets;

CREATE OR REPLACE TABLE gold_dim_fund AS
SELECT
  row_number() OVER (ORDER BY fund_id) AS fund_key,
  fund_id, fund_name, strategy, vintage_year, base_currency, target_size, manager_id, region
FROM silver_funds;

CREATE OR REPLACE TABLE gold_dim_investor AS
SELECT
  row_number() OVER (ORDER BY investor_id) AS investor_key,
  investor_id, investor_name, investor_type, domicile, risk_segment
FROM silver_investors;

CREATE OR REPLACE TABLE gold_dim_asset AS
SELECT
  row_number() OVER (ORDER BY asset_id) AS asset_key,
  asset_id, asset_name, sector, region, asset_type
FROM silver_assets;

CREATE OR REPLACE TABLE gold_fact_cashflow AS
SELECT c.cashflow_id, f.fund_key, i.investor_key,
       cast(date_format(to_date(c.cashflow_date),'yyyyMMdd') as int) AS date_key,
       c.cashflow_type, c.amount, c.currency, c.source_system
FROM silver_cashflows c
JOIN gold_dim_fund f USING (fund_id)
JOIN gold_dim_investor i USING (investor_id);

CREATE OR REPLACE VIEW mart_fund_performance AS
WITH paid AS (
  SELECT fund_id, sum(amount) paid_in_capital FROM silver_cashflows WHERE cashflow_type='CONTRIBUTION' GROUP BY fund_id
), dist AS (
  SELECT fund_id, sum(amount) distributions FROM silver_cashflows WHERE cashflow_type='DISTRIBUTION' GROUP BY fund_id
), nav_ranked AS (
  SELECT *, row_number() OVER(PARTITION BY fund_id, as_of_date ORDER BY version DESC, reported_at DESC) rn FROM silver_nav
), latest_nav AS (
  SELECT fund_id, nav_amount FROM (
    SELECT *, row_number() OVER(PARTITION BY fund_id ORDER BY as_of_date DESC) latest_rn
    FROM nav_ranked WHERE rn=1
  ) WHERE latest_rn=1
), commitment AS (
  SELECT fund_id, sum(commitment_amount) total_commitment FROM silver_commitments GROUP BY fund_id
)
SELECT f.fund_id, f.fund_name, f.strategy, f.vintage_year,
       coalesce(p.paid_in_capital,0) paid_in_capital,
       coalesce(d.distributions,0) distributions,
       coalesce(n.nav_amount,0) latest_nav,
       coalesce(c.total_commitment,0) total_commitment,
       greatest(coalesce(c.total_commitment,0)-coalesce(p.paid_in_capital,0),0) unfunded_commitment,
       CASE WHEN p.paid_in_capital>0 THEN d.distributions/p.paid_in_capital ELSE 0 END dpi,
       CASE WHEN p.paid_in_capital>0 THEN n.nav_amount/p.paid_in_capital ELSE 0 END rvpi,
       CASE WHEN p.paid_in_capital>0 THEN (d.distributions+n.nav_amount)/p.paid_in_capital ELSE 0 END tvpi
FROM silver_funds f
LEFT JOIN paid p USING(fund_id)
LEFT JOIN dist d USING(fund_id)
LEFT JOIN latest_nav n USING(fund_id)
LEFT JOIN commitment c USING(fund_id);


CREATE OR REPLACE VIEW mart_exposure_sector AS
SELECT a.sector, sum(p.fair_value * fx.gbp_per_unit) AS fair_value_gbp
FROM silver_positions p
JOIN silver_assets a USING (asset_id)
JOIN silver_fx_rates fx USING (currency)
GROUP BY a.sector;

CREATE OR REPLACE VIEW mart_exposure_region AS
SELECT a.region, sum(p.fair_value * fx.gbp_per_unit) AS fair_value_gbp
FROM silver_positions p
JOIN silver_assets a USING (asset_id)
JOIN silver_fx_rates fx USING (currency)
GROUP BY a.region;
