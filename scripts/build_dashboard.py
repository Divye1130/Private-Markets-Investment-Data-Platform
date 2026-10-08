from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT_IMPORT = Path(__file__).resolve().parents[1]
if str(ROOT_IMPORT) not in sys.path:
    sys.path.insert(0, str(ROOT_IMPORT))

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "warehouse/private_markets.db"
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)


def money_gbp(v: float) -> str:
    if abs(v) >= 1e9:
        return f"£{v/1e9:,.2f}bn"
    if abs(v) >= 1e6:
        return f"£{v/1e6:,.1f}m"
    return f"£{v:,.0f}"


def money_local(v: float, currency: str) -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(str(currency), f"{currency} ")
    if abs(v) >= 1e9:
        return f"{symbol}{v/1e9:,.2f}bn"
    if abs(v) >= 1e6:
        return f"{symbol}{v/1e6:,.1f}m"
    return f"{symbol}{v:,.0f}"


def fig_html(fig, include_js=False):
    return fig.to_html(full_html=False, include_plotlyjs=True if include_js else False, config={"displayModeBar": False})


def build():
    conn = sqlite3.connect(DB)
    perf = pd.read_sql_query("select * from mart_fund_performance", conn)
    sec = pd.read_sql_query("select * from mart_exposure_sector", conn)
    reg = pd.read_sql_query("select * from mart_exposure_region", conn)
    recon = pd.read_sql_query("select * from mart_nav_position_reconciliation", conn)
    dq = pd.read_sql_query("select * from mart_data_quality", conn)
    docs = pd.read_sql_query("select * from mart_document_reconciliation", conn)
    conn.close()
    summary = json.loads((ROOT / "reports/run_summary.json").read_text())

    fig_tvpi = px.scatter(
        perf,
        x="vintage_year",
        y="tvpi",
        size="latest_nav",
        hover_name="fund_name",
        hover_data=["strategy", "dpi", "rvpi", "irr", "unfunded_commitment"],
        title="Fund performance: TVPI by vintage",
        labels={"vintage_year": "Vintage", "tvpi": "TVPI (x)"},
    )
    fig_tvpi.add_hline(y=1.0, line_dash="dash", annotation_text="1.0x")

    fig_sector = px.bar(sec, x="sector", y="fair_value_gbp", title="Latest NAV exposure by sector", labels={"fair_value_gbp": "Fair value (GBP-normalised)"})
    fig_region = px.bar(reg, x="region", y="fair_value_gbp", title="Latest NAV exposure by region", labels={"fair_value_gbp": "Fair value (GBP-normalised)"})

    rcounts = recon["status"].value_counts().rename_axis("status").reset_index(name="funds")
    fig_recon = px.pie(rcounts, names="status", values="funds", title="Position-to-NAV reconciliation")

    dcounts = docs["reconciliation_status"].value_counts().rename_axis("status").reset_index(name="documents")
    fig_docs = px.bar(dcounts, x="status", y="documents", title="Capital-call document reconciliation")

    if len(dq):
        dq_plot = dq.groupby("entity", as_index=False)["rows"].sum()
        fig_dq = px.bar(dq_plot, x="entity", y="rows", title="Quarantined rows by entity")
    else:
        fig_dq = go.Figure().update_layout(title="No quarantined rows")

    cards = [
        ("Funds", summary["gold"]["funds"]),
        ("Valid cashflows", f"{summary['gold']['cashflows']:,}"),
        ("Quarantined rows", summary["quarantined_rows"]),
        ("NAV restatements retained", summary["vault"]["restatement_rows_preserved"]),
        ("Median TVPI", f"{summary['portfolio_metrics']['median_tvpi']:.2f}x"),
        ("Portfolio NAV", money_gbp(summary["portfolio_metrics"]["total_nav_gbp"])),
        ("Document review queue", summary["documents"]["review_queue"]),
    ]
    card_html = "".join(f"<div class='card'><div class='v'>{v}</div><div class='k'>{k}</div></div>" for k, v in cards)

    table = perf.sort_values("tvpi", ascending=False)[
        ["fund_name", "strategy", "vintage_year", "base_currency", "tvpi", "dpi", "rvpi", "irr", "latest_nav", "unfunded_commitment"]
    ].head(12).copy()
    for c in ["tvpi", "dpi", "rvpi"]:
        table[c] = table[c].map(lambda x: f"{x:.2f}x")
    table["irr"] = table["irr"].map(lambda x: "-" if pd.isna(x) else f"{x:.1%}")
    table["latest_nav"] = [money_local(v, c) for v, c in zip(table["latest_nav"], table["base_currency"])]
    table["unfunded_commitment"] = [money_local(v, c) for v, c in zip(table["unfunded_commitment"], table["base_currency"])]

    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Private Markets Investment Data Platform</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f5f7fa;color:#152238}}
.wrap{{max-width:1200px;margin:auto;padding:28px}}
h1{{margin:0 0 5px}} .sub{{color:#536579;margin-bottom:22px}}
.cards{{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin:18px 0 22px}}
.card{{background:white;border:1px solid #e1e7ee;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.v{{font-size:25px;font-weight:700}} .k{{font-size:12px;color:#64748b;margin-top:5px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel{{background:white;border:1px solid #e1e7ee;border-radius:10px;padding:8px}}
.wide{{grid-column:1/-1}} table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:8px;border-bottom:1px solid #e8edf2;text-align:left}}
@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style></head>
<body><div class='wrap'>
<h1>Private Markets Investment Data Platform</h1>
<div class='sub'>Synthetic private-markets portfolio | Bronze → Silver → Data Vault 2.0 → Kimball Gold → reconciliation & document controls</div>
<div class='cards'>{card_html}</div>
<div class='grid'>
<div class='panel wide'>{fig_html(fig_tvpi, include_js=True)}</div>
<div class='panel'>{fig_html(fig_sector)}</div><div class='panel'>{fig_html(fig_region)}</div>
<div class='panel'>{fig_html(fig_recon)}</div><div class='panel'>{fig_html(fig_docs)}</div>
<div class='panel wide'>{fig_html(fig_dq)}</div>
<div class='panel wide'><h3 style='padding-left:10px'>Leading funds by synthetic TVPI</h3>{table.to_html(index=False, escape=True)}</div>
</div>
</div></body></html>"""
    (DOCS / "index.html").write_text(html, encoding="utf-8")

    # Lightweight static preview for README / quick review.
    fig, ax = plt.subplots(figsize=(10, 6))
    top = perf.sort_values("tvpi", ascending=False).head(10)
    ax.barh(top["fund_name"].str.replace("Northstar ", "", regex=False), top["tvpi"])
    ax.set_xlabel("TVPI (x)")
    ax.set_title("Private Markets Platform - synthetic fund performance preview")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(DOCS / "dashboard_preview.png", dpi=160)
    plt.close(fig)
    return DOCS / "index.html"


if __name__ == "__main__":
    print(build())
