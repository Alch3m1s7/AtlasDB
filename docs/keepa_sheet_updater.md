# Keepa Sheet Updater

## Scope — CA MVP only

This is the first-pass rolling updater. Only the CA marketplace (`KeepaCA` tab) is
wired up. US, UK, and DE can be added later by extending `_SHEET_CONFIG` in
`src/keepa/sheet_updater.py`.

---

## Commands

```powershell
# Dry-run — queries Keepa, shows planned writes, does NOT write to Sheets
python src/main.py update-keepa-sheets --marketplace CA --max-asins 10 --dry-run

# First real write — safe starting point (5 ASINs from checkpoint position)
python src/main.py update-keepa-sheets --marketplace CA --max-asins 5

# Larger batch
python src/main.py update-keepa-sheets --marketplace CA --max-asins 20

# Restart from first ASIN (ignores checkpoint)
python src/main.py update-keepa-sheets --marketplace CA --max-asins 20 --reset-checkpoint
```

`--max-asins N` caps how many ASINs are processed per run (default: 20).

---

## Field mapping

| Sheet column | Field | Keepa source |
|---|---|---|
| Q | Locale | Derived from marketplace config (`CA`) |
| R | Title | `product.title` |
| Z | Amazon availability | `product.availabilityAmazon` (label, e.g. `out_of_stock`) |
| AB | Pick and Pack / FBA fee | `product.fbaFees.pickAndPackFee` ÷ 100 |
| AG | Current Buy Box | `stats.current[18]` ÷ 100 (BUY_BOX_SHIPPING) |
| AI | 90-day Buy Box average | `stats.avg90[18]` ÷ 100 |
| AM | Buy Box Seller | `product.buyBoxSellerIdHistory` latest string entry |
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

## Token maths

| Scenario | Tokens/run |
|---|---|
| `--max-asins 5` | 15 tokens |
| `--max-asins 20` | 60 tokens |
| `--max-asins 100` | 300 tokens |

Refill rate: 5 tokens/min = 300 tokens/hour.

To update 629 CA ASINs in one full cycle: 629 × 3 = 1,887 tokens ≈ 6.3 hours at
300 tokens/hour. Run with `--max-asins 20` every 12 minutes to drain at full
refill rate (300/20=15 runs/hour), or run `--max-asins 100` once per 20 minutes.

**Token check rule**: if `tokens_available < batch_size × 3`, the batch is
reduced to `tokens_available ÷ 3`. If no tokens remain for even one ASIN, the
run raises a `RuntimeError` with a wait-and-retry message.

The command will never wait more than a few seconds for token refill. It does
not loop indefinitely. For scheduled operation, run the command on a cron schedule
that matches the refill rate.

---

## Checkpoint behaviour

Checkpoint file: `data/state/keepa_rolling_checkpoint.json`

```json
{
  "marketplace": "CA",
  "next_row_number": 28,
  "last_processed_asin": "B00BUXVV9A",
  "last_success_at": "2026-05-01 18:30:00",
  "total_processed_in_last_run": 20,
  "tokens_before": 300,
  "tokens_after": 240,
  "tokens_consumed": 60
}
```

- The checkpoint is only saved after a successful Sheets `batchUpdate` write.
- `next_row_number` is the sheet row number (e.g. 28 = row after the last
  processed ASIN in a batch ending at row 27).
- If the checkpoint row is past the last ASIN in the list, the updater wraps
  back to row 8 automatically.
- `--reset-checkpoint` ignores the saved checkpoint entirely and starts from
  row 8. This does not delete the file; it is overwritten on the next
  successful write.

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
`buybox=True, history=False, stats=90` query mode. This was confirmed by the
field-probe: the key is absent from the product dict for all 10 tested ASINs.
Obtaining monthly sales data from Keepa would require a different API tier or
query parameters not investigated in the probe.

If this field is needed in the future, it should be sourced from:
- Keepa's product finder / sales rank history endpoint (separate probe needed), or
- A third-party sales estimator API.

---

## Why blanks are not written

Writing a blank/null to a cell would overwrite any value the user has manually
entered or that was populated by a prior import (e.g. a Bqool report). This is
a non-reversible data loss without a change log.

The rule is: if Keepa does not return a value, the corresponding sheet cell is
unchanged. The log records how many cells were skipped per ASIN so the operator
can see what was not updated.

---

## FBA fee source caveat

AB (Pick and Pack / FBA fee) is populated from `product.fbaFees.pickAndPackFee`,
which is Keepa's cached fee value. This may lag Amazon's current fee schedule.

For an authoritative FBA fee, use the SP-API `getMyFeesEstimate` endpoint. The
existing `probe-marketplace-pricing-fees` command covers this. The Keepa value
is a useful quick fill but should not be treated as billing-accurate.

---

## Logging

Each run writes a timestamped log to:
```
data/logs/keepa_sheet_update_YYYYMMDD_HHMMSS.log
```

The log records:
- Marketplace, mode, max_asins
- Token balance before/after/consumed
- Each ASIN processed: row number, columns written, columns skipped (blank)
- Any ASIN-level skips (empty Keepa response, ASIN mismatch)
- Checkpoint row saved
- Final cell count summary

---

## Extending to US / UK / DE

Add an entry to `_SHEET_CONFIG` in `src/keepa/sheet_updater.py`:

```python
"US": {
    "spreadsheet_id": "<US sheet ID>",
    "tab": "KeepaUS",
    "asin_col": "AR",
    "first_data_row": 8,
    "locale": "US",
},
```

Then run:
```powershell
python src/main.py update-keepa-sheets --marketplace US --max-asins 10 --dry-run
```

The checkpoint file stores one marketplace at a time. If you want to checkpoint
multiple marketplaces independently, the checkpoint schema will need a per-market
map (not yet needed for the CA-only MVP).
