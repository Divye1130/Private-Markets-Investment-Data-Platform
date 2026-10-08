-- Databricks notebook source
USE CATALOG main;
USE SCHEMA private_markets;

-- Reusable semantic queries for reporting/AI consumption.
CREATE OR REPLACE VIEW semantic_fund_kpis AS
SELECT fund_id, fund_name, strategy, vintage_year,
       paid_in_capital, distributions, latest_nav, total_commitment, unfunded_commitment,
       dpi, rvpi, tvpi
FROM mart_fund_performance;

CREATE OR REPLACE VIEW semantic_review_queue AS
SELECT * FROM mart_document_reconciliation
WHERE reconciliation_status <> 'MATCH';
