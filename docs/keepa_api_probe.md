# Keepa API Probe

## Purpose

Before building a full rolling Keepa API updater, this probe answers three
questions cheaply:

1. Does `stats=90` (no history, no buybox) return current Buy Box price and
   90-day Buy Box average at ~1 token/ASIN?
2. Does `buybox=True` improve data quality, and at what extra token cost?
3. Does `history=True` provide a `BUY_BOX_SHIPPING` history array we can use
   to compute our own averages?

The probe **does not write to Google Sheets** and does not schedule anything.

---

## Target fields (for future updater — not written yet)

| Sheet column | Field | Keepa path |
|---|---|---|
| `AR8:AR` | ASIN (source / read) | ASIN input range |
| `AB8:AB` | FBA fulfilment fee | Not in Keepa — use SP-API fees |
| `AG8:AG` | Current Buy Box | `stats.current[18]` (BUY_BOX_SHIPPING) |
| `AI8:AI` | 90-day Buy Box average | `stats.avg90[18]` |

Note: Keepa price index 18 = `BUY_BOX_SHIPPING`.  Prices are stored as
integers in units of 1/100 of the local currency (divide by 100 for the actual
price).  -1 / NaN = unavailable.

---

## Prerequisites

### 1. Install keepa (already in requirements.txt)

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add KEEPA_API_KEY to .env

```
KEEPA_API_KEY=your_keepa_api_access_key_here
```

Never commit the `.env` file.  The key is never printed to the terminal (only
the last 4 characters are shown for confirmation).

### 3. Check your token balance

Log in to Keepa → Account → API.  Note your current token balance and refill
rate before running the probe.

---

## Commands

```powershell
# cheap mode — baseline token cost (recommended first run)
python src/main.py probe-keepa-api --marketplace CA --mode cheap --limit 10

# buybox mode — compare token cost and data quality
python src/main.py probe-keepa-api --marketplace CA --mode buybox --limit 10

# history mode — check BUY_BOX_SHIPPING history array
python src/main.py probe-keepa-api --marketplace CA --mode history --limit 10

# all — run all three sequentially with separate ASIN slices
python src/main.py probe-keepa-api --marketplace CA --mode all --limit 40

# field-probe — test all 17 sheet fields in a single buybox=True query
python src/main.py probe-keepa-api --marketplace CA --mode field-probe --limit 10
```

The `--limit N` flag caps how many ASINs are read from `KeepaCA!AR8:AR`.
For `--mode all`, ASINs are split into three non-overlapping slices of 10 each.

---

## Probe modes

### cheap

```
stats=90, history=False, buybox=False
```

Baseline.  The `stats=90` parameter has no extra token cost per the Keepa docs.
This should return `stats.current[18]` (current Buy Box) and `stats.avg90[18]`
(90-day Buy Box average) if the product has recent Buy Box history.

**Expected token cost:** ~1 per product.

### buybox

```
stats=90, history=False, buybox=True
```

Adds full Buy Box data including `buyBoxSellerIdHistory`.  Per the Keepa docs,
`buybox=True` costs +2 tokens per product on top of the base cost.

**Expected token cost:** ~3 per product.

### history

```
stats=90, history=True, days=90, buybox=False
```

Returns up to 90 days of price history.  The `data['BUY_BOX_SHIPPING']` array
(if present) lets us compute our own weighted average without `buybox=True`.

**Expected token cost:** ~1 per product (history payload may be larger, but
the base token cost should not increase unless Keepa recollects data).

---

## Token tracking method

The keepa Python library (v1.4.4) exposes:

```python
api.update_status()          # free API call to refresh token count
api.tokens_left              # updated automatically after every query
api.status.refillRate        # tokens per minute
api.status.refillIn          # milliseconds to next refill
```

The probe calls `update_status()` before each mode, reads `tokens_left`, runs
the query, then reads `tokens_left` again.  `tokens_consumed = before - after`.

If the token balance cannot be read (e.g. API error), the probe still runs and
notes "token balance unavailable".

---

## Output files

```
data\processed\keepa_api_probe\
  keepa_api_probe_CA_cheap_<timestamp>.csv
  keepa_api_probe_CA_cheap_<timestamp>.json
```

### CSV columns

| Column | Description |
|--------|-------------|
| `asin` | Product ASIN |
| `title` | Product title (truncated to 100 chars) |
| `domain_id` | Keepa domain ID returned by API |
| `current_buybox_price` | `stats.current[18]` ÷ 100, or blank |
| `buybox_90_day_avg` | `stats.avg90[18]` ÷ 100, or blank |
| `buybox_source_field` | Where the value was found, or why it's missing |
| `fba_fee` | Always blank — not in Keepa |
| `extraction_notes` | What was found / not found |
| `raw_top_keys` | All top-level keys in the product dict |
| `stats_keys` | Keys inside the `stats` dict |
| `data_bb_present` | True if `data` contains BUY_BOX keys |
| `data_bb_len` | Length of BUY_BOX history array if present |
| `data_all_keys_sample` | First 20 keys in `data` dict |

### JSON structure

```json
{
  "probe_meta": { "marketplace": "CA", "mode": "cheap", ... },
  "query_params": { "stats": 90, "history": false, "buybox": false, ... },
  "token_tracking": {
    "before": { "tokens_left": 450, "refill_rate_per_min": 5 },
    "after":  { "tokens_left": 440 },
    "consumed": 10,
    "per_asin": 1.0
  },
  "requested_asins": ["B001ABC...", ...],
  "returned_count": 10,
  "extraction_summary": {
    "bb_current_found": 8,
    "bb_avg90_found": 7,
    "data_bb_history_found": 0,
    "total": 10
  },
  "samples": [ <first 3 products — compact, no large arrays> ]
}
```

---

## How to interpret results

### Reading the terminal output

```
  [cheap   ]  returned=10  tokens_consumed=10  per_asin=1.00
               BB_current=8/10  BB_avg90=7/10
```

- `BB_current=8/10` — 8 of 10 products had a current Buy Box price in `stats.current[18]`
- `BB_avg90=7/10` — 7 had a 90-day average in `stats.avg90[18]`
- `per_asin=1.00` — 1 token consumed per product (ideal)

### Reading the CSV

Open the CSV in Excel.  Sort by `current_buybox_price` being blank to see which
ASINs are missing Buy Box data.  Check `extraction_notes` for the reason.

Common patterns:

| `extraction_notes` | Meaning |
|---|---|
| `BB_current OK via stats.current[18]` | Data is present — good |
| `BB_current not found (stats.current[18] not found)` | stats.current is shorter than index 18 |
| `BB_current not found (stats.current missing)` | Product has no stats at all |
| `data BUY_BOX keys: [...] len=45` | history mode returned BB history |

---

## Decision rules

After running the probe, use these rules to decide next steps.

### ✅ Build the rolling updater if:

- **cheap** mode returns `BB_current` for ≥ 70% of ASINs at ~1 token/ASIN
- **cheap** mode returns `BB_avg90` for ≥ 70% of ASINs at ~1 token/ASIN
- Token cost is sustainable at your refill rate (300 tokens/hour = 5/min)

With 300 tokens/hour and 1 token/ASIN, you can update ~300 ASINs/hour.
For 4 marketplaces × ~200 ASINs = ~800 ASINs total, a 3-hour window covers
one full refresh.

### ⚠️ Acceptable if buybox mode needed:

- **cheap** misses Buy Box for > 30% of ASINs but **buybox** fills the gap
- `buybox=True` costs 3 tokens/ASIN
- 300 tokens/hour ÷ 3 = 100 ASINs/hour → 8 hours for 800 ASINs

Still acceptable for 48–72h refresh cadence.  Calculate before committing.

### ❌ Do not build the Keepa API updater if:

- Neither **cheap** nor **buybox** returns reliable `BB_current` for > 50% of ASINs
- This likely means the products are frequently out of Buy Box or the
  marketplace has low Buy Box coverage in Keepa's data

### FBA fee:

- FBA fee is **not in Keepa** regardless of mode
- `NEW_FBA` (index 10) is the cheapest FBA-fulfilled new listing price, not a fee
- If FBA fee is needed in `AB8:AB`, use the existing SP-API fees endpoint
  (`probe-marketplace-pricing-fees` already tests this)

---

## Assumptions and limitations

1. **CA only**: Only `KeepaCA!AR8:AR` is configured in this probe.  Adding
   US/UK/DE requires one entry in `_ASIN_SOURCES` in `src/probes/keepa_api_probe.py`.

2. **Token budget**: The probe consumes real tokens.  Running `--mode all
   --limit 40` may consume up to ~120 tokens (worst case: 3 tokens/ASIN ×
   40 ASINs if all three modes run with 10 ASINs each).

3. **`wait=True` (default)**: The keepa library waits automatically if
   tokens run out.  On a 5-token/min plan this may cause significant delays.
   Do not run large limits in the same session as other keepa operations.

4. **stats structure**: The probe assumes `stats['current']` and `stats['avg90']`
   are indexed lists where index 18 = BUY_BOX_SHIPPING.  If the library returns
   a different structure, the `extraction_notes` column will describe what was
   found so the probe can be updated.

5. **Data freshness**: The probe does not set `update=0` (live data), so Keepa
   returns cached data.  Cached data is sufficient for coverage testing.
   Setting `update=0` would cost an extra token per product.

---

## Extending to US / UK / DE

1. Add an entry to `_ASIN_SOURCES` in `src/probes/keepa_api_probe.py`:
   ```python
   "UK": {
       "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
       "sheet_range": "KeepaUK!AR8:AR",
   },
   ```

2. Run: `python src/main.py probe-keepa-api --marketplace UK --mode cheap --limit 10`

No other code changes required.

---

## Field probe mode

### Purpose

Tests all 17 sheet fields using a single `buybox=True, stats=90, history=False`
query.  This is the same query confirmed to return Buy Box data at ~3 tokens/ASIN.

```powershell
python src/main.py probe-keepa-api --marketplace CA --mode field-probe --limit 10
```

Output files:
```
data\processed\keepa_api_probe\
  keepa_field_probe_CA_buybox_<timestamp>.csv
  keepa_field_probe_CA_buybox_<timestamp>.json
```

### Field mapping table

| Sheet col | CSV column | Keepa source | Notes |
|---|---|---|---|
| Q | `locale` | derived | Always the marketplace code (e.g. `CA`) |
| R | `title` | `product.title` | Truncated to 120 chars |
| Z | `availability_amazon_raw` / `availability_amazon_label` | `product.availabilityAmazon` | Codes: -1=out_of_stock, 0=in_stock_amazon, 1=not_amazon, 2=preorder, 3=back_ordered |
| AB | `fba_pick_pack_fee` | `product.fbaFees.pickAndPackFee` | In local currency. **If missing: use SP-API fees endpoint** |
| AG | `current_buybox_price` | `stats.current[18]` | BUY_BOX_SHIPPING; divide raw integer by 100 |
| AI | `buybox_90_day_avg` | `stats.avg90[18]` | BUY_BOX_SHIPPING 90-day average |
| AM | `buybox_seller_id` | `product.buyBoxSellerIdHistory` | Latest seller ID from alternating timestamp/ID array |
| AP | `category` | `product.categoryTree[0].name` | Root (broadest) category |
| AQ | `subcategory` | `product.categoryTree[-1].name` | Deepest category (excludes root if >1 level) |
| AS | `ean` | `product.eanList` | First value or pipe-joined list (up to 5) |
| AT | `upc` | `product.upcList` | First value or pipe-joined list (up to 5) |
| AU | `part_number` | `product.partNumber` | Raw string |
| AW | `brand` | `product.brand` | Raw string |
| BB | `weight_grams` | `product.packageWeight` / `product.itemWeight` | Grams; prefers packageWeight |
| BD | `monthly_sold` | `product.monthlySold` | Estimated monthly sales count |
| BF | `referral_fee_percentage` | `product.referralFeePercentage` | Fallback: deprecated `referralFeePercent` |
| BG | `type` / `product_type_raw` | `product.type` / `product.productType` | Both raw values recorded |

### SP-API fallback rules

Use SP-API instead of Keepa for these fields regardless of coverage:

| Field | Reason |
|---|---|
| `fba_pick_pack_fee` (AB) | `fbaFees.pickAndPackFee` may be absent or stale; SP-API fees endpoint is authoritative |
| Any field showing `--` in the coverage table | Keepa does not have it for this ASIN set |

For fields showing `OK` (all 10 found) or `~` (partial): Keepa is sufficient for the
rolling updater.  Use `extraction_notes` in the CSV to understand per-ASIN gaps.

### Interpreting the terminal coverage table

```
  [OK] title                           10/10  product.title
  [OK] current_buybox_price            10/10  stats.current[18]
  [ ~] fba_pick_pack_fee                7/10  product.fbaFees.pickAndPackFee
  [--] upc                              0/10  product.upcList
```

- `[OK]` — field present for all returned products; safe to use in rolling updater
- `[ ~]` — field present for some products; use with fallback or SP-API for gaps
- `[--]` — field absent for all products; use SP-API or a different source
