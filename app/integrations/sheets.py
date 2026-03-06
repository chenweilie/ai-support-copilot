"""
Integration: Google Sheets write-back using gspread.
Appends each processed ticket as a row in the configured spreadsheet.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

import gspread
from google.oauth2.service_account import Credentials

from app.observability.logger import get_logger
from app.observability.metrics import SHEETS_WRITE_TOTAL

if TYPE_CHECKING:
    from app.models import TicketResult

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Ticket ID",
    "Processed At",
    "Category",
    "Confidence",
    "Needs Review",
    "Status",
    "Priority",
    "Sentiment",
    "Action Items",
    "Summary",
    "Reply Draft",
    "Latency (ms)",
    "Errors",
]


def _get_client() -> gspread.Client:
    creds_json = os.environ.get("GOOGLE_CREDS_JSON", "")
    if creds_json:
        import io
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds_path = os.environ.get("GOOGLE_CREDS_PATH", "credentials.json")
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _ensure_headers(sheet: gspread.Worksheet) -> None:
    """Add header row if sheet is empty."""
    existing = sheet.row_values(1)
    if not existing:
        sheet.append_row(HEADERS, value_input_option="RAW")
        logger.info("Added header row to Google Sheet")


async def write_ticket_to_sheet(result: "TicketResult") -> bool:
    """Append a ticket result as a new row in Google Sheets."""
    spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Tickets")

    if not spreadsheet_id:
        logger.warning("GOOGLE_SHEET_ID not set — skipping Sheets write")
        return False

    try:
        gc = _get_client()
        sh = gc.open_by_key(spreadsheet_id)

        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=sheet_name, rows=1000, cols=len(HEADERS))
            logger.info(f"Created worksheet '{sheet_name}'")

        _ensure_headers(worksheet)

        row = [
            result.ticket_id,
            result.processed_at.isoformat(),
            result.category.value,
            round(result.confidence, 3),
            "Yes" if result.needs_review else "No",
            result.status.value,
            result.extract.priority.value,
            result.extract.sentiment.value,
            "; ".join(result.extract.action_items),
            result.extract.summary,
            result.draft.reply_draft,
            round(result.latency_ms, 1),
            "; ".join(result.errors) if result.errors else "",
        ]

        worksheet.append_row(row, value_input_option="RAW")
        SHEETS_WRITE_TOTAL.labels(status="success").inc()
        logger.info(f"Ticket {result.ticket_id} written to Google Sheets")
        return True

    except Exception as e:
        SHEETS_WRITE_TOTAL.labels(status="error").inc()
        logger.error(f"Google Sheets write failed for {result.ticket_id}: {e}")
        # Fallback: write to local JSON
        _local_fallback(result)
        return False


def _local_fallback(result: "TicketResult") -> None:
    """Write to local JSONL file as fallback when Sheets is unavailable."""
    import json
    fallback_path = "logs/sheets_fallback.jsonl"
    os.makedirs("logs", exist_ok=True)
    with open(fallback_path, "a") as f:
        f.write(result.model_dump_json() + "\n")
    logger.info(f"Ticket {result.ticket_id} saved to local fallback: {fallback_path}")
