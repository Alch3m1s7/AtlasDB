"""
UI-downloaded report file importer (Keepa, Bqool).

Reads a manually downloaded XLSX or CSV file and writes it verbatim
to the configured Google Sheet tab without filtering, transformation,
or column reordering.

Supported formats: .xlsx, .xlsm, .csv
Not supported: .xls (legacy Excel) — re-save as .xlsx or export as CSV.

Usage (via CLI):
    python src/main.py import-ui-report --source keepa --marketplace US \\
        --file "C:\\path\\to\\report.xlsx" --dry-run

    python src/main.py import-ui-report --source bqool --marketplace UK \\
        --file "C:\\path\\to\\report.csv"
"""

import csv
import datetime
import json
import os
from zoneinfo import ZoneInfo

from config.ui_report_imports import UI_REPORT_IMPORTS

_LONDON_TZ = ZoneInfo("Europe/London")
_LOG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")
)


def _london_timestamp() -> str:
    """Return current Europe/London time as 'YYYY-MM-DD HH.MM'."""
    return datetime.datetime.now(_LONDON_TZ).strftime("%Y-%m-%d %H.%M")


# ---- Cell normalization ----

def _normalize_cell(v):
    """Convert a raw cell value to a type accepted by the Sheets API.

    Sheets API (valueInputOption=RAW) accepts: str, int, float, bool.
    None → ""   (empty cell)
    datetime/date → ISO string  (openpyxl returns these for date-formatted cells)
    Everything else → str()
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, (datetime.datetime, datetime.date)):
        return str(v)
    return str(v)


# ---- File readers ----

def _read_xlsx(file_path: str) -> list[list]:
    """Read an XLSX/XLSM file via openpyxl; returns list of rows."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".xls":
        raise ValueError(
            "Legacy .xls format is not supported. "
            "Open the file in Excel and save as .xlsx, or use the CSV export option."
        )
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required to read XLSX files. "
            "Run: pip install -r requirements.txt"
        )
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active
    rows = [
        [_normalize_cell(v) for v in row]
        for row in ws.iter_rows(values_only=True)
    ]
    wb.close()
    return rows


def _read_csv(file_path: str) -> list[list]:
    """Read a CSV file, trying common encodings; returns list of rows."""
    # utf-8-sig handles UTF-8 with BOM (common from Excel CSV export).
    # Fallback to cp1252 / latin-1 for older Windows-generated files.
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(file_path, encoding=enc, newline="") as fh:
                rows = [list(row) for row in csv.reader(fh)]
            return rows
        except UnicodeDecodeError:
            continue
    raise ValueError(
        f"Could not decode {os.path.basename(file_path)!r} with any of: "
        "utf-8-sig, utf-8, cp1252, latin-1. "
        "Re-save the file as UTF-8 CSV and retry."
    )


def _strip_trailing_empty_rows(rows: list[list]) -> list[list]:
    """Remove trailing rows where every cell is empty.

    Some XLSX files include thousands of blank rows below the data due to
    applied formatting; stripping them avoids writing blank rows to Sheets.
    CSV files can have trailing blank lines for the same reason.
    """
    while rows and all(v == "" or v is None for v in rows[-1]):
        rows.pop()
    return rows


def _read_file(file_path: str) -> list[list]:
    """Dispatch to the correct reader based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        rows = _read_xlsx(file_path)
    elif ext == ".csv":
        rows = _read_csv(file_path)
    else:
        raise ValueError(
            f"Unsupported file extension {ext!r}. "
            "Accepted: .xlsx, .xlsm, .csv  "
            "(Not supported: .xls — re-save as .xlsx)"
        )
    return _strip_trailing_empty_rows(rows)


# ---- Log writer ----

def _write_log(
    *,
    source: str,
    marketplace: str,
    file_path: str,
    status: str,
    row_count: int,
    col_count: int,
    spreadsheet_id: str,
    tab: str,
    clear_range: str,
    dry_run: bool,
    error: str | None,
) -> str:
    """Write a one-line JSON record to data/logs/; return the log path."""
    os.makedirs(_LOG_DIR, exist_ok=True)
    ts_file = datetime.datetime.now(_LONDON_TZ).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(_LOG_DIR, f"ui_import_{ts_file}.log")
    record = {
        "timestamp": datetime.datetime.now(_LONDON_TZ).strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "marketplace": marketplace,
        "file": os.path.basename(file_path),
        "status": status,
        "row_count": row_count,
        "col_count": col_count,
        "spreadsheet_id": spreadsheet_id,
        "tab": tab,
        "clear_range": clear_range,
        "dry_run": dry_run,
        "error": error,
    }
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return log_path


# ---- Main importer ----

def import_ui_report(
    source: str,
    marketplace: str,
    file_path: str,
    dry_run: bool = False,
) -> dict:
    """Import a manually downloaded UI report (Keepa or Bqool) into Google Sheets.

    Args:
        source      : "keepa" or "bqool"
        marketplace : "US", "CA", "UK", "DE"
        file_path   : Path to the downloaded XLSX or CSV file
        dry_run     : Read + validate only; do not write to Sheets

    Returns dict with keys:
        status, source, marketplace, file_path, spreadsheet_id, tab,
        clear_range, start_cell, row_count, col_count, error
    """
    # --- 1. Config lookup ---
    source_cfg = UI_REPORT_IMPORTS.get(source)
    if source_cfg is None:
        raise ValueError(
            f"Unknown source {source!r}. "
            f"Valid sources: {sorted(UI_REPORT_IMPORTS)}"
        )
    mkt_cfg = source_cfg.get(marketplace)
    if mkt_cfg is None:
        raise ValueError(
            f"Source {source!r} is not configured for marketplace {marketplace!r}. "
            f"Available marketplaces for {source}: {sorted(source_cfg)}"
        )

    spreadsheet_id = mkt_cfg["spreadsheet_id"]
    tab            = mkt_cfg["tab"]
    start_cell     = mkt_cfg["start_cell"]
    clear_range    = mkt_cfg["clear_range"]
    max_cols       = mkt_cfg["max_cols"]
    timestamp_cell = mkt_cfg.get("timestamp_cell")  # None → no timestamp write

    # --- 2. Validate file exists ---
    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Input file not found: {abs_path}")

    # --- 3. Read file ---
    print(f"  Reading        : {abs_path}")
    try:
        rows = _read_file(abs_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to read {os.path.basename(abs_path)!r}: {exc}") from exc

    # --- 4. Validate row count ---
    row_count = len(rows)
    col_count = len(rows[0]) if rows else 0

    if row_count == 0:
        raise ValueError(f"File contains no rows after stripping empty rows: {abs_path}")

    # --- 5. Validate column count ---
    col_check_pass = col_count <= max_cols
    print(f"  Source         : {source}")
    print(f"  Marketplace    : {marketplace}")
    print(f"  File           : {os.path.basename(abs_path)}")
    print(f"  Rows           : {row_count}  (includes header row)")
    print(f"  Columns        : {col_count}  (max allowed: {max_cols})")
    print(f"  Spreadsheet    : {spreadsheet_id}")
    print(f"  Tab            : {tab}")
    print(f"  Start cell     : {start_cell}")
    print(f"  Clear range    : {tab}!{clear_range}")
    print(f"  Col check      : {'PASS' if col_check_pass else f'FAIL — {col_count} > {max_cols}'}")

    if not col_check_pass:
        msg = (
            f"Column count mismatch: file has {col_count} columns but "
            f"{source}/{marketplace} allows at most {max_cols} "
            f"(clear range {clear_range}). "
            f"Sheet NOT modified. "
            f"If the report layout changed, update max_cols in "
            f"src/config/ui_report_imports.py and verify the clear_range is still correct."
        )
        raise ValueError(msg)

    # --- 6. Dry run: report plan only ---
    if dry_run:
        if timestamp_cell:
            print(f"  Timestamp cell : {tab}!{timestamp_cell}  (not written in dry-run)")
        print(f"  [DRY RUN] Validation passed. Sheet NOT modified.")
        return {
            "status": "DRY_RUN",
            "source": source,
            "marketplace": marketplace,
            "file_path": abs_path,
            "spreadsheet_id": spreadsheet_id,
            "tab": tab,
            "clear_range": clear_range,
            "start_cell": start_cell,
            "row_count": row_count,
            "col_count": col_count,
            "timestamp_cell": timestamp_cell,
            "error": None,
        }

    # --- 7. Authenticate with Google Sheets ---
    try:
        from exports.google_sheets_client import get_sheets_service
        service = get_sheets_service()
    except Exception as exc:
        err = f"Google Sheets auth failed: {exc}"
        print(f"  AUTH ERROR     : {err}")
        log_path = _write_log(
            source=source, marketplace=marketplace, file_path=abs_path,
            status="FAILED_AUTH", row_count=row_count, col_count=col_count,
            spreadsheet_id=spreadsheet_id, tab=tab, clear_range=clear_range,
            dry_run=dry_run, error=err,
        )
        print(f"  Log written    : {log_path}")
        return _error_result("FAILED_AUTH", source, marketplace, abs_path,
                             spreadsheet_id, tab, clear_range, start_cell,
                             row_count, col_count, err)

    # --- 8. Verify target tab exists ---
    try:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_tabs = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if tab not in existing_tabs:
            raise RuntimeError(
                f"Target tab {tab!r} not found in spreadsheet {spreadsheet_id}. "
                f"Existing tabs: {sorted(existing_tabs)}. "
                f"Create the tab manually and re-run."
            )
    except Exception as exc:
        err = f"Spreadsheet access failed: {exc}"
        print(f"  SHEET ERROR    : {err}")
        log_path = _write_log(
            source=source, marketplace=marketplace, file_path=abs_path,
            status="FAILED_SHEET_CHECK", row_count=row_count, col_count=col_count,
            spreadsheet_id=spreadsheet_id, tab=tab, clear_range=clear_range,
            dry_run=dry_run, error=err,
        )
        print(f"  Log written    : {log_path}")
        return _error_result("FAILED_SHEET_CHECK", source, marketplace, abs_path,
                             spreadsheet_id, tab, clear_range, start_cell,
                             row_count, col_count, err)

    # --- 9. Clear contents only (preserves formatting) ---
    full_clear_range = f"{tab}!{clear_range}"
    try:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=full_clear_range,
        ).execute()
        print(f"  Cleared        : {full_clear_range}")
    except Exception as exc:
        err = f"Clear failed: {exc}"
        print(f"  CLEAR ERROR    : {err}")
        log_path = _write_log(
            source=source, marketplace=marketplace, file_path=abs_path,
            status="FAILED_CLEAR", row_count=row_count, col_count=col_count,
            spreadsheet_id=spreadsheet_id, tab=tab, clear_range=clear_range,
            dry_run=dry_run, error=err,
        )
        print(f"  Log written    : {log_path}")
        return _error_result("FAILED_CLEAR", source, marketplace, abs_path,
                             spreadsheet_id, tab, clear_range, start_cell,
                             row_count, col_count, err)

    # --- 10. Write rows starting at start_cell ---
    write_range = f"{tab}!{start_cell}"
    try:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=write_range,
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
        print(f"  Written        : {row_count} rows × {col_count} cols → {write_range}")
    except Exception as exc:
        err = f"Write failed: {exc}"
        print(f"  WRITE ERROR    : {err}")
        log_path = _write_log(
            source=source, marketplace=marketplace, file_path=abs_path,
            status="FAILED_WRITE", row_count=row_count, col_count=col_count,
            spreadsheet_id=spreadsheet_id, tab=tab, clear_range=clear_range,
            dry_run=dry_run, error=err,
        )
        print(f"  Log written    : {log_path}")
        return _error_result("FAILED_WRITE", source, marketplace, abs_path,
                             spreadsheet_id, tab, clear_range, start_cell,
                             row_count, col_count, err)

    # --- 11. Write timestamp to configured cell (only on success) ---
    if timestamp_cell:
        ts = _london_timestamp()
        try:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{tab}!{timestamp_cell}",
                valueInputOption="RAW",
                body={"values": [[ts]]},
            ).execute()
            print(f"  Timestamp written: {tab}!{timestamp_cell} = {ts}")
        except Exception as exc:
            # Non-fatal: data was written successfully; warn but do not fail.
            print(f"  [warn] Timestamp write failed for {tab}!{timestamp_cell}: {exc}")

    # --- 12. Write log and return ---
    log_path = _write_log(
        source=source, marketplace=marketplace, file_path=abs_path,
        status="SUCCESS", row_count=row_count, col_count=col_count,
        spreadsheet_id=spreadsheet_id, tab=tab, clear_range=clear_range,
        dry_run=dry_run, error=None,
    )
    print(f"  Log written    : {log_path}")

    return {
        "status": "SUCCESS",
        "source": source,
        "marketplace": marketplace,
        "file_path": abs_path,
        "spreadsheet_id": spreadsheet_id,
        "tab": tab,
        "clear_range": clear_range,
        "start_cell": start_cell,
        "row_count": row_count,
        "col_count": col_count,
        "timestamp_cell": timestamp_cell,
        "error": None,
    }


def _error_result(
    status: str, source: str, marketplace: str, file_path: str,
    spreadsheet_id: str, tab: str, clear_range: str, start_cell: str,
    row_count: int, col_count: int, error: str,
) -> dict:
    return {
        "status": status,
        "source": source,
        "marketplace": marketplace,
        "file_path": file_path,
        "spreadsheet_id": spreadsheet_id,
        "tab": tab,
        "clear_range": clear_range,
        "start_cell": start_cell,
        "row_count": row_count,
        "col_count": col_count,
        "error": error,
    }
