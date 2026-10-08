-- Databricks notebook source
USE CATALOG main;
USE SCHEMA private_markets;

CREATE OR REPLACE TABLE vault_hub_fund AS
SELECT DISTINCT
  sha2(concat_ws('|','FUND', upper(trim(fund_id))), 256) AS fund_hk,
  fund_id,
  current_timestamp() AS load_ts,
  'silver_funds' AS record_source
FROM silver_funds;

CREATE OR REPLACE TABLE vault_hub_investor AS
SELECT DISTINCT
  sha2(concat_ws('|','INVESTOR', upper(trim(investor_id))), 256) AS investor_hk,
  investor_id,
  current_timestamp() AS load_ts,
  'silver_investors' AS record_source
FROM silver_investors;

CREATE OR REPLACE TABLE vault_hub_asset AS
SELECT DISTINCT
  sha2(concat_ws('|','ASSET', upper(trim(asset_id))), 256) AS asset_hk,
  asset_id,
  current_timestamp() AS load_ts,
  'silver_assets' AS record_source
FROM silver_assets;

CREATE OR REPLACE TABLE vault_link_fund_investor AS
SELECT DISTINCT
  sha2(concat_ws('|','FUND_INVESTOR', c.fund_id, c.investor_id), 256) AS fund_investor_hk,
  f.fund_hk,
  i.investor_hk,
  current_timestamp() AS load_ts
FROM (
  SELECT fund_id, investor_id FROM silver_commitments
  UNION
  SELECT fund_id, investor_id FROM silver_cashflows
) c
JOIN vault_hub_fund f USING (fund_id)
JOIN vault_hub_investor i USING (investor_id);

CREATE OR REPLACE TABLE vault_sat_nav_history AS
SELECT
  f.fund_hk,
  n.as_of_date,
  n.nav_amount,
  n.currency,
  n.version,
  n.is_restatement,
  n.reported_at,
  sha2(concat_ws('|', n.as_of_date, n.nav_amount, n.currency, n.version, n.reported_at), 256) AS hashdiff,
  current_timestamp() AS load_ts
FROM silver_nav n
JOIN vault_hub_fund f USING (fund_id);
