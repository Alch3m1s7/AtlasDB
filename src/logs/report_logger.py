import json
import os
from datetime import datetime, timezone

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs", "report_runs.jsonl")


def _append(record: dict) -> None:
    log_path = os.path.abspath(LOG_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def log_report_created(region: str, marketplace_id: str, report_type: str, report_id: str) -> None:
    _append({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "region": region,
        "marketplace_id": marketplace_id,
        "report_type": report_type,
        "report_id": report_id,
        "status": "CREATED",
    })


def log_status_checked(report_id: str, processing_status: str, report_document_id: str) -> None:
    _append({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "report_id": report_id,
        "processingStatus": processing_status,
        "reportDocumentId": report_document_id,
    })


def log_report_downloaded(report_document_id: str, saved_path: str) -> None:
    _append({
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "reportDocumentId": report_document_id,
        "saved_path": saved_path,
    })


def log_fatal_status(report_id: str, processing_status: str, status_body: dict) -> None:
    _append({
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "event": "FATAL_STATUS",
        "report_id": report_id,
        "processingStatus": processing_status,
        "status_body": status_body,
    })


def log_ingest_result(
    source_file: str,
    status: str,
    expected_rows: int,
    inserted_rows: int,
    skipped_rows: int,
    report_id: str | None = None,
    report_document_id: str | None = None,
    marketplace_id: str | None = None,
    report_type: str | None = None,
    reused_existing_report: bool | None = None,
) -> None:
    record: dict = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "event": "INGEST_RESULT",
        "source_file": source_file,
        "status": status,
        "expected_rows": expected_rows,
        "inserted_rows": inserted_rows,
        "skipped_rows": skipped_rows,
    }
    if report_id is not None:
        record["report_id"] = report_id
    if report_document_id is not None:
        record["report_document_id"] = report_document_id
    if marketplace_id is not None:
        record["marketplace_id"] = marketplace_id
    if report_type is not None:
        record["report_type"] = report_type
    if reused_existing_report is not None:
        record["reused_existing_report"] = reused_existing_report
    _append(record)
