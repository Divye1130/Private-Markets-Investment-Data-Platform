-- Representative control logic used by the platform.
-- Local execution is implemented in src/pipeline.py; this file is the SQL-equivalent design.
SELECT cashflow_id, fund_id, investor_id, cashflow_type, amount, currency,
       CASE
         WHEN amount <= 0 THEN 'non_positive_amount'
         WHEN currency NOT IN ('GBP','USD','EUR') THEN 'invalid_currency'
         WHEN cashflow_type NOT IN ('CONTRIBUTION','DISTRIBUTION') THEN 'invalid_cashflow_type'
         ELSE NULL
       END AS quarantine_reason
FROM bronze_cashflows;
