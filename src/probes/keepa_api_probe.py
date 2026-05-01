"""
Keepa API probe — token cost and field coverage test.

Tests whether the Keepa Product API can supply:
  - Current Buy Box price
  - 90-day Buy Box average
  - FBA fee (expected: not available — use SP-API instead)

Probe modes:
  cheap      : stats=90, history=False, buybox=False  (baseline token cost)
  buybox     : stats=90, history=False, buybox=True   (+2 tokens/product)
  history    : stats=90, history=True,  days=90        (larger payload)
  all        : runs cheap → buybox → history sequentially
  field-probe: buybox=True, stats=90 — tests all 17 sheet fields for coverage

Each mode writes a CSV and a JSON summary to data/processed/keepa_api_probe/.

Token tracking:
  api.update_status() fetches the token balance without consuming tokens.
  api.tokens_left is updated automatically after every query call.
  tokens_consumed = tokens_before - tokens_after

Keepa price units:
  All prices are integers in units of 1/100 of the local currency
  (e.g. 1999 → $19.99 CAD).  -1 means the price type is unavailable.
  When out_of_stock_as_nan=True (default) unavailable prices become NaN.

Price type indices (keepa.csv_indices):
  18 = BUY_BOX_SHIPPING   ← current Buy Box price
  10 = NEW_FBA            ← cheapest FBA-fulfilled new price (NOT an FBA fee)
  FBA fee: NOT returned by Keepa — use SP-API product fees endpoint instead.
"""

import csv
import datetime
import json
import math
import os
import re
from zoneinfo import ZoneInfo

_LONDON_TZ = ZoneInfo("Europe/London")
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

_BUY_BOX_IDX = 18  # csv_indices index for BUY_BOX_SHIPPING
_NEW_FBA_IDX = 10   # csv_indices index for NEW_FBA (FBA seller price, not a fee)

_ASIN_SOURCES: dict[str, dict] = {
    "CA": {
        "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
        "sheet_range": "KeepaCA!AR8:AR",
    },
}

_OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "keepa_api_probe")
)

# Probe mode definitions
_MODE_PARAMS: dict[str, dict] = {
    "cheap": {
        "stats": 90,
        "history": False,
        "buybox": False,
        "days": None,
        "description": "stats=90, no history, no buybox — baseline token cost",
        "expected_token_cost": "~1 per product",
    },
    "buybox": {
        "stats": 90,
        "history": False,
        "buybox": True,
        "days": None,
        "description": "stats=90, buybox=True — +2 tokens/product vs cheap",
        "expected_token_cost": "~3 per product",
    },
    "history": {
        "stats": 90,
        "history": True,
        "buybox": False,
        "days": 90,
        "description": "stats=90, history=True, days=90 — includes BUY_BOX_SHIPPING history array",
        "expected_token_cost": "~1 per product (history cost depends on data size)",
    },
}

# ── Field-probe constants ─────────────────────────────────────────────────────

_AVAILABILITY_AMAZON_LABELS: dict[int, str] = {
    -1: "out_of_stock",
    0:  "in_stock_amazon",
    1:  "not_amazon",
    2:  "preorder",
    3:  "back_ordered",
}

_FIELD_PROBE_CSV_FIELDS = [
    "asin", "locale", "title",
    "availability_amazon_raw", "availability_amazon_label",
    "fba_fees_raw_summary", "fba_pick_pack_fee",
    "current_buybox_price", "buybox_90_day_avg",
    "buybox_seller_id",
    "category", "subcategory",
    "ean", "upc", "part_number", "brand",
    "weight_grams",
    "monthly_sold", "monthly_sold_history_summary",
    "referral_fee_percentage",
    "type", "product_type_raw",
    "extraction_notes",
]


# ── Keepa check ───────────────────────────────────────────────────────────────

def _check_keepa() -> None:
    try:
        import keepa  # noqa: F401
    except ImportError:
        raise ImportError(
            "keepa is not installed. Run: pip install keepa"
        )


# ── ASIN reading ──────────────────────────────────────────────────────────────

def read_asins(marketplace: str, limit: int) -> tuple[list[str], dict]:
    """Read, validate, and deduplicate ASINs from the source spreadsheet.

    Returns up to `limit` valid ASINs and a stats dict.
    """
    if marketplace not in _ASIN_SOURCES:
        raise ValueError(
            f"Marketplace {marketplace!r} not configured. "
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
            invalid += 1
            continue
        if cell in seen:
            dup += 1
            continue
        seen.add(cell)
        valid.append(cell)
        if len(valid) >= limit:
            break

    stats = {
        "raw": len(raw_rows),
        "blank": blank,
        "invalid": invalid,
        "duplicates_removed": dup,
        "valid": len(valid),
        "limit_applied": limit,
    }

    print(f"  Raw rows     : {len(raw_rows)}")
    print(f"  Invalid/blank: {blank + invalid}  dupes: {dup}")
    print(f"  Valid (capped at {limit}): {len(valid)}")

    if not valid:
        raise ValueError(
            f"No valid ASINs found in {src['sheet_range']}. "
            "Check the range contains 10-char uppercase alphanumeric ASINs."
        )

    return valid, stats


# ── Token tracking ────────────────────────────────────────────────────────────

def _get_token_status(api) -> dict:
    """Call update_status() and return token info dict. Never raises."""
    try:
        api.update_status()
        return {
            "tokens_left": api.tokens_left,
            "refill_rate_per_min": getattr(api.status, "refillRate", None),
            "refill_in_ms": getattr(api.status, "refillIn", None),
        }
    except Exception as exc:
        return {
            "tokens_left": None,
            "refill_rate_per_min": None,
            "refill_in_ms": None,
            "error": str(exc),
        }


# ── Product data extraction ───────────────────────────────────────────────────

def _keepa_price(raw) -> float | None:
    """Convert raw Keepa price integer to float currency value.

    Returns None if value is -1, NaN, None, or otherwise unavailable.
    """
    if raw is None:
        return None
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or f < 0:
        return None
    return round(f / 100.0, 2)


def _safe_list_get(seq, idx):
    """Return seq[idx] or None without raising."""
    try:
        return seq[idx]
    except (IndexError, KeyError, TypeError):
        return None


def _extract_stats_field(stats: dict, field: str, idx: int):
    """Extract stats[field][idx] using both list and dict access."""
    container = stats.get(field)
    if container is None:
        return None, f"stats.{field} missing"
    val = _safe_list_get(container, idx)
    if val is None:
        val = _safe_list_get(container, str(idx))
    if val is None:
        return None, f"stats.{field}[{idx}] not found"
    return _keepa_price(val), f"stats.{field}[{idx}]"


def _extract_buybox_seller(product: dict) -> tuple[str | None, str]:
    """Extract the latest Buy Box seller ID from buyBoxSellerIdHistory."""
    history = product.get("buyBoxSellerIdHistory")
    if not history or not isinstance(history, (list, tuple)):
        return None, "buyBoxSellerIdHistory missing or empty"
    sellers = [v for v in history if isinstance(v, str) and v]
    if sellers:
        return sellers[-1], f"buyBoxSellerIdHistory, {len(sellers)} seller entries"
    last = history[-1]
    if isinstance(last, str) and last:
        return last, "buyBoxSellerIdHistory[-1]"
    return None, f"buyBoxSellerIdHistory present (len={len(history)}) but no string seller ID"


def _extract_categories(product: dict) -> tuple[str | None, str | None, str]:
    """Return (root_category, deepest_category, note) from categoryTree."""
    cat_tree = product.get("categoryTree")
    if not cat_tree or not isinstance(cat_tree, (list, tuple)):
        return None, None, "categoryTree missing or empty"
    names: list[str] = []
    for item in cat_tree:
        if isinstance(item, dict):
            name = (item.get("name") or item.get("catName") or "").strip()
            if not name and "catId" in item:
                name = f"catId={item['catId']}"
        elif isinstance(item, str):
            name = item.strip()
        else:
            name = str(item)
        if name:
            names.append(name)
    if not names:
        return None, None, f"categoryTree len={len(cat_tree)} but no names found"
    root = names[0]
    leaf = names[-1] if len(names) > 1 else None
    return root, leaf, f"categoryTree depth={len(names)}"


def _extract_fba_fees(product: dict) -> tuple[float | None, str, str]:
    """Extract FBA pick/pack fee from fbaFees dict.

    Returns (fee_float_or_None, raw_summary_string, notes).
    Prices in fbaFees are stored as integers in 1/100 of local currency.
    """
    fba = product.get("fbaFees")
    if fba is None:
        return None, "", "fbaFees missing/null — use SP-API fees endpoint"
    if not isinstance(fba, dict):
        return None, repr(fba)[:120], f"fbaFees unexpected type: {type(fba).__name__}"
    summary_parts = [
        f"{k}={v}" for k, v in fba.items()
        if isinstance(v, (int, float)) and v is not None
    ]
    raw_summary = ", ".join(summary_parts[:10])
    pick_and_pack = fba.get("pickAndPackFee")
    if pick_and_pack is not None and float(pick_and_pack) >= 0:
        return round(float(pick_and_pack) / 100.0, 2), raw_summary, f"fbaFees.pickAndPackFee={pick_and_pack}"
    generic = fba.get("fbaFee")
    if generic is not None and float(generic) >= 0:
        return round(float(generic) / 100.0, 2), raw_summary, f"fbaFees.fbaFee={generic}"
    return None, raw_summary, f"fbaFees present, no known pick/pack key (keys: {list(fba.keys())})"


def _extract_weight(product: dict) -> tuple[float | None, str]:
    """Return (weight_grams, source_note), preferring packageWeight over itemWeight."""
    pkg_w = product.get("packageWeight")
    if pkg_w is not None:
        try:
            f = float(pkg_w)
            if f > 0:
                return f, "packageWeight"
        except (TypeError, ValueError):
            pass
    item_w = product.get("itemWeight")
    if item_w is not None:
        try:
            f = float(item_w)
            if f > 0:
                return f, "itemWeight (packageWeight missing/zero)"
        except (TypeError, ValueError):
            pass
    return None, "packageWeight and itemWeight both missing/zero"


def _extract_monthly_sold(product: dict) -> tuple[str | None, str | None, str]:
    """Return (monthly_sold_str, history_summary_or_None, notes)."""
    monthly = product.get("monthlySold")
    notes: list[str] = []
    if monthly is not None:
        monthly_str: str | None = str(monthly)
        notes.append(f"monthlySold={monthly}")
    else:
        monthly_str = None
        notes.append("monthlySold missing")
    history_summary: str | None = None
    data = product.get("data") or {}
    if isinstance(data, dict):
        sales_key = next((k for k in data.keys() if "SALES" in str(k).upper()), None)
        if sales_key:
            arr = data[sales_key]
            if hasattr(arr, "__len__") and len(arr) > 0:
                history_summary = f"last={arr[-1]}, len={len(arr)}"
                notes.append(f"data[{sales_key!r}] len={len(arr)}")
            else:
                notes.append(f"data[{sales_key!r}] empty")
        else:
            notes.append("data has no SALES key (expected with history=False)")
    return monthly_str, history_summary, " | ".join(notes)


def _extract_referral_fee(product: dict) -> tuple[float | None, str]:
    """Return (referral_fee_percentage, source_note)."""
    fee = product.get("referralFeePercentage")
    if fee is not None:
        try:
            return float(fee), "referralFeePercentage"
        except (TypeError, ValueError):
            pass
    fee2 = product.get("referralFeePercent")
    if fee2 is not None:
        try:
            return float(fee2), "referralFeePercent (deprecated fallback)"
        except (TypeError, ValueError):
            pass
    return None, "referralFeePercentage and referralFeePercent both missing"


def extract_product(product: dict) -> dict:
    """Extract probe fields from one Keepa product dict.

    Returns a flat dict suitable for CSV output.
    """
    asin = str(product.get("asin") or "")
    title = str(product.get("title") or "")[:100]
    domain_id = product.get("domainId", "")

    notes: list[str] = []
    top_keys = sorted(str(k) for k in product.keys())

    # ── stats block ───────────────────────────────────────────────────────────
    stats = product.get("stats") or {}
    stats_keys = sorted(str(k) for k in stats.keys()) if isinstance(stats, dict) else []

    current_bb, bb_src = _extract_stats_field(stats, "current", _BUY_BOX_IDX)
    avg90_bb, avg90_src = _extract_stats_field(stats, "avg90", _BUY_BOX_IDX)

    if current_bb is not None:
        notes.append(f"BB_current OK via {bb_src}")
    else:
        notes.append(f"BB_current not found ({bb_src})")

    if avg90_bb is not None:
        notes.append(f"BB_avg90 OK via {avg90_src}")
    else:
        notes.append(f"BB_avg90 not found ({avg90_src})")

    # ── data / history block ──────────────────────────────────────────────────
    data = product.get("data") or {}
    data_bb_present = False
    data_bb_len = None
    data_all_keys: list[str] = []

    if isinstance(data, dict):
        data_all_keys = sorted(str(k) for k in data.keys())
        bb_keys = [k for k in data.keys() if "BUY_BOX" in str(k).upper()]
        if bb_keys:
            data_bb_present = True
            data_bb_len = len(data.get(bb_keys[0], []))
            notes.append(f"data BUY_BOX keys: {bb_keys}  len={data_bb_len}")
        else:
            notes.append("data has no BUY_BOX keys")

    # ── FBA fee ───────────────────────────────────────────────────────────────
    # Keepa does not provide FBA fees directly.
    # NEW_FBA (idx 10) is the cheapest FBA-fulfilled new price, not a fee amount.
    fba_fee = None
    notes.append("fba_fee: not in Keepa — use SP-API fees endpoint")

    return {
        "asin": asin,
        "title": title,
        "domain_id": domain_id,
        "current_buybox_price": current_bb,
        "buybox_90_day_avg": avg90_bb,
        "buybox_source_field": bb_src,
        "fba_fee": fba_fee,
        "extraction_notes": " | ".join(notes),
        "raw_top_keys": ",".join(top_keys),
        "stats_keys": ",".join(stats_keys),
        "data_bb_present": data_bb_present,
        "data_bb_len": data_bb_len,
        "data_all_keys_sample": ",".join(data_all_keys[:20]),
    }


def extract_product_fields(product: dict, marketplace: str) -> dict:
    """Extract all 17 expanded field-probe columns from one Keepa product dict."""
    asin = str(product.get("asin") or "")
    notes: list[str] = []

    # 1. Locale (derived)
    locale = marketplace

    # 2. Title
    title = str(product.get("title") or "")[:120]

    # 3. Amazon availability
    avail_raw = product.get("availabilityAmazon")
    if avail_raw is None:
        avail_label: str = "missing"
        notes.append("availabilityAmazon missing")
    else:
        avail_label = _AVAILABILITY_AMAZON_LABELS.get(avail_raw, f"unknown({avail_raw})")

    # 4. FBA fees
    fba_pick_pack, fba_raw_summary, fba_note = _extract_fba_fees(product)
    notes.append(f"fba: {fba_note}")

    # 5 & 6. Buy Box current and 90-day avg
    stats = product.get("stats") or {}
    current_bb, bb_src = _extract_stats_field(stats, "current", _BUY_BOX_IDX)
    avg90_bb, _ = _extract_stats_field(stats, "avg90", _BUY_BOX_IDX)
    if current_bb is None:
        notes.append(f"BB_current not found ({bb_src})")

    # 7. Buy Box seller
    bb_seller, seller_note = _extract_buybox_seller(product)
    notes.append(f"bb_seller: {seller_note}")

    # 8 & 9. Category / subcategory
    category, subcategory, cat_note = _extract_categories(product)
    notes.append(f"category: {cat_note}")

    # 10 & 11. EAN / UPC
    ean_list = product.get("eanList")
    ean: str | None = None
    if ean_list and isinstance(ean_list, (list, tuple)):
        ean = "|".join(str(v) for v in ean_list[:5]) if len(ean_list) > 1 else str(ean_list[0])

    upc_list = product.get("upcList")
    upc: str | None = None
    if upc_list and isinstance(upc_list, (list, tuple)):
        upc = "|".join(str(v) for v in upc_list[:5]) if len(upc_list) > 1 else str(upc_list[0])

    # 12. Part number
    part_number_raw = product.get("partNumber")
    part_number = str(part_number_raw) if part_number_raw else None

    # 13. Brand
    brand_raw = product.get("brand")
    brand = str(brand_raw) if brand_raw else None

    # 14. Weight
    weight_grams, weight_src = _extract_weight(product)
    if weight_grams is None:
        notes.append(f"weight: {weight_src}")

    # 15. Monthly sold
    monthly_sold, monthly_history, monthly_note = _extract_monthly_sold(product)
    notes.append(f"monthly: {monthly_note}")

    # 16. Referral fee
    referral_fee_pct, ref_note = _extract_referral_fee(product)
    notes.append(f"referral: {ref_note}")

    # 17. Type
    ptype = product.get("type")
    ptype_raw = product.get("productType")
    type_val = str(ptype) if ptype is not None else None

    return {
        "asin": asin,
        "locale": locale,
        "title": title,
        "availability_amazon_raw": avail_raw,
        "availability_amazon_label": avail_label,
        "fba_fees_raw_summary": fba_raw_summary or "",
        "fba_pick_pack_fee": fba_pick_pack,
        "current_buybox_price": current_bb,
        "buybox_90_day_avg": avg90_bb,
        "buybox_seller_id": bb_seller,
        "category": category,
        "subcategory": subcategory,
        "ean": ean,
        "upc": upc,
        "part_number": part_number,
        "brand": brand,
        "weight_grams": weight_grams,
        "monthly_sold": monthly_sold,
        "monthly_sold_history_summary": monthly_history,
        "referral_fee_percentage": referral_fee_pct,
        "type": type_val,
        "product_type_raw": ptype_raw,
        "extraction_notes": " | ".join(notes),
    }


def _sanitize_for_json(product: dict) -> dict:
    """Return a compact, JSON-safe summary of a product dict (no huge arrays)."""
    out: dict = {}
    for key, val in product.items():
        if isinstance(val, (str, int, float, bool, type(None))):
            out[key] = val
        elif isinstance(val, dict):
            # stats is usually compact; include it fully
            if key == "stats":
                out[key] = _safe_dict_for_json(val)
            else:
                inner = {k: v for k, v in list(val.items())[:8]
                         if isinstance(v, (str, int, float, bool, type(None)))}
                inner["_key_count"] = len(val)
                out[key] = inner
        elif hasattr(val, "__len__"):
            n = len(val)
            if n <= 5:
                try:
                    out[key] = [_json_safe(v) for v in val]
                except Exception:
                    out[key] = f"<len={n}>"
            else:
                try:
                    out[key] = [_json_safe(v) for v in list(val)[:3]] + [f"...({n} total)"]
                except Exception:
                    out[key] = f"<len={n}>"
        else:
            out[key] = repr(val)[:120]
    return out


def _safe_dict_for_json(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        elif hasattr(v, "__len__"):
            n = len(v)
            if n <= 5:
                try:
                    out[k] = [_json_safe(x) for x in v]
                except Exception:
                    out[k] = f"<len={n}>"
            else:
                try:
                    out[k] = [_json_safe(x) for x in list(v)[:3]] + [f"...({n} total)"]
                except Exception:
                    out[k] = f"<len={n}>"
        elif isinstance(v, dict):
            out[k] = {str(kk): _json_safe(vv) for kk, vv in list(v.items())[:5]}
        else:
            out[k] = repr(v)[:80]
    return out


def _json_safe(val):
    """Convert a value to something JSON-serializable."""
    if isinstance(val, (str, bool, type(None))):
        return val
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        # Return int if it looks like one, else float
        if f == int(f) and abs(f) < 1e15:
            return int(f)
        return round(f, 6)
    except (TypeError, ValueError):
        return repr(val)[:80]


# ── Field probe runner ────────────────────────────────────────────────────────

def _run_field_probe(
    api,
    asins: list[str],
    marketplace: str,
    timestamp: str,
) -> dict:
    """Run expanded field-availability probe with buybox=True, stats=90.

    Tests 17 sheet fields in a single query pass to determine which are
    reliably available from the Keepa Product API at ~3 tokens/ASIN.
    """
    print()
    print("  -- Mode: field-probe -----------------------------------------------")
    print(f"  ASINs      : {len(asins)}  ({asins[0]} ... {asins[-1]})")
    print("  Params     : stats=90  history=False  buybox=True")
    print("  Expected   : ~3 tokens per product")

    tok_before = _get_token_status(api)
    print(f"  Tokens before: {tok_before.get('tokens_left', 'unavailable')}"
          f"  refill_rate={tok_before.get('refill_rate_per_min', '?')}/min")

    qkwargs: dict = {
        "stats": 90,
        "history": False,
        "buybox": True,
        "domain": marketplace,
        "progress_bar": False,
    }

    t0 = datetime.datetime.now(_LONDON_TZ)
    try:
        products = api.query(asins, **qkwargs)
    except Exception as exc:
        print(f"  QUERY ERROR: {exc}")
        return {
            "mode": "field-probe",
            "status": "QUERY_ERROR",
            "error": str(exc),
            "tokens_before": tok_before,
        }
    t1 = datetime.datetime.now(_LONDON_TZ)
    elapsed = (t1 - t0).total_seconds()

    tok_after = _get_token_status(api)
    tb = tok_before.get("tokens_left")
    ta = tok_after.get("tokens_left")
    tokens_consumed = (tb - ta) if (tb is not None and ta is not None) else None
    per_asin = (tokens_consumed / len(asins)) if tokens_consumed is not None else None

    print(f"  Tokens after : {ta}  consumed: {tokens_consumed}"
          f"  per ASIN: {f'{per_asin:.2f}' if per_asin is not None else 'n/a'}")
    print(f"  Returned     : {len(products)} products  elapsed: {elapsed:.1f}s")

    rows: list[dict] = [extract_product_fields(p, marketplace) for p in products]

    coverage_fields: list[tuple[str, str]] = [
        ("locale",                  "derived (marketplace)"),
        ("title",                   "product.title"),
        ("availability_amazon_raw", "product.availabilityAmazon"),
        ("fba_pick_pack_fee",       "product.fbaFees.pickAndPackFee"),
        ("current_buybox_price",    "stats.current[18]"),
        ("buybox_90_day_avg",       "stats.avg90[18]"),
        ("buybox_seller_id",        "product.buyBoxSellerIdHistory"),
        ("category",                "product.categoryTree[0]"),
        ("subcategory",             "product.categoryTree[-1]"),
        ("ean",                     "product.eanList"),
        ("upc",                     "product.upcList"),
        ("part_number",             "product.partNumber"),
        ("brand",                   "product.brand"),
        ("weight_grams",            "product.packageWeight / itemWeight"),
        ("monthly_sold",            "product.monthlySold"),
        ("referral_fee_percentage", "product.referralFeePercentage"),
        ("type",                    "product.type"),
    ]

    coverage: dict[str, dict] = {}
    for col, source in coverage_fields:
        found = sum(
            1 for r in rows
            if r.get(col) is not None and r.get(col) != ""
        )
        coverage[col] = {"found": found, "total": len(rows), "source": source}

    print()
    print(f"  {'Field':<35} {'Found':>7}  Source")
    for col, info in coverage.items():
        total = info["total"]
        found = info["found"]
        if found == total:
            mark = "OK"
        elif found > 0:
            mark = " ~"
        else:
            mark = "--"
        print(f"  [{mark}] {col:<31} {found:>2}/{total}  {info['source']}")

    for r in rows[:3]:
        bb = f"${r['current_buybox_price']:.2f}" if r["current_buybox_price"] is not None else "--"
        print(f"    {r['asin']}  BB={bb}  brand={r['brand'] or '--'}  {r['title'][:50]}")

    # Write CSV
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(
        _OUTPUT_DIR, f"keepa_field_probe_{marketplace}_buybox_{timestamp}.csv"
    )
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELD_PROBE_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV          : {csv_path}")

    # Write JSON
    json_payload = {
        "probe_meta": {
            "probe_type": "field-probe",
            "marketplace": marketplace,
            "timestamp": timestamp,
            "elapsed_s": round(elapsed, 2),
        },
        "query_params": qkwargs,
        "token_tracking": {
            "before": tok_before,
            "after": tok_after,
            "consumed": tokens_consumed,
            "per_asin": round(per_asin, 3) if per_asin is not None else None,
        },
        "requested_asins": asins,
        "returned_count": len(products),
        "coverage_summary": coverage,
        "field_samples": [extract_product_fields(p, marketplace) for p in products[:3]],
    }
    json_path = os.path.join(
        _OUTPUT_DIR, f"keepa_field_probe_{marketplace}_buybox_{timestamp}.json"
    )
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(json_payload, fh, indent=2, default=str)
    print(f"  JSON         : {json_path}")

    return {
        "mode": "field-probe",
        "status": "SUCCESS",
        "asins_requested": len(asins),
        "asins_returned": len(products),
        "tokens_consumed": tokens_consumed,
        "tokens_per_asin": per_asin,
        "coverage": coverage,
        "elapsed_s": round(elapsed, 2),
        "csv_path": csv_path,
        "json_path": json_path,
    }


# ── Single-mode runner ────────────────────────────────────────────────────────

def _run_mode(
    api,
    mode: str,
    asins: list[str],
    marketplace: str,
    timestamp: str,
) -> dict:
    """Run one probe mode and write its CSV and JSON output files."""
    import keepa

    params = _MODE_PARAMS[mode]
    print()
    print(f"  ── Mode: {mode} ──────────────────────────────────────────")
    print(f"  ASINs      : {len(asins)}  ({asins[0]} … {asins[-1]})")
    print(f"  Params     : stats={params['stats']}  history={params['history']}"
          f"  buybox={params['buybox']}  days={params['days']}")
    print(f"  Expected   : {params['expected_token_cost']}")

    # Token status before
    tok_before = _get_token_status(api)
    print(f"  Tokens before: {tok_before.get('tokens_left', 'unavailable')}"
          f"  refill_rate={tok_before.get('refill_rate_per_min', '?')}/min")

    # Build query kwargs
    qkwargs: dict = {
        "stats": params["stats"],
        "history": params["history"],
        "buybox": params["buybox"],
        "domain": marketplace,
        "progress_bar": False,
    }
    if params["days"] is not None:
        qkwargs["days"] = params["days"]

    # Run query
    t0 = datetime.datetime.now(_LONDON_TZ)
    try:
        products = api.query(asins, **qkwargs)
    except Exception as exc:
        print(f"  QUERY ERROR: {exc}")
        return {
            "mode": mode,
            "status": "QUERY_ERROR",
            "error": str(exc),
            "tokens_before": tok_before,
        }
    t1 = datetime.datetime.now(_LONDON_TZ)
    elapsed = (t1 - t0).total_seconds()

    # Token status after
    tok_after = _get_token_status(api)
    tb = tok_before.get("tokens_left")
    ta = tok_after.get("tokens_left")
    tokens_consumed = (tb - ta) if (tb is not None and ta is not None) else None
    per_asin = (tokens_consumed / len(asins)) if tokens_consumed is not None else None

    print(f"  Tokens after : {ta}  consumed: {tokens_consumed}"
          f"  per ASIN: {f'{per_asin:.2f}' if per_asin is not None else 'n/a'}")
    print(f"  Returned     : {len(products)} products  elapsed: {elapsed:.1f}s")

    # Extract fields
    rows: list[dict] = [extract_product(p) for p in products]

    # Print per-product summary
    bb_found = sum(1 for r in rows if r["current_buybox_price"] is not None)
    avg_found = sum(1 for r in rows if r["buybox_90_day_avg"] is not None)
    data_bb = sum(1 for r in rows if r["data_bb_present"])
    print(f"  BB_current   : {bb_found}/{len(rows)} products have a value")
    print(f"  BB_avg90     : {avg_found}/{len(rows)} products have a value")
    print(f"  data BUY_BOX : {data_bb}/{len(rows)} products have history array")

    # Print first 3 rows concisely
    for r in rows[:3]:
        bb = f"${r['current_buybox_price']:.2f}" if r["current_buybox_price"] else "—"
        avg = f"${r['buybox_90_day_avg']:.2f}" if r["buybox_90_day_avg"] else "—"
        print(f"    {r['asin']}  BB={bb}  avg90={avg}  {r['title'][:50]}")

    # ── Write CSV ─────────────────────────────────────────────────────────────
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(
        _OUTPUT_DIR, f"keepa_api_probe_{marketplace}_{mode}_{timestamp}.csv"
    )
    _csv_fields = [
        "asin", "title", "domain_id",
        "current_buybox_price", "buybox_90_day_avg", "buybox_source_field",
        "fba_fee", "extraction_notes",
        "raw_top_keys", "stats_keys", "data_bb_present", "data_bb_len",
        "data_all_keys_sample",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV          : {csv_path}")

    # ── Write JSON ────────────────────────────────────────────────────────────
    json_payload = {
        "probe_meta": {
            "marketplace": marketplace,
            "mode": mode,
            "timestamp": timestamp,
            "elapsed_s": round(elapsed, 2),
        },
        "query_params": qkwargs,
        "token_tracking": {
            "before": tok_before,
            "after": tok_after,
            "consumed": tokens_consumed,
            "per_asin": round(per_asin, 3) if per_asin is not None else None,
            "note": (
                "tokens_left updated by api.tokens_left after each query call"
                if tb is not None else "token balance unavailable"
            ),
        },
        "requested_asins": asins,
        "returned_count": len(products),
        "extraction_summary": {
            "bb_current_found": bb_found,
            "bb_avg90_found": avg_found,
            "data_bb_history_found": data_bb,
            "total": len(rows),
        },
        "samples": [_sanitize_for_json(p) for p in products[:3]],
    }
    json_path = os.path.join(
        _OUTPUT_DIR, f"keepa_api_probe_{marketplace}_{mode}_{timestamp}.json"
    )
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(json_payload, fh, indent=2, default=str)
    print(f"  JSON         : {json_path}")

    return {
        "mode": mode,
        "status": "SUCCESS",
        "asins_requested": len(asins),
        "asins_returned": len(products),
        "tokens_consumed": tokens_consumed,
        "tokens_per_asin": per_asin,
        "bb_current_found": bb_found,
        "bb_avg90_found": avg_found,
        "data_bb_found": data_bb,
        "elapsed_s": round(elapsed, 2),
        "csv_path": csv_path,
        "json_path": json_path,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def run_probe(
    marketplace: str,
    mode: str,
    limit: int,
) -> dict:
    """Run the Keepa API probe.

    marketplace: 'CA' (only CA is configured for this MVP)
    mode: 'cheap' | 'buybox' | 'history' | 'all'
    limit: max ASINs to read from the spreadsheet (default 40)
    """
    _check_keepa()
    import keepa

    valid_modes = ("cheap", "buybox", "history", "all", "field-probe")
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode {mode!r}. Valid: {valid_modes}")

    # ── 1. API key ────────────────────────────────────────────────────────────
    api_key = os.environ.get("KEEPA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "KEEPA_API_KEY is not set in the environment.\n"
            "Add it to your .env file:\n"
            "  KEEPA_API_KEY=your_key_here\n"
            "Then re-run the command."
        )
    print(f"  API key      : {'*' * 8}{api_key[-4:]} (last 4 chars shown)")

    # ── 2. Initialise Keepa API ───────────────────────────────────────────────
    print("  Connecting to Keepa API...")
    try:
        api = keepa.Keepa(api_key)
    except Exception as exc:
        raise RuntimeError(f"Keepa API init failed: {exc}") from exc

    init_tokens = _get_token_status(api)
    print(f"  Token balance: {init_tokens.get('tokens_left', 'unavailable')}"
          f"  refill_rate={init_tokens.get('refill_rate_per_min', '?')}/min")

    # ── 3. Read ASINs ─────────────────────────────────────────────────────────
    print()
    print(f"  Reading ASINs (marketplace={marketplace}, limit={limit})...")
    asins, asin_stats = read_asins(marketplace, limit)
    timestamp = datetime.datetime.now(_LONDON_TZ).strftime("%Y%m%d_%H%M%S")

    # ── field-probe: separate early path ─────────────────────────────────────
    if mode == "field-probe":
        fp_result = _run_field_probe(
            api=api,
            asins=asins,
            marketplace=marketplace,
            timestamp=timestamp,
        )
        final_tokens = _get_token_status(api)
        init_t = init_tokens.get("tokens_left")
        final_t = final_tokens.get("tokens_left")
        total_consumed = (init_t - final_t) if (init_t is not None and final_t is not None) else None
        print()
        print("  === FIELD PROBE SUMMARY ==========================================")
        print(f"  Marketplace    : {marketplace}")
        print(f"  ASINs read     : {len(asins)}")
        if fp_result.get("status") == "SUCCESS":
            tc = fp_result.get("tokens_consumed")
            tpa = fp_result.get("tokens_per_asin")
            print(f"  Tokens consumed: {tc if tc is not None else 'n/a'}"
                  f"  per ASIN: {f'{tpa:.2f}' if tpa is not None else 'n/a'}")
        else:
            print(f"  ERROR: {fp_result.get('error', '?')}")
        print(f"  Tokens start   : {init_t}")
        print(f"  Tokens end     : {final_t}")
        print(f"  Total consumed : {total_consumed if total_consumed is not None else 'n/a'}")
        print(f"  Output dir     : {os.path.abspath(_OUTPUT_DIR)}")
        print("  ==================================================================")
        return {
            "marketplace": marketplace,
            "mode": "field-probe",
            "asins_read": len(asins),
            "result": fp_result,
            "tokens_start": init_t,
            "tokens_end": final_t,
            "total_tokens_consumed": total_consumed,
        }

    # ── 4. Slice ASINs per mode ───────────────────────────────────────────────
    modes_to_run: list[str] = ["cheap", "buybox", "history"] if mode == "all" else [mode]

    if mode == "all":
        # Each sub-mode gets its own non-overlapping ASIN slice of up to 10
        chunk = min(10, len(asins) // len(modes_to_run) or len(asins))
        asin_slices = {
            "cheap":   asins[0:chunk],
            "buybox":  asins[chunk:chunk * 2],
            "history": asins[chunk * 2:chunk * 3],
        }
        print(f"  Mode 'all': {len(modes_to_run)} sub-modes × {chunk} ASINs each")
    else:
        asin_slices = {mode: asins[:min(len(asins), limit)]}
        print(f"  Using {len(asin_slices[mode])} ASINs for mode '{mode}'")

    # ── 5. Run each mode ──────────────────────────────────────────────────────
    mode_results: list[dict] = []
    for m in modes_to_run:
        slice_asins = asin_slices.get(m, [])
        if not slice_asins:
            print(f"  [skip] No ASINs available for mode {m!r}")
            continue
        result = _run_mode(api, m, slice_asins, marketplace, timestamp)
        mode_results.append(result)

    # ── 6. Print summary ──────────────────────────────────────────────────────
    print()
    print("  ═══ PROBE SUMMARY ════════════════════════════════════════")
    print(f"  Marketplace    : {marketplace}")
    print(f"  Mode(s)        : {mode}")
    print(f"  ASINs read     : {len(asins)}")
    for r in mode_results:
        if r.get("status") == "SUCCESS":
            tc = r.get("tokens_consumed")
            tpa = r.get("tokens_per_asin")
            print(
                f"  [{r['mode']:8}]  returned={r['asins_returned']}"
                f"  tokens_consumed={tc if tc is not None else 'n/a'}"
                f"  per_asin={f'{tpa:.2f}' if tpa is not None else 'n/a'}"
                f"  BB_current={r['bb_current_found']}/{r['asins_returned']}"
                f"  BB_avg90={r['bb_avg90_found']}/{r['asins_returned']}"
            )
        else:
            print(f"  [{r['mode']:8}]  ERROR: {r.get('error', '?')}")

    final_tokens = _get_token_status(api)
    init_t = init_tokens.get("tokens_left")
    final_t = final_tokens.get("tokens_left")
    total_consumed = (init_t - final_t) if (init_t is not None and final_t is not None) else None
    print(f"  Tokens start   : {init_t}")
    print(f"  Tokens end     : {final_t}")
    print(f"  Total consumed : {total_consumed if total_consumed is not None else 'n/a'}")
    print(f"  Output dir     : {os.path.abspath(_OUTPUT_DIR)}")
    print("  ══════════════════════════════════════════════════════════")

    return {
        "marketplace": marketplace,
        "mode": mode,
        "asins_read": len(asins),
        "mode_results": mode_results,
        "tokens_start": init_t,
        "tokens_end": final_t,
        "total_tokens_consumed": total_consumed,
    }
