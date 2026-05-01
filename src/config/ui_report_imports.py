# Config for UI-downloaded report imports (Keepa, Bqool).
# Each entry defines the target spreadsheet, tab, start cell, clear range,
# maximum allowed column count, and timestamp cell for that source/marketplace.
#
# max_cols: if the downloaded file header has MORE than this many columns,
# the import is aborted and the sheet is not modified.
#
# clear_range: cleared with clearContent() (values only, formatting preserved)
# before writing. Never modify this range to be wider than intended.
#
# timestamp_cell: cell written with "YYYY-MM-DD HH.MM" (Europe/London) after a
# successful real import. Only the value is overwritten; formatting is preserved.
# Keepa → R1   (outside the P7:BJ data area)
# Bqool → A1

UI_REPORT_IMPORTS: dict[str, dict[str, dict]] = {
    "keepa": {
        # US — KeepaUS tab, P7:BJ = 47 columns
        "US": {
            "spreadsheet_id": "1gzJUJe-FlC1W4VBB7HpvNPiSrMQwAY0gX3d4Z32Qkeo",
            "tab": "KeepaUS",
            "start_cell": "P7",
            "clear_range": "P7:BJ",
            "max_cols": 47,
            "timestamp_cell": "R1",
        },
        # CA — KeepaCA tab, P7:BJ = 47 columns
        "CA": {
            "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
            "tab": "KeepaCA",
            "start_cell": "P7",
            "clear_range": "P7:BJ",
            "max_cols": 47,
            "timestamp_cell": "R1",
        },
        # UK — KeepaUK tab, P7:BJ = 47 columns
        "UK": {
            "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
            "tab": "KeepaUK",
            "start_cell": "P7",
            "clear_range": "P7:BJ",
            "max_cols": 47,
            "timestamp_cell": "R1",
        },
        # DE — KeepaDE tab, P7:BJ = 47 columns
        "DE": {
            "spreadsheet_id": "1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk",
            "tab": "KeepaDE",
            "start_cell": "P7",
            "clear_range": "P7:BJ",
            "max_cols": 47,
            "timestamp_cell": "R1",
        },
        # AU: no Keepa import — not listed intentionally
    },
    "bqool": {
        # UK — bqUK tab, P7:CC = 66 columns
        "UK": {
            "spreadsheet_id": "1OTWzsdPvICJv7h_nYFYsFshueKkyRgduIqLw29oRErM",
            "tab": "bqUK",
            "start_cell": "P7",
            "clear_range": "P7:CC",
            "max_cols": 66,
            "timestamp_cell": "A1",
        },
        # CA — bqCA tab, P7:CC = 66 columns
        "CA": {
            "spreadsheet_id": "1Ber9_AllcA5NJ2iqT-0KPudWx5MG2DYvi3i4Jtw1su8",
            "tab": "bqCA",
            "start_cell": "P7",
            "clear_range": "P7:CC",
            "max_cols": 66,
            "timestamp_cell": "A1",
        },
        # DE: deferred — add when spreadsheet and tab are ready:
        # "DE": {
        #     "spreadsheet_id": "1pXbUdAUy6k4tf_dEtC8DUGnFcjqNlvg0xjdu8Humdqk",
        #     "tab": "bqDE",
        #     "start_cell": "P7",
        #     "clear_range": "P7:CC",
        #     "max_cols": 66,
        #     "timestamp_cell": "A1",
        # },
    },
}
