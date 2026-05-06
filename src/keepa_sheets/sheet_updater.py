"""
Keepa rolling sheet updater — US / CA / UK / DE.

Reads ASINs from the ASIN source column (AR) in the marketplace's KeepaXX tab,
queries the Keepa Product API in batches, and writes the returned product/pricing
fields back to the same sheet row.

Query mode: buybox=True, stats=90, history=False (~3 tokens/ASIN).

Supported marketplaces and Keepa domains:
  US → Keepa domain 'US'
  CA → Keepa domain 'CA'
  UK → Keepa domain 'GB'
  DE → Keepa domain 'DE'

Safety guarantees:
  - Dry-run queries Keepa but never writes to Google Sheets.
  - Blank/null values are never written (preserves existing cell data).
  - buybox_seller_id and upc are only written when Keepa returns a value.
  - No range clears; only targeted cell writes via batchUpdate.
  - Checkpoint file stores progress per marketplace independently.
  - API key is never printed or saved to output files.

BD (Monthly Sales Trends) is excluded: product.monthlySold is not returned
by the Keepa Product API in the buybox=True, history=False query mode.
"""

import datetime
import json
import logging
import math
import os
import re
from zoneinfo import ZoneInfo

_LONDON_TZ = ZoneInfo("Europe/London")
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_SRC_DIR, "..", ".."))
_STATE_DIR = os.path.join(_PROJECT_ROOT, "data", "state")
_LOG_DIR = os.path.join(_PROJECT_ROOT, "data", "logs")
_CHECKPOINT_FILE = os.path.join(_STATE_DIR, "keepa_rolling_checkpoint.json")

_BUY_BOX_IDX = 18  # Keepa csv_indices index for BUY_BOX_SHIPPING

_SHEET_CONFIG: dict[str, dict] = {
    "US": {
        "spreadsheet_id": "1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo",
        "tab": "KeepaUS",
        "asin_col": "AR",
        "first_data_row": 8,
        "sheet_locale": "com",   # value written to column Q
        "keepa_domain": "US",
    },
    "CA": {
        "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
        "tab": "KeepaCA",
        "asin_col": "AR",
        "first_data_row": 8,
        "sheet_locale": "ca",    # value written to column Q
        "keepa_domain": "CA",
    },
    "UK": {
        "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
        "tab": "KeepaUK",
        "asin_col": "AR",
        "first_data_row": 8,
        "sheet_locale": "co.uk", # value written to column Q
        "keepa_domain": "GB",    # Keepa uses 'GB' for the UK marketplace
    },
    "DE": {
        "spreadsheet_id": "1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk",
        "tab": "KeepaDE",
        "asin_col": "AR",
        "first_data_row": 8,
        "sheet_locale": "de",    # value written to column Q
        "keepa_domain": "DE",
    },
}

# Column letter for each writable field.
# Order matters for log output readability.
_COL_MAP: dict[str, str] = {
    "locale":                  "Q",
    "title":                   "R",
    "availability_amazon":     "Z",
    "fba_pick_pack_fee":       "AB",
    "current_buybox_price":    "AG",
    "buybox_90_day_avg":       "AI",
    "buybox_seller_id":        "AM",
    "category":                "AP",
    "subcategory":             "AQ",
    "ean":                     "AS",
    "upc":                     "AT",
    "part_number":             "AU",
    "brand":                   "AW",
    "weight_grams":            "BB",
    "referral_fee_percentage": "BF",
    "type":                    "BG",
}

# Fields only written when Keepa actually returns a value; a None result must
# not overwrite an existing cell value (e.g. a manually-entered seller ID).
# The general None-skip in _build_updates already handles this; this set
# documents intent and is checked explicitly in the log.
_CONDITIONAL_FIELDS = frozenset({"buybox_seller_id", "upc"})

_AVAIL_LABELS: dict[int, str] = {
    -1: "out_of_stock",
    0:  "in_stock_amazon",
    1:  "not_amazon",
    2:  "preorder",
    3:  "back_ordered",
}


# ── Checkpoint ────────────────────────────────────────────────────────────────
#
# Checkpoint file format (multi-marketplace):
#   { "CA": { "next_row_number": 18, "last_processed_asin": "B00...", ... },
#     "US": { ... }, ... }
#
# Old single-marketplace format ({"marketplace": "CA", "next_row_number": ...})
# is detected and silently migrated on first read.


def _read_all_checkpoints() -> dict:
    """Read the checkpoint file and return the full multi-marketplace dict.

    Migrates old single-marketplace format to the new format automatically.
    Returns {} if the file is absent or unreadable.
    """
    try:
        with open(_CHECKPOINT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    # Detect old format: top-level "marketplace" key with a string value
    if isinstance(data.get("marketplace"), str) and isinstance(data.get("next_row_number"), int):
        old_mp = data["marketplace"]
        migrated = {old_mp: {k: v for k, v in data.items() if k != "marketplace"}}
        _write_all_checkpoints(migrated)
        return migrated

    return data if isinstance(data, dict) else {}


def _write_all_checkpoints(all_data: dict) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    tmp_path = _CHECKPOINT_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2)
    os.replace(tmp_path, _CHECKPOINT_FILE)


def load_checkpoint(marketplace: str) -> dict | None:
    """Return the saved checkpoint entry for marketplace, or None if absent."""
    return _read_all_checkpoints().get(marketplace)


def save_checkpoint(
    marketplace: str,
    next_row: int,
    last_asin: str,
    tokens_before: int | None,
    tokens_after: int | None,
    total_processed: int,
) -> None:
    all_data = _read_all_checkpoints()
    all_data[marketplace] = {
        "next_row_number": next_row,
        "last_processed_asin": last_asin,
        "last_success_at": datetime.datetime.now(_LONDON_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "total_processed_in_last_run": total_processed,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "tokens_consumed": (
            (tokens_before - tokens_after)
            if tokens_before is not None and tokens_after is not None
            else None
        ),
    }
    _write_all_checkpoints(all_data)


# ── Field extraction ──────────────────────────────────────────────────────────

def _bb_price(stats: dict, field: str, idx: int) -> float | None:
    """Extract BUY_BOX_SHIPPING from stats[field][idx] and convert to currency."""
    container = stats.get(field)
    if container is None:
        return None
    try:
        val = container[idx]
    except (IndexError, KeyError, TypeError):
        try:
            val = container[str(idx)]
        except (IndexError, KeyError, TypeError):
            return None
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or f < 0:
        return None
    return round(f / 100.0, 2)


def _extract_fields(product: dict, locale: str) -> dict[str, object]:
    """Return {field_name: value} ready for sheet writing.

    None means 'no data available — skip this cell'.
    All field names correspond to keys in _COL_MAP.
    """
    r: dict = {}

    # Locale (always set — derived from config, not from Keepa)
    r["locale"] = locale

    # Title
    title = (product.get("title") or "").strip()
    r["title"] = title[:120] if title else None

    # Amazon availability — write human-readable label
    avail = product.get("availabilityAmazon")
    if avail is not None:
        r["availability_amazon"] = _AVAIL_LABELS.get(avail, f"code_{avail}")
    else:
        r["availability_amazon"] = None

    # FBA pick/pack fee (Keepa-cached; not SP-API authoritative)
    # Stored as integer 1/100 of local currency; divide by 100 for actual value
    fba_fees = product.get("fbaFees")
    r["fba_pick_pack_fee"] = None
    if isinstance(fba_fees, dict):
        ppf = fba_fees.get("pickAndPackFee")
        if ppf is not None:
            try:
                f = float(ppf)
                if f >= 0:
                    r["fba_pick_pack_fee"] = round(f / 100.0, 2)
            except (TypeError, ValueError):
                pass

    # Buy Box current and 90-day average
    stats = product.get("stats") or {}
    r["current_buybox_price"] = _bb_price(stats, "current", _BUY_BOX_IDX)
    r["buybox_90_day_avg"] = _bb_price(stats, "avg90", _BUY_BOX_IDX)

    # Buy Box seller (conditional — only written when non-null)
    # buyBoxSellerIdHistory is [timestamp, sellerId, timestamp, sellerId, ...];
    # filter to strings (seller IDs) and take the latest.
    bb_hist = product.get("buyBoxSellerIdHistory")
    r["buybox_seller_id"] = None
    if bb_hist and isinstance(bb_hist, (list, tuple)):
        sellers = [v for v in bb_hist if isinstance(v, str) and v]
        if sellers:
            r["buybox_seller_id"] = sellers[-1]

    # Category / subcategory (root and deepest node of categoryTree)
    cat_tree = product.get("categoryTree")
    r["category"] = None
    r["subcategory"] = None
    if cat_tree and isinstance(cat_tree, (list, tuple)):
        names: list[str] = []
        for item in cat_tree:
            if isinstance(item, dict):
                name = (item.get("name") or item.get("catName") or "").strip()
            elif isinstance(item, str):
                name = item.strip()
            else:
                name = ""
            if name:
                names.append(name)
        if names:
            r["category"] = names[0]
            r["subcategory"] = names[-1] if len(names) > 1 else None

    # EAN — first value only
    ean_list = product.get("eanList")
    r["ean"] = str(ean_list[0]) if ean_list and isinstance(ean_list, (list, tuple)) else None

    # UPC — first value only (conditional — only written when non-null)
    upc_list = product.get("upcList")
    r["upc"] = str(upc_list[0]) if upc_list and isinstance(upc_list, (list, tuple)) else None

    # Part number
    pn = product.get("partNumber")
    r["part_number"] = str(pn).strip() if pn else None

    # Brand
    brand = product.get("brand")
    r["brand"] = str(brand).strip() if brand else None

    # Weight — prefer packageWeight, fallback itemWeight (both in grams)
    weight_grams = None
    for wkey in ("packageWeight", "itemWeight"):
        w = product.get(wkey)
        if w is not None:
            try:
                fw = float(w)
                if fw > 0:
                    weight_grams = fw
                    break
            except (TypeError, ValueError):
                pass
    r["weight_grams"] = weight_grams

    # Referral fee % — prefer newer referralFeePercentage, fallback deprecated field
    referral = None
    for fkey in ("referralFeePercentage", "referralFeePercent"):
        fee = product.get(fkey)
        if fee is not None:
            try:
                referral = float(fee)
                break
            except (TypeError, ValueError):
                pass
    r["referral_fee_percentage"] = referral

    # Product type
    ptype = product.get("type")
    r["type"] = str(ptype) if ptype is not None else None

    return r


def _build_updates(row_num: int, fields: dict, tab: str) -> list[dict]:
    """Build Sheets ValueRange list for one row, skipping None/empty values.

    Conditional fields (buybox_seller_id, upc) are also None when absent, so
    the None check here naturally prevents overwriting existing cell data.
    """
    updates = []
    for field, col in _COL_MAP.items():
        val = fields.get(field)
        if val is None or val == "":
            continue
        updates.append({
            "range": f"{tab}!{col}{row_num}",
            "values": [[val]],
        })
    return updates


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging() -> tuple[logging.Logger, str]:
    os.makedirs(_LOG_DIR, exist_ok=True)
    ts = datetime.datetime.now(_LONDON_TZ).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(_LOG_DIR, f"keepa_sheet_update_{ts}.log")

    logger = logging.getLogger(f"keepa_updater_{ts}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    file_fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_fmt = logging.Formatter("  %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(file_fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(console_fmt)
    logger.addHandler(ch)

    return logger, log_path


# ── Main entry point ──────────────────────────────────────────────────────────

def run_sheet_update(
    marketplace: str,
    max_asins: int,
    dry_run: bool,
    reset_checkpoint: bool,
) -> dict:
    """Run one update pass for the given marketplace.

    marketplace:       'US' | 'CA' | 'UK' | 'DE'
    max_asins:         max ASINs to process in this run
    dry_run:           query Keepa, show planned writes, skip Sheets write
    reset_checkpoint:  ignore existing checkpoint and start from first row
    """
    if marketplace not in _SHEET_CONFIG:
        raise ValueError(
            f"Marketplace {marketplace!r} not configured. "
            f"Configured: {sorted(_SHEET_CONFIG)}"
        )

    cfg = _SHEET_CONFIG[marketplace]
    tab = cfg["tab"]
    spreadsheet_id = cfg["spreadsheet_id"]
    first_row = cfg["first_data_row"]
    locale = cfg["sheet_locale"]
    keepa_domain = cfg["keepa_domain"]
    run_mode = "DRY-RUN" if dry_run else "LIVE"

    logger, log_path = _setup_logging()
    logger.info(
        f"=== Keepa sheet updater  marketplace={marketplace}  "
        f"mode={run_mode}  max_asins={max_asins} ==="
    )
    logger.info(f"Log: {log_path}")

    # ── API key ───────────────────────────────────────────────────────────────
    try:
        import keepa
    except ImportError:
        raise ImportError("keepa is not installed. Run: pip install keepa")

    api_key = os.environ.get("KEEPA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "KEEPA_API_KEY not set. Add KEEPA_API_KEY=<key> to .env and retry."
        )
    logger.info(f"API key: ****{api_key[-4:]}")

    # ── Init Keepa ────────────────────────────────────────────────────────────
    try:
        api = keepa.Keepa(api_key)
    except Exception as exc:
        raise RuntimeError(f"Keepa API init failed: {exc}") from exc

    tokens_before: int | None = None
    refill_rate: int | None = None
    try:
        api.update_status()
        tokens_before = api.tokens_left
        refill_rate = getattr(api.status, "refillRate", None)
    except Exception as exc:
        logger.warning(f"Could not read token status: {exc}")

    logger.info(
        f"Tokens available: {tokens_before if tokens_before is not None else 'unavailable'}"
        f"  refill_rate={refill_rate}/min"
    )

    # ── Read ASINs from sheet ─────────────────────────────────────────────────
    from exports.google_sheets_client import get_sheets_service
    service = get_sheets_service()

    asin_range = f"{tab}!{cfg['asin_col']}{first_row}:{cfg['asin_col']}"
    resp = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=asin_range,
    ).execute()
    raw_rows = resp.get("values", [])

    # Build ordered list of (asin, sheet_row_number); dedup preserving order
    asin_rows: list[tuple[str, int]] = []
    seen: set[str] = set()
    for i, row in enumerate(raw_rows):
        if not row:
            continue
        cell = str(row[0]).strip().upper()
        if not _ASIN_RE.match(cell):
            continue
        if cell in seen:
            continue
        seen.add(cell)
        asin_rows.append((cell, first_row + i))

    logger.info(
        f"ASIN source: {asin_range}  "
        f"raw_rows={len(raw_rows)}  valid_unique={len(asin_rows)}"
    )

    if not asin_rows:
        raise ValueError(f"No valid ASINs found in {asin_range}")

    # ── Checkpoint ────────────────────────────────────────────────────────────
    if reset_checkpoint:
        logger.info("--reset-checkpoint: ignoring saved checkpoint, starting from row 1")
        start_row = first_row
    else:
        cp = load_checkpoint(marketplace)
        if cp:
            start_row = cp.get("next_row_number", first_row)
            logger.info(
                f"Checkpoint: next_row={start_row}  "
                f"last_asin={cp.get('last_processed_asin')}  "
                f"last_success={cp.get('last_success_at')}"
            )
        else:
            start_row = first_row
            logger.info("No checkpoint found, starting from first row")

    # Wrap-around: if checkpoint is past the last ASIN row, cycle back to start
    max_row = asin_rows[-1][1]
    if start_row > max_row:
        logger.info(
            f"Checkpoint row {start_row} is past last ASIN row {max_row}. "
            "Wrapping to beginning."
        )
        start_row = first_row

    # Find index in asin_rows where row_number >= start_row
    start_idx = 0
    for idx, (_, rn) in enumerate(asin_rows):
        if rn >= start_row:
            start_idx = idx
            break

    batch_items = asin_rows[start_idx : start_idx + max_asins]
    batch_truncated = False

    if not batch_items:
        logger.info("No ASINs in batch range — nothing to do.")
        return {
            "status": "NOTHING_TO_DO",
            "marketplace": marketplace,
            "max_asin_row": max_row,
            "batch_last_row": None,
            "checkpoint_saved": False,
            "batch_truncated": False,
        }

    batch_asins = [a for a, _ in batch_items]
    batch_rows = [r for _, r in batch_items]

    logger.info(
        f"Batch: {len(batch_items)} ASINs  "
        f"rows {batch_rows[0]}–{batch_rows[-1]}  "
        f"first={batch_asins[0]}  last={batch_asins[-1]}"
    )

    # ── Token check ───────────────────────────────────────────────────────────
    required_tokens = len(batch_asins) * 3

    if tokens_before is not None and tokens_before < required_tokens:
        reduced = tokens_before // 3
        if reduced == 0:
            raise RuntimeError(
                f"Insufficient tokens: need {required_tokens} "
                f"({len(batch_asins)} ASINs × 3), have {tokens_before}. "
                f"Refill rate: {refill_rate}/min. Wait and retry."
            )
        logger.warning(
            f"Tokens ({tokens_before}) < required ({required_tokens}). "
            f"Reducing batch from {len(batch_asins)} to {reduced} ASINs."
        )
        batch_items = batch_items[:reduced]
        batch_asins = [a for a, _ in batch_items]
        batch_rows = [r for _, r in batch_items]
        required_tokens = len(batch_asins) * 3
        batch_truncated = True

    logger.info(
        f"{'DRY-RUN: Would query' if dry_run else 'Querying'} "
        f"{len(batch_asins)} ASINs  est_tokens={required_tokens}"
    )

    # ── Query Keepa ───────────────────────────────────────────────────────────
    try:
        products = api.query(
            batch_asins,
            stats=90,
            history=False,
            buybox=True,
            domain=keepa_domain,
            progress_bar=False,
        )
    except Exception as exc:
        raise RuntimeError(f"Keepa query failed: {exc}") from exc

    tokens_after: int | None = None
    try:
        api.update_status()
        tokens_after = api.tokens_left
    except Exception:
        pass

    tokens_consumed = (
        (tokens_before - tokens_after)
        if tokens_before is not None and tokens_after is not None
        else None
    )
    logger.info(
        f"Tokens after: {tokens_after}  consumed: {tokens_consumed}  "
        f"per_asin: {f'{tokens_consumed / len(batch_asins):.2f}' if tokens_consumed is not None else 'n/a'}"
    )

    # ── Extract fields and build updates ──────────────────────────────────────
    # Keepa returns products sorted by ASIN, not in request order.
    # Build a lookup dict so each requested ASIN maps to its correct product.
    asin_to_product: dict[str, dict] = {
        str(p.get("asin") or "").upper(): p
        for p in products
        if p.get("asin")
    }

    if len(asin_to_product) != len(batch_asins):
        logger.warning(
            f"Keepa returned {len(asin_to_product)} unique ASINs "
            f"for {len(batch_asins)} requested"
        )

    all_updates: list[dict] = []
    skipped_asins: list[str] = []
    total_cells_written = 0
    total_cells_skipped = 0

    for req_asin, row_num in batch_items:
        product = asin_to_product.get(req_asin)
        if product is None:
            logger.warning(
                f"  {req_asin} row={row_num}: not in Keepa response — skipping"
            )
            skipped_asins.append(req_asin)
            continue

        # Skip products with no meaningful data
        has_data = any(
            product.get(k) for k in ("title", "brand", "fbaFees", "stats")
        )
        if not has_data:
            logger.warning(
                f"  {req_asin} row={row_num}: Keepa returned empty product — skipping"
            )
            skipped_asins.append(req_asin)
            continue

        fields = _extract_fields(product, locale)
        row_updates = _build_updates(row_num, fields, tab)

        written_ranges = {u["range"] for u in row_updates}
        n_written = len(row_updates)
        n_skipped = len(_COL_MAP) - n_written
        total_cells_written += n_written
        total_cells_skipped += n_skipped

        written_cols = [u["range"].split("!")[-1] for u in row_updates]
        all_updates.extend(row_updates)

        cond_skipped = [
            f for f in _CONDITIONAL_FIELDS if fields.get(f) is None
        ]
        skip_note = f"  cond_skipped={cond_skipped}" if cond_skipped else ""
        logger.info(
            f"  {req_asin} row={row_num}  "
            f"write={n_written} [{','.join(written_cols)}]  "
            f"blank_skip={n_skipped}{skip_note}"
        )

    # ── Dry-run output ────────────────────────────────────────────────────────
    if dry_run:
        print(f"\n  {'=' * 58}")
        print(f"  DRY-RUN SUMMARY  marketplace={marketplace}  mode=buybox")
        print(f"  {'=' * 58}")
        print(f"  ASINs queried       : {len(batch_asins)}")
        print(f"  Tokens consumed     : {tokens_consumed}")
        print(f"  Cells would write   : {total_cells_written}")
        print(f"  Cells skipped blank : {total_cells_skipped}")
        print(f"  Skipped ASINs       : {skipped_asins or 'none'}")
        if all_updates:
            print()
            print("  Planned writes (first 30):")
            for upd in all_updates[:30]:
                val = upd["values"][0][0]
                print(f"    {upd['range']:<28}  {repr(val)[:60]}")
            if len(all_updates) > 30:
                print(f"    ... and {len(all_updates) - 30} more")
        print()
        print("  No data was written to Google Sheets.")
        print(f"  Log: {log_path}")
        logger.info(
            f"DRY-RUN complete: {total_cells_written} updates prepared, 0 written"
        )
        return {
            "status": "DRY_RUN",
            "marketplace": marketplace,
            "batch_size": len(batch_asins),
            "updates_prepared": total_cells_written,
            "cells_skipped": total_cells_skipped,
            "skipped_asins": skipped_asins,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_consumed": tokens_consumed,
            "log_path": log_path,
            "max_asin_row": max_row,
            "batch_last_row": batch_rows[-1],
            "checkpoint_saved": False,
            "batch_truncated": batch_truncated,
        }

    # ── Live write ────────────────────────────────────────────────────────────
    if not all_updates:
        logger.info("No updates to write — all fields blank or all ASINs skipped")
        return {
            "status": "SUCCESS",
            "marketplace": marketplace,
            "batch_size": len(batch_asins),
            "cells_written": 0,
            "cells_skipped": total_cells_skipped,
            "skipped_asins": skipped_asins,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_consumed": tokens_consumed,
            "log_path": log_path,
            "max_asin_row": max_row,
            "batch_last_row": batch_rows[-1],
            "checkpoint_saved": False,
            "batch_truncated": batch_truncated,
        }

    logger.info(
        f"Writing {len(all_updates)} cell updates to {tab} via batchUpdate..."
    )
    body = {
        "valueInputOption": "USER_ENTERED",
        "data": all_updates,
    }
    try:
        resp = service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body,
        ).execute()
        sheets_written = resp.get("totalUpdatedCells", len(all_updates))
        logger.info(f"Sheets batchUpdate: {sheets_written} cells updated")
    except Exception as exc:
        raise RuntimeError(f"Sheets batchUpdate failed: {exc}") from exc

    # ── Save checkpoint ───────────────────────────────────────────────────────
    last_asin_written, last_row_written = batch_items[-1]
    next_row = last_row_written + 1
    save_checkpoint(
        marketplace=marketplace,
        next_row=next_row,
        last_asin=last_asin_written,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        total_processed=len(batch_items),
    )
    logger.info(
        f"Checkpoint saved: next_row={next_row}  last_asin={last_asin_written}"
    )

    logger.info(
        f"=== DONE  cells_written={total_cells_written}  "
        f"cells_skipped_blank={total_cells_skipped}  "
        f"skipped_asins={skipped_asins} ==="
    )

    return {
        "status": "SUCCESS",
        "marketplace": marketplace,
        "batch_size": len(batch_asins),
        "cells_written": total_cells_written,
        "cells_skipped": total_cells_skipped,
        "skipped_asins": skipped_asins,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "tokens_consumed": tokens_consumed,
        "next_row": next_row,
        "log_path": log_path,
        "max_asin_row": max_row,
        "batch_last_row": batch_rows[-1],
        "checkpoint_saved": True,
        "batch_truncated": batch_truncated,
    }
