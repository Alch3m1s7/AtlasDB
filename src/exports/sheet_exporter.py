import glob
import json
import os
import re
from datetime import datetime, timezone

from config.sheet_exports import BLANK_COLUMNS_BY_REPORT, EXPORT_COLUMN_ORDER, SHEET_EXPORTS

# google_sheets_client is imported lazily inside export_report so that
# --dry-run works even if the Google API packages are not yet installed.

_PROCESSED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed")
)

_LOG_HEADERS = [
    "exported_at", "marketplace", "report_key", "spreadsheet_id",
    "tab", "start_cell", "source_jsonl", "rows_exported",
    "columns_exported", "blanked_columns", "status", "error_message",
]


def _find_latest_jsonl(marketplace_code: str, report_key: str) -> str | None:
    pattern = os.path.join(_PROCESSED_DIR, f"{marketplace_code}_{report_key}_*.jsonl")
    matches = sorted(glob.glob(pattern))
    return os.path.abspath(matches[-1]) if matches else None


def _read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _to_cell(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v) if v else ""
    if isinstance(v, dict):
        return json.dumps(v)
    return v


def _col_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _exact_clear_range(tab: str, start_cell: str, col_count: int) -> str:
    """Return a range string that covers exactly col_count columns from start_cell."""
    m = re.match(r"^([A-Za-z]+)(\d+)$", start_cell)
    if not m:
        return f"{tab}!{start_cell}:ZZ"
    start_letters = m.group(1).upper()
    row = m.group(2)
    end_letters = _col_letter(_col_number(start_letters) + col_count - 1)
    return f"{tab}!{start_letters}{row}:{end_letters}"


def _build_sheet_rows(
    rows: list[dict],
    blank_col_names: set[str],
    export_columns: list[str] | None = None,
) -> tuple[list[str], list[list]]:
    """Return (headers, data_rows) ready for the Sheets API.

    export_columns (explicit mapping):
    - Use the provided list as the column order and headers.
    - Columns missing from the JSONL row are exported as "".
    - Internal _-prefixed columns are allowed (e.g. _is_valid).

    No export_columns (natural order):
    - Strip internal _-prefixed metadata keys.
    - Use the key order of the first row.

    In both modes, columns in blank_col_names have data values replaced with "".
    Headers are always written as-is; blanking never removes a column.
    """
    if not rows:
        return (export_columns if export_columns is not None else []), []

    if export_columns is not None:
        headers = export_columns
        blank_indices = {i for i, h in enumerate(headers) if h in blank_col_names}
        data_rows = []
        for row in rows:
            cells = [_to_cell(row.get(h)) for h in headers]
            for idx in blank_indices:
                cells[idx] = ""
            data_rows.append(cells)
    else:
        clean_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        headers = list(clean_rows[0].keys())
        blank_indices = {headers.index(c) for c in blank_col_names if c in headers}
        data_rows = []
        for row in clean_rows:
            cells = [_to_cell(row.get(h)) for h in headers]
            for idx in blank_indices:
                cells[idx] = ""
            data_rows.append(cells)

    return headers, data_rows


def _ensure_log_tab(service, spreadsheet_id: str, log_tab: str) -> None:
    """Create the export log tab with headers if it does not already exist."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}

    if log_tab in existing:
        return

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": log_tab}}}]},
    ).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{log_tab}!A1",
        valueInputOption="RAW",
        body={"values": [_LOG_HEADERS]},
    ).execute()
    print(f"  [sheets] Created log tab: {log_tab}")


def _append_log_row(service, spreadsheet_id: str, log_tab: str, row: list) -> None:
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{log_tab}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def export_report(marketplace_code: str, report_key: str, dry_run: bool = False) -> dict:
    mkt_cfg = SHEET_EXPORTS.get(marketplace_code)
    if not mkt_cfg:
        raise ValueError(f"No sheet config for marketplace: {marketplace_code!r}")

    report_cfg = mkt_cfg["reports"].get(report_key)
    if not report_cfg:
        raise ValueError(f"No sheet config for {marketplace_code}/{report_key!r}")

    spreadsheet_id = mkt_cfg["spreadsheet_id"]
    tab = report_cfg["tab"]
    start_cell = report_cfg["start_cell"]
    log_tab = mkt_cfg["log_tab"]
    blank_col_names = BLANK_COLUMNS_BY_REPORT.get(report_key, set())
    export_columns = EXPORT_COLUMN_ORDER.get(report_key)  # None → natural JSONL order

    # --- Locate and read JSONL (no auth needed) ---
    jsonl_path = _find_latest_jsonl(marketplace_code, report_key)
    if not jsonl_path:
        err = (
            f"No JSONL found matching "
            f"{marketplace_code}_{report_key}_*.jsonl in {_PROCESSED_DIR}"
        )
        print(f"  ERROR: {err}")
        return {"report_key": report_key, "status": "FAILED_NO_JSONL", "error": err}

    raw_rows = _read_jsonl(jsonl_path)
    headers, data_rows = _build_sheet_rows(raw_rows, blank_col_names, export_columns)
    row_count = len(data_rows)
    col_count = len(headers)
    blanked_present = sorted(blank_col_names & set(headers))

    # Columns in the explicit mapping that are absent from the JSONL (will export blank)
    if export_columns and raw_rows:
        jsonl_keys = set(raw_rows[0].keys())
        missing_cols = [c for c in export_columns if c not in jsonl_keys]
    else:
        missing_cols = []

    clear_range = _exact_clear_range(tab, start_cell, col_count)

    # --- Dry run: print plan only, no authentication ---
    if dry_run:
        print(f"  [DRY RUN]")
        print(f"  source_jsonl   : {jsonl_path}")
        print(f"  spreadsheet_id : {spreadsheet_id}")
        print(f"  tab            : {tab}")
        print(f"  start_cell     : {start_cell}")
        print(f"  clear_range    : {clear_range}")
        print(f"  row_count      : {row_count}")
        print(f"  col_count      : {col_count}")
        print(f"  blanked_cols   : {', '.join(blanked_present) if blanked_present else '(none)'}")
        if export_columns:
            print(f"  col_mapping    : explicit ({len(export_columns)} cols)")
            print(f"  export_cols    : {export_columns}")
            if missing_cols:
                print(f"  missing→blank  : {missing_cols}")
        return {
            "report_key": report_key,
            "status": "DRY_RUN",
            "jsonl_path": jsonl_path,
            "spreadsheet_id": spreadsheet_id,
            "tab": tab,
            "start_cell": start_cell,
            "row_count": row_count,
            "col_count": col_count,
            "blanked_cols": blanked_present,
            "missing_cols": missing_cols,
            "error": None,
        }

    # --- Real write ---
    exported_at = datetime.now(timezone.utc).isoformat()
    status = "SUCCESS"
    error_message = ""
    service = None

    try:
        from exports.google_sheets_client import get_sheets_service
        service = get_sheets_service()
    except Exception as exc:
        error_message = str(exc)
        print(f"  AUTH ERROR: {error_message}")
        return {
            "report_key": report_key,
            "status": "FAILED_AUTH",
            "jsonl_path": jsonl_path,
            "error": error_message,
        }

    try:
        # Verify target tab exists — do NOT auto-create business report tabs
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_tabs = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if tab not in existing_tabs:
            raise RuntimeError(
                f"Target tab {tab!r} not found in spreadsheet {spreadsheet_id}. "
                f"Existing tabs: {sorted(existing_tabs)}"
            )

        # Clear exactly the export width — never beyond the last written column
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=clear_range,
        ).execute()

        # Write header row + data rows
        values = [headers] + data_rows
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!{start_cell}",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

        status = "SUCCESS_EMPTY" if row_count == 0 else "SUCCESS"
        print(
            f"  Written {row_count} data row(s) + 1 header → "
            f"{tab}!{start_cell}  ({col_count} cols)"
        )

    except Exception as exc:
        status = "FAILED_WRITE"
        error_message = str(exc)
        print(f"  WRITE ERROR: {error_message}")

    # Append to export log (attempt regardless of write success/failure)
    try:
        _ensure_log_tab(service, spreadsheet_id, log_tab)
        _append_log_row(service, spreadsheet_id, log_tab, [
            exported_at, marketplace_code, report_key, spreadsheet_id,
            tab, start_cell, jsonl_path, row_count, col_count,
            ", ".join(blanked_present), status, error_message,
        ])
    except Exception as log_exc:
        print(f"  [warn] Log write failed: {log_exc}")

    return {
        "report_key": report_key,
        "status": status,
        "jsonl_path": jsonl_path,
        "spreadsheet_id": spreadsheet_id,
        "tab": tab,
        "start_cell": start_cell,
        "row_count": row_count,
        "col_count": col_count,
        "blanked_cols": blanked_present,
        "error": error_message or None,
    }
