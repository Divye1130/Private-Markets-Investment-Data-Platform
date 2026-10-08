# Databricks notebook source
# Production seam: document -> extracted text -> model endpoint -> typed schema -> deterministic reconciliation.
# The repository's verified local build uses deterministic PDF text extraction and the same reconciliation controls.

from dataclasses import dataclass
from typing import Optional

@dataclass
class CapitalCall:
    fund_id: str
    investor_id: str
    notice_date: str
    due_date: str
    currency: str
    call_amount: float
    reference: str

# In a live workspace, replace this stub with your approved Mosaic AI / Model Serving endpoint.
def model_extract(document_text: str) -> CapitalCall:
    raise NotImplementedError("Connect an approved Databricks Model Serving endpoint in your workspace.")

# Deterministic controls remain mandatory after model extraction:
# 1) schema/type validation
# 2) allowed-currency validation
# 3) positive-amount validation
# 4) fund/investor master-data checks
# 5) reconciliation against the referenced ledger cashflow
# 6) route mismatches or low confidence to human review
