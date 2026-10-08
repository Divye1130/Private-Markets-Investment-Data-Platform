from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

from pypdf import PdfReader


@dataclass
class NoticeExtraction:
    document_id: str
    file_name: str
    fund_id: Optional[str]
    investor_id: Optional[str]
    notice_date: Optional[str]
    due_date: Optional[str]
    currency: Optional[str]
    call_amount: Optional[float]
    reference: Optional[str]
    extraction_method: str
    extraction_confidence: float
    validation_status: str
    validation_message: str


def _search(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def deterministic_extract(path: Path) -> NoticeExtraction:
    text = extract_pdf_text(path)
    fund_id = _search(r"Fund ID:\s*([A-Z0-9]+)", text)
    investor_id = _search(r"Investor ID:\s*([A-Z0-9]+)", text)
    notice_date = _search(r"Notice Date:\s*(\d{4}-\d{2}-\d{2})", text)
    due_date = _search(r"Due Date:\s*(\d{4}-\d{2}-\d{2})", text)
    currency = _search(r"Currency:\s*([A-Z]{3})", text)
    amount_raw = _search(r"Call Amount:\s*([0-9,]+\.\d{2})", text)
    reference = _search(r"Reference:\s*([A-Z0-9]+)", text)
    amount = float(amount_raw.replace(",", "")) if amount_raw else None
    fields = [fund_id, investor_id, notice_date, due_date, currency, amount, reference]
    present = sum(v is not None for v in fields)
    confidence = present / len(fields)
    errors = []
    if present < len(fields):
        errors.append(f"missing {len(fields) - present} required fields")
    if currency and currency not in {"GBP", "USD", "EUR"}:
        errors.append("unsupported currency")
    if amount is not None and amount <= 0:
        errors.append("non-positive call amount")
    return NoticeExtraction(
        document_id=path.stem,
        file_name=path.name,
        fund_id=fund_id,
        investor_id=investor_id,
        notice_date=notice_date,
        due_date=due_date,
        currency=currency,
        call_amount=amount,
        reference=reference,
        extraction_method="deterministic_pdf_text",
        extraction_confidence=round(confidence, 3),
        validation_status="REVIEW" if errors else "PASS",
        validation_message="; ".join(errors) if errors else "schema checks passed",
    )


class DatabricksModelServingExtractor:
    """Optional integration point for Databricks Model Serving / Mosaic AI.

    This adapter is intentionally not invoked by the local reference build because the
    execution environment has no Databricks workspace or credentials. It documents the
    production seam: PDF/text -> model endpoint -> typed fields -> deterministic validation.
    """

    def __init__(self, endpoint_name: Optional[str] = None):
        self.endpoint_name = endpoint_name or os.getenv("DATABRICKS_MODEL_ENDPOINT")
        self.host = os.getenv("DATABRICKS_HOST")
        self.token = os.getenv("DATABRICKS_TOKEN")

    def configured(self) -> bool:
        return bool(self.endpoint_name and self.host and self.token)

    def extract(self, path: Path) -> Dict[str, object]:
        raise RuntimeError(
            "Databricks Model Serving integration is a deployment adapter only in this repository. "
            "Configure a workspace endpoint and implement the HTTPS call before production use."
        )


def extraction_to_dict(x: NoticeExtraction) -> Dict[str, object]:
    return asdict(x)
