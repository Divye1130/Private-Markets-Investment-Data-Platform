from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SEED = 42
CURRENCIES = ["GBP", "USD", "EUR"]
STRATEGIES = ["Buyout", "Growth", "Private Credit", "Infrastructure", "Real Estate", "Secondaries"]
REGIONS = ["UK", "Europe", "North America", "Asia-Pacific"]
SECTORS = ["Technology", "Healthcare", "Industrials", "Consumer", "Financials", "Energy", "Real Estate"]


@dataclass(frozen=True)
class GenerationConfig:
    n_funds: int = 24
    n_investors: int = 180
    n_assets: int = 240
    n_documents: int = 60
    seed: int = SEED


def _quarter_ends(start_year: int = 2022, end_year: int = 2026) -> List[pd.Timestamp]:
    out: List[pd.Timestamp] = []
    for year in range(start_year, end_year + 1):
        for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            dt = pd.Timestamp(year=year, month=month, day=day)
            if dt <= pd.Timestamp("2026-09-30"):
                out.append(dt)
    return out


def _make_funds(cfg: GenerationConfig, rng: np.random.Generator) -> pd.DataFrame:
    vintage = rng.integers(2017, 2025, size=cfg.n_funds)
    rows = []
    for i in range(cfg.n_funds):
        target = float(rng.integers(150, 1200)) * 1_000_000
        rows.append(
            {
                "fund_id": f"FUND{i+1:03d}",
                "fund_name": f"Northstar {STRATEGIES[i % len(STRATEGIES)]} Fund {i+1}",
                "strategy": STRATEGIES[i % len(STRATEGIES)],
                "vintage_year": int(vintage[i]),
                "base_currency": CURRENCIES[i % len(CURRENCIES)],
                "target_size": round(target, 2),
                "manager_id": f"MGR{(i % 8)+1:03d}",
                "region": REGIONS[i % len(REGIONS)],
            }
        )
    return pd.DataFrame(rows)


def _make_investors(cfg: GenerationConfig, rng: np.random.Generator) -> pd.DataFrame:
    investor_types = ["Pension Fund", "Insurance", "Family Office", "Endowment", "Sovereign Wealth", "Fund of Funds"]
    rows = []
    for i in range(cfg.n_investors):
        rows.append(
            {
                "investor_id": f"INV{i+1:04d}",
                "investor_name": f"Institutional Investor {i+1}",
                "investor_type": investor_types[i % len(investor_types)],
                "domicile": REGIONS[i % len(REGIONS)],
                "risk_segment": ["Conservative", "Balanced", "Growth"][i % 3],
            }
        )
    return pd.DataFrame(rows)


def _make_assets(cfg: GenerationConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(cfg.n_assets):
        rows.append(
            {
                "asset_id": f"AST{i+1:04d}",
                "asset_name": f"Portfolio Company {i+1}",
                "sector": SECTORS[i % len(SECTORS)],
                "region": REGIONS[(i * 3) % len(REGIONS)],
                "asset_type": ["Equity", "Debt", "Real Asset"][i % 3],
            }
        )
    return pd.DataFrame(rows)


def _make_fx_rates() -> pd.DataFrame:
    """Illustrative deterministic FX rates used only to make portfolio-level sums comparable.

    `gbp_per_unit` means GBP value of one unit of the source currency. These are synthetic
    demonstration rates, not market data. Fund-level ratios are calculated in each fund's
    own base currency and therefore do not depend on these rates.
    """
    return pd.DataFrame(
        [
            {"currency": "GBP", "as_of_date": "2026-09-30", "gbp_per_unit": 1.00, "rate_source": "synthetic_demo"},
            {"currency": "USD", "as_of_date": "2026-09-30", "gbp_per_unit": 0.76, "rate_source": "synthetic_demo"},
            {"currency": "EUR", "as_of_date": "2026-09-30", "gbp_per_unit": 0.87, "rate_source": "synthetic_demo"},
        ]
    )


def _make_commitments(funds: pd.DataFrame, investors: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    cid = 1
    for _, fund in funds.iterrows():
        n = int(rng.integers(22, 41))
        chosen = rng.choice(investors["investor_id"].to_numpy(), size=n, replace=False)
        weights = rng.dirichlet(np.ones(n))
        committed_total = fund["target_size"] * rng.uniform(0.82, 1.02)
        for inv, w in zip(chosen, weights):
            rows.append(
                {
                    "commitment_id": f"COM{cid:05d}",
                    "fund_id": fund["fund_id"],
                    "investor_id": str(inv),
                    "commitment_amount": round(float(committed_total * w), 2),
                    "currency": fund["base_currency"],
                    "commitment_date": pd.Timestamp(year=int(fund["vintage_year"]), month=6, day=30).date().isoformat(),
                }
            )
            cid += 1
    return pd.DataFrame(rows)


def _make_cashflows(commitments: pd.DataFrame, funds: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    fund_map = funds.set_index("fund_id").to_dict("index")
    rows = []
    cfid = 1
    today = pd.Timestamp("2026-09-30")
    for _, c in commitments.iterrows():
        vintage = int(fund_map[c["fund_id"]]["vintage_year"])
        start = pd.Timestamp(year=max(vintage, 2019), month=9, day=30)
        possible = [d for d in _quarter_ends(max(vintage, 2019), 2026) if d >= start and d <= today]
        if not possible:
            possible = [today]
        # Drawdown 55%-95% of commitment over 2-5 contribution events.
        paid_in_frac = float(rng.uniform(0.55, 0.95))
        paid_in = float(c["commitment_amount"]) * paid_in_frac
        n_contrib = min(len(possible), int(rng.integers(2, 6)))
        contrib_dates = sorted(rng.choice(possible, size=n_contrib, replace=False))
        contrib_weights = rng.dirichlet(np.ones(n_contrib))
        for dt, w in zip(contrib_dates, contrib_weights):
            rows.append(
                {
                    "cashflow_id": f"CF{cfid:07d}",
                    "fund_id": c["fund_id"],
                    "investor_id": c["investor_id"],
                    "cashflow_date": pd.Timestamp(dt).date().isoformat(),
                    "cashflow_type": "CONTRIBUTION",
                    "amount": round(float(paid_in * w), 2),
                    "currency": c["currency"],
                    "source_system": "fund_admin",
                }
            )
            cfid += 1
        # Mature vintages distribute some cash back. Keep synthetic distributions on/after
        # the first contribution so the generated series is economically plausible while
        # still allowing overlapping drawdown/distribution phases.
        age = 2026 - vintage
        if age >= 3:
            dist_frac = float(np.clip(rng.normal(0.45 + 0.09 * (age - 3), 0.18), 0.05, 1.35))
            dist_total = paid_in * dist_frac
            first_contribution = pd.Timestamp(contrib_dates[0])
            dist_candidates = [d for d in possible if pd.Timestamp(d) >= first_contribution]
            if not dist_candidates:
                dist_candidates = [possible[-1]]
            n_dist = min(len(dist_candidates), int(rng.integers(1, 5)))
            dist_dates = sorted(rng.choice(dist_candidates, size=n_dist, replace=False))
            dist_weights = rng.dirichlet(np.ones(n_dist))
            for dt, w in zip(dist_dates, dist_weights):
                rows.append(
                    {
                        "cashflow_id": f"CF{cfid:07d}",
                        "fund_id": c["fund_id"],
                        "investor_id": c["investor_id"],
                        "cashflow_date": pd.Timestamp(dt).date().isoformat(),
                        "cashflow_type": "DISTRIBUTION",
                        "amount": round(float(dist_total * w), 2),
                        "currency": c["currency"],
                        "source_system": "fund_admin",
                    }
                )
                cfid += 1
    return pd.DataFrame(rows)


def _make_nav(funds: pd.DataFrame, cashflows: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    nav_id = 1
    qends = _quarter_ends(2022, 2026)
    for _, fund in funds.iterrows():
        fcf = cashflows[cashflows["fund_id"] == fund["fund_id"]].copy()
        vintage = int(fund["vintage_year"])
        for dt in qends:
            if dt.year < max(vintage, 2022):
                continue
            upto = fcf[pd.to_datetime(fcf["cashflow_date"]) <= dt]
            contrib = float(upto.loc[upto["cashflow_type"] == "CONTRIBUTION", "amount"].sum())
            dist = float(upto.loc[upto["cashflow_type"] == "DISTRIBUTION", "amount"].sum())
            age = max((dt.year - vintage) + (dt.month / 12), 0.25)
            growth = 1 + 0.05 * min(age, 6) + rng.normal(0, 0.035)
            nav = max((contrib - dist) * growth, 0.0)
            rows.append(
                {
                    "nav_record_id": f"NAV{nav_id:06d}",
                    "fund_id": fund["fund_id"],
                    "as_of_date": dt.date().isoformat(),
                    "nav_amount": round(float(nav), 2),
                    "currency": fund["base_currency"],
                    "version": 1,
                    "is_restatement": 0,
                    "reported_at": (dt + pd.Timedelta(days=25)).date().isoformat(),
                }
            )
            nav_id += 1
    nav = pd.DataFrame(rows)
    # Add 18 restatements that preserve history and supersede original values.
    candidates = nav.sample(n=min(18, len(nav)), random_state=SEED).copy()
    restated = []
    for _, r in candidates.iterrows():
        x = r.to_dict()
        x["nav_record_id"] = f"NAV{nav_id:06d}"
        nav_id += 1
        x["version"] = 2
        x["is_restatement"] = 1
        x["nav_amount"] = round(float(r["nav_amount"] * rng.uniform(0.965, 1.04)), 2)
        x["reported_at"] = (pd.Timestamp(r["reported_at"]) + pd.Timedelta(days=int(rng.integers(15, 55)))).date().isoformat()
        restated.append(x)
    if restated:
        nav = pd.concat([nav, pd.DataFrame(restated)], ignore_index=True)
    return nav


def _make_positions(funds: pd.DataFrame, assets: pd.DataFrame, nav: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    pid = 1
    # latest quarter only - enough for exposure/concentration analytics.
    as_of = "2026-09-30"
    latest_nav = (
        nav[nav["as_of_date"] == as_of]
        .sort_values(["fund_id", "version", "reported_at"])
        .groupby("fund_id", as_index=False)
        .tail(1)
        .set_index("fund_id")["nav_amount"]
        .to_dict()
    )
    for _, fund in funds.iterrows():
        n = int(rng.integers(8, 16))
        chosen = rng.choice(assets["asset_id"].to_numpy(), size=n, replace=False)
        weights = rng.dirichlet(np.ones(n))
        total = float(latest_nav.get(fund["fund_id"], 0.0))
        for aid, w in zip(chosen, weights):
            rows.append(
                {
                    "position_id": f"POS{pid:06d}",
                    "fund_id": fund["fund_id"],
                    "asset_id": str(aid),
                    "as_of_date": as_of,
                    "fair_value": round(total * float(w), 2),
                    "currency": fund["base_currency"],
                }
            )
            pid += 1
    return pd.DataFrame(rows)


def _write_notice(pdf_path: Path, payload: Dict[str, object], variant: int = 0) -> None:
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, height - 70, "CAPITAL CALL NOTICE")
    c.setFont("Helvetica", 10)
    y = height - 110
    lines = [
        ("Fund", payload["fund_name"]),
        ("Fund ID", payload["fund_id"]),
        ("Investor ID", payload["investor_id"]),
        ("Notice Date", payload["notice_date"]),
        ("Due Date", payload["due_date"]),
        ("Currency", payload["currency"]),
        ("Call Amount", f"{float(payload['call_amount']):,.2f}"),
        ("Reference", payload["reference"]),
    ]
    if variant == 1:
        c.drawString(60, y, "Private Markets Operations - Funding Request")
        y -= 30
    for label, value in lines:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(60, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(170, y, str(value))
        y -= 24 if variant == 0 else 21
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(60, 75, "Synthetic document generated for portfolio demonstration only.")
    c.save()


def _make_documents(
    out_dir: Path,
    funds: pd.DataFrame,
    cashflows: pd.DataFrame,
    rng: np.random.Generator,
    n_docs: int,
) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    fund_names = funds.set_index("fund_id")["fund_name"].to_dict()
    contrib = cashflows[cashflows["cashflow_type"] == "CONTRIBUTION"].copy()
    sample = contrib.sample(n=min(n_docs, len(contrib)), random_state=SEED).reset_index(drop=True)
    mismatch_idx = set(rng.choice(sample.index.to_numpy(), size=min(8, len(sample)), replace=False).tolist())
    rows = []
    for i, r in sample.iterrows():
        call_amount = float(r["amount"])
        mismatch = i in mismatch_idx
        if mismatch:
            call_amount = round(call_amount * float(rng.choice([0.95, 1.05, 1.08])), 2)
        notice_date = pd.Timestamp(r["cashflow_date"]) - pd.Timedelta(days=20)
        due_date = pd.Timestamp(r["cashflow_date"])
        payload = {
            "document_id": f"DOC{i+1:04d}",
            "fund_name": fund_names[r["fund_id"]],
            "fund_id": r["fund_id"],
            "investor_id": r["investor_id"],
            "notice_date": notice_date.date().isoformat(),
            "due_date": due_date.date().isoformat(),
            "currency": r["currency"],
            "call_amount": call_amount,
            "reference": r["cashflow_id"],
            "expected_cashflow_id": r["cashflow_id"],
            "expected_match": 0 if mismatch else 1,
        }
        path = out_dir / f"{payload['document_id']}.pdf"
        _write_notice(path, payload, variant=i % 2)
        rows.append({k: payload[k] for k in payload if k != "fund_name"} | {"file_name": path.name})
    return pd.DataFrame(rows)


def _inject_quality_issues(
    commitments: pd.DataFrame,
    cashflows: pd.DataFrame,
    nav: pd.DataFrame,
    positions: pd.DataFrame,
    rng: np.random.Generator,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, int]]:
    """Inject isolated quality failures so each control can be reconciled exactly.

    Rows selected for one corruption subtype are not reused for another subtype. This makes
    generation metadata, quarantine counts and tests deterministic and auditable.
    """
    commitments = commitments.copy()
    cashflows = cashflows.copy()
    nav = nav.copy()
    positions = positions.copy()
    stats: Dict[str, int] = {}

    # Duplicate 24 otherwise-valid cashflows. Append after selecting corruption candidates so
    # currency/orphan failures cannot accidentally land on duplicate IDs.
    base_indices = cashflows.index.to_numpy()
    # Corrupt distribution rows for currency/orphan checks so quarantining deliberately bad
    # records never removes the only/earliest contribution supporting a valid distribution.
    distribution_indices = cashflows.index[cashflows["cashflow_type"].eq("DISTRIBUTION")].to_numpy()
    corruption_pool = distribution_indices if len(distribution_indices) >= 21 else base_indices
    invalid_ccy_idx = rng.choice(corruption_pool, size=min(12, len(corruption_pool)), replace=False)
    remaining_corrupt = np.setdiff1d(corruption_pool, invalid_ccy_idx)
    orphan_idx = rng.choice(remaining_corrupt, size=min(9, len(remaining_corrupt)), replace=False)
    remaining = np.setdiff1d(base_indices, np.concatenate([invalid_ccy_idx, orphan_idx]))
    dup_src_idx = rng.choice(remaining, size=min(24, len(remaining)), replace=False)

    cashflows.loc[invalid_ccy_idx, "currency"] = "GBX_BAD"
    stats["invalid_cashflow_currency"] = len(invalid_ccy_idx)

    cashflows.loc[orphan_idx, "fund_id"] = "FUND999"
    stats["orphan_cashflow_fund"] = len(orphan_idx)

    dup = cashflows.loc[dup_src_idx].copy()
    cashflows = pd.concat([cashflows, dup], ignore_index=True)
    stats["duplicate_cashflow_rows"] = len(dup)

    idx = rng.choice(commitments.index.to_numpy(), size=min(6, len(commitments)), replace=False)
    commitments.loc[idx, "commitment_amount"] = -abs(commitments.loc[idx, "commitment_amount"])
    stats["negative_commitment"] = len(idx)

    idx = rng.choice(nav.index.to_numpy(), size=min(5, len(nav)), replace=False)
    nav.loc[idx, "nav_amount"] = -abs(nav.loc[idx, "nav_amount"])
    stats["negative_nav"] = len(idx)

    idx = rng.choice(positions.index.to_numpy(), size=min(7, len(positions)), replace=False)
    positions.loc[idx, "asset_id"] = "AST9999"
    stats["orphan_position_asset"] = len(idx)
    return commitments, cashflows, nav, positions, stats


def generate_dataset(root: Path, cfg: GenerationConfig = GenerationConfig()) -> Dict[str, object]:
    rng = np.random.default_rng(cfg.seed)
    random.seed(cfg.seed)
    raw = root / "data" / "raw"
    docs = root / "data" / "documents"
    raw.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    # Make repeated runs idempotent: remove only generated inputs, never repository placeholders.
    for old_file in raw.glob("*.csv"):
        old_file.unlink()
    for old_file in raw.glob("*.json"):
        old_file.unlink()
    for old_file in docs.glob("*.pdf"):
        old_file.unlink()

    funds = _make_funds(cfg, rng)
    investors = _make_investors(cfg, rng)
    assets = _make_assets(cfg, rng)
    fx_rates = _make_fx_rates()
    commitments = _make_commitments(funds, investors, rng)
    cashflows = _make_cashflows(commitments, funds, rng)
    nav = _make_nav(funds, cashflows, rng)
    positions = _make_positions(funds, assets, nav, rng)
    doc_manifest = _make_documents(docs, funds, cashflows, rng, cfg.n_documents)

    commitments, cashflows, nav, positions, issue_stats = _inject_quality_issues(
        commitments, cashflows, nav, positions, rng
    )

    tables = {
        "funds": funds,
        "investors": investors,
        "assets": assets,
        "fx_rates": fx_rates,
        "commitments": commitments,
        "cashflows": cashflows,
        "nav": nav,
        "positions": positions,
        "document_manifest": doc_manifest,
    }
    for name, df in tables.items():
        df.to_csv(raw / f"{name}.csv", index=False)

    meta = {
        "seed": cfg.seed,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "row_counts": {name: int(len(df)) for name, df in tables.items()},
        "injected_quality_issues": issue_stats,
        "document_mismatches": int((doc_manifest["expected_match"] == 0).sum()),
    }
    (raw / "generation_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(generate_dataset(args.root), indent=2))
