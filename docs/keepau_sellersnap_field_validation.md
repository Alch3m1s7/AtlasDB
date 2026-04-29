# KeepAU MVP — SellerSnap Field Coverage Checklist

**Purpose:** Validate that SellerSnap export/API data covers the fields required for the KeepAU MVP before committing to any database schema or ingestion pipeline.

**Status:** Pre-validation — do not build DB tables until coverage is confirmed.

---

## Ground rules

- [ ] Test against a minimum of 20 ASINs from the active AU inventory list
- [ ] Save the raw SellerSnap CSV exactly as downloaded — do not modify before checking
- [ ] Record the exact column header name as it appears in the export (case-sensitive)
- [ ] For any field marked REQUIRED MVP that is missing or empty for >20% of test ASINs, document it under [Missing / Partial Fields](#missing--partial-fields) before proceeding
- [ ] Do not create or alter any database tables until all REQUIRED MVP fields are confirmed present and parseable
- [ ] Attach a copy of the raw CSV (or a 20-row sample) to the pull request or task that closes this checklist

---

## Field coverage table

| # | KeepAU Field | Priority | Expected SellerSnap Column(s) | Notes / Fallback |
|---|---|---|---|---|
| 1 | ASIN | **REQUIRED MVP** | `ASIN`, `asin` | Primary key — must be present on every row |
| 2 | Product title | **REQUIRED MVP** | `Product Title`, `title`, `name` | Used for display and dedup sanity checks |
| 3 | Brand | **REQUIRED MVP** | `Brand`, `brand` | Used for supplier grouping |
| 4 | Category | **REQUIRED MVP** | `Category`, `category`, `Root Category` | Top-level browse node |
| 5 | Subcategory | NICE TO HAVE | `Subcategory`, `Sub Category`, `Browse Node` | Second-level browse node; derive from BSR node if absent |
| 6 | Buy Box price | **REQUIRED MVP** | `Buy Box Price`, `buybox_price`, `Buy Box: Price` | Currency must be AUD; reject row if currency unclear |
| 7 | BSR (Best Seller Rank) | **REQUIRED MVP** | `BSR`, `Best Seller Rank`, `Sales Rank`, `Rank` | Record rank value AND category it was measured in |
| 8 | BSR category | **REQUIRED MVP** | `BSR Category`, `Rank Category`, `Sales Rank Category` | Must accompany rank — rank alone is not comparable across categories |
| 9 | Buy Box seller name | **REQUIRED MVP** | `Buy Box Seller`, `buybox_seller`, `Buy Box: Seller Name` | Used to detect Amazon.com.au as seller (see row 10) |
| 10 | Amazon.com.au is Buy Box seller | **REQUIRED MVP** | Derive from Buy Box seller field: check if value matches `Amazon.com.au` / `Amazon` / seller ID `A3LWZX34UCHM1W` | If SellerSnap exposes a boolean flag (e.g. `Amazon Wins Buy Box`, `is_amazon`) prefer that directly |
| 11 | UPC / EAN | NICE TO HAVE | `UPC`, `EAN`, `upc`, `ean`, `Barcode` | Not always present; useful for cross-marketplace matching |
| 12 | Manufacturer part number | NICE TO HAVE | `MPN`, `Part Number`, `manufacturer_part_number` | Often missing; do not block MVP on this |
| 13 | Product weight (grams) | NICE TO HAVE | `Weight`, `weight_grams`, `Item Weight`, `Weight (g)` | Check units — SellerSnap may export kg or lbs; convert to grams on ingest |
| 14 | Observed / snapshot timestamp | **REQUIRED MVP** | `Date`, `Snapshot Date`, `Timestamp`, `Last Updated`, `report_date` | Must be parseable as a date; use file-level date from filename as fallback if column missing |

---

## Validation instructions

### Step 1 — Obtain the export

1. Log in to SellerSnap and navigate to the product list or reporting section.
2. Export or download the CSV for the AU marketplace.
3. Save the file to `data/raw/sellersnap/` with a filename that includes the date, e.g. `sellersnap_au_products_20260429.csv`.
4. Do not rename or reformat the file.

### Step 2 — Check column headers

Open the file and record the exact column header row. For each field in the table above, note:
- The exact matching column name (or `— NOT FOUND —`)
- Whether it is always populated, sometimes populated, or mostly empty across the 20 test ASINs

### Step 3 — Spot-check 20 ASINs

Use the 20 AU inventory ASINs below (or substitute from the live list):

```
B0DGVWT3M5  B08TRMF51Z  B082T3KPJP  B08TRJCS51  B08TRJT6BT
B08TRJQBLF  B01BTZTO24  B0063G80FM  B07CXQTC71  B003K71VDK
B07BL5NKXT  B013SJO2JE  B006ZZ7GV0  B00LSQX0S4  B07FTYT8XT
B079G1HXGC  B0BG91L162  B08PG1C7LL  B086DN2QQ6  B08PG1FRBS
```

For each ASIN, confirm:
- [ ] Row exists in the export
- [ ] Buy Box price is a number and currency is AUD
- [ ] BSR value is a number
- [ ] BSR category is present
- [ ] Buy Box seller field is non-empty

### Step 4 — Derive the Amazon seller flag

Check whether SellerSnap already provides a boolean `Amazon wins Buy Box` column. If not:
- Extract the `Buy Box seller` column value
- Confirm whether Amazon's AU seller identity appears as `Amazon.com.au`, `Amazon`, or a known seller ID
- Document the exact string(s) observed so the derivation logic can be hardcoded

### Step 5 — Timestamp handling

- If a `Date` / `Snapshot Date` column exists, record its format (e.g. `YYYY-MM-DD`, `DD/MM/YYYY`)
- If no column exists, check whether the filename includes a date and use that as the snapshot date
- If neither is available, flag as a blocker — ingestion cannot proceed without a timestamp

---

## Missing / partial fields

Document any REQUIRED MVP field that is absent or unreliable below before closing this checklist.

| Field | Status | Detail | Proposed resolution |
|---|---|---|---|
| *(none yet — fill in after Step 2)* | | | |

---

## Sign-off

- [ ] All REQUIRED MVP fields confirmed present and parseable
- [ ] Missing / partial fields table filled in (or marked "none")
- [ ] Raw CSV sample saved to `data/raw/sellersnap/`
- [ ] No DB schema changes made during this validation
- [ ] Findings shared with team before ingestion pipeline work begins
