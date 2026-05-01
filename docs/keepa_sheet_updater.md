# Keepa Sheet Updater

## Supported marketplaces

| Marketplace | Sheet tab | Keepa domain | Spreadsheet ID |
|---|---|---|---|
| US | KeepaUS | US | 1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo |
| CA | KeepaCA | CA | 1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8 |
| UK | KeepaUK | GB | 1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM |
| DE | KeepaDE | DE | 1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk |

Note: Keepa uses domain code `'GB'` for the UK marketplace. The `keepa_domain`
field in `_SHEET_CONFIG` handles this translation; the CLI always uses `--marketplace UK`.

---

## Commands

```powershell
# Dry-run (no Sheets writes) — safe for all marketplaces
python src/main.py update-keepa-sheets --marketplace US --max-asins 10 --dry-run
python src/main.py update-keepa-sheets --marketplace CA --max-asins 10 --dry-run
python src/main.py update-keepa-sheets --marketplace UK --max-asins 10 --dry-run
python src/main.py update-keepa-sheets --marketplace DE --max-asins 10 --dry-run

# First live write for a new marketplace — 3 ASINs is a safe starting point
python src/main.py update-keepa-sheets --marketplace US --max-asins 3
python src/main.py update-keepa-sheets --marketplace UK --max-asins 3
python src/main.py update-keepa-sheets --marketplace DE --max-asins 3

# Normal operating batch
python src/main.py update-keepa-sheets --marketplace CA --max-asins 20

# Restart from first ASIN (ignores checkpoint for that marketplace only)
python src/main.py update-keepa-sheets --marketplace CA --max-asins 20 --reset-checkpoint
```

`--max-asins N` caps how many ASINs are processed per run (default: 20).

---

## Field mapping

Same column layout for all KeepaXX tabs.

| Sheet column | Field | Keepa source |
|---|---|---|
| Q | Locale | Derived from config (`com` / `ca` / `co.uk` / `de`) |
| R | Title | `product.title` |
| Z | Amazon availability | `product.availabilityAmazon` (label, e.g. `out_of_stock`) |
| AB | Pick and Pack / FBA fee | `product.fbaFees.pickAndPackFee` ÷ 100 |
| AG | Current Buy Box | `stats.current[18]` ÷ 100 (BUY_BOX_SHIPPING) |
| AI | 90-day Buy Box average | `stats.avg90[18]` ÷ 100 |
| AM | Buy Box Seller | `product.buyBoxSellerIdHistory` latest entry (conditional) |
| AP | Category | `product.categoryTree[0].name` (root) |
| AQ | Subcategory | `product.categoryTree[-1].name` (deepest) |
| AS | EAN | `product.eanList[0]` |
| AT | UPC | `product.upcList[0]` (conditional — only when returned) |
| AU | Part Number | `product.partNumber` |
| AW | Brand | `product.brand` |
| BB | Weight grams | `product.packageWeight` (fallback: `product.itemWeight`) |
| BF | Referral Fee % | `product.referralFeePercentage` |
| BG | Type | `product.type` |

**Not updated**: BD (Monthly Sales Trends) — see exclusion reason below.

---

## Token budget

| Batch size | Tokens per run |
|---|---|
| 3 ASINs | 9 tokens |
| 10 ASINs | 30 tokens |
| 20 ASINs | 60 tokens |
| 100 ASINs | 300 tokens |

Refill rate: 5 tokens/min = 300 tokens/hour.

Running all 4 marketplaces in sequence at `--max-asins 20` costs 240 tokens
(~48 minutes of refill). Plan accordingly when rotating through marketplaces.

**Token check rule**: if `tokens_available < batch_size × 3`, the batch is
trimmed to `tokens_available ÷ 3`. If fewer than 3 tokens remain, the run
raises a `RuntimeError` with a wait-and-retry message.

---

## Checkpoint behaviour

Checkpoint file: `data/state/keepa_rolling_checkpoint.json`

Checkpoints are stored per marketplace so runs for different markets are
completely independent:

```json
{
  "CA": {
    "next_row_number": 28,
    "last_processed_asin": "B00BUXVV9A",
    "last_success_at": "2026-05-01 18:30:00",
    "total_processed_in_last_run": 20,
    "tokens_before": 300,
    "tokens_after": 240,
    "tokens_consumed": 60
  },
  "US": {
    "next_row_number": 11,
    "last_processed_asin": "B07XYZ1234",
    "last_success_at": "2026-05-01 19:00:00",
    ...
  }
}
```

- Checkpoint is only saved after a successful Sheets `batchUpdate` write.
- `next_row_number` is the sheet row number after the last processed batch.
- If the checkpoint row is past the last ASIN in the list, the updater wraps
  back to row 8 automatically.
- `--reset-checkpoint` ignores the saved checkpoint for that marketplace only.
  Other marketplaces are not affected.
- **Migration**: if an old single-marketplace checkpoint exists
  (`{"marketplace": "CA", "next_row_number": ...}`), it is silently migrated
  to the new per-marketplace format on first read.

---

## Recommended live test sequence for new marketplaces

1. Dry-run first: `--max-asins 10 --dry-run` — verify ASIN list, token cost,
   planned writes.
2. First live write: `--max-asins 3` — inspect the 3 rows in the sheet manually.
3. If correct: `--max-asins 20` for a normal batch.

---

## Safety rules

1. **Dry-run never writes** to Google Sheets (even though it queries Keepa).
2. **Blank values are never written** — if a Keepa field is absent/null, that
   cell is skipped. Existing sheet data is preserved.
3. **AM (Buy Box Seller) and AT (UPC)** are conditional: they are only written
   when Keepa returns a non-null value.
4. **No `batchClear` or range clears** — only targeted `batchUpdate` writes.
5. **Formulas and formatting are not touched** — only the specific data cells
   listed in `_COL_MAP` are written.
6. If Keepa returns an empty/minimal product for an ASIN, that ASIN is skipped
   with a warning in the log; the row is not written.
7. The API key is never printed in full and never saved to output files.
8. `update=0` (live re-collection) is NOT used — Keepa's cached data is
   acceptable for 48–72h freshness. Cached data costs the standard 3
   tokens/ASIN; `update=0` would cost an extra token per product.

---

## Why BD (Monthly Sales Trends) is excluded

`product.monthlySold` is not returned by the Keepa Product API in the
`buybox=True, history=False, stats=90` query mode. Confirmed by the field-probe:
the key is absent from the product dict for all ASINs tested.

If needed in the future, source it from Keepa's product finder / sales rank
history endpoint (requires a separate probe) or a third-party estimator API.

---

## Why blanks are not written

Writing a blank/null to a cell would overwrite any value the user has manually
entered or that was populated by a prior import (e.g. a Bqool report). This is
a non-reversible data loss without a change log.

The rule is: if Keepa does not return a value, the corresponding sheet cell is
unchanged. The log records how many cells were skipped per ASIN.

---

## FBA fee source caveat

AB (Pick and Pack / FBA fee) is populated from `product.fbaFees.pickAndPackFee`,
which is Keepa's cached fee value. This may lag Amazon's current fee schedule.

For an authoritative FBA fee, use the SP-API `getMyFeesEstimate` endpoint.
The existing `probe-marketplace-pricing-fees` command covers this. The Keepa
value is a useful quick fill but should not be treated as billing-accurate.

---

## Logging

Each run writes a timestamped log to:
```
data/logs/keepa_sheet_update_YYYYMMDD_HHMMSS.log
```

The log records: marketplace, mode, max_asins; token balance before/after/consumed;
each ASIN processed (row number, columns written, columns skipped); any ASIN-level
skips; checkpoint row saved; final cell count summary.
