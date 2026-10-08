from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.document_intelligence import deterministic_extract
from src.generate_data import GenerationConfig, generate_dataset
from src.pipeline import run_pipeline


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("pm_platform")
    for d in ["data/raw", "data/processed", "data/quarantine", "data/documents", "warehouse", "reports"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    generate_dataset(root, GenerationConfig(n_funds=12, n_investors=90, n_assets=120, n_documents=20, seed=42))
    summary = run_pipeline(root)
    conn = sqlite3.connect(root / "warehouse/private_markets.db")
    yield root, summary, conn
    conn.close()


def q(conn, sql):
    return pd.read_sql_query(sql, conn)


def test_generation_is_nontrivial(built):
    _, summary, _ = built
    assert summary["bronze_rows"]["cashflows"] > 1000


def test_fund_hub_is_unique(built):
    _, _, conn = built
    df = q(conn, "select fund_hk, fund_id from vault_hub_fund")
    assert df["fund_hk"].is_unique and df["fund_id"].is_unique


def test_investor_hub_is_unique(built):
    _, _, conn = built
    df = q(conn, "select investor_hk, investor_id from vault_hub_investor")
    assert df["investor_hk"].is_unique


def test_asset_hub_is_unique(built):
    _, _, conn = built
    df = q(conn, "select asset_hk, asset_id from vault_hub_asset")
    assert df["asset_hk"].is_unique


def test_cashflow_duplicates_quarantined(built):
    _, _, conn = built
    qdf = q(conn, "select * from quarantine_all where entity='cashflows' and quarantine_reason='duplicate_cashflow_id'")
    assert len(qdf) > 0


def test_invalid_currency_quarantined(built):
    _, _, conn = built
    qdf = q(conn, "select * from quarantine_all where quarantine_reason='invalid_currency'")
    assert len(qdf) > 0


def test_negative_commitment_quarantined(built):
    _, _, conn = built
    qdf = q(conn, "select * from quarantine_all where quarantine_reason='non_positive_commitment'")
    assert len(qdf) > 0


def test_negative_nav_quarantined(built):
    _, _, conn = built
    qdf = q(conn, "select * from quarantine_all where quarantine_reason='negative_nav'")
    assert len(qdf) > 0


def test_silver_cashflow_ids_unique(built):
    _, _, conn = built
    df = q(conn, "select cashflow_id from silver_cashflows")
    assert df["cashflow_id"].is_unique


def test_silver_cashflows_have_valid_funds(built):
    _, _, conn = built
    n = q(conn, "select count(*) n from silver_cashflows c left join silver_funds f on c.fund_id=f.fund_id where f.fund_id is null").iloc[0, 0]
    assert int(n) == 0


def test_silver_positions_have_valid_assets(built):
    _, _, conn = built
    n = q(conn, "select count(*) n from silver_positions p left join silver_assets a on p.asset_id=a.asset_id where a.asset_id is null").iloc[0, 0]
    assert int(n) == 0


def test_nav_history_preserves_restatements(built):
    _, summary, conn = built
    n = q(conn, "select count(*) n from vault_sat_nav_history where is_restatement=1").iloc[0, 0]
    assert int(n) == summary["vault"]["restatement_rows_preserved"]
    assert int(n) > 0


def test_gold_fund_dimension_has_surrogate_key(built):
    _, _, conn = built
    df = q(conn, "select fund_key, fund_id from gold_dim_fund")
    assert df["fund_key"].is_unique and df["fund_id"].is_unique


def test_fact_cashflow_grain_unique(built):
    _, _, conn = built
    df = q(conn, "select cashflow_id from gold_fact_cashflow")
    assert df["cashflow_id"].is_unique


def test_fact_position_grain_unique(built):
    _, _, conn = built
    df = q(conn, "select position_id from gold_fact_position")
    assert df["position_id"].is_unique


def test_fund_performance_metrics_are_nonnegative(built):
    _, _, conn = built
    df = q(conn, "select paid_in_capital, distributions, latest_nav, unfunded_commitment, dpi, rvpi, tvpi from mart_fund_performance")
    assert (df >= 0).all().all()


def test_tvpi_identity(built):
    _, _, conn = built
    df = q(conn, "select paid_in_capital, distributions, latest_nav, tvpi from mart_fund_performance where paid_in_capital > 0")
    calc = (df["distributions"] + df["latest_nav"]) / df["paid_in_capital"]
    assert ((calc - df["tvpi"]).abs() < 1e-9).all()



def test_fund_irr_is_computed_for_most_funds(built):
    _, _, conn = built
    df = q(conn, "select irr from mart_fund_performance")
    valid = df["irr"].dropna()
    assert len(valid) >= max(1, int(len(df) * 0.50))
    assert (valid > -1).all()
    assert (valid < 10).all()


def test_document_schema_extraction_passes(built):
    root, summary, _ = built
    first = sorted((root / "data/documents").glob("*.pdf"))[0]
    ext = deterministic_extract(first)
    assert ext.validation_status == "PASS"
    assert ext.call_amount and ext.call_amount > 0
    assert summary["documents"]["schema_pass"] == summary["documents"]["documents_parsed"]


def test_document_reconciliation_has_controlled_review_queue(built):
    _, summary, _ = built
    assert summary["documents"]["review_queue"] > 0
    assert summary["documents"]["ledger_matches"] > summary["documents"]["review_queue"]


def test_nav_position_reconciliation_has_both_pass_and_review(built):
    _, summary, _ = built
    assert summary["reconciliation"]["funds_pass"] > 0
    assert summary["reconciliation"]["funds_review"] > 0


def test_processed_outputs_created(built):
    root, _, _ = built
    assert (root / "data/processed/silver_cashflows.csv").exists()
    assert (root / "reports/mart_fund_performance.csv").exists()


def test_run_summary_is_serializable(built):
    root, summary, _ = built
    saved = json.loads((root / "reports/run_summary.json").read_text())
    assert saved["gold"]["funds"] == summary["gold"]["funds"]


def test_silver_fx_rates_are_complete_and_positive(built):
    _, _, conn = built
    df = q(conn, "select currency, gbp_per_unit from silver_fx_rates order by currency")
    assert set(df["currency"]) == {"GBP", "USD", "EUR"}
    assert df["currency"].is_unique
    assert (df["gbp_per_unit"] > 0).all()


def test_silver_cashflow_currency_matches_fund_base_currency(built):
    _, _, conn = built
    n = q(conn, """
        select count(*) n
        from silver_cashflows c
        join silver_funds f on c.fund_id=f.fund_id
        where c.currency <> f.base_currency
    """).iloc[0, 0]
    assert int(n) == 0


def test_silver_cashflows_have_valid_commitment_relationship(built):
    _, _, conn = built
    n = q(conn, """
        select count(*) n
        from silver_cashflows c
        left join (
            select distinct fund_id, investor_id from bronze_commitments
        ) k on c.fund_id=k.fund_id and c.investor_id=k.investor_id
        where k.fund_id is null
    """).iloc[0, 0]
    assert int(n) == 0


def test_gold_fact_foreign_keys_are_populated(built):
    _, _, conn = built
    for table, cols in [
        ("gold_fact_cashflow", ["fund_key", "investor_key", "date_key"]),
        ("gold_fact_commitment", ["fund_key", "investor_key", "date_key"]),
        ("gold_fact_position", ["fund_key", "asset_key", "date_key"]),
        ("gold_fact_nav", ["fund_key", "date_key"]),
    ]:
        where = " or ".join(f"{c} is null" for c in cols)
        n = q(conn, f"select count(*) n from {table} where {where}").iloc[0, 0]
        assert int(n) == 0, table


def test_nav_latest_version_selection_is_correct(built):
    _, _, conn = built
    silver = q(conn, "select * from silver_nav")
    expected = (
        silver.sort_values(["fund_id", "as_of_date", "version", "reported_at"])
        .groupby(["fund_id", "as_of_date"], as_index=False)
        .tail(1)
    )
    fact = q(conn, """
        select f.fund_id, n.date_key, n.nav_amount, n.version, n.reported_at
        from gold_fact_nav n join gold_dim_fund f using(fund_key)
    """)
    fact["as_of_date"] = pd.to_datetime(fact["date_key"].astype(str)).dt.strftime("%Y-%m-%d")
    merged = expected.merge(fact, on=["fund_id", "as_of_date"], suffixes=("_exp", "_fact"))
    assert len(merged) == len(expected) == len(fact)
    assert (merged["version_exp"] == merged["version_fact"]).all()
    assert ((merged["nav_amount_exp"] - merged["nav_amount_fact"]).abs() < 0.01).all()


def test_performance_metric_identities(built):
    _, _, conn = built
    df = q(conn, "select * from mart_fund_performance where paid_in_capital > 0")
    assert (((df["distributions"] / df["paid_in_capital"]) - df["dpi"]).abs() < 1e-9).all()
    assert (((df["latest_nav"] / df["paid_in_capital"]) - df["rvpi"]).abs() < 1e-9).all()
    expected_unfunded = (df["total_commitment"] - df["paid_in_capital"]).clip(lower=0)
    assert ((expected_unfunded - df["unfunded_commitment"]).abs() < 0.01).all()


def test_gbp_normalised_fund_values_are_consistent(built):
    _, _, conn = built
    df = q(conn, "select * from mart_fund_performance")
    for col in ["paid_in_capital", "distributions", "latest_nav", "total_commitment", "unfunded_commitment"]:
        assert ((df[col] * df["gbp_per_unit"] - df[f"{col}_gbp"]).abs() < 0.01).all()


def test_exposure_marts_use_fx_normalised_values(built):
    _, _, conn = built
    expected = q(conn, """
        select sum(p.fair_value * x.gbp_per_unit) as total
        from silver_positions p join silver_fx_rates x on p.currency=x.currency
    """).iloc[0, 0]
    sec = q(conn, "select sum(fair_value_gbp) total from mart_exposure_sector").iloc[0, 0]
    reg = q(conn, "select sum(fair_value_gbp) total from mart_exposure_region").iloc[0, 0]
    assert abs(float(sec) - float(expected)) < 0.01
    assert abs(float(reg) - float(expected)) < 0.01


def test_summary_gbp_total_nav_identity(built):
    _, summary, conn = built
    total = q(conn, "select sum(latest_nav_gbp) total from mart_fund_performance").iloc[0, 0]
    assert abs(float(total) - summary["portfolio_metrics"]["total_nav_gbp"]) < 0.01


def test_document_reconciliation_exactly_matches_injected_expectation(built):
    _, _, conn = built
    df = q(conn, "select expected_match, reconciliation_status from mart_document_reconciliation")
    actual_match = df["reconciliation_status"].eq("MATCH").astype(int)
    assert (actual_match == df["expected_match"].astype(int)).all()


def test_distribution_is_never_before_first_contribution_for_investor_fund(built):
    _, _, conn = built
    df = q(conn, "select fund_id, investor_id, cashflow_date, cashflow_type from silver_cashflows")
    df["cashflow_date"] = pd.to_datetime(df["cashflow_date"])
    for _, g in df.groupby(["fund_id", "investor_id"]):
        contrib = g.loc[g["cashflow_type"] == "CONTRIBUTION", "cashflow_date"]
        dist = g.loc[g["cashflow_type"] == "DISTRIBUTION", "cashflow_date"]
        if len(dist):
            assert len(contrib)
            assert dist.min() >= contrib.min()


def test_injected_quality_issue_counts_reconcile_exactly(built):
    root, _, conn = built
    meta = json.loads((root / "data/raw/generation_metadata.json").read_text())
    expected = {
        "duplicate_cashflow_rows": ("cashflows", "duplicate_cashflow_id"),
        "invalid_cashflow_currency": ("cashflows", "invalid_currency"),
        "orphan_cashflow_fund": ("cashflows", "orphan_fund"),
        "negative_commitment": ("commitments", "non_positive_commitment"),
        "negative_nav": ("nav", "negative_nav"),
        "orphan_position_asset": ("positions", "orphan_asset"),
    }
    for source_key, (entity, reason) in expected.items():
        n = q(conn, "select count(*) n from quarantine_all where entity=? and quarantine_reason=?", params=(entity, reason)).iloc[0, 0] if False else None
        actual = q(conn, f"select count(*) n from quarantine_all where entity='{entity}' and quarantine_reason='{reason}'").iloc[0, 0]
        assert int(actual) == int(meta["injected_quality_issues"][source_key])


def test_generation_is_idempotent_for_document_count(tmp_path):
    root = tmp_path / "rerun"
    for d in ["data/raw", "data/processed", "data/quarantine", "data/documents", "warehouse", "reports"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    generate_dataset(root, GenerationConfig(n_funds=8, n_investors=50, n_assets=70, n_documents=15, seed=42))
    assert len(list((root / "data/documents").glob("*.pdf"))) == 15
    generate_dataset(root, GenerationConfig(n_funds=8, n_investors=50, n_assets=70, n_documents=7, seed=42))
    assert len(list((root / "data/documents").glob("*.pdf"))) == 7


def test_vault_fund_investor_links_cover_all_valid_cashflow_relationships(built):
    _, _, conn = built
    n = q(conn, """
        select count(*) n
        from (
            select distinct c.fund_id, c.investor_id
            from silver_cashflows c
        ) c
        left join vault_hub_fund f on c.fund_id=f.fund_id
        left join vault_hub_investor i on c.investor_id=i.investor_id
        left join vault_link_fund_investor l on f.fund_hk=l.fund_hk and i.investor_hk=l.investor_hk
        where l.fund_investor_hk is null
    """).iloc[0, 0]
    assert int(n) == 0
