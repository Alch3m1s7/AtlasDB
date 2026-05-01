# UI Report Imports — Keepa and Bqool

## Current scope

This document covers importing manually downloaded Keepa and Bqool XLSX/CSV files
into the existing marketplace Google Sheets.

| Source | Marketplaces | Status |
|--------|-------------|--------|
| Keepa  | US, CA, UK, DE | Active |
| Bqool  | UK, CA | Active |
| Bqool  | DE | Deferred — tab and spreadsheet not yet configured |
| Keepa  | AU | Not applicable — no Keepa for AU |

Browser automation (automatic download without manual steps) is **planned but not
implemented**. The current workflow requires a human to download the file first.

---

## Target ranges

### Keepa

| Marketplace | Spreadsheet ID | Tab | Clear range | Columns | Timestamp cell |
|-------------|---------------|-----|-------------|---------|----------------|
| US | `1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo` | KeepaUS | P7:BJ | 47 | R1 |
| CA | `1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8` | KeepaCA | P7:BJ | 47 | R1 |
| UK | `1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM` | KeepaUK | P7:BJ | 47 | R1 |
| DE | `1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk` | KeepaDE | P7:BJ | 47 | R1 |

### Bqool

| Marketplace | Spreadsheet ID | Tab | Clear range | Columns | Timestamp cell |
|-------------|---------------|-----|-------------|---------|----------------|
| UK | `1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM` | bqUK | P7:CC | 66 | A1 |
| CA | `1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8` | bqCA | P7:CC | 66 | A1 |

**P7:BJ = 47 columns** (P=16, BJ=62, 62−16+1=47)
**P7:CC = 66 columns** (P=16, CC=81, 81−16+1=66)

Keepa timestamp cell R1 is in column R (within the P–BJ column span) but in row 1.
The clear range P7:BJ starts at row 7, so row 1 is never cleared and R1 is safe.

Config lives in `src/config/ui_report_imports.py`.

---

## File importer usage

### Prerequisites

1. Activate the project venv:
   ```powershell
   .venv\Scripts\activate
   ```

2. Ensure Google OAuth is authorised (same credentials used by the SP-API export):
   ```powershell
   python src/main.py export-sheets --marketplace US --report fba-inventory --dry-run
   ```
   If you see `AUTH ERROR`, run without `--dry-run` once to trigger the browser auth flow.

3. Place the downloaded file somewhere accessible. Recommended:
   ```
   data\ui_downloads\keepa_US_20260501.xlsx
   data\ui_downloads\bqool_UK_20260501.xlsx
   ```
   The `data\ui_downloads\` directory is git-ignored.

---

### Dry-run commands (always run these first)

```powershell
# Keepa
python src/main.py import-ui-report --source keepa --marketplace US --file "data\ui_downloads\keepa_US.xlsx" --dry-run
python src/main.py import-ui-report --source keepa --marketplace CA --file "data\ui_downloads\keepa_CA.xlsx" --dry-run
python src/main.py import-ui-report --source keepa --marketplace UK --file "data\ui_downloads\keepa_UK.xlsx" --dry-run
python src/main.py import-ui-report --source keepa --marketplace DE --file "data\ui_downloads\keepa_DE.xlsx" --dry-run

# Bqool
python src/main.py import-ui-report --source bqool --marketplace UK --file "data\ui_downloads\bqool_UK.xlsx" --dry-run
python src/main.py import-ui-report --source bqool --marketplace CA --file "data\ui_downloads\bqool_CA.xlsx" --dry-run
```

Dry-run output confirms:
- File read successfully
- Row and column count
- Target spreadsheet / tab / range
- Whether column count would pass validation
- **Does NOT write anything to any sheet**

---

### Real-write commands

```powershell
# Keepa
python src/main.py import-ui-report --source keepa --marketplace US --file "data\ui_downloads\keepa_US.xlsx"
python src/main.py import-ui-report --source keepa --marketplace CA --file "data\ui_downloads\keepa_CA.xlsx"
python src/main.py import-ui-report --source keepa --marketplace UK --file "data\ui_downloads\keepa_UK.xlsx"
python src/main.py import-ui-report --source keepa --marketplace DE --file "data\ui_downloads\keepa_DE.xlsx"

# Bqool
python src/main.py import-ui-report --source bqool --marketplace UK --file "data\ui_downloads\bqool_UK.xlsx"
python src/main.py import-ui-report --source bqool --marketplace CA --file "data\ui_downloads\bqool_CA.xlsx"
```

A successful run prints:
```
============================================================
import-ui-report  source=keepa  marketplace=US  dry_run=False
============================================================
  Reading        : C:\DevProjects-b\AtlasDB\data\ui_downloads\keepa_US.xlsx
  Source         : keepa
  Marketplace    : US
  File           : keepa_US.xlsx
  Rows           : 1234  (includes header row)
  Columns        : 47  (max allowed: 47)
  Spreadsheet    : 1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo
  Tab            : KeepaUS
  Start cell     : P7
  Clear range    : KeepaUS!P7:BJ
  Col check      : PASS
  Cleared        : KeepaUS!P7:BJ
  Written        : 1234 rows × 47 cols → KeepaUS!P7
  Log written    : C:\DevProjects-b\AtlasDB\data\logs\ui_import_20260501_101523.log
  status         : SUCCESS
```

---

## Keepa download steps (manual, before running importer)

1. Open Keepa Viewer in your browser.
2. Select the correct **marketplace** tab:
   - US → USA
   - CA → Canada
   - UK → United Kingdom
   - DE → Germany
3. Paste the ASINs from the corresponding spreadsheet column:
   - KeepaUS → `BK8:BK` of the US spreadsheet
   - KeepaCA → `BK8:BK` of the CA spreadsheet
   - KeepaUK → `BK8:BK` of the UK spreadsheet
   - KeepaDE → `BK8:BK` of the DE spreadsheet
4. Select column preset: **`Daily-Report-2.0--XLS`**
5. Download as XLSX (or CSV if XLSX is unavailable).
6. Save to `data\ui_downloads\keepa_<MKT>_<date>.xlsx`.
7. Run the dry-run command, then the real import command.

---

## Bqool download steps (manual, before running importer)

1. Log in to Bqool.
2. Navigate to **Listings → Active Listings**.
3. Select **Amazon UK**, then click **DOWNLOAD → DOWNLOAD LISTINGS**.
4. Repeat with **Amazon CA**.
5. Save each file to `data\ui_downloads\bqool_<MKT>_<date>.xlsx`.
6. Run the dry-run command, then the real import command.

**Bqool DE is deferred.** When ready, add `"DE"` to the `bqool` section of
`src/config/ui_report_imports.py` with the correct tab name and verify the
column count before enabling.

---

## Manual testing checklist

Before treating a marketplace as validated:

- [ ] Run dry-run; confirm row count matches expectations (not 0, not excessively large).
- [ ] Confirm column count = expected (47 for Keepa, 66 for Bqool).
- [ ] Confirm correct spreadsheet ID appears in the dry-run output.
- [ ] Confirm correct tab name appears.
- [ ] Run real import.
- [ ] Open the Google Sheet. Verify P7 contains the header row (not blank, not data from
      a different report).
- [ ] Check that columns to the left of P (A–O) are untouched.
- [ ] Check that columns to the right of BJ (for Keepa) or CC (for Bqool) are untouched.
- [ ] Keepa: verify R1 contains a timestamp in the format `YYYY-MM-DD HH.MM`.
- [ ] Bqool: verify A1 contains a timestamp in the format `YYYY-MM-DD HH.MM`.
- [ ] Verify a log file exists in `data\logs\ui_import_<timestamp>.log`.
- [ ] Verify the log file contains `"status": "SUCCESS"`.

---

## Safety rules

1. **Clear range is exact.** `P7:BJ` (47 cols) and `P7:CC` (66 cols) are hard-coded in
   config. If the downloaded file has more columns than the max allowed, the import aborts
   before clearing or writing anything. The sheet is never left in a partially-written state
   because clearing happens before writing.

2. **Formatting is preserved.** The importer uses `values().clear()` (values only), which
   is equivalent to Google Sheets "Clear contents". Number formats, conditional formatting,
   and borders are not touched.

3. **Timestamp written only on success.** After a successful real import, the importer
   writes a `YYYY-MM-DD HH.MM` (Europe/London) timestamp to the configured cell:
   Keepa → `R1`, Bqool → `A1`. Only the cell value is updated; formatting is preserved.
   The timestamp is **not** written during `--dry-run`, if file validation fails, if the
   column count check fails, or if the sheet clear/write fails.

4. **Column overflow protection.** If `col_count > max_cols`, the import exits with a clear
   error message. To handle a new report format with more columns, first update the
   `max_cols` and `clear_range` in config, verify the new range is still safe, then re-run.

5. **CSV trailing comma note.** Some CSV exports add a trailing comma on each row, which
   `csv.reader` interprets as an extra empty column. If a 47-column Keepa CSV reports
   48 columns, check the raw file. Re-export from the tool or open in Excel and save as
   XLSX instead.

6. **Only one file per run.** Always run one marketplace at a time. Confirm the result
   before running the next.

---

## Failure modes

| Failure | Message / symptom | Fix |
|---------|-------------------|-----|
| File not found | `Input file not found: ...` | Check the `--file` path; use the exact path including extension |
| Unsupported format | `Unsupported file extension '.xls'` | Re-save as `.xlsx` in Excel, or export as `.csv` |
| openpyxl not installed | `openpyxl is required` | Run `pip install -r requirements.txt` |
| 0 rows after stripping | `File contains no rows` | The file is empty or all rows are blank |
| Column count too high | `Column count mismatch: ... Sheet NOT modified` | Report format changed — update `max_cols` in config after verifying |
| Wrong Google account | `AUTH ERROR` or `FAILED_SHEET_CHECK` | Ensure `GOOGLE_OAUTH_TOKEN_JSON` and `GOOGLE_OAUTH_CLIENT_SECRET_JSON` are set correctly in `.env` |
| Target tab missing | `Target tab 'KeepaUS' not found` | Create the tab in the Google Sheet manually, then re-run |
| CSV encoding error | `Could not decode ... with any of: utf-8-sig, utf-8, cp1252, latin-1` | Save the file as UTF-8 CSV from the source application |
| Spreadsheet not accessible | HTTP 403 from Sheets API | The Google account running the importer lacks Edit access to the spreadsheet |
| Bqool DE attempted | `not configured for marketplace 'DE'` | Expected — DE Bqool is deferred. Uncomment the DE block in config when ready |
| Keepa AU attempted | `not configured for marketplace 'AU'` | Expected — no Keepa for AU |

---

## Logs

Each real run (success or failure) writes a one-line JSON record to:
```
data\logs\ui_import_<YYYYMMDD_HHmmss>.log
```

Example success record:
```json
{"timestamp": "2026-05-01 10:15", "source": "keepa", "marketplace": "US",
 "file": "keepa_US_20260501.xlsx", "status": "SUCCESS", "row_count": 1234,
 "col_count": 47, "spreadsheet_id": "1gzJUJe...", "tab": "KeepaUS",
 "clear_range": "P7:BJ", "dry_run": false, "error": null}
```

The `data\logs\` directory is git-ignored.

---

## Planned browser automation (Playwright — not yet implemented)

The following describes the intended future approach. **Do not implement until
explicitly requested.**

### Design principles

- Use a **persistent browser profile** stored at `data\browser_profiles\keepa\` and
  `data\browser_profiles\bqool\`. Never delete these between runs.
- **Manual bootstrap login**: run a one-time setup script that opens the browser for
  a human to log in. The session cookies are saved in the persistent profile.
  No passwords are ever stored in code, config, or `.env`.
- Runtime automation uses only element selectors and URL navigation — no AI/vision.
- **Fail hard** if the expected marketplace selector or preset dropdown is not found
  within a timeout. Do not silently proceed with the wrong data.
- **Fail hard** if the downloaded file is not found in `data\ui_downloads\` within a
  timeout after clicking download.
- **Download target directory**: `data\ui_downloads\` (git-ignored).
- After download, automatically call `import_ui_report()` with the downloaded file path.

### Planned CLI command

```powershell
python src/main.py download-and-import --source keepa --marketplace US
python src/main.py download-and-import --source bqool --marketplace UK
```

### Playwright implementation notes (for when this is built)

```
pip install playwright
playwright install chromium
```

Persistent profile path:
```python
context = browser.new_context(
    storage_state="data/browser_profiles/keepa/storage_state.json"
)
```

Bootstrap (manual login, run once):
```python
# Opens browser, user logs in manually, saves session
browser.new_context().storage_state(path="data/browser_profiles/keepa/storage_state.json")
```

Keepa automation flow:
1. Navigate to Keepa Viewer URL
2. Assert marketplace dropdown exists; select correct marketplace
3. Assert column preset dropdown exists; select `Daily-Report-2.0--XLS`
4. Paste ASINs (read from Sheets via Sheets API first)
5. Click download; wait for file to appear in `data\ui_downloads\`
6. Call `import_ui_report()` with the downloaded file

Bqool automation flow:
1. Navigate to `Listings → Active Listings`
2. Assert marketplace selector exists; select correct Amazon marketplace
3. Click `DOWNLOAD → DOWNLOAD LISTINGS`
4. Wait for file in `data\ui_downloads\`
5. Call `import_ui_report()` with the downloaded file

### Files to be added (future)

```
src/automation/keepa_downloader.py
src/automation/bqool_downloader.py
data/browser_profiles/keepa/        ← git-ignored
data/browser_profiles/bqool/        ← git-ignored
```

---

## What NOT to do

- **Do not clear wider than the configured range.** Changing `clear_range` to `P7:ZZ`
  or similar would destroy data in adjacent columns used by other pipeline components.
- **Do not use `spreadsheets().batchUpdate()` with `DeleteRange` or `ClearBasicFilter`**
  instead of `values().clear()`. Those operations can remove formatting.
- **Do not modify `src/exports/sheet_exporter.py` or the SP-API pipeline** for any UI
  import feature. The two workflows are intentionally separate.
- **Do not commit downloaded XLSX/CSV files.** They belong in `data\ui_downloads\` which
  is git-ignored.
- **Do not commit browser sessions, cookies, or storage state files.** They belong in
  `data\browser_profiles\` which is git-ignored.
- **Do not store passwords or API keys** for Keepa or Bqool in `.env`, config files,
  or the repository. Browser session persistence handles authentication.
- **Do not run Bqool DE** until the tab name and spreadsheet are confirmed and the
  config entry is uncommented and validated.
