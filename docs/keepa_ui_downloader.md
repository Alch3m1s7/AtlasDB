# Keepa UI Downloader — CA marketplace (MVP)

## Scope

This covers automated browser download of Keepa Daily Reports for the **CA
marketplace only**.  US / UK / DE automation is not yet implemented.

| Marketplace | Status |
|-------------|--------|
| CA | Active — this document |
| US | Not yet implemented |
| UK | Not yet implemented |
| DE | Not yet implemented |

---

## Overview

The downloader reads CA ASINs from the `KeepaCA` Google Sheet, opens Keepa Viewer
in a persistent Chromium browser profile, pastes the ASINs, selects the
`Daily-Report-2.0--XLS` preset, and saves the download to:

```
data\ui_downloads\keepa\CA\keepa_CA_YYYYMMDD_HHMMSS.xlsx
```

With `--import-after-download` it then calls the existing `import-ui-report`
logic to push the file to the `KeepaCA` Google Sheet.

---

## Prerequisites

### 1. Install playwright and Chromium

```powershell
.venv\Scripts\activate
pip install playwright
.venv\Scripts\playwright install chromium
```

Chromium is downloaded to a Playwright-managed cache directory (not the repo).
This is a one-time step per machine.

### 2. Google OAuth

The ASIN read (and optional import) uses the same Google OAuth credentials as
`export-sheets`. If you have not authorised yet:

```powershell
python src/main.py export-sheets --marketplace CA --report fba-inventory --dry-run
```

If that prints `AUTH ERROR`, run without `--dry-run` once to trigger the browser
auth flow.

### 3. Bootstrap Keepa login (one time per machine)

See [Bootstrap login](#bootstrap-login) below.

---

## Bootstrap login

Run once to establish a logged-in Keepa session:

```powershell
python src/main.py keepa-bootstrap-login
```

This opens a Chromium window at `https://keepa.com/#!viewer`.
Log in to Keepa manually, then press Enter in the terminal.
The session is saved to `data\browser_profiles\keepa\` and reused in all
subsequent download runs.

**The browser profile is git-ignored.** Never commit it.

---

## Dry-run

Always run the dry-run first.  It reads ASINs from the spreadsheet, validates
them, and prints the planned actions without opening the browser:

```powershell
python src/main.py download-keepa --marketplace CA --dry-run
```

Expected output:

```
============================================================
download-keepa  marketplace=CA  dry_run=True  import_after_download=False
============================================================
  Spreadsheet : 1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8
  Range       : KeepaCA!BK8:BK
  Raw rows    : 312
  Blank/empty : 0
  Invalid     : 0
  Dupes removed: 0
  Valid ASINs : 312

  Planned actions (NOT executed in dry-run):
    Keepa Viewer URL  : https://keepa.com/#!viewer/3
    Browser profile   : C:\DevProjects-b\AtlasDB\data\browser_profiles\keepa
    ASINs to paste    : 312
    Preset            : Daily-Report-2.0--XLS
    Save download to  : C:\DevProjects-b\AtlasDB\data\ui_downloads\keepa\CA\keepa_CA_20260501_143022.xlsx

  [DRY RUN] No browser opened. No file downloaded. No import.
  status : DRY_RUN
  ASINs  : 312
```

---

## Real download

```powershell
python src/main.py download-keepa --marketplace CA
```

The browser opens, automation runs, and the file is saved to
`data\ui_downloads\keepa\CA\`.

---

## Download and import

```powershell
python src/main.py download-keepa --marketplace CA --import-after-download
```

After a successful download, automatically calls `import-ui-report` for
`source=keepa marketplace=CA` to push the data to the `KeepaCA` Google Sheet.

This is equivalent to running:

```powershell
python src/main.py download-keepa --marketplace CA
python src/main.py import-ui-report --source keepa --marketplace CA --file "data\ui_downloads\keepa\CA\keepa_CA_....xlsx"
```

---

## What to verify manually after the first real run

- [ ] Browser opened and navigated to Keepa Viewer
- [ ] Canada marketplace was selected (confirm `.ca` tab is active)
- [ ] ASINs were pasted into the input area (count matches dry-run)
- [ ] `Daily-Report-2.0--XLS` preset was selected
- [ ] Download started and completed (file exists in `data\ui_downloads\keepa\CA\`)
- [ ] File size is > 0 bytes
- [ ] File extension is `.xlsx`
- [ ] With `--import-after-download`: `KeepaCA` sheet has data in `P7:BJ`, `R1` has a timestamp

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `playwright is not installed` | `pip install playwright` then `.venv\Scripts\playwright install chromium` |
| `Browser profile not found` | Run `python src/main.py keepa-bootstrap-login` |
| `Could not find/click the marketplace selector` | See [Updating selectors](#verifying-and-updating-selectors) below |
| `Could not find/fill the ASIN input textarea` | See [Updating selectors](#verifying-and-updating-selectors) |
| `Could not set the column preset` | See [Updating selectors](#verifying-and-updating-selectors) |
| `Download did not complete within 120s` | Keepa may be slow — check browser window; may need a longer `_DOWNLOAD_TIMEOUT_MS` |
| `Unexpected extension '.csv'` | Keepa exported CSV instead of XLSX; check preset selection |
| `No valid ASINs found` | Check that `KeepaCA!BK8:BK` has data in the spreadsheet |
| Keepa shows login screen | Session expired — run `keepa-bootstrap-login` again |
| Google auth error | Run `export-sheets --marketplace CA --report fba-inventory` without `--dry-run` to re-auth |

---

## Verifying and updating selectors

All Playwright selectors in `src/ui_downloaders/keepa_downloader.py` are marked
**BRITTLE** and must be verified against the live Keepa Viewer UI.

### How to find the correct selectors

1. Run `python src/main.py keepa-bootstrap-login` to open the browser
2. Navigate to `https://keepa.com/#!viewer`
3. Open DevTools (F12)
4. Right-click each element → **Inspect**
5. In the Elements panel, right-click the highlighted node → **Copy → Copy selector**
6. Update the relevant constant in `src/ui_downloaders/keepa_downloader.py`

### Elements to verify

| Element | Constant | What to look for |
|---------|----------|-----------------|
| Canada marketplace tab | `_SEL_MARKETPLACE["CA"]` | The `.ca` tab/button in the domain row |
| ASIN input area | `_SEL_ASIN_TEXTAREA` | The textarea where you paste ASINs in bulk |
| Preset dropdown | `_SEL_PRESET_DROPDOWN` | The `<select>` or dropdown containing preset names |
| Preset option label | `_PRESET_OPTION_LABEL` | The exact text of the `Daily-Report-2.0--XLS` option |
| Download button | `_SEL_DOWNLOAD_BTN` | The button/link that triggers the XLSX file download |

### Playwright selector syntax reference

```python
page.locator('button:has-text("Download")')  # button containing text
page.locator('[data-id="ca"]')               # attribute selector
page.locator('#download-btn')                # ID selector
page.locator('.domain-tab.active')           # class selector
page.locator('select[name="preset"]')        # attribute + tag
```

After updating a selector, re-run the dry-run to confirm ASIN reading still
works, then run the real download and watch the browser carefully for each step.

---

## File locations

| Path | Purpose |
|------|---------|
| `src/ui_downloaders/keepa_downloader.py` | Automation module — edit selectors here |
| `data\browser_profiles\keepa\` | Persistent Chromium profile (git-ignored) |
| `data\ui_downloads\keepa\CA\` | Downloaded XLSX files (git-ignored) |
| `data\logs\ui_import_*.log` | Import logs written by `import-ui-report` (git-ignored) |

---

## Known assumptions and limitations

1. **Keepa Viewer URL**: `https://keepa.com/#!viewer/3` — the `/3` fragment is
   assumed to correspond to the Canada domain (Keepa internal domain ID = 3).
   If this does not pre-select Canada, the automation falls back to clicking the
   marketplace selector.

2. **All `_SEL_*` selectors are guesses** based on common SPA patterns.
   Keepa uses Angular or a similar framework; actual element IDs and attributes
   must be verified via DevTools before the first real run.

3. **Preset option label** `Daily-Report-2.0--XLS` must match the exact text
   visible in the dropdown.  Case and punctuation matter.

4. **One ASIN per line** is assumed for the ASIN textarea.  Verify this matches
   Keepa's expected format.

5. **Non-headless mode**: The browser is always visible.  Headless mode is not
   used because Keepa may employ bot detection.

6. **Slow-motion**: `slow_mo=150ms` is set for automation stability on complex
   SPAs.  Increase this if you observe timing-related failures.

---

## What NOT to do

- Do not store Keepa credentials in `.env`, config files, or code.
- Do not commit `data\browser_profiles\` (git-ignored; contains session cookies).
- Do not commit downloaded XLSX files (git-ignored via `data\ui_downloads\`).
- Do not call this automation for US, UK, or DE — only CA is configured.
- Do not run `--import-after-download` unless you have first verified the
  download file is correct for the CA marketplace.
