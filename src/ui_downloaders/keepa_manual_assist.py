"""
Keepa manual-assist for CA marketplace.

Human-in-the-loop replacement for the Playwright downloader (parked after
anti-bot triggers).  No browser automation — the user's normal logged-in
browser session handles Keepa authentication entirely.

Workflow:
  1. Read CA ASINs from Google Sheets (KeepaCA!BK8:BK)
  2. Validate / deduplicate ASINs
  3. Copy ASINs to Windows clipboard (one per line, ready to paste)
  4. Open Keepa Viewer in the system default browser
  5. Print step-by-step manual instructions
  6. Wait for the user to press Enter after downloading
  7. Detect the newest XLSX in Downloads / data/ui_downloads/keepa/CA/
  8. Show file details and ask for confirmation
  9. Call import_ui_report() for source=keepa marketplace=CA (unless --no-import)

Usage:
  python src/main.py keepa-manual-assist --marketplace CA
  python src/main.py keepa-manual-assist --marketplace CA --no-import
  python src/main.py keepa-manual-assist --marketplace CA --downloads-dir "D:\\Downloads"
  python src/main.py keepa-manual-assist --marketplace CA --dry-run
"""

import datetime
import os
import re
import subprocess
import webbrowser
from pathlib import Path
from zoneinfo import ZoneInfo

_LONDON_TZ = ZoneInfo("Europe/London")

# ── Spreadsheet ASIN sources (CA only in this MVP) ────────────────────────────
_ASIN_SOURCES: dict[str, dict] = {
    "CA": {
        "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
        "sheet_range": "KeepaCA!BK8:BK",
    },
}

_MARKETPLACE_NAME: dict[str, str] = {
    "CA": "Canada",
}

_KEEPA_VIEWER_URL = "https://keepa.com/#!viewer"
_PRESET_LABEL = "Daily-Report-2.0--XLS"

_SRC_DIR = os.path.dirname(__file__)
_DOWNLOAD_BASE = os.path.normpath(
    os.path.join(_SRC_DIR, "..", "..", "data", "ui_downloads", "keepa")
)

_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

# ── ASIN reading ──────────────────────────────────────────────────────────────

def read_asins(marketplace: str) -> tuple[list[str], dict]:
    """Read, validate, and deduplicate ASINs from the KeepaCA spreadsheet.

    Returns (valid_asins, stats).  Raises ValueError if none are found.
    """
    if marketplace not in _ASIN_SOURCES:
        raise ValueError(
            f"Marketplace {marketplace!r} is not configured. "
            f"Configured marketplaces: {sorted(_ASIN_SOURCES)}"
        )

    src = _ASIN_SOURCES[marketplace]
    print(f"  Spreadsheet : {src['spreadsheet_id']}")
    print(f"  Range       : {src['sheet_range']}")

    from exports.google_sheets_client import get_sheets_service
    service = get_sheets_service()
    resp = service.spreadsheets().values().get(
        spreadsheetId=src["spreadsheet_id"],
        range=src["sheet_range"],
    ).execute()

    raw_rows = resp.get("values", [])
    blank = invalid = dup = 0
    seen: set[str] = set()
    valid: list[str] = []

    for row in raw_rows:
        if not row:
            blank += 1
            continue
        cell = str(row[0]).strip().upper()
        if not cell:
            blank += 1
            continue
        if not _ASIN_RE.match(cell):
            print(f"  [warn] Invalid ASIN skipped: {cell!r}")
            invalid += 1
            continue
        if cell in seen:
            dup += 1
            continue
        seen.add(cell)
        valid.append(cell)

    stats = {
        "raw": len(raw_rows),
        "blank": blank,
        "invalid": invalid,
        "duplicates_removed": dup,
        "valid": len(valid),
    }

    print(f"  Raw rows     : {len(raw_rows)}")
    print(f"  Blank/empty  : {blank}")
    print(f"  Invalid      : {invalid}")
    print(f"  Dupes removed: {dup}")
    print(f"  Valid ASINs  : {len(valid)}")

    if not valid:
        raise ValueError(
            f"No valid ASINs found in {src['sheet_range']}. "
            "Ensure the range contains 10-character uppercase alphanumeric ASINs."
        )

    return valid, stats


# ── Clipboard ─────────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the Windows clipboard via the built-in 'clip' command.

    ASINs are pure ASCII so no encoding issues arise.
    Returns True on success, False on failure (non-fatal — user can copy manually).
    """
    try:
        proc = subprocess.Popen(
            ["clip"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.communicate(input=text.encode("utf-8"))
        return proc.returncode == 0
    except Exception as exc:
        print(f"  [warn] Clipboard copy failed: {exc}")
        return False


# ── File detection ────────────────────────────────────────────────────────────

def _find_xlsx_files(start_time: float, extra_dirs: list[str]) -> list[dict]:
    """Scan for .xlsx files created/modified after start_time.

    Searches: %USERPROFILE%\\Downloads, data/ui_downloads/keepa/CA/, extra_dirs.
    Returns list of dicts sorted newest-first.
    """
    search_dirs: list[Path] = [
        Path.home() / "Downloads",
        Path(_DOWNLOAD_BASE) / "CA",
    ]
    for d in extra_dirs:
        p = Path(d)
        if p not in search_dirs:
            search_dirs.append(p)

    candidates = []
    # Allow 30s before command start to catch files that were mid-download
    threshold = start_time - 30

    for d in search_dirs:
        if not d.is_dir():
            continue
        try:
            entries = list(d.glob("*.xlsx"))
        except OSError:
            continue
        for f in entries:
            try:
                stat = f.stat()
                file_time = max(stat.st_mtime, stat.st_ctime)
                if file_time >= threshold:
                    ts = datetime.datetime.fromtimestamp(
                        stat.st_mtime, _LONDON_TZ
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    candidates.append({
                        "path": str(f),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "mtime_str": ts,
                        "dir": str(d),
                    })
            except OSError:
                continue

    candidates.sort(key=lambda x: x["mtime"], reverse=True)
    return candidates


def _resolve_file(start_time: float, extra_dirs: list[str]) -> str | None:
    """Detect the downloaded file and ask user to confirm or enter a path."""
    candidates = _find_xlsx_files(start_time, extra_dirs)

    if not candidates:
        print()
        print("  No new XLSX files found automatically in:")
        print(f"    {Path.home() / 'Downloads'}")
        print(f"    {os.path.abspath(os.path.join(_DOWNLOAD_BASE, 'CA'))}")
        for d in extra_dirs:
            print(f"    {d}")
        print()
        manual = input(
            "  Enter full path to the downloaded XLSX (or press Enter to skip): "
        ).strip().strip('"')
        if not manual:
            return None
        if not os.path.isfile(manual):
            raise FileNotFoundError(f"File not found: {manual}")
        return manual

    if len(candidates) == 1:
        c = candidates[0]
        print()
        print("  Detected download:")
        print(f"    Path    : {c['path']}")
        print(f"    Size    : {c['size']:,} bytes")
        print(f"    Modified: {c['mtime_str']}")
        return c["path"]

    # Multiple candidates — let user pick
    print()
    print(f"  Found {len(candidates)} recent XLSX files:")
    for i, c in enumerate(candidates, 1):
        print(f"    [{i}] {c['path']}")
        print(f"         {c['size']:,} bytes  modified {c['mtime_str']}")
    print()
    raw = input(
        f"  Enter number 1–{len(candidates)} to select, or full path, "
        "or Enter to skip: "
    ).strip().strip('"')

    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]["path"]
        raise ValueError(f"Invalid choice {raw!r}. Must be 1–{len(candidates)}.")
    if os.path.isfile(raw):
        return raw
    raise ValueError(f"Not a valid file path: {raw!r}")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_manual_assist(
    marketplace: str,
    dry_run: bool = False,
    no_import: bool = False,
    downloads_dir: str | None = None,
) -> dict:
    """Human-in-the-loop Keepa report download and optional import.

    dry_run  : Read ASINs + copy to clipboard only. No browser, no import.
    no_import: Complete the file-find flow but skip the import step.
    downloads_dir: Additional directory to search for the downloaded file.
    """
    if marketplace not in _ASIN_SOURCES:
        raise ValueError(
            f"Marketplace {marketplace!r} is not configured. "
            f"Only CA is supported in this MVP. Configured: {sorted(_ASIN_SOURCES)}"
        )

    extra_dirs = [downloads_dir] if downloads_dir else []

    # ── 1. Read and validate ASINs ────────────────────────────────────────────
    print(f"  Marketplace : {marketplace} ({_MARKETPLACE_NAME.get(marketplace, '')})")
    asins, stats = read_asins(marketplace)
    asin_text = "\n".join(asins)

    # ── 2. Copy to clipboard ──────────────────────────────────────────────────
    ok = _copy_to_clipboard(asin_text)
    if ok:
        print(f"  Clipboard   : {len(asins)} ASINs copied (ready to paste)")
    else:
        print(f"  Clipboard   : FAILED — copy manually from below")
        print()
        print("  ─── ASINs (copy all) ───")
        for a in asins:
            print(f"  {a}")
        print("  ────────────────────────")

    if dry_run:
        print()
        print("  [DRY RUN] ASINs read and copied. No browser opened. No import.")
        return {
            "status": "DRY_RUN",
            "marketplace": marketplace,
            "asin_count": len(asins),
        }

    # ── 3. Record start time and open browser ─────────────────────────────────
    import time as _time
    start_time = _time.time()

    print()
    print(f"  Opening Keepa Viewer in your default browser...")
    webbrowser.open(_KEEPA_VIEWER_URL)

    # ── 4. Print manual instructions ──────────────────────────────────────────
    print()
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │  Manual steps in Keepa Viewer                           │")
    print("  ├─────────────────────────────────────────────────────────┤")
    print(f"  │  1. Select marketplace : {_MARKETPLACE_NAME[marketplace]:<32}│")
    print("  │  2. Paste ASINs        : Ctrl+V into the ASIN field     │")
    print(f"  │     ({len(asins)} ASINs already on clipboard)              │")
    print(f"  │  3. Select preset     : {_PRESET_LABEL:<32}│")
    print("  │  4. Click Download    : save as .xlsx                   │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()

    # ── 5. Wait for user ──────────────────────────────────────────────────────
    input("  ► Press Enter after the XLSX has finished downloading  ")

    # ── 6. Detect downloaded file ─────────────────────────────────────────────
    try:
        file_path = _resolve_file(start_time, extra_dirs)
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc

    if not file_path:
        print()
        print("  No file selected. Exiting without import.")
        return {
            "status": "NO_FILE",
            "marketplace": marketplace,
            "asin_count": len(asins),
            "file_path": None,
        }

    # ── 7. Validate file ──────────────────────────────────────────────────────
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    size = os.path.getsize(file_path)
    if size == 0:
        raise RuntimeError(f"File is 0 bytes: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".xlsx":
        raise RuntimeError(
            f"Expected .xlsx but got {ext!r}: {file_path}\n"
            "Re-download from Keepa Viewer making sure the XLSX option is selected."
        )

    # ── 8. Confirm before importing ───────────────────────────────────────────
    if no_import:
        print()
        print(f"  File ready : {file_path}")
        print(f"  Size       : {size:,} bytes")
        print("  --no-import set. Skipping import.")
        return {
            "status": "DOWNLOAD_ONLY",
            "marketplace": marketplace,
            "asin_count": len(asins),
            "file_path": file_path,
        }

    print()
    print(f"  File       : {file_path}")
    print(f"  Size       : {size:,} bytes")
    print()
    confirm = input(
        "  Import this file into the KeepaCA Google Sheet? [Y/n] "
    ).strip().lower()
    if confirm not in ("", "y", "yes"):
        print("  Import skipped.")
        return {
            "status": "IMPORT_SKIPPED",
            "marketplace": marketplace,
            "asin_count": len(asins),
            "file_path": file_path,
        }

    # ── 9. Import ─────────────────────────────────────────────────────────────
    print()
    from imports.ui_report_importer import import_ui_report
    import_result = import_ui_report(
        source="keepa",
        marketplace=marketplace,
        file_path=file_path,
        dry_run=False,
    )

    return {
        "status": import_result.get("status", "?"),
        "marketplace": marketplace,
        "asin_count": len(asins),
        "file_path": file_path,
        "import_result": import_result,
    }
