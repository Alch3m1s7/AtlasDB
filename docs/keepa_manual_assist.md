# Keepa Manual Assist — CA marketplace

## Why Playwright was parked

The Playwright-based Keepa downloader (`keepa_downloader.py`) was built first
and immediately triggered Keepa's anti-bot protection during the bootstrap login
step — before any automation even ran.

**Decision:** Do not attempt to bypass anti-bot checks.  No stealth plugins,
proxy rotation, fingerprint spoofing, or headless-detection workarounds.

**Replacement:** A human-in-the-loop assistant that:
- Uses the user's existing browser session (no Playwright, no new browser profile)
- Copies ASINs to the clipboard so the user just presses Ctrl+V
- Opens Keepa Viewer in the system default browser
- Waits while the user completes the download manually
- Detects the downloaded file automatically
- Optionally calls the proven `import-ui-report` pipeline

---

## Scope

| Marketplace | Status |
|-------------|--------|
| CA | Active — this document |
| US | Not yet implemented |
| UK | Not yet implemented |
| DE | Not yet implemented |

US uses SellerSnap (Gmail import), not Keepa.  AU has no Keepa.

---

## Prerequisites

1. **Google OAuth** — same credentials used by `export-sheets`.
   If not yet authorised, run:
   ```powershell
   python src/main.py export-sheets --marketplace CA --report fba-inventory --dry-run
   ```
   If you see `AUTH ERROR`, run without `--dry-run` once to trigger the browser flow.

2. **Keepa account** — log in to Keepa in your normal browser before running.
   No credentials are stored anywhere in this project.

---

## Commands

### Dry-run (safe test — reads ASINs and copies to clipboard)

```powershell
python src/main.py keepa-manual-assist --marketplace CA --dry-run
```

What it does:
- Reads ASINs from `KeepaCA!BK8:BK`
- Validates and deduplicates
- Copies ASINs to clipboard
- Prints ASIN count
- **No browser opened. No file detected. No import.**

Use this to confirm:
1. Google Sheets auth is working
2. The ASIN range is populated
3. Clipboard copy works (paste into Notepad to verify)

---

### Full run (default — download + import)

```powershell
python src/main.py keepa-manual-assist --marketplace CA
```

Steps:
1. Reads and validates ASINs → copies to clipboard
2. Opens `https://keepa.com/#!viewer` in your default browser
3. Prints instructions (see below)
4. Waits for you to press Enter
5. Scans `%USERPROFILE%\Downloads` and `data\ui_downloads\keepa\CA\` for the newest XLSX
6. Shows the detected file and asks `[Y/n]` to confirm import
7. Calls `import-ui-report source=keepa marketplace=CA` on the selected file

---

### Download only (no import)

```powershell
python src/main.py keepa-manual-assist --marketplace CA --no-import
```

Same as above but stops after detecting the file.  Does not write to Google Sheets.

---

### Custom download directory

```powershell
python src/main.py keepa-manual-assist --marketplace CA --downloads-dir "D:\Downloads"
```

Adds `D:\Downloads` to the search list alongside `%USERPROFILE%\Downloads`.

---

## Manual steps inside Keepa Viewer

When the browser opens, follow these steps:

1. **Select marketplace**: Click the **Canada** tab (`.ca`)
2. **Paste ASINs**: Click the ASIN input field → **Ctrl+V**
   *(ASINs are already on your clipboard — one per line)*
3. **Select preset**: Choose **`Daily-Report-2.0--XLS`** from the column preset dropdown
4. **Download**: Click the download button → save as `.xlsx`
5. **Return to the terminal** → press Enter

---

## File detection

After you press Enter, the command scans for `.xlsx` files modified since the
command started in:
- `%USERPROFILE%\Downloads`
- `data\ui_downloads\keepa\CA\`
- Any directory specified via `--downloads-dir`

A 30-second buffer is applied to catch files that were mid-download when you
pressed Enter.

If exactly one candidate is found, it is shown automatically.  If multiple are
found, you are asked to pick by number.  If none are found, you are prompted to
enter the path manually.

---

## Safety rules

1. **No credentials stored** — Keepa login lives in your browser profile only.
2. **No anti-bot bypasses** — If Keepa blocks access, re-login manually.
3. **Confirm before import** — The `[Y/n]` prompt prevents accidental writes.
4. **`--no-import` is safe** — Stops before touching any Google Sheet.
5. **Importer is unchanged** — `import-ui-report` is called verbatim; the
   column-count guard, clear-before-write, and timestamp logic all apply.
6. **Files are git-ignored** — Downloaded XLSX files stay in
   `data\ui_downloads\` which is never committed.

---

## Expected output (full run)

```
============================================================
keepa-manual-assist  marketplace=CA  dry_run=False  no_import=False
============================================================
  Marketplace : CA (Canada)
  Spreadsheet : 1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8
  Range       : KeepaCA!BK8:BK
  Raw rows    : 646
  Blank/empty : 7
  Invalid     : 0
  Dupes removed: 7
  Valid ASINs : 632
  Clipboard   : 632 ASINs copied (ready to paste)

  Opening Keepa Viewer in your default browser...

  ┌─────────────────────────────────────────────────────────┐
  │  Manual steps in Keepa Viewer                           │
  ├─────────────────────────────────────────────────────────┤
  │  1. Select marketplace : Canada                         │
  │  2. Paste ASINs        : Ctrl+V into the ASIN field     │
  │     (632 ASINs already on clipboard)                    │
  │  3. Select preset     : Daily-Report-2.0--XLS           │
  │  4. Click Download    : save as .xlsx                   │
  └─────────────────────────────────────────────────────────┘

  ► Press Enter after the XLSX has finished downloading

  Detected download:
    Path    : C:\Users\attil\Downloads\keepa_CA_report.xlsx
    Size    : 1,456,234 bytes
    Modified: 2026-05-01 14:30:12

  Import this file into the KeepaCA Google Sheet? [Y/n]
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Google auth error | Run `export-sheets --marketplace CA --report fba-inventory` without `--dry-run` |
| No ASINs found | Check `KeepaCA!BK8:BK` in the spreadsheet — range may be empty |
| Clipboard copy failed | Command prints ASINs to terminal — copy manually |
| Browser did not open | Navigate to `https://keepa.com/#!viewer` manually |
| No file detected | Enter the full file path when prompted, or use `--downloads-dir` |
| Wrong file detected | Multiple candidates are shown — pick by number |
| `.csv` instead of `.xlsx` | In Keepa, make sure you click the XLSX download option |
| Column count mismatch | Report format may have changed — check `max_cols` in `src/config/ui_report_imports.py` |
| Keepa shows login | Log in manually in your browser; no token is stored in this project |

---

## Extending to US / UK / DE

When ready to add another marketplace:

1. Add an entry to `_ASIN_SOURCES` in `src/ui_downloaders/keepa_manual_assist.py`:
   ```python
   "UK": {
       "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
       "sheet_range": "KeepaUK!BK8:BK",
   },
   ```

2. Add the display name to `_MARKETPLACE_NAME`:
   ```python
   "UK": "United Kingdom",
   ```

3. Verify `src/config/ui_report_imports.py` has a matching entry for the
   new marketplace under `"keepa"`.

4. Test with `--dry-run` first, then `--no-import`, then the full run.

No other code changes are required — the importer already supports US/CA/UK/DE.

---

## File locations

| Path | Purpose |
|------|---------|
| `src/ui_downloaders/keepa_manual_assist.py` | Manual assist module |
| `src/ui_downloaders/keepa_downloader.py` | Parked Playwright version (reference only) |
| `data\ui_downloads\keepa\CA\` | Downloaded XLSX files (git-ignored) |
| `data\logs\ui_import_*.log` | Import logs (git-ignored) |
| `docs/keepa_ui_downloader.md` | Original Playwright design notes (parked) |
