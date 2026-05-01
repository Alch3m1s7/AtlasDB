# SellerSnap Daily Report Gmail Import — Google Apps Script

## 1. What the script does

`sellersnap_gmail_import.gs` is a Google Apps Script that:

1. Searches Gmail for the latest unprocessed SellerSnap Scheduled Report email
   (`from:support@sellersnap.io`, subject contains `Scheduled Report: DailyReports | Inspire30`,
   arrived within the last 3 days).
2. Extracts the CSV download link from the email HTML body.
3. Downloads the CSV file via `UrlFetchApp`.
4. Parses the CSV with `Utilities.parseCsv`.
5. Validates that the CSV has exactly **75 columns** and contains the expected key headers.
6. Clears only `SllrSnpUS!P7:CL` using `clearContent()` (formatting is preserved).
7. Writes the full CSV (header + all data rows) starting at `P7`.
8. Writes a `YYYY-MM-DD HH:MM` timestamp to cell `A1` of the `SllrSnpUS` tab.
9. Applies the Gmail label `AtlasDB/SellerSnapImported` to the email so it is never processed twice.

The script does **not** touch the Python SP-API pipeline, any other sheet tab, or any cell
outside `P7:CL` (except the configurable status cell `A1`).

---

## 2. Which Google account should own and run the script

The script must run under the **Google account that receives the SellerSnap email**.

- If you keep the SellerSnap email arriving at `vrdretailtd@gmail.com`, create the Apps Script
  project under that account.
- If you set up Gmail auto-forwarding (see Section 3) so the email arrives at
  `attila@vrdretail.co.uk`, create the project under that account instead.

> **Important:** Running the script under an account that does not receive the email will cause
> it to find zero matching threads and exit silently every time.

---

## 3. Gmail auto-forwarding setup (if needed)

If the SellerSnap email arrives at `vrdretailtd@gmail.com` and you prefer to manage the script
from `attila@vrdretail.co.uk`:

1. Sign in to `vrdretailtd@gmail.com`.
2. Go to **Settings → See all settings → Forwarding and POP/IMAP**.
3. Click **Add a forwarding address**, enter `attila@vrdretail.co.uk`, and confirm.
4. To forward only SellerSnap emails (recommended over forwarding all mail), use a Gmail filter:
   - **From:** `support@sellersnap.io`
   - **Subject:** `Scheduled Report: DailyReports | Inspire30`
   - **Action:** Forward to `attila@vrdretail.co.uk`
5. Leave the original in `vrdretailtd@gmail.com` as a backup (do not set it to delete).

After forwarding is set up, the Apps Script project should be owned by `attila@vrdretail.co.uk`.

---

## 4. How to paste the script into Google Apps Script

1. Go to [script.google.com](https://script.google.com) while signed in to the **correct account**
   (see Section 2).
2. Click **New project**.
3. Rename the project (top-left, click "Untitled project") to something like
   `AtlasDB SellerSnap Import`.
4. Delete all default content in the editor.
5. Copy the full contents of `sellersnap_gmail_import.gs` and paste into the editor.
6. Click the **Save** button (floppy disk icon) or press `Ctrl+S`.

No additional files, libraries, or bound spreadsheets are needed. The spreadsheet is referenced
by ID inside the script constants.

---

## 5. Required Apps Script permissions

When you run any function for the first time, Google will ask you to authorise the following
scopes:

| Scope | Why |
|-------|-----|
| `https://mail.google.com/` | Read Gmail messages, search threads, create/apply labels |
| `https://www.googleapis.com/auth/spreadsheets` | Write CSV data and timestamp to the Google Sheet |
| `https://www.googleapis.com/auth/script.external_request` | Download the CSV via `UrlFetchApp` |

To authorise:
1. In the Apps Script editor, select `setupSellerSnapLabel` from the function dropdown.
2. Click **Run**.
3. Click **Review permissions** → choose your account → **Allow**.

These permissions persist for the project. You will not be re-prompted on subsequent runs.

---

## 6. Run the dry-run function first

The dry-run function downloads and validates the CSV **without writing anything to the sheet**.
Run this at least once before setting up the trigger.

1. In the Apps Script editor, select `dryRunSellerSnap` from the function dropdown.
2. Click **Run**.
3. Click **Execution log** (or **View → Logs**) to see the output.

A successful dry run looks like:

```
[DRY RUN] ===== SellerSnap import starting =====
[DRY RUN] Email subject  : Scheduled Report: DailyReports | Inspire30 | 2026/04/01-2026/04/30
[DRY RUN] Email date     : Thu Apr 01 09:04:22 GMT+0100 2026
[DRY RUN] Download URL   : https://...
[DRY RUN] CSV rows       : 1234
[DRY RUN] CSV cols       : 75
[DRY RUN] Validation     : PASSED
[DRY RUN] Target range   : SllrSnpUS!P7:CL
[DRY RUN] Rows to write  : 1234
[DRY RUN] === Dry run complete — sheet NOT modified ===
```

If the dry run fails, see Section 10 (Failure modes).

---

## 7. Run the real import function

1. In the Apps Script editor, select `importSellerSnapDailyReport` from the function dropdown.
2. Click **Run**.
3. Check the execution log to confirm success.
4. Open the Google Sheet and verify the `SllrSnpUS` tab (see Section 9).

> The email will be labelled `AtlasDB/SellerSnapImported` after a successful real run.
> Running it again on the same email will skip it. If you need to re-process the same email,
> remove the label from it in Gmail first.

---

## 8. Set up a daily time-based trigger

To run the import automatically every morning:

1. In the Apps Script editor, click the **clock icon** (Triggers) in the left sidebar,
   or go to **Extensions → Apps Script → Triggers**.
2. Click **+ Add Trigger** (bottom-right).
3. Configure:
   - **Function to run:** `importSellerSnapDailyReport`
   - **Deployment:** `Head`
   - **Event source:** `Time-driven`
   - **Type of time based trigger:** `Day timer`
   - **Time of day:** `9am to 10am` (or `10am to 11am` if the email sometimes arrives late)
4. Click **Save**.

The trigger fires once per day in the selected window. Apps Script picks a random minute
within the hour — you do not need to specify an exact time.

> The SellerSnap download link expires after **48 hours**. The script's Gmail query uses
> `newer_than:3d` as a broad search but the 48-hour expiry means it is best to run within a
> few hours of the email arriving. A 09:30–10:00 trigger is recommended.

---

## 9. How to verify success

After a real run:

1. **Execution log:** Should end with `[REAL RUN] ===== Import complete =====`.
2. **Google Sheet → SllrSnpUS tab:**
   - Cell `A1` contains a timestamp like `2026-05-01 10.02`.
   - Cell `P7` contains the CSV header row (e.g., `title`, `asin`, `sku`, ...).
   - Cell `P8` onwards contains the data rows.
   - Columns to the right of `CL` and rows above row 7 are untouched.
3. **Gmail:** The SellerSnap email now has the label `AtlasDB/SellerSnapImported`.

---

## 10. Failure modes

### No email found
```
[REAL RUN] No unprocessed SellerSnap email found. Exiting.
```
- The email may not have arrived yet. Wait and re-run, or run manually after it arrives.
- Check that the Gmail query `GMAIL_QUERY` constant matches the actual email.
- Check that the script is running under the correct account (Section 2).

### Forwarded email not visible
If you set up forwarding but the script still finds nothing:
- Confirm the forwarding filter is saving to the correct account's inbox (not spam).
- Check that the forwarded email's `From:` header is preserved as `support@sellersnap.io`
  (some forwarders rewrite the sender). If the sender is rewritten, update `GMAIL_QUERY` to
  match the new `from:` address or remove that filter condition.

### Download link expired
```
CSV download returned HTTP 403. The download link has likely expired.
```
- The 48-hour expiry has passed. The email cannot be used. Wait for the next day's email.
- Consider moving the trigger earlier (e.g., `8am to 9am`) to reduce expiry risk.

### SellerSnap changed email HTML
```
Could not extract a download link from the SellerSnap email.
```
- The execution log will list all `href` URLs found in the email body.
- Identify the correct download URL from that list.
- Update the `patterns` array in `_extractDownloadLink()` to match the new HTML structure.

### CSV column count changed
```
CSV column count mismatch: expected 75 columns but got 76.
```
- SellerSnap added or removed a column. The sheet is **not modified**.
- Update `EXPECTED_COLS` to the new count.
- Update `CLEAR_RANGE` if the end column changes (P + N-1 columns).
- Check whether `EXPECTED_HEADERS` still lists valid column names.
- Re-run after updating constants.

### Target tab missing
```
Target tab 'SllrSnpUS' not found in spreadsheet ...
```
- The `SllrSnpUS` tab does not exist in the sheet. Create it manually and re-run.

### Wrong Google account running the script
- The script will find 0 emails and exit silently, because Gmail search runs in the context
  of the script owner's account, not the sheet owner's account.
- Verify in Apps Script: **Project settings** shows the owner email. It must match the account
  receiving the SellerSnap email.

---

## 11. What NOT to do

- **Do not clear wider than `P7:CL`.** Columns to the left of P and to the right of CL may
  contain formulas or data used by other parts of the sheet.
- **Do not use `clear()` instead of `clearContent()`.** `clear()` removes formatting as well as
  content. `clearContent()` wipes only the values, leaving number formats, conditional formatting,
  and borders intact.
- **Do not modify the Python SP-API pipeline.** This Apps Script is a separate workflow. The
  Python exporter writes to different tabs and should not be changed to accommodate this script.
- **Do not process old emails repeatedly.** Always check the `AtlasDB/SellerSnapImported` label
  before re-running manually. Remove the label only if you intentionally want to re-import.
- **Do not commit credentials or tokens.** The `SPREADSHEET_ID` constant is not a secret and is
  safe to commit. Never put refresh tokens, OAuth client secrets, or service account keys in the
  `.gs` file or anywhere in the repo.
