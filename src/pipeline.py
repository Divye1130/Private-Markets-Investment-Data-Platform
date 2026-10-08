from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from .document_intelligence import deterministic_extract, extraction_to_dict

VALID_CURRENCIES = {"GBP", "USD", "EUR"}


def _hash_key(*parts: object) -> str:
    raw = "|".join("" if p is None else str(p).strip().upper() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()




def _xirr(dates: pd.Series, amounts: pd.Series) -> float:
    """Simple bisection XIRR for conventional private-markets cashflows.

    Contributions should be negative and distributions / terminal NAV positive.
    Returns NaN when a root cannot be bracketed.
    """
    d = pd.to_datetime(dates)
    a = np.asarray(amounts, dtype=float)
    if len(a) < 2 or not ((a < 0).any() and (a > 0).any()):
        return float("nan")
    t = (d - d.min()).dt.days.to_numpy(dtype=float) / 365.25
    def f(rate: float) -> float:
        if rate <= -1:
            return float("inf")
        return float(np.sum(a / np.power(1.0 + rate, t)))
    lo, hi = -0.9999, 10.0
    flo, fhi = f(lo), f(hi)
    if not np.isfinite(flo) or not np.isfinite(fhi) or flo * fhi > 0:
        return float("nan")
    for _ in range(120):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0

def _write_table(conn: sqlite3.Connection, name: str, df: pd.DataFrame) -> None:
    df.to_sql(name, conn, if_exists="replace", index=False)


def _read_csv(root: Path, name: str) -> pd.DataFrame:
    df = pd.read_csv(root / "data" / "raw" / f"{name}.csv")
    df["_source_file"] = f"{name}.csv"
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return df


def _apply_validation(
    df: pd.DataFrame,
    checks: List[Tuple[str, pd.Series]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    reason = pd.Series("", index=df.index, dtype="object")
    for label, bad in checks:
        mask = bad.fillna(False) & reason.eq("")
        reason.loc[mask] = label
    valid = df[reason.eq("")].copy()
    invalid = df[~reason.eq("")].copy()
    invalid["quarantine_reason"] = reason[~reason.eq("")]
    return valid.reset_index(drop=True), invalid.reset_index(drop=True)


def run_pipeline(root: Path) -> Dict[str, object]:
    warehouse = root / "warehouse"
    warehouse.mkdir(parents=True, exist_ok=True)
    db_path = warehouse / "private_markets.db"
    if db_path.exists():
        db_path.unlink()

    # Remove generated outputs from previous runs so a changed input size cannot leave stale files.
    for out_dir in [root / "data" / "processed", root / "data" / "quarantine", root / "reports"]:
        out_dir.mkdir(parents=True, exist_ok=True)
        for pattern in ["*.csv", "*.json"]:
            for old_file in out_dir.glob(pattern):
                old_file.unlink()

    conn = sqlite3.connect(db_path)

    names = ["funds", "investors", "assets", "fx_rates", "commitments", "cashflows", "nav", "positions", "document_manifest"]
    bronze: Dict[str, pd.DataFrame] = {}
    for name in names:
        bronze[name] = _read_csv(root, name)
        _write_table(conn, f"bronze_{name}", bronze[name])

    funds = bronze["funds"]
    investors = bronze["investors"]
    assets = bronze["assets"]
    fx = bronze["fx_rates"]

    silver_funds, q_funds = _apply_validation(
        funds,
        [
            ("duplicate_fund_id", funds["fund_id"].duplicated(keep="first")),
            ("invalid_base_currency", ~funds["base_currency"].isin(VALID_CURRENCIES)),
            ("non_positive_target_size", funds["target_size"] <= 0),
        ],
    )
    silver_investors, q_investors = _apply_validation(
        investors,
        [("duplicate_investor_id", investors["investor_id"].duplicated(keep="first"))],
    )
    silver_assets, q_assets = _apply_validation(
        assets,
        [("duplicate_asset_id", assets["asset_id"].duplicated(keep="first"))],
    )
    silver_fx, q_fx = _apply_validation(
        fx,
        [
            ("duplicate_fx_currency", fx["currency"].duplicated(keep="first")),
            ("invalid_currency", ~fx["currency"].isin(VALID_CURRENCIES)),
            ("non_positive_fx_rate", fx["gbp_per_unit"] <= 0),
        ],
    )
    fund_ids = set(silver_funds["fund_id"])
    investor_ids = set(silver_investors["investor_id"])
    asset_ids = set(silver_assets["asset_id"])
    fund_currency = silver_funds.set_index("fund_id")["base_currency"].to_dict()

    c = bronze["commitments"]
    silver_commitments, q_commitments = _apply_validation(
        c,
        [
            ("duplicate_commitment_id", c["commitment_id"].duplicated(keep="first")),
            ("orphan_fund", ~c["fund_id"].isin(fund_ids)),
            ("orphan_investor", ~c["investor_id"].isin(investor_ids)),
            ("invalid_currency", ~c["currency"].isin(VALID_CURRENCIES)),
            ("fund_currency_mismatch", c["fund_id"].map(fund_currency).notna() & (c["currency"] != c["fund_id"].map(fund_currency))),
            ("non_positive_commitment", c["commitment_amount"] <= 0),
        ],
    )

    cf = bronze["cashflows"]
    # Cashflow relationship validity is checked against the source commitment relationship,
    # not the commitment amount-quality outcome. A bad commitment amount should not by itself
    # invalidate an otherwise valid ledger cashflow for the same fund/investor relationship.
    valid_commitment_pairs = set(zip(c["fund_id"], c["investor_id"]))
    pair_is_valid = pd.Series(
        [(f, i) in valid_commitment_pairs for f, i in zip(cf["fund_id"], cf["investor_id"])],
        index=cf.index,
    )
    silver_cashflows, q_cashflows = _apply_validation(
        cf,
        [
            ("duplicate_cashflow_id", cf["cashflow_id"].duplicated(keep="first")),
            ("orphan_fund", ~cf["fund_id"].isin(fund_ids)),
            ("orphan_investor", ~cf["investor_id"].isin(investor_ids)),
            ("missing_fund_investor_commitment", ~pair_is_valid & cf["fund_id"].isin(fund_ids) & cf["investor_id"].isin(investor_ids)),
            ("invalid_currency", ~cf["currency"].isin(VALID_CURRENCIES)),
            ("fund_currency_mismatch", cf["fund_id"].map(fund_currency).notna() & (cf["currency"] != cf["fund_id"].map(fund_currency))),
            ("invalid_cashflow_type", ~cf["cashflow_type"].isin(["CONTRIBUTION", "DISTRIBUTION"])),
            ("non_positive_amount", cf["amount"] <= 0),
        ],
    )

    nav = bronze["nav"]
    silver_nav, q_nav = _apply_validation(
        nav,
        [
            ("duplicate_nav_record_id", nav["nav_record_id"].duplicated(keep="first")),
            ("orphan_fund", ~nav["fund_id"].isin(fund_ids)),
            ("invalid_currency", ~nav["currency"].isin(VALID_CURRENCIES)),
            ("fund_currency_mismatch", nav["fund_id"].map(fund_currency).notna() & (nav["currency"] != nav["fund_id"].map(fund_currency))),
            ("negative_nav", nav["nav_amount"] < 0),
            ("invalid_version", nav["version"] < 1),
        ],
    )

    pos = bronze["positions"]
    silver_positions, q_positions = _apply_validation(
        pos,
        [
            ("duplicate_position_id", pos["position_id"].duplicated(keep="first")),
            ("orphan_fund", ~pos["fund_id"].isin(fund_ids)),
            ("orphan_asset", ~pos["asset_id"].isin(asset_ids)),
            ("invalid_currency", ~pos["currency"].isin(VALID_CURRENCIES)),
            ("fund_currency_mismatch", pos["fund_id"].map(fund_currency).notna() & (pos["currency"] != pos["fund_id"].map(fund_currency))),
            ("negative_fair_value", pos["fair_value"] < 0),
        ],
    )

    silver_tables = {
        "funds": silver_funds,
        "investors": silver_investors,
        "assets": silver_assets,
        "fx_rates": silver_fx,
        "commitments": silver_commitments,
        "cashflows": silver_cashflows,
        "nav": silver_nav,
        "positions": silver_positions,
    }
    for name, df in silver_tables.items():
        _write_table(conn, f"silver_{name}", df)
        clean_cols = [c for c in df.columns if not c.startswith("_")]
        df[clean_cols].to_csv(root / "data" / "processed" / f"silver_{name}.csv", index=False)

    quarantines = []
    for entity, q in [
        ("funds", q_funds),
        ("investors", q_investors),
        ("assets", q_assets),
        ("fx_rates", q_fx),
        ("commitments", q_commitments),
        ("cashflows", q_cashflows),
        ("nav", q_nav),
        ("positions", q_positions),
    ]:
        if not q.empty:
            q = q.copy()
            q.insert(0, "entity", entity)
            q.to_csv(root / "data" / "quarantine" / f"{entity}.csv", index=False)
            quarantines.append(q)
    quarantine_all = pd.concat(quarantines, ignore_index=True) if quarantines else pd.DataFrame()
    _write_table(conn, "quarantine_all", quarantine_all)

    # Document intelligence + deterministic control layer.
    extracted = []
    for path in sorted((root / "data" / "documents").glob("*.pdf")):
        extracted.append(extraction_to_dict(deterministic_extract(path)))
    doc_ext = pd.DataFrame(extracted)
    manifest = bronze["document_manifest"].drop(columns=["_source_file", "_ingested_at"])
    doc_ext = doc_ext.merge(
        manifest[["document_id", "expected_cashflow_id", "expected_match"]],
        on="document_id",
        how="left",
    )
    cash_ref = silver_cashflows[["cashflow_id", "fund_id", "investor_id", "cashflow_date", "amount", "currency"]].rename(
        columns={
            "cashflow_id": "reference",
            "fund_id": "ledger_fund_id",
            "investor_id": "ledger_investor_id",
            "cashflow_date": "ledger_cashflow_date",
            "amount": "ledger_amount",
            "currency": "ledger_currency",
        }
    )
    doc_ext = doc_ext.merge(cash_ref, on="reference", how="left")
    doc_ext["amount_difference"] = (doc_ext["call_amount"] - doc_ext["ledger_amount"]).round(2)
    doc_ext["reconciliation_status"] = np.where(
        doc_ext["validation_status"] != "PASS",
        "REVIEW_EXTRACTION_VALIDATION",
        np.where(
            doc_ext["ledger_amount"].isna(),
            "REVIEW_MISSING_LEDGER_REFERENCE",
            np.where(
                (doc_ext["amount_difference"].abs() <= 0.01)
                & (doc_ext["fund_id"] == doc_ext["ledger_fund_id"])
                & (doc_ext["investor_id"] == doc_ext["ledger_investor_id"])
                & (doc_ext["currency"] == doc_ext["ledger_currency"])
                & (doc_ext["due_date"] == doc_ext["ledger_cashflow_date"]),
                "MATCH",
                "REVIEW_MISMATCH",
            ),
        ),
    )
    _write_table(conn, "silver_document_extractions", doc_ext)
    doc_ext.to_csv(root / "data" / "processed" / "silver_document_extractions.csv", index=False)

    # Raw Vault 2.0-style historical core.
    hub_fund = silver_funds[["fund_id"]].drop_duplicates().copy()
    hub_fund["fund_hk"] = hub_fund["fund_id"].map(lambda x: _hash_key("FUND", x))
    hub_fund["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    hub_fund["record_source"] = "silver_funds"
    hub_fund = hub_fund[["fund_hk", "fund_id", "load_ts", "record_source"]]

    hub_investor = silver_investors[["investor_id"]].drop_duplicates().copy()
    hub_investor["investor_hk"] = hub_investor["investor_id"].map(lambda x: _hash_key("INVESTOR", x))
    hub_investor["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    hub_investor["record_source"] = "silver_investors"
    hub_investor = hub_investor[["investor_hk", "investor_id", "load_ts", "record_source"]]

    hub_asset = silver_assets[["asset_id"]].drop_duplicates().copy()
    hub_asset["asset_hk"] = hub_asset["asset_id"].map(lambda x: _hash_key("ASSET", x))
    hub_asset["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    hub_asset["record_source"] = "silver_assets"
    hub_asset = hub_asset[["asset_hk", "asset_id", "load_ts", "record_source"]]

    fund_hk = hub_fund.set_index("fund_id")["fund_hk"].to_dict()
    inv_hk = hub_investor.set_index("investor_id")["investor_hk"].to_dict()
    asset_hk = hub_asset.set_index("asset_id")["asset_hk"].to_dict()

    link_fund_investor = pd.concat(
        [
            silver_commitments[["fund_id", "investor_id"]],
            silver_cashflows[["fund_id", "investor_id"]],
        ],
        ignore_index=True,
    ).drop_duplicates().copy()
    link_fund_investor["fund_investor_hk"] = link_fund_investor.apply(
        lambda r: _hash_key("FUND_INVESTOR", r["fund_id"], r["investor_id"]), axis=1
    )
    link_fund_investor["fund_hk"] = link_fund_investor["fund_id"].map(fund_hk)
    link_fund_investor["investor_hk"] = link_fund_investor["investor_id"].map(inv_hk)
    link_fund_investor["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    link_fund_investor = link_fund_investor[["fund_investor_hk", "fund_hk", "investor_hk", "load_ts"]]

    link_fund_asset = silver_positions[["fund_id", "asset_id"]].drop_duplicates().copy()
    link_fund_asset["fund_asset_hk"] = link_fund_asset.apply(
        lambda r: _hash_key("FUND_ASSET", r["fund_id"], r["asset_id"]), axis=1
    )
    link_fund_asset["fund_hk"] = link_fund_asset["fund_id"].map(fund_hk)
    link_fund_asset["asset_hk"] = link_fund_asset["asset_id"].map(asset_hk)
    link_fund_asset["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    link_fund_asset = link_fund_asset[["fund_asset_hk", "fund_hk", "asset_hk", "load_ts"]]

    sat_fund_details = silver_funds.copy()
    sat_fund_details["fund_hk"] = sat_fund_details["fund_id"].map(fund_hk)
    sat_fund_details["hashdiff"] = sat_fund_details.apply(
        lambda r: _hash_key(r["fund_name"], r["strategy"], r["vintage_year"], r["base_currency"], r["target_size"], r["region"]),
        axis=1,
    )
    sat_fund_details["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    sat_fund_details = sat_fund_details[
        ["fund_hk", "fund_name", "strategy", "vintage_year", "base_currency", "target_size", "manager_id", "region", "hashdiff", "load_ts"]
    ]

    sat_nav_history = silver_nav.copy()
    sat_nav_history["fund_hk"] = sat_nav_history["fund_id"].map(fund_hk)
    sat_nav_history["hashdiff"] = sat_nav_history.apply(
        lambda r: _hash_key(r["as_of_date"], r["nav_amount"], r["currency"], r["version"], r["reported_at"]), axis=1
    )
    sat_nav_history["load_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    sat_nav_history = sat_nav_history[
        ["fund_hk", "as_of_date", "nav_amount", "currency", "version", "is_restatement", "reported_at", "hashdiff", "load_ts"]
    ]

    for name, df in {
        "vault_hub_fund": hub_fund,
        "vault_hub_investor": hub_investor,
        "vault_hub_asset": hub_asset,
        "vault_link_fund_investor": link_fund_investor,
        "vault_link_fund_asset": link_fund_asset,
        "vault_sat_fund_details": sat_fund_details,
        "vault_sat_nav_history": sat_nav_history,
    }.items():
        _write_table(conn, name, df)

    # Gold Kimball model.
    dim_fund = silver_funds.drop(columns=[c for c in silver_funds.columns if c.startswith("_")]).copy().reset_index(drop=True)
    dim_fund.insert(0, "fund_key", np.arange(1, len(dim_fund) + 1))
    dim_investor = silver_investors.drop(columns=[c for c in silver_investors.columns if c.startswith("_")]).copy().reset_index(drop=True)
    dim_investor.insert(0, "investor_key", np.arange(1, len(dim_investor) + 1))
    dim_asset = silver_assets.drop(columns=[c for c in silver_assets.columns if c.startswith("_")]).copy().reset_index(drop=True)
    dim_asset.insert(0, "asset_key", np.arange(1, len(dim_asset) + 1))

    fund_key = dim_fund.set_index("fund_id")["fund_key"].to_dict()
    investor_key = dim_investor.set_index("investor_id")["investor_key"].to_dict()
    asset_key = dim_asset.set_index("asset_id")["asset_key"].to_dict()

    all_dates = sorted(
        set(pd.to_datetime(silver_cashflows["cashflow_date"]).dt.date)
        | set(pd.to_datetime(silver_nav["as_of_date"]).dt.date)
        | set(pd.to_datetime(silver_positions["as_of_date"]).dt.date)
    )
    dim_date = pd.DataFrame({"date": [d.isoformat() for d in all_dates]})
    dim_date.insert(0, "date_key", pd.to_datetime(dim_date["date"]).dt.strftime("%Y%m%d").astype(int))
    dim_date["year"] = pd.to_datetime(dim_date["date"]).dt.year
    dim_date["quarter"] = pd.to_datetime(dim_date["date"]).dt.quarter
    dim_date["month"] = pd.to_datetime(dim_date["date"]).dt.month

    fact_cashflow = silver_cashflows.drop(columns=[c for c in silver_cashflows.columns if c.startswith("_")]).copy()
    fact_cashflow["fund_key"] = fact_cashflow["fund_id"].map(fund_key)
    fact_cashflow["investor_key"] = fact_cashflow["investor_id"].map(investor_key)
    fact_cashflow["date_key"] = pd.to_datetime(fact_cashflow["cashflow_date"]).dt.strftime("%Y%m%d").astype(int)
    fact_cashflow = fact_cashflow[
        ["cashflow_id", "fund_key", "investor_key", "date_key", "cashflow_type", "amount", "currency", "source_system"]
    ]

    fact_commitment = silver_commitments.drop(columns=[c for c in silver_commitments.columns if c.startswith("_")]).copy()
    fact_commitment["fund_key"] = fact_commitment["fund_id"].map(fund_key)
    fact_commitment["investor_key"] = fact_commitment["investor_id"].map(investor_key)
    fact_commitment["date_key"] = pd.to_datetime(fact_commitment["commitment_date"]).dt.strftime("%Y%m%d").astype(int)
    fact_commitment = fact_commitment[
        ["commitment_id", "fund_key", "investor_key", "date_key", "commitment_amount", "currency"]
    ]

    fact_position = silver_positions.drop(columns=[c for c in silver_positions.columns if c.startswith("_")]).copy()
    fact_position["fund_key"] = fact_position["fund_id"].map(fund_key)
    fact_position["asset_key"] = fact_position["asset_id"].map(asset_key)
    fact_position["date_key"] = pd.to_datetime(fact_position["as_of_date"]).dt.strftime("%Y%m%d").astype(int)
    fact_position = fact_position[["position_id", "fund_key", "asset_key", "date_key", "fair_value", "currency"]]

    nav_clean = silver_nav.drop(columns=[c for c in silver_nav.columns if c.startswith("_")]).copy()
    nav_clean = nav_clean.sort_values(["fund_id", "as_of_date", "version", "reported_at"]).groupby(
        ["fund_id", "as_of_date"], as_index=False
    ).tail(1)
    fact_nav = nav_clean.copy()
    fact_nav["fund_key"] = fact_nav["fund_id"].map(fund_key)
    fact_nav["date_key"] = pd.to_datetime(fact_nav["as_of_date"]).dt.strftime("%Y%m%d").astype(int)
    fact_nav = fact_nav[["nav_record_id", "fund_key", "date_key", "nav_amount", "currency", "version", "is_restatement", "reported_at"]]

    for name, df in {
        "gold_dim_fund": dim_fund,
        "gold_dim_investor": dim_investor,
        "gold_dim_asset": dim_asset,
        "gold_dim_date": dim_date,
        "gold_fact_cashflow": fact_cashflow,
        "gold_fact_commitment": fact_commitment,
        "gold_fact_position": fact_position,
        "gold_fact_nav": fact_nav,
    }.items():
        _write_table(conn, name, df)

    # Analytical marts.
    cf_base = silver_cashflows.copy()
    paid = cf_base[cf_base["cashflow_type"] == "CONTRIBUTION"].groupby("fund_id")["amount"].sum()
    dist = cf_base[cf_base["cashflow_type"] == "DISTRIBUTION"].groupby("fund_id")["amount"].sum()
    comm = silver_commitments.groupby("fund_id")["commitment_amount"].sum()
    latest_nav = (
        nav_clean.sort_values(["fund_id", "as_of_date"]).groupby("fund_id", as_index=False).tail(1).set_index("fund_id")["nav_amount"]
    )
    perf = silver_funds[["fund_id", "fund_name", "strategy", "vintage_year", "base_currency", "region"]].copy()
    perf["paid_in_capital"] = perf["fund_id"].map(paid).fillna(0.0)
    perf["distributions"] = perf["fund_id"].map(dist).fillna(0.0)
    perf["latest_nav"] = perf["fund_id"].map(latest_nav).fillna(0.0)
    perf["total_commitment"] = perf["fund_id"].map(comm).fillna(0.0)
    perf["unfunded_commitment"] = (perf["total_commitment"] - perf["paid_in_capital"]).clip(lower=0)
    denom = perf["paid_in_capital"].replace(0, np.nan)
    perf["dpi"] = perf["distributions"] / denom
    perf["rvpi"] = perf["latest_nav"] / denom
    perf["tvpi"] = (perf["distributions"] + perf["latest_nav"]) / denom
    perf[["dpi", "rvpi", "tvpi"]] = perf[["dpi", "rvpi", "tvpi"]].fillna(0.0)

    irr_map = {}
    latest_nav_date = (
        nav_clean.sort_values(["fund_id", "as_of_date"]).groupby("fund_id", as_index=False).tail(1)
        .set_index("fund_id")[["as_of_date", "nav_amount"]].to_dict("index")
    )
    for fund_id, grp in cf_base.groupby("fund_id"):
        g = grp.copy()
        amounts = np.where(g["cashflow_type"].eq("CONTRIBUTION"), -g["amount"], g["amount"]).astype(float)
        dates = list(g["cashflow_date"].astype(str))
        vals = list(amounts)
        terminal = latest_nav_date.get(fund_id)
        if terminal and float(terminal["nav_amount"]) > 0:
            dates.append(str(terminal["as_of_date"]))
            vals.append(float(terminal["nav_amount"]))
        irr_map[fund_id] = _xirr(pd.Series(dates), pd.Series(vals))
    perf["irr"] = perf["fund_id"].map(irr_map)

    fx_map = silver_fx.set_index("currency")["gbp_per_unit"].astype(float).to_dict()
    pos_detail = silver_positions.merge(silver_assets[["asset_id", "sector", "region", "asset_type"]], on="asset_id", how="left")
    pos_detail["gbp_per_unit"] = pos_detail["currency"].map(fx_map)
    pos_detail["fair_value_gbp"] = pos_detail["fair_value"] * pos_detail["gbp_per_unit"]
    exposure_sector = (
        pos_detail.groupby("sector", as_index=False)["fair_value_gbp"].sum().sort_values("fair_value_gbp", ascending=False)
    )
    exposure_region = (
        pos_detail.groupby("region", as_index=False)["fair_value_gbp"].sum().sort_values("fair_value_gbp", ascending=False)
    )

    perf["gbp_per_unit"] = perf["base_currency"].map(fx_map)
    for col in ["paid_in_capital", "distributions", "latest_nav", "total_commitment", "unfunded_commitment"]:
        perf[f"{col}_gbp"] = perf[col] * perf["gbp_per_unit"]

    latest_nav_df = nav_clean.sort_values(["fund_id", "as_of_date"]).groupby("fund_id", as_index=False).tail(1)[["fund_id", "nav_amount"]]
    pos_sum = silver_positions.groupby("fund_id", as_index=False)["fair_value"].sum().rename(columns={"fair_value": "position_fair_value"})
    recon = latest_nav_df.merge(pos_sum, on="fund_id", how="left").fillna({"position_fair_value": 0.0})
    recon["difference"] = (recon["position_fair_value"] - recon["nav_amount"]).round(2)
    recon["difference_pct"] = np.where(recon["nav_amount"].abs() > 0, recon["difference"] / recon["nav_amount"], 0.0)
    recon["status"] = np.where(recon["difference_pct"].abs() <= 0.01, "PASS", "REVIEW")

    q_summary = (
        quarantine_all.groupby(["entity", "quarantine_reason"]).size().reset_index(name="rows")
        if not quarantine_all.empty
        else pd.DataFrame(columns=["entity", "quarantine_reason", "rows"])
    )

    for name, df in {
        "mart_fund_performance": perf,
        "mart_exposure_sector": exposure_sector,
        "mart_exposure_region": exposure_region,
        "mart_nav_position_reconciliation": recon,
        "mart_data_quality": q_summary,
        "mart_document_reconciliation": doc_ext,
    }.items():
        _write_table(conn, name, df)
        df.to_csv(root / "reports" / f"{name}.csv", index=False)

    conn.commit()

    summary = {
        "database": str(db_path.relative_to(root)),
        "bronze_rows": {k: int(len(v)) for k, v in bronze.items()},
        "silver_rows": {k: int(len(v)) for k, v in silver_tables.items()},
        "quarantined_rows": int(len(quarantine_all)),
        "quarantine_by_entity": (
            quarantine_all["entity"].value_counts().sort_index().astype(int).to_dict() if not quarantine_all.empty else {}
        ),
        "vault": {
            "fund_hubs": int(len(hub_fund)),
            "investor_hubs": int(len(hub_investor)),
            "asset_hubs": int(len(hub_asset)),
            "fund_investor_links": int(len(link_fund_investor)),
            "fund_asset_links": int(len(link_fund_asset)),
            "nav_history_rows": int(len(sat_nav_history)),
            "restatement_rows_preserved": int(sat_nav_history["is_restatement"].sum()),
        },
        "gold": {
            "funds": int(len(dim_fund)),
            "investors": int(len(dim_investor)),
            "assets": int(len(dim_asset)),
            "cashflows": int(len(fact_cashflow)),
            "positions": int(len(fact_position)),
            "nav_snapshots_latest_version": int(len(fact_nav)),
        },
        "documents": {
            "documents_parsed": int(len(doc_ext)),
            "schema_pass": int((doc_ext["validation_status"] == "PASS").sum()),
            "ledger_matches": int((doc_ext["reconciliation_status"] == "MATCH").sum()),
            "review_queue": int((doc_ext["reconciliation_status"] != "MATCH").sum()),
        },
        "reconciliation": {
            "funds_pass": int((recon["status"] == "PASS").sum()),
            "funds_review": int((recon["status"] == "REVIEW").sum()),
        },
        "portfolio_metrics": {
            "median_tvpi": round(float(perf["tvpi"].median()), 3),
            "median_dpi": round(float(perf["dpi"].median()), 3),
            "median_irr": round(float(perf["irr"].dropna().median()), 4),
            "total_nav_gbp": round(float(perf["latest_nav_gbp"].sum()), 2),
            "total_unfunded_gbp": round(float(perf["unfunded_commitment_gbp"].sum()), 2),
        },
        "fx_normalisation": {
            "as_of_date": str(silver_fx["as_of_date"].iloc[0]),
            "rates_to_gbp": {k: float(v) for k, v in fx_map.items()},
            "rate_source": str(silver_fx["rate_source"].iloc[0]),
        },
        "execution_note": "Verified local reference implementation using Python/pandas/SQLite. Databricks/PySpark assets are deployment-ready source code but were not executed in this environment.",
    }
    (root / "reports" / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    conn.close()
    return summary


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args()
    print(json.dumps(run_pipeline(args.root), indent=2))
