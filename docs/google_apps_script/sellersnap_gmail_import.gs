// ============================================================
// AtlasDB — SellerSnap Daily Report Gmail Import
// ============================================================
// Searches Gmail for the latest unprocessed SellerSnap
// Scheduled Report email, downloads the CSV via the embedded
// link, and writes it to the SllrSnpUS tab starting at P7.
//
// Entry points:
//   importSellerSnapDailyReport()  — real import
//   dryRunSellerSnap()             — validate only, no sheet writes
//   setupSellerSnapLabel()         — one-time: create Gmail label
//
// Trigger: time-based, daily around 09:30–10:00.
// Must run under the Google account that receives the email.
// ============================================================

// ---- Configuration constants ----

var SPREADSHEET_ID   = "1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo";
var TAB_NAME         = "SllrSnpUS";
var START_ROW        = 7;       // P7
var START_COL        = 16;      // Column P (1-indexed)
var EXPECTED_COLS    = 75;      // P:CL = 75 columns
var CLEAR_RANGE      = "P7:CL"; // clearContent() target — never wider
var STATUS_CELL      = "A1";    // Timestamp/status cell (outside report area)

var GMAIL_QUERY      = 'from:support@sellersnap.io subject:"Scheduled Report: DailyReports | Inspire30" newer_than:3d';
var PROCESSED_LABEL  = "AtlasDB/SellerSnapImported";
var GMAIL_SEARCH_MAX = 10;      // Max threads to inspect

// Key header columns expected in every valid SellerSnap CSV.
// If SellerSnap renames or removes any of these, the import aborts.
var EXPECTED_HEADERS = [
  "title",
  "listing_state",
  "asin",
  "sku",
  "cur_bb_price",
  "cur_sales_rank",
  "store_name"
];

// ============================================================
// Public entry points
// ============================================================

function importSellerSnapDailyReport() {
  _run(false);
}

function dryRunSellerSnap() {
  _run(true);
}

// ============================================================
// Core pipeline
// ============================================================

function _run(dryRun) {
  var mode = dryRun ? "[DRY RUN]" : "[REAL RUN]";
  Logger.log(mode + " ===== SellerSnap import starting =====");

  // --- 1. Find the most recent unprocessed email thread ---
  var thread = _findUnprocessedThread();
  if (!thread) {
    Logger.log(mode + " No unprocessed SellerSnap email found. Exiting.");
    return;
  }

  // Use the first (most recent) message in the thread.
  var message   = thread.getMessages()[0];
  var subject   = message.getSubject();
  var emailDate = message.getDate();
  Logger.log(mode + " Email subject  : " + subject);
  Logger.log(mode + " Email date     : " + emailDate);

  // --- 2. Extract download URL ---
  var downloadUrl = _extractDownloadLink(message);
  Logger.log(mode + " Download URL   : " + downloadUrl);

  // --- 3. Download CSV ---
  var csvText = _downloadCsv(downloadUrl);

  // --- 4. Parse ---
  var rows = Utilities.parseCsv(csvText);
  var rawRowCount = rows.length;
  var rawColCount = rawRowCount > 0 ? rows[0].length : 0;
  Logger.log(mode + " CSV rows       : " + rawRowCount);
  Logger.log(mode + " CSV cols       : " + rawColCount);

  // --- 5. Validate ---
  _validateCsv(rows);
  Logger.log(mode + " Validation     : PASSED");

  // --- 6. Normalize row widths (pad trailing empty fields) ---
  var normalized = _normalizeRows(rows);

  Logger.log(mode + " Target range   : " + TAB_NAME + "!" + CLEAR_RANGE);
  Logger.log(mode + " Rows to write  : " + normalized.length);

  if (dryRun) {
    Logger.log(mode + " === Dry run complete — sheet NOT modified ===");
    return;
  }

  // --- 7. Open sheet and validate tab ---
  var ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = _getTab(ss);

  // --- 8. Clear only the report area (preserve formatting) ---
  sheet.getRange(CLEAR_RANGE).clearContent();
  Logger.log(mode + " Cleared        : " + TAB_NAME + "!" + CLEAR_RANGE);

  // --- 9. Write CSV ---
  var writeRange = sheet.getRange(START_ROW, START_COL, normalized.length, EXPECTED_COLS);
  writeRange.setValues(normalized);
  Logger.log(mode + " Written        : " + normalized.length + " rows → " + TAB_NAME + "!" + CLEAR_RANGE);

  // --- 10. Write import timestamp to status cell ---
  var ts = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm");
  sheet.getRange(STATUS_CELL).setValue(ts);
  Logger.log(mode + " Status cell    : " + TAB_NAME + "!" + STATUS_CELL + " = " + ts);

  // --- 11. Label the email so it is not processed again ---
  _labelThread(thread);
  Logger.log(mode + " Email labelled : " + PROCESSED_LABEL);

  Logger.log(mode + " ===== Import complete =====");
}

// ============================================================
// Gmail helpers
// ============================================================

function _findUnprocessedThread() {
  var threads = GmailApp.search(GMAIL_QUERY, 0, GMAIL_SEARCH_MAX);
  if (!threads || threads.length === 0) {
    Logger.log("Gmail search returned 0 results for query: " + GMAIL_QUERY);
    return null;
  }

  Logger.log("Gmail search found " + threads.length + " thread(s). Checking for unprocessed...");

  for (var i = 0; i < threads.length; i++) {
    var thread = threads[i];
    var labels = thread.getLabels();
    var alreadyProcessed = false;

    for (var j = 0; j < labels.length; j++) {
      if (labels[j].getName() === PROCESSED_LABEL) {
        alreadyProcessed = true;
        break;
      }
    }

    if (!alreadyProcessed) {
      Logger.log("Found unprocessed thread: " + thread.getFirstMessageSubject());
      return thread;
    }

    Logger.log("Skipping already-processed thread: " + thread.getFirstMessageSubject());
  }

  return null;
}

function _extractDownloadLink(message) {
  var body = message.getBody(); // HTML body

  if (!body || body.trim().length === 0) {
    throw new Error(
      "Email body is empty. Cannot extract download link. " +
      "If this is a forwarded email, check that HTML forwarding is enabled."
    );
  }

  // Ordered from most specific to most general.
  // Patterns look for an <a href="URL"> near a DOWNLOAD call-to-action.
  var patterns = [
    // href in <a> tag whose visible text contains DOWNLOAD
    /<a[^>]+href=["']([^"'>\s]+)["'][^>]*>[^<]*(?:<[^>]*>[^<]*)*DOWNLOAD/i,
    // DOWNLOAD text followed (within ~500 chars) by an href
    /DOWNLOAD[\s\S]{0,500}?<a[^>]+href=["']([^"'>\s]+)["']/i,
    // Any href URL that explicitly contains the word "download"
    /<a[^>]+href=["'](https?:\/\/[^"'>\s]*download[^"'>\s]*)["']/i,
    // Any href URL from a sellersnap.io domain
    /<a[^>]+href=["'](https?:\/\/[^"'>\s]*sellersnap\.io[^"'>\s]*)["']/i,
    // Any href URL ending in .csv (with optional query string)
    /<a[^>]+href=["'](https?:\/\/[^"'>\s]+\.csv[^"'>\s]*)["']/i,
  ];

  for (var p = 0; p < patterns.length; p++) {
    var match = body.match(patterns[p]);
    if (match && match[1] && match[1].indexOf("http") === 0) {
      return match[1];
    }
  }

  // Debug help: log all hrefs found so the user can update the pattern
  var allHrefs = body.match(/href=["'](https?:\/\/[^"'>\s]+)["']/gi) || [];
  Logger.log("No download link matched. All hrefs found in email body (" + allHrefs.length + "):");
  for (var h = 0; h < Math.min(allHrefs.length, 20); h++) {
    Logger.log("  " + allHrefs[h]);
  }

  throw new Error(
    "Could not extract a download link from the SellerSnap email. " +
    "SellerSnap may have changed their email HTML. " +
    "Check the execution log for all hrefs found. " +
    "Update the patterns in _extractDownloadLink() to match the new format."
  );
}

function _downloadCsv(url) {
  var response;
  try {
    response = UrlFetchApp.fetch(url, {muteHttpExceptions: true, followRedirects: true});
  } catch (e) {
    throw new Error("UrlFetchApp.fetch failed: " + e.message);
  }

  var code = response.getResponseCode();
  if (code !== 200) {
    throw new Error(
      "CSV download returned HTTP " + code + ". " +
      (code === 403 || code === 410
        ? "The download link has likely expired (links expire after 48 hours)."
        : "Unexpected response from the download URL.")
    );
  }

  var content = response.getContentText("UTF-8");
  if (!content || content.trim().length === 0) {
    throw new Error("CSV download returned empty content.");
  }

  return content;
}

function _labelThread(thread) {
  var label = _getOrCreateLabel(PROCESSED_LABEL);
  thread.addLabel(label);
}

function _getOrCreateLabel(name) {
  var label = GmailApp.getUserLabelByName(name);
  if (!label) {
    label = GmailApp.createLabel(name);
    Logger.log("Created Gmail label: " + name);
  }
  return label;
}

// ============================================================
// Validation helpers
// ============================================================

function _validateCsv(rows) {
  if (!rows || rows.length === 0) {
    throw new Error("CSV is empty — no rows parsed.");
  }

  var headerRow = rows[0];

  if (headerRow.length !== EXPECTED_COLS) {
    throw new Error(
      "CSV column count mismatch: expected " + EXPECTED_COLS +
      " columns but got " + headerRow.length + ". " +
      "SellerSnap may have added or removed columns. " +
      "Update EXPECTED_COLS and CLEAR_RANGE before re-running. " +
      "Sheet NOT modified."
    );
  }

  var headerLower = headerRow.map(function(h) { return h.trim().toLowerCase(); });
  for (var i = 0; i < EXPECTED_HEADERS.length; i++) {
    var expected = EXPECTED_HEADERS[i].toLowerCase();
    if (headerLower.indexOf(expected) === -1) {
      throw new Error(
        "Expected header column '" + EXPECTED_HEADERS[i] + "' not found in CSV. " +
        "SellerSnap may have renamed columns. " +
        "Update EXPECTED_HEADERS before re-running. " +
        "Sheet NOT modified."
      );
    }
  }
}

function _getTab(ss) {
  var sheet = ss.getSheetByName(TAB_NAME);
  if (!sheet) {
    throw new Error(
      "Target tab '" + TAB_NAME + "' not found in spreadsheet " + SPREADSHEET_ID + ". " +
      "Create the tab manually and re-run."
    );
  }
  return sheet;
}

// Pad or truncate each row to exactly EXPECTED_COLS columns.
// parseCsv may strip trailing empty fields; setValues requires uniform width.
function _normalizeRows(rows) {
  return rows.map(function(row) {
    var r = row.slice(0, EXPECTED_COLS);
    while (r.length < EXPECTED_COLS) {
      r.push("");
    }
    return r;
  });
}

// ============================================================
// Setup helper — run once
// ============================================================

// Creates the AtlasDB/SellerSnapImported Gmail label if it does not exist.
// Run this manually once before the first real import.
function setupSellerSnapLabel() {
  var label = _getOrCreateLabel(PROCESSED_LABEL);
  Logger.log("Label ready: " + label.getName());
}
