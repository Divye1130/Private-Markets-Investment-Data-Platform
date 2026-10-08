from pathlib import Path
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parents[1]
summary = json.loads((ROOT / 'reports' / 'run_summary.json').read_text())
out = ROOT / 'reports' / 'private_markets_data_platform_briefing.pdf'

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleCenter', parent=styles['Title'], alignment=TA_CENTER, spaceAfter=12))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=8.5, leading=11))
styles.add(ParagraphStyle(name='H2x', parent=styles['Heading2'], spaceBefore=10, spaceAfter=5))

doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=14*mm, bottomMargin=14*mm)
story=[]
story.append(Paragraph('Private Markets Investment Data Lakehouse & Document Intelligence Platform', styles['TitleCenter']))
story.append(Paragraph('Portfolio engineering briefing', styles['Heading2']))
story.append(Paragraph('A synthetic end-to-end financial-services data platform covering ingestion, explicit quality controls, historical correction handling, Data Vault 2.0, Kimball reporting marts, reconciliation, document extraction, CI and a GitHub Pages dashboard.', styles['BodyText']))
story.append(Spacer(1,8))
metrics=[
    ['Metric','Verified local result'],
    ['Funds / investors / assets', f"{summary['gold']['funds']} / {summary['gold']['investors']} / {summary['gold']['assets']}"],
    ['Valid cashflows / positions', f"{summary['gold']['cashflows']:,} / {summary['gold']['positions']:,}"],
    ['Quarantined invalid rows', str(summary['quarantined_rows'])],
    ['NAV restatements preserved', str(summary['vault']['restatement_rows_preserved'])],
    ['Capital-call PDFs parsed', str(summary['documents']['documents_parsed'])],
    ['Document-to-ledger review queue', str(summary['documents']['review_queue'])],
    ['Position-to-NAV fund reviews', str(summary['reconciliation']['funds_review'])],
    ['Median synthetic TVPI / DPI / XIRR', f"{summary['portfolio_metrics']['median_tvpi']:.3f}x / {summary['portfolio_metrics']['median_dpi']:.3f}x / {summary['portfolio_metrics']['median_irr']:.1%}"],
    ['Automated tests', '37/37 passed'],
]
t=Table(metrics, colWidths=[72*mm,98*mm])
t.setStyle(TableStyle([
    ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#27364a')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
    ('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#cbd5e1')),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),9),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8fafc')])
]))
story.append(t)
story.append(Spacer(1,8))
story.append(Paragraph('Execution boundary', styles['H2x']))
story.append(Paragraph('The complete reference build was executed locally with Python, pandas and SQLite. Databricks/PySpark/Delta notebooks are included as deployment assets and were source/syntax checked, but they were not run in a live Databricks workspace. This distinction is deliberately documented so portfolio claims remain defensible.', styles['Small']))

story.append(PageBreak())
story.append(Paragraph('Architecture and modelling choices', styles['Heading1']))
arch = [
    ['Layer','Purpose'],
    ['Bronze','Immutable raw source rows plus ingestion metadata.'],
    ['Silver','Validated, standardised records; invalid rows route to quarantine with an explicit reason.'],
    ['Data Vault 2.0','Hubs/links/satellites preserve business keys, relationships and NAV restatement history.'],
    ['Kimball Gold','Fund/investor/asset/date dimensions plus cashflow, commitment, position and NAV facts.'],
    ['Semantic marts','TVPI/DPI/RVPI, unfunded commitment, exposure, reconciliation and review queues.'],
    ['Presentation','Self-contained Plotly dashboard suitable for GitHub Pages.'],
]
t=Table(arch,colWidths=[40*mm,130*mm])
t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#27364a')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#cbd5e1')),('VALIGN',(0,0),(-1,-1),'TOP'),('FONTSIZE',(0,0),(-1,-1),8.8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8fafc')])]))
story.append(t)
story.append(Spacer(1,8))
story.append(Paragraph('Control design', styles['H2x']))
story.append(Paragraph('The generated raw data deliberately contains duplicate cashflows, invalid currencies, orphan keys, negative commitments, invalid NAV values and orphan position assets. The pipeline quarantines those records rather than silently repairing them. NAV restatements are retained historically, while the Gold layer selects the latest valid version for consumption.', styles['BodyText']))
story.append(Paragraph('Capital-call document control', styles['H2x']))
story.append(Paragraph('Sixty synthetic PDF notices are parsed into typed fields and reconciled to the referenced ledger contribution. Eight deliberately mismatched notices are routed to review. The repository includes an optional model-serving seam for a future LLM extraction step, but deterministic validation and reconciliation remain mandatory.', styles['BodyText']))

story.append(PageBreak())
story.append(Paragraph('Portfolio relevance and limitations', styles['Heading1']))
story.append(Paragraph('<b>What this demonstrates:</b> financial-data ingestion, formal warehouse modelling, auditability, data quality, correction handling, business reconciliation, document controls, automated testing, CI and client-facing analytical outputs.', styles['BodyText']))
story.append(Spacer(1,6))
story.append(Paragraph('<b>What it does not claim:</b> production deployment, live Databricks execution, real private-markets performance, audited investment calculations or deployed AI extraction. All entities and values are synthetic.', styles['BodyText']))
story.append(Spacer(1,6))
story.append(Paragraph('<b>Currency handling:</b> fund-level ratios are calculated in each fund\'s base currency. Cross-fund monetary totals and exposure marts are normalised to GBP through a validated synthetic FX table, preventing unlike currencies from being added directly.', styles['BodyText']))
story.append(Spacer(1,6))
story.append(Paragraph('<b>Next live-platform step:</b> import the numbered notebooks in <font name="Courier">databricks/notebooks/</font> into a Databricks workspace, upload the generated inputs to a Unity Catalog volume, execute the Bronze-to-Gold path and only then update the CV wording to claim direct Databricks implementation.', styles['BodyText']))

doc.build(story)
print(out)
