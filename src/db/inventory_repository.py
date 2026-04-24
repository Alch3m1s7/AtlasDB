import uuid

from db.db_connection import get_connection

INSERT_SNAPSHOT_SQL = """
INSERT INTO fba_inventory_snapshots (
    snapshot_id,
    region, marketplace_id, marketplace_code,
    sku, fnsku, asin, product_name, condition,
    your_price,
    mfn_listing_exists, mfn_fulfillable_quantity,
    afn_listing_exists,
    afn_warehouse_quantity, afn_fulfillable_quantity, afn_unsellable_quantity,
    afn_reserved_quantity, afn_total_quantity,
    per_unit_volume,
    afn_inbound_working_quantity, afn_inbound_shipped_quantity,
    afn_inbound_receiving_quantity, afn_researching_quantity,
    afn_reserved_future_supply, afn_future_supply_buyable,
    afn_fulfillable_quantity_local, afn_fulfillable_quantity_remote,
    source_file
) VALUES (
    %(snapshot_id)s,
    %(region)s, %(marketplace_id)s, %(marketplace_code)s,
    %(sku)s, %(fnsku)s, %(asin)s, %(product_name)s, %(condition)s,
    %(your_price)s,
    %(mfn_listing_exists)s, %(mfn_fulfillable_quantity)s,
    %(afn_listing_exists)s,
    %(afn_warehouse_quantity)s, %(afn_fulfillable_quantity)s, %(afn_unsellable_quantity)s,
    %(afn_reserved_quantity)s, %(afn_total_quantity)s,
    %(per_unit_volume)s,
    %(afn_inbound_working_quantity)s, %(afn_inbound_shipped_quantity)s,
    %(afn_inbound_receiving_quantity)s, %(afn_researching_quantity)s,
    %(afn_reserved_future_supply)s, %(afn_future_supply_buyable)s,
    %(afn_fulfillable_quantity_local)s, %(afn_fulfillable_quantity_remote)s,
    %(source_file)s
)
"""

INSERT_IMPORT_SQL = """
INSERT INTO fba_inventory_imports (
    snapshot_id, source_file, region, marketplace_id, marketplace_code,
    row_count, inserted_row_count, status, error_message
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _yes_no_to_bool(value) -> bool | None:
    if value == "Yes":
        return True
    if value == "No":
        return False
    return None


def _to_params(
    row: dict,
    region: str,
    marketplace_id: str,
    marketplace_code: str,
    source_file: str,
    snapshot_id: str,
) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "region": region,
        "marketplace_id": marketplace_id,
        "marketplace_code": marketplace_code,
        "sku": row.get("sku"),
        "fnsku": row.get("fnsku"),
        "asin": row.get("asin"),
        "product_name": row.get("product-name"),
        "condition": row.get("condition"),
        "your_price": row.get("your-price"),
        "mfn_listing_exists": _yes_no_to_bool(row.get("mfn-listing-exists")),
        "mfn_fulfillable_quantity": row.get("mfn-fulfillable-quantity"),
        "afn_listing_exists": _yes_no_to_bool(row.get("afn-listing-exists")),
        "afn_warehouse_quantity": row.get("afn-warehouse-quantity"),
        "afn_fulfillable_quantity": row.get("afn-fulfillable-quantity"),
        "afn_unsellable_quantity": row.get("afn-unsellable-quantity"),
        "afn_reserved_quantity": row.get("afn-reserved-quantity"),
        "afn_total_quantity": row.get("afn-total-quantity"),
        "per_unit_volume": row.get("per-unit-volume"),
        "afn_inbound_working_quantity": row.get("afn-inbound-working-quantity"),
        "afn_inbound_shipped_quantity": row.get("afn-inbound-shipped-quantity"),
        "afn_inbound_receiving_quantity": row.get("afn-inbound-receiving-quantity"),
        "afn_researching_quantity": row.get("afn-researching-quantity"),
        "afn_reserved_future_supply": row.get("afn-reserved-future-supply"),
        "afn_future_supply_buyable": row.get("afn-future-supply-buyable"),
        "afn_fulfillable_quantity_local": row.get("afn-fulfillable-quantity-local"),
        "afn_fulfillable_quantity_remote": row.get("afn-fulfillable-quantity-remote"),
        "source_file": source_file,
    }


def source_file_already_loaded(source_file: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM fba_inventory_snapshots WHERE source_file = %s LIMIT 1;",
            (source_file,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def insert_fba_inventory_snapshot_rows(
    rows: list[dict],
    region: str,
    marketplace_id: str,
    marketplace_code: str,
    source_file: str,
) -> int:
    if source_file_already_loaded(source_file):
        print("Source file already loaded, skipping insert")
        return 0

    snapshot_id = str(uuid.uuid4())
    params_list = [
        _to_params(row, region, marketplace_id, marketplace_code, source_file, snapshot_id)
        for row in rows
    ]
    row_count = len(params_list)
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.executemany(INSERT_SNAPSHOT_SQL, params_list)
        conn.execute(INSERT_IMPORT_SQL, (
            snapshot_id, source_file, region, marketplace_id, marketplace_code,
            row_count, row_count, "SUCCESS", None,
        ))
        conn.commit()
        return row_count
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        try:
            fail_conn = get_connection()
            try:
                fail_conn.execute(INSERT_IMPORT_SQL, (
                    snapshot_id, source_file, region, marketplace_id, marketplace_code,
                    row_count, 0, "FAILED", str(exc),
                ))
                fail_conn.commit()
            finally:
                fail_conn.close()
        except Exception:
            pass
        raise
    finally:
        if conn is not None:
            conn.close()
