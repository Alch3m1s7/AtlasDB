import glob
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.sheet_exports import (
    BLANK_COLUMNS_BY_REPORT,
    EXPORT_COLUMN_ORDER,
    NUMERIC_COLUMNS,
    NUMBER_FORMAT_SPECS,
    SHEET_EXPORTS,
)

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

_LONDON_TZ = ZoneInfo("Europe/London")

_DIAG_FIELDS = ["seller-sku", "asin1", "item-name"]


def _london_timestamp() -> str:
    return datetime.now(_LONDON_TZ).strftime("%Y-%m-%d %H.%M")


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


def _convert_cell(v, col_name: str, int_cols: set, decimal_cols: set) -> tuple:
    """Return (converted_value, warning_count).

    Numeric columns: strip commas, parse to int or float.
    Empty/null → ("", 0).  Unparseable → ("", 1) with a warning.
    Non-numeric columns fall through to _to_cell unchanged.
    """
    if col_name not in int_cols and col_name not in decimal_cols:
        return _to_cell(v), 0
    if v is None:
        return "", 0
    s = str(v).strip().replace(",", "")
    if not s:
        return "", 0
    try:
        if col_name in int_cols:
            return int(float(s)), 0
        return float(s), 0
    except (ValueError, TypeError):
        return "", 1


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


def _a1_range_to_grid_range(sheet_id: int, a1_range: str) -> dict:
    """Convert an A1-notation range (no sheet prefix) to a Sheets API GridRange.

    endRowIndex is omitted for open-ended ranges (formats to bottom of sheet).
    endColumnIndex is always exclusive per the Sheets API spec.
    """
    m = re.match(r"^([A-Za-z]+)(\d+)?(?::([A-Za-z]+)(\d+)?)?$", a1_range)
    if not m:
        raise ValueError(f"Cannot parse A1 range: {a1_range!r}")
    start_col = _col_number(m.group(1)) - 1          # 0-indexed inclusive
    start_row = int(m.group(2)) - 1 if m.group(2) else 0
    end_col = _col_number(m.group(3)) if m.group(3) else start_col + 1  # exclusive
    end_row = int(m.group(4)) if m.group(4) else None
    result = {
        "sheetId": sheet_id,
        "startRowIndex": start_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }
    if end_row is not None:
        result["endRowIndex"] = end_row
    return result


_FMT_OBJECTS = {
    "text":    {"type": "TEXT"},
    "int":     {"type": "NUMBER", "pattern": "0"},
    "decimal": {"type": "NUMBER", "pattern": "0.00"},
}


def _apply_number_formats(
    service,
    spreadsheet_id: str,
    sheet_id: int,
    format_specs: list[tuple[str, str]],
) -> list[str]:
    """Apply number formats via a single batchUpdate; return list of applied range strings."""
    requests = []
    for a1_range, fmt_type in format_specs:
        requests.append({
            "repeatCell": {
                "range": _a1_range_to_grid_range(sheet_id, a1_range),
                "cell": {"userEnteredFormat": {"numberFormat": _FMT_OBJECTS[fmt_type]}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    return [f"{r} ({t})" for r, t in format_specs]


def _build_sheet_rows(
    rows: list[dict],
    blank_col_names: set[str],
    export_columns: list[str] | None = None,
    int_cols: set[str] | None = None,
    decimal_cols: set[str] | None = None,
) -> tuple[list[str], list[list], int]:
    """Return (headers, data_rows, conversion_warnings) ready for the Sheets API.

    Numeric columns (int_cols / decimal_cols) are converted to Python int/float.
    Empty/null stays blank; unparseable values become blank and increment warnings.
    Blanked columns (blank_col_names) are zeroed out after conversion.
    """
    int_cols = int_cols or set()
    decimal_cols = decimal_cols or set()
    warnings = 0

    if not rows:
        return (export_columns if export_columns is not None else []), [], 0

    if export_columns is not None:
        headers = export_columns
        blank_indices = {i for i, h in enumerate(headers) if h in blank_col_names}
        data_rows = []
        for row in rows:
            cells = []
            for h in headers:
                val, w = _convert_cell(row.get(h), h, int_cols, decimal_cols)
                cells.append(val)
                warnings += w
            for idx in blank_indices:
                cells[idx] = ""
            data_rows.append(cells)
    else:
        clean_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        headers = list(clean_rows[0].keys())
        blank_indices = {headers.index(c) for c in blank_col_names if c in headers}
        data_rows = []
        for row in clean_rows:
            cells = []
            for h in headers:
                val, w = _convert_cell(row.get(h), h, int_cols, decimal_cols)
                cells.append(val)
                warnings += w
            for idx in blank_indices:
                cells[idx] = ""
            data_rows.append(cells)

    return headers, data_rows, warnings


def _ensure_log_tab(service, spreadsheet_id: str, log_tab: str) -> None:
    """Ensure the export log tab exists with headers in row 3.

    Layout: A1 = last-updated timestamp, row 2 = blank, row 3 = headers,
    row 4+ = log data.  This is idempotent — safe to call on existing tabs
    that previously had headers in row 1.
    """
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}

    if log_tab not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": log_tab}}}]},
        ).execute()
        print(f"  [sheets] Created log tab: {log_tab}")

    # Always (re)write headers to row 3 — handles both new tabs and old tabs
    # that had headers in row 1 before the A1-timestamp layout was introduced.
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{log_tab}!A3",
        valueInputOption="RAW",
        body={"values": [_LOG_HEADERS]},
    ).execute()


def _append_log_row(service, spreadsheet_id: str, log_tab: str, row: list, ts: str) -> None:
    # Append after the last data row below row 3 (headers row)
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{log_tab}!A3",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    # A1 of the log tab = last-updated timestamp
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{log_tab}!A1",
        valueInputOption="RAW",
        body={"values": [[ts]]},
    ).execute()
    print(f"  Timestamp written: {log_tab}!A1 = {ts}")


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
    numeric_cfg = NUMERIC_COLUMNS.get(report_key, {})
    int_cols = set(numeric_cfg.get("int", []))
    decimal_cols = set(numeric_cfg.get("decimal", []))
    format_specs = NUMBER_FORMAT_SPECS.get(report_key, [])

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
    headers, data_rows, warn_count = _build_sheet_rows(
        raw_rows, blank_col_names, export_columns, int_cols, decimal_cols
    )
    row_count = len(data_rows)
    col_count = len(headers)
    blanked_present = sorted(blank_col_names & set(headers))

    # Columns in the explicit mapping that are absent from the JSONL (will export blank)
    if export_columns and raw_rows:
        jsonl_keys = set(raw_rows[0].keys())
        missing_cols = [c for c in export_columns if c not in jsonl_keys]
    else:
        missing_cols = []

    # Part B: source-verification sample — first 3 rows of key diagnostic fields
    sample_data = {}
    if raw_rows:
        for f in _DIAG_FIELDS:
            vals = [str(raw_rows[i].get(f) or "") for i in range(min(3, len(raw_rows)))]
            if any(vals):
                sample_data[f] = vals

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
        if int_cols:
            print(f"  int_cols       : {sorted(int_cols)}")
        if decimal_cols:
            print(f"  decimal_cols   : {sorted(decimal_cols)}")
        for rng, ftype in format_specs:
            print(f"  fmt            : {rng} ({ftype})")
        if warn_count:
            print(f"  conv_warnings  : {warn_count}")
        if sample_data:
            print(f"  --- source data sample (first 3 rows) ---")
            for field, vals in sample_data.items():
                print(f"  {field:<30} : {' | '.join(v[:60] for v in vals)}")
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
        sheets_by_name = {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in meta.get("sheets", [])
        }
        if tab not in sheets_by_name:
            raise RuntimeError(
                f"Target tab {tab!r} not found in spreadsheet {spreadsheet_id}. "
                f"Existing tabs: {sorted(sheets_by_name)}"
            )
        sheet_id = sheets_by_name[tab]

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

        # Write last-updated timestamp to A1 of the report tab
        ts = _london_timestamp()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [[ts]]},
        ).execute()
        print(f"  Timestamp written: {tab}!A1 = {ts}")

        # Apply number formats to data rows
        if format_specs:
            applied = _apply_number_formats(service, spreadsheet_id, sheet_id, format_specs)
            for r in applied:
                print(f"  Format applied : {r}")

    except Exception as exc:
        status = "FAILED_WRITE"
        error_message = str(exc)
        ts = _london_timestamp()
        print(f"  WRITE ERROR: {error_message}")

    if warn_count:
        print(f"  Conv warnings  : {warn_count}")

    # Append to export log (attempt regardless of write success/failure)
    try:
        _ensure_log_tab(service, spreadsheet_id, log_tab)
        _append_log_row(service, spreadsheet_id, log_tab, [
            exported_at, marketplace_code, report_key, spreadsheet_id,
            tab, start_cell, jsonl_path, row_count, col_count,
            ", ".join(blanked_present), status, error_message,
        ], ts)
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
