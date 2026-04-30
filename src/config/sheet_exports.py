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
