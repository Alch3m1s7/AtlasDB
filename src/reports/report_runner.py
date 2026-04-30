import os
import time
from datetime import datetime, timedelta, timezone

from auth.spapi_auth import get_access_token
from config.marketplaces import MARKETPLACES
from config.report_types import REPORT_TYPES
from db.audit_runs import start_ingestion_run, finish_ingestion_run, fail_ingestion_run
from reports.report_downloads import get_report_document, download_report
from reports.report_exports import export_rows_to_jsonl
from reports.report_parsers import parse_tab_delimited_report
from reports.report_requests import create_report, get_report_status, get_recent_done_report

# TODO: add Google Sheets export layer after raw/JSONL/audit is validated per marketplace

_PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed")

# Poll schedule: wait between each status check.  Covers ~10 minutes total.
_POLL_DELAYS = [30, 45, 60, 90, 120, 120, 120, 120]


def _resolve_token(marketplace_code: str, mkt: dict) -> tuple[str, str]:
    token_source = next((v for v in mkt["token_env_vars"] if os.getenv(v)), None)
    refresh_token = os.getenv(token_source) if token_source else None
    if not refresh_token:
        raise RuntimeError(
            f"[{marketplace_code}] No refresh token found. Set one of: {mkt['token_env_vars']}"
        )
    return refresh_token, token_source


def _fail(run_id: str, report_id: str | None, error_msg: str, marketplace: str, report_key: str, report_type: str, document_id: str | None, raw_path: str | None, status: str) -> dict:
    fail_ingestion_run(run_id=run_id, error_message=error_msg, report_id=report_id)
    return {
        "marketplace": marketplace,
        "report_key": report_key,
        "report_type": report_type,
        "report_id": report_id,
        "report_document_id": document_id,
        "raw_path": raw_path,
        "jsonl_path": None,
        "row_count": 0,
        "status": status,
        "error": error_msg,
    }


def run_report(marketplace_code: str, report_key: str) -> dict:
    mkt = MARKETPLACES.get(marketplace_code)
    if not mkt:
        raise ValueError(f"Unknown marketplace: {marketplace_code!r}")

    rtype_cfg = REPORT_TYPES.get(report_key)
    if not rtype_cfg:
        raise ValueError(f"Unknown report key: {report_key!r}")

    report_type = rtype_cfg["report_type"]
    base_url = mkt["base_url"]
    marketplace_id = mkt["marketplace_id"]

    refresh_token, token_source = _resolve_token(marketplace_code, mkt)
    access_token = get_access_token(refresh_token)
    print(f"[{marketplace_code}/{report_key}] token={token_source} OK")

    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%Y%m%d_%H%M%S")

    run_id = start_ingestion_run(source="ingest-report", report_type=report_type)

    # Compute date range for time-windowed reports
    data_start_time = None
    data_end_time = None
    if rtype_cfg["date_range_days"]:
        data_end_time = now_utc.isoformat()
        data_start_time = (now_utc - timedelta(days=rtype_cfg["date_range_days"])).isoformat()
        print(f"[{marketplace_code}/{report_key}] date range: {data_start_time} -> {data_end_time}")

    # Try to reuse a recent DONE report when safe to do so
    report_id = None
    document_id = None
    reused = False

    if rtype_cfg["reuse_done"] and rtype_cfg["reuse_window_hours"]:
        created_since = (now_utc - timedelta(hours=rtype_cfg["reuse_window_hours"])).isoformat()
        try:
            recent = get_recent_done_report(
                base_url, access_token, report_type, marketplace_id,
                created_since_iso=created_since,
            )
        except Exception as e:
            print(f"[{marketplace_code}/{report_key}] Warning: could not check recent reports: {e}")
            recent = None

        if recent:
            document_id = recent.get("reportDocumentId")
            report_id = recent.get("reportId")
            reused = True
            print(f"[{marketplace_code}/{report_key}] Reusing DONE report: {report_id}")

    if not reused:
        try:
            report_id = create_report(
                base_url, access_token, marketplace_id, report_type,
                data_start_time=data_start_time,
                data_end_time=data_end_time,
            )
        except Exception as e:
            return _fail(run_id, None, f"create_report failed: {e}", marketplace_code, report_key, report_type, None, None, "FAILED_CREATE")

        print(f"[{marketplace_code}/{report_key}] Created report: {report_id}")

        done = False
        for attempt, delay in enumerate(_POLL_DELAYS):
            print(f"[{marketplace_code}/{report_key}] Waiting {delay}s (poll {attempt + 1}/{len(_POLL_DELAYS)})...")
            time.sleep(delay)

            try:
                status = get_report_status(base_url, access_token, report_id)
            except Exception as e:
                print(f"[{marketplace_code}/{report_key}] Poll {attempt + 1} error: {e}")
                continue

            processing_status = status.get("processingStatus")
            document_id = status.get("reportDocumentId")
            print(f"[{marketplace_code}/{report_key}] Poll {attempt + 1}/{len(_POLL_DELAYS)}: {processing_status}")

            if processing_status == "DONE":
                done = True
                break

            if processing_status in ("FATAL", "CANCELLED"):
                err_msg = (
                    f"Report {processing_status}: reportId={report_id}  "
                    f"reportDocumentId={document_id or 'none'}"
                )
                print(f"[{marketplace_code}/{report_key}] {err_msg}")
                return _fail(run_id, report_id, err_msg, marketplace_code, report_key, report_type, document_id, None, f"FAILED_{processing_status}")

        if not done:
            err_msg = f"Polling window exceeded without DONE status: reportId={report_id}"
            return _fail(run_id, report_id, err_msg, marketplace_code, report_key, report_type, None, None, "FAILED_TIMEOUT")

    if not document_id:
        err_msg = f"No reportDocumentId: reportId={report_id}"
        return _fail(run_id, report_id, err_msg, marketplace_code, report_key, report_type, None, None, "FAILED_NO_DOCUMENT")

    # Download raw file
    try:
        doc = get_report_document(base_url, access_token, document_id)
        raw_filename = f"{marketplace_code}_{report_key}_{timestamp}.txt"
        raw_path = download_report(
            url=doc["url"],
            compression_algorithm=doc.get("compressionAlgorithm"),
            filename=raw_filename,
        )
        print(f"[{marketplace_code}/{report_key}] Downloaded: {raw_path}")
    except Exception as e:
        return _fail(run_id, report_id, f"Download failed: {e}", marketplace_code, report_key, report_type, document_id, None, "FAILED_DOWNLOAD")

    # Parse
    try:
        rows = parse_tab_delimited_report(raw_path)
    except Exception as e:
        return _fail(run_id, report_id, f"Parse failed: {e}", marketplace_code, report_key, report_type, document_id, raw_path, "FAILED_PARSE")

    row_count = len(rows)
    print(f"[{marketplace_code}/{report_key}] Parsed {row_count} rows")

    # Export JSONL
    jsonl_path = os.path.join(_PROCESSED_DIR, f"{marketplace_code}_{report_key}_{timestamp}.jsonl")
    try:
        export_rows_to_jsonl(rows, jsonl_path)
        print(f"[{marketplace_code}/{report_key}] Exported: {jsonl_path}")
    except Exception as e:
        return _fail(run_id, report_id, f"JSONL export failed: {e}", marketplace_code, report_key, report_type, document_id, raw_path, "FAILED_EXPORT")

    final_status = "SUCCESS_EMPTY" if row_count == 0 else "SUCCESS"

    finish_ingestion_run(
        run_id=run_id,
        status=final_status,
        report_id=report_id,
        source_file=raw_path,
        parsed_rows=row_count,
        expected_rows=row_count,
        inserted_rows=0,
        skipped_rows=0,
        snapshot_id=None,
    )

    return {
        "marketplace": marketplace_code,
        "report_key": report_key,
        "report_type": report_type,
        "report_id": report_id,
        "report_document_id": document_id,
        "raw_path": raw_path,
        "jsonl_path": jsonl_path,
        "row_count": row_count,
        "status": final_status,
        "error": None,
    }
