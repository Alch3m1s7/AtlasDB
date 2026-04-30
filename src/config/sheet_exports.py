# Google Sheets export configuration per marketplace.
# TODO: add scheduling / auto-trigger layer once per-marketplace export is validated end-to-end.

SHEET_EXPORTS = {
    "US": {
        "spreadsheet_id": "1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo",
        "reports": {
            "orders-30d":        {"tab": "Sales30US",  "start_cell": "P7"},
            "fba-inventory":     {"tab": "FbaInvUS",   "start_cell": "P7"},
            "all-listings":      {"tab": "P4Y-Fp",     "start_cell": "A7"},
            "stranded-inventory":{"tab": "StrdUS",     "start_cell": "I7"},
        },
        "log_tab": "ExportLogUS",
    },
    "CA": {
        "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
        "reports": {
            "orders-30d":        {"tab": "Sales30CA",  "start_cell": "P7"},
            "fba-inventory":     {"tab": "FbaInvCA",   "start_cell": "P7"},
            "all-listings":      {"tab": "P4Y-Fp",     "start_cell": "A7"},
            "stranded-inventory":{"tab": "StrdCA",     "start_cell": "I7"},
        },
        "log_tab": "ExportLogCA",
    },
    "UK": {
        "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
        "reports": {
            "orders-30d":        {"tab": "Sales30UK",  "start_cell": "P7"},
            "fba-inventory":     {"tab": "FbaInvUK",   "start_cell": "P7"},
            "all-listings":      {"tab": "P4Y-Fp",     "start_cell": "A7"},
            "stranded-inventory":{"tab": "StrdUK",     "start_cell": "I7"},
        },
        "log_tab": "ExportLogUK",
    },
    "DE": {
        "spreadsheet_id": "1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk",
        "reports": {
            "orders-30d":        {"tab": "Sales30DE",  "start_cell": "P7"},
            "fba-inventory":     {"tab": "FbaInvDE",   "start_cell": "P7"},
            "all-listings":      {"tab": "P4Y-Fp",     "start_cell": "A7"},
            "stranded-inventory":{"tab": "StrdDE",     "start_cell": "I7"},
        },
        "log_tab": "ExportLogDE",
    },
    "AU": {
        "spreadsheet_id": "1gU-8FE5PtMr1w7g9B6msRKh33BJZLSBrNI57c50wMqE",
        "reports": {
            "orders-30d":        {"tab": "Sales30AU",  "start_cell": "P7"},
            "fba-inventory":     {"tab": "FbaInvAU",   "start_cell": "P7"},
            "all-listings":      {"tab": "P4Y-Fp",     "start_cell": "A7"},
            "stranded-inventory":{"tab": "StrdAU",     "start_cell": "I7"},
        },
        "log_tab": "ExportLogAU",
    },
}

# Column values to blank out (replace with "") for specific report types.
# Headers are preserved in place; only data cell values are cleared.
# Columns not present in a report are silently ignored.
BLANK_COLUMNS_BY_REPORT: dict[str, set[str]] = {
    "orders-30d": {"ship-city", "ship-state", "ship-postal-code"},
}

# Explicit export column order for reports that need a fixed layout.
# When present for a report_key, this list overrides the natural JSONL column order.
# Columns not found in the JSONL are exported as blank (header kept, value "").
# Internal _-prefixed columns may be included deliberately (e.g. _is_valid).
EXPORT_COLUMN_ORDER: dict[str, list[str]] = {
    "orders-30d": [
        "amazon-order-id",
        "merchant-order-id",
        "purchase-date",
        "last-updated-date",
        "order-status",
        "fulfillment-channel",
        "sales-channel",
        "order-channel",
        "url",
        "ship-service-level",
        "product-name",
        "sku",
        "asin",
        "item-status",
        "quantity",
        "currency",
        "item-price",
        "item-tax",
        "shipping-price",
        "shipping-tax",
        "gift-wrap-price",
        "gift-wrap-tax",
        "item-promotion-discount",
        "ship-promotion-discount",
        "ship-city",
        "ship-state",
        "ship-postal-code",
        "ship-country",
        "promotion-ids",
        "is-business-order",
        "purchase-order-number",
        "price-designation",
        "signature-confirmation-recommended",
        "buyer-identification-number",
        "buyer-identification-type",
    ],
    # P4Y-Fp tab expects exactly this 7-column layout; all other all-listings
    # columns are intentionally excluded.  Missing columns export as blank.
    "all-listings": [
        "seller-sku",
        "asin1",
        "item-name",
        "price",
        "ProductTaxCode",
        "status",
        "minimum-seller-allowed-price",
    ],
}

# Columns to convert to Python int or float before writing to Sheets.
# Empty/null stays blank; invalid values become blank and increment a warning counter.
# Text identifier columns (order IDs, ASINs, SKUs, etc.) are intentionally absent.
NUMERIC_COLUMNS: dict[str, dict[str, list[str]]] = {
    "orders-30d": {
        "int": ["quantity"],
        "decimal": [
            "item-price", "item-tax", "shipping-price", "shipping-tax",
            "gift-wrap-price", "gift-wrap-tax",
            "item-promotion-discount", "ship-promotion-discount",
        ],
    },
    "fba-inventory": {
        "decimal": ["your-price", "per-unit-volume"],
        "int": [
            "mfn-fulfillable-quantity", "afn-warehouse-quantity",
            "afn-fulfillable-quantity", "afn-unsellable-quantity",
            "afn-reserved-quantity", "afn-total-quantity",
            "afn-inbound-working-quantity", "afn-inbound-shipped-quantity",
            "afn-inbound-receiving-quantity", "afn-researching-quantity",
            "afn-reserved-future-supply", "afn-future-supply-buyable",
        ],
    },
    "stranded-inventory": {
        "int": ["fulfillable-qty", "unfulfillable-qty", "reserved-quantity", "inbound-shipped-qty"],
        "decimal": ["your-price"],
    },
    "all-listings": {
        "decimal": ["price", "minimum-seller-allowed-price"],
        "int": [],
    },
}

# Number format specs applied after each report tab write (data rows only, row 8+).
# Ranges are absolute spreadsheet column positions, not relative to the export block.
# Format types: "text" → Sheets TEXT (@), "int" → NUMBER 0, "decimal" → NUMBER 0.00
#
# orders-30d column layout (P7, 35 cols → P..AX):
#   P1-14 (P:AC)  = text identifiers
#   P15   (AD)    = quantity (int)
#   P16   (AE)    = currency (text)
#   P17-24 (AF:AM)= money cols (decimal)
#   P25-35 (AN:AX)= ship/promo/buyer fields (text)
#
# fba-inventory column layout (P7, 22 cols → P..AK):
#   Verified from live JSONL: sku,fnsku,asin,product-name,condition,your-price,
#   mfn-listing-exists,mfn-fulfillable-quantity,afn-listing-exists,
#   afn-warehouse..afn-total,per-unit-volume,afn-inbound-working..afn-future-supply-buyable,store
#
# stranded-inventory column layout (I7, 19 cols → I..AA):
#   Verified from live JSONL: primary-action..fulfilled-by (text), fulfillable-qty,
#   your-price, unfulfillable-qty..inbound-shipped-qty (int), program (text)
NUMBER_FORMAT_SPECS: dict[str, list[tuple[str, str]]] = {
    "orders-30d": [
        ("P8:AC", "text"),      # amazon-order-id … item-status
        ("AD8:AD", "int"),      # quantity
        ("AE8:AE", "text"),     # currency
        ("AF8:AM", "decimal"),  # item-price … ship-promotion-discount
        ("AN8:AX", "text"),     # ship-city … buyer-identification-type
    ],
    "fba-inventory": [
        ("P8:T", "text"),       # sku … condition
        ("U8:U", "decimal"),    # your-price
        ("V8:V", "text"),       # mfn-listing-exists
        ("W8:W", "int"),        # mfn-fulfillable-quantity
        ("X8:X", "text"),       # afn-listing-exists
        ("Y8:AC", "int"),       # afn-warehouse-quantity … afn-total-quantity
        ("AD8:AD", "decimal"),  # per-unit-volume
        ("AE8:AJ", "int"),      # afn-inbound-working-quantity … afn-future-supply-buyable
        ("AK8:AK", "text"),     # store
    ],
    "all-listings": [
        ("A8:C", "text"),       # seller-sku, asin1, item-name
        ("D8:D", "decimal"),    # price
        ("E8:G", "text"),       # ProductTaxCode, status, minimum-seller-allowed-price
    ],
    "stranded-inventory": [
        ("I8:U", "text"),       # primary-action … fulfilled-by
        ("V8:V", "int"),        # fulfillable-qty
        ("W8:W", "decimal"),    # your-price
        ("X8:Z", "int"),        # unfulfillable-qty, reserved-quantity, inbound-shipped-qty
        ("AA8:AA", "text"),     # program
    ],
}
