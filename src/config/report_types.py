REPORT_TYPES = {
    "fba-inventory": {
        "report_type": "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA",
        "reuse_done": True,
        "reuse_window_hours": 48,
        "date_range_days": None,
    },
    "orders-30d": {
        # Always create a fresh report; verifying date-range match on existing reports is unsafe.
        "report_type": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
        "reuse_done": False,
        "reuse_window_hours": None,
        "date_range_days": 30,
    },
    "all-listings": {
        # Always create a fresh report; US/CA share NA token so a reused DONE
        # report may be cross-market.
        "report_type": "GET_MERCHANT_LISTINGS_ALL_DATA",
        "reuse_done": False,
        "reuse_window_hours": None,
        "date_range_days": None,
    },
    "stranded-inventory": {
        "report_type": "GET_STRANDED_INVENTORY_UI_DATA",
        "reuse_done": True,
        "reuse_window_hours": 48,
        "date_range_days": None,
    },
}

REPORT_KEYS = list(REPORT_TYPES.keys())
