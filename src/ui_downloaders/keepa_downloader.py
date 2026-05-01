# PARKED — triggered Keepa anti-bot during bootstrap login.
# Use keepa_manual_assist.py and the keepa-manual-assist CLI command instead.
# Kept for reference only; not reachable from main.py.
"""
Keepa Viewer browser automation — CA marketplace, MVP.

Downloads a Keepa Daily Report XLSX by:
  1. Reading CA ASINs from Google Sheets (KeepaCA!BK8:BK)
  2. Validating and deduplicating ASINs
  3. Opening Keepa Viewer in a persistent Playwright Chromium context
  4. Selecting the Canada marketplace
  5. Pasting ASINs and selecting the Daily-Report-2.0--XLS preset
  6. Downloading the XLSX to data/ui_downloads/keepa/CA/

Usage:
  python src/main.py keepa-bootstrap-login
  python src/main.py download-keepa --marketplace CA --dry-run
  python src/main.py download-keepa --marketplace CA
  python src/main.py download-keepa --marketplace CA --import-after-download

─────────────────────────────────────────────────────────────────────────────
BRITTLE UI SELECTORS
─────────────────────────────────────────────────────────────────────────────
All _SEL_* constants below are assumptions about the Keepa Viewer UI.
Verify each selector after running keepa-bootstrap-login:
  1. Run:  python src/main.py keepa-bootstrap-login
  2. In the browser, open DevTools (F12)
  3. Right-click each element → Inspect → copy a reliable selector
  4. Update the relevant constant in the BRITTLE SELECTORS block below

See docs/keepa_ui_downloader.md § "Verifying and updating selectors".
─────────────────────────────────────────────────────────────────────────────
"""

import datetime
import os
import re
from zoneinfo import ZoneInfo

_LONDON_TZ = ZoneInfo("Europe/London")

# ── Spreadsheet ASIN sources ──────────────────────────────────────────────────
# Only CA is supported in this MVP.
_ASIN_SOURCES: dict[str, dict] = {
    "CA": {
        "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
        "sheet_range": "KeepaCA!BK8:BK",
    },
}

# ── File-system paths ─────────────────────────────────────────────────────────
_SRC_DIR = os.path.dirname(__file__)
_PROFILE_DIR = os.path.normpath(
    os.path.join(_SRC_DIR, "..", "..", "data", "browser_profiles", "keepa")
)
_DOWNLOAD_BASE = os.path.normpath(
    os.path.join(_SRC_DIR, "..", "..", "data", "ui_downloads", "keepa")
)

# ── ASIN validation ───────────────────────────────────────────────────────────
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


# ═════════════════════════════════════════════════════════════════════════════
# BRITTLE UI SELECTORS — update these if Keepa changes their UI
#
# Keepa Viewer URL.  Domain suffix on the fragment selects the marketplace
# (Keepa internal IDs: US=1, GB=2, CA=3, DE=4, FR=5, AU=10).
# ASSUMPTION: navigating directly to the domain-suffixed URL pre-selects CA.
# ═════════════════════════════════════════════════════════════════════════════
_KEEPA_VIEWER_URL = "https://keepa.com/#!viewer"

_VIEWER_URL_BY_MARKETPLACE: dict[str, str] = {
    "CA": "https://keepa.com/#!viewer/3",
}

# Selector for the marketplace tab/button — tried in order, first match wins.
# BRITTLE: Keepa shows domain tabs (.ca, .com, .co.uk …) or flag icons.
# Right-click the Canada tab → Inspect → copy selector.
_SEL_MARKETPLACE: dict[str, str] = {
    "CA": (
        'a[href*="domain=3"], '         # URL-based anchor (most stable if present)
        'button[data-domain="3"], '     # data-attribute (speculative)
        'span:text-is(".ca"), '         # text ".ca"
        'a:text-is(".ca"), '
        '[title="Canada"], '
        '[title=".ca"]'
    ),
}

# Selector for the bulk ASIN input textarea.
# BRITTLE: Keepa Viewer has a textarea for pasting one ASIN per line.
# Right-click the text area → Inspect → copy selector.
_SEL_ASIN_TEXTAREA = (
    'textarea[placeholder*="ASIN"], '
    'textarea[id*="asin"], '
    'textarea[name*="asin"], '
    'textarea'  # last-resort: first visible textarea on the page
)

# Selector for the column-preset dropdown.
# BRITTLE: Keepa has a <select> for choosing named column presets.
# Right-click the preset dropdown → Inspect → copy selector.
_SEL_PRESET_DROPDOWN = (
    'select[ng-model*="preset"], '
    'select[id*="preset"], '
    'select[name*="preset"], '
    'select'  # last-resort: first visible <select>
)

# Exact option label as it appears in the preset dropdown.
# BRITTLE: open the dropdown in DevTools and confirm this text matches exactly.
_PRESET_OPTION_LABEL = "Daily-Report-2.0--XLS"

# Selector for the download/export button.
# BRITTLE: this is the button that triggers the XLSX file download.
# Right-click the download button → Inspect → copy selector.
_SEL_DOWNLOAD_BTN = (
    'button:has-text("Download"), '
    'a:has-text("Download"), '
    'button:has-text("XLSX"), '
    'a:has-text("XLSX"), '
    'button[id*="download"], '
    'a[id*="download"]'
)

# ── Timeouts ──────────────────────────────────────────────────────────────────
_NAV_TIMEOUT_MS      = 30_000   # page.goto / wait_for_load_state
_ELEMENT_TIMEOUT_MS  = 20_000   # waiting for a selector to become visible
_DOWNLOAD_TIMEOUT_MS = 120_000  # waiting for download event after button click
# ═════════════════════════════════════════════════════════════════════════════


def _now_str() -> str:
    return datetime.datetime.now(_LONDON_TZ).strftime("%Y%m%d_%H%M%S")


def _check_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise ImportError(
            "playwright is not installed. Run:\n"
            "  pip install playwright\n"
            "  .venv\\Scripts\\playwright install chromium"
        )


# ── Public: read + validate ASINs ─────────────────────────────────────────────

def read_asins(marketplace: str) -> tuple[list[str], dict]:
    """Read, validate, and deduplicate ASINs from the source spreadsheet.

    Returns (valid_asins, stats_dict).  Raises ValueError if none are found.
    """
    if marketplace not in _ASIN_SOURCES:
        raise ValueError(
            f"Marketplace {marketplace!r} is not configured for Keepa download. "
            f"Configured: {sorted(_ASIN_SOURCES)}"
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

    print(f"  Raw rows    : {len(raw_rows)}")
    print(f"  Blank/empty : {blank}")
    print(f"  Invalid     : {invalid}")
    print(f"  Dupes removed: {dup}")
    print(f"  Valid ASINs : {len(valid)}")

    if not valid:
        raise ValueError(
            f"No valid ASINs found in {src['sheet_range']}. "
            "Ensure the range contains 10-character uppercase alphanumeric ASINs."
        )

    return valid, stats


# ── Public: dry-run ───────────────────────────────────────────────────────────

def run_dry_run(marketplace: str) -> dict:
    """Validate ASINs and print planned actions. Does not open the browser."""
    print(f"  Marketplace : {marketplace}")
    asins, _ = read_asins(marketplace)

    viewer_url = _VIEWER_URL_BY_MARKETPLACE.get(marketplace, _KEEPA_VIEWER_URL)
    ts = _now_str()
    out_dir = os.path.join(_DOWNLOAD_BASE, marketplace)
    out_path = os.path.abspath(os.path.join(out_dir, f"keepa_{marketplace}_{ts}.xlsx"))

    print()
    print("  Planned actions (NOT executed in dry-run):")
    print(f"    Keepa Viewer URL  : {viewer_url}")
    print(f"    Browser profile   : {os.path.abspath(_PROFILE_DIR)}")
    print(f"    ASINs to paste    : {len(asins)}")
    print(f"    Preset            : {_PRESET_OPTION_LABEL}")
    print(f"    Save download to  : {out_path}")
    print()
    print("  [DRY RUN] No browser opened. No file downloaded. No import.")

    return {
        "status": "DRY_RUN",
        "marketplace": marketplace,
        "asin_count": len(asins),
        "planned_output_path": out_path,
    }


# ── Public: bootstrap login ───────────────────────────────────────────────────

def run_bootstrap_login() -> None:
    """Open Keepa Viewer in a visible Chromium window for manual login.

    Run this once to establish a session.  The session persists automatically
    in the browser profile directory and is reused by run_download().
    """
    _check_playwright()
    from playwright.sync_api import sync_playwright

    abs_profile = os.path.abspath(_PROFILE_DIR)
    os.makedirs(abs_profile, exist_ok=True)

    print(f"  Profile dir : {abs_profile}")
    print(f"  URL         : {_KEEPA_VIEWER_URL}")
    print()
    print("  A Chromium browser window will open.")
    print("  Log in to Keepa manually, then press Enter here to close it.")
    print()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=abs_profile,
            headless=False,
            viewport={"width": 1400, "height": 900},
            slow_mo=100,
        )
        page = ctx.new_page()
        try:
            page.goto(_KEEPA_VIEWER_URL, timeout=_NAV_TIMEOUT_MS)
        except Exception as exc:
            print(f"  [warn] Initial navigation failed: {exc}")
            print("  Browser is open — navigate to Keepa manually and log in.")

        input("  ► Press Enter when logged in and ready to close the browser  ")
        ctx.close()

    print()
    print(f"  Session saved to: {abs_profile}")
    print("  Next: python src/main.py download-keepa --marketplace CA --dry-run")


# ── Public: download ──────────────────────────────────────────────────────────

def run_download(marketplace: str, import_after_download: bool = False) -> dict:
    """Download a Keepa report for the given marketplace via browser automation.

    Returns a result dict with status, file_path, asin_count, import_result.
    Raises RuntimeError on any automation failure (browser not opened).
    """
    if marketplace not in _ASIN_SOURCES:
        raise ValueError(
            f"Marketplace {marketplace!r} is not supported. "
            f"Only CA is supported in this MVP. Configured: {sorted(_ASIN_SOURCES)}"
        )

    _check_playwright()
    from playwright.sync_api import sync_playwright

    abs_profile = os.path.abspath(_PROFILE_DIR)
    if not os.path.isdir(abs_profile):
        raise RuntimeError(
            f"Browser profile not found: {abs_profile}\n"
            "Run: python src/main.py keepa-bootstrap-login"
        )

    print(f"  Marketplace : {marketplace}")
    asins, _ = read_asins(marketplace)
    asin_text = "\n".join(asins)

    ts = _now_str()
    out_dir = os.path.normpath(os.path.join(_DOWNLOAD_BASE, marketplace))
    os.makedirs(out_dir, exist_ok=True)
    out_filename = f"keepa_{marketplace}_{ts}.xlsx"
    out_path = os.path.join(out_dir, out_filename)
    print(f"  Output      : {out_path}")

    downloaded_path: str | None = None
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=abs_profile,
            headless=False,
            viewport={"width": 1400, "height": 900},
            slow_mo=150,
            accept_downloads=True,
        )
        page = ctx.new_page()
        try:
            downloaded_path = _automate_keepa_viewer(
                page, marketplace, asin_text, out_path
            )
        finally:
            ctx.close()

    if not downloaded_path:
        raise RuntimeError("Automation completed but no file was captured.")

    _validate_file(downloaded_path)

    result: dict = {
        "status": "SUCCESS",
        "marketplace": marketplace,
        "file_path": downloaded_path,
        "asin_count": len(asins),
        "import_result": None,
    }

    if import_after_download:
        print()
        print("  Running import-ui-report...")
        from imports.ui_report_importer import import_ui_report
        import_result = import_ui_report(
            source="keepa",
            marketplace=marketplace,
            file_path=downloaded_path,
            dry_run=False,
        )
        result["import_result"] = import_result
        print(f"  Import status: {import_result.get('status', '?')}")

    return result


# ── Internal: browser automation ──────────────────────────────────────────────

def _automate_keepa_viewer(page, marketplace: str, asin_text: str, out_path: str) -> str:
    """Drive Keepa Viewer through the download flow. Returns saved file path."""
    viewer_url = _VIEWER_URL_BY_MARKETPLACE.get(marketplace, _KEEPA_VIEWER_URL)

    # ── Navigate ──────────────────────────────────────────────────────────────
    print(f"  Navigating  : {viewer_url}")
    page.goto(viewer_url, timeout=_NAV_TIMEOUT_MS)
    page.wait_for_load_state("networkidle", timeout=_NAV_TIMEOUT_MS)

    # ── Step 1: select marketplace ────────────────────────────────────────────
    mkt_sel = _SEL_MARKETPLACE.get(marketplace)
    if mkt_sel:
        print(f"  Step 1/4: selecting marketplace ({marketplace})")
        try:
            el = page.locator(mkt_sel).first
            el.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
            el.click()
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception as exc:
            raise RuntimeError(
                f"Could not find/click the marketplace selector for {marketplace!r}.\n"
                f"Selector tried: {mkt_sel!r}\n"
                f"BRITTLE selector — open Keepa Viewer, right-click the Canada tab,\n"
                f"Inspect → copy selector, then update _SEL_MARKETPLACE['CA'].\n"
                f"Error: {exc}"
            ) from exc

    # ── Step 2: fill ASIN textarea ────────────────────────────────────────────
    asin_count = len(asin_text.strip().splitlines())
    print(f"  Step 2/4: pasting {asin_count} ASINs into textarea")
    try:
        ta = page.locator(_SEL_ASIN_TEXTAREA).first
        ta.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
        ta.click()
        ta.fill("")        # clear any prior content
        ta.fill(asin_text)
    except Exception as exc:
        raise RuntimeError(
            f"Could not find/fill the ASIN input textarea.\n"
            f"Selector tried: {_SEL_ASIN_TEXTAREA!r}\n"
            f"BRITTLE selector — right-click the ASIN text area in Keepa Viewer,\n"
            f"Inspect → copy selector, then update _SEL_ASIN_TEXTAREA.\n"
            f"Error: {exc}"
        ) from exc

    # ── Step 3: select preset ─────────────────────────────────────────────────
    print(f"  Step 3/4: selecting preset '{_PRESET_OPTION_LABEL}'")
    try:
        dd = page.locator(_SEL_PRESET_DROPDOWN).first
        dd.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
        dd.select_option(label=_PRESET_OPTION_LABEL)
    except Exception as exc:
        raise RuntimeError(
            f"Could not set the column preset to {_PRESET_OPTION_LABEL!r}.\n"
            f"Selector tried: {_SEL_PRESET_DROPDOWN!r}\n"
            f"BRITTLE selector — right-click the preset dropdown, Inspect → copy selector,\n"
            f"then update _SEL_PRESET_DROPDOWN and confirm _PRESET_OPTION_LABEL matches\n"
            f"the exact option text visible in the dropdown.\n"
            f"Error: {exc}"
        ) from exc

    # ── Step 4: click download, capture file ──────────────────────────────────
    print("  Step 4/4: clicking download button and waiting for file")
    try:
        with page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as dl_info:
            btn = page.locator(_SEL_DOWNLOAD_BTN).first
            btn.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
            btn.click()
        dl = dl_info.value
        dl.save_as(out_path)
    except Exception as exc:
        raise RuntimeError(
            f"Download did not complete within {_DOWNLOAD_TIMEOUT_MS // 1000}s.\n"
            f"Button selector tried: {_SEL_DOWNLOAD_BTN!r}\n"
            f"BRITTLE selector — right-click the download button, Inspect → copy selector,\n"
            f"then update _SEL_DOWNLOAD_BTN.\n"
            f"Error: {exc}"
        ) from exc

    return out_path


# ── Internal: file validation ─────────────────────────────────────────────────

def _validate_file(path: str) -> None:
    if not os.path.isfile(path):
        raise RuntimeError(f"File not found after download: {path}")
    size = os.path.getsize(path)
    if size == 0:
        raise RuntimeError(f"Downloaded file is 0 bytes: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext != ".xlsx":
        raise RuntimeError(
            f"Unexpected extension {ext!r}: {path}\n"
            "Expected .xlsx — check Keepa Viewer export settings."
        )
    print(f"  File size   : {size:,} bytes  ({os.path.basename(path)})")
