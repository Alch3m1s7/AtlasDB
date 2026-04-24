from datetime import datetime, timezone

from db.db_connection import get_connection

_NO_SNAPSHOT_MSG = (
    "No successful snapshot_id-based import found. "
    "Run ingest-local or ingest-spapi after migration."
)


def get_latest_snapshot_import() -> dict | None:
    """Return the latest fba_inventory_imports row where status='SUCCESS' and snapshot_id IS NOT NULL."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT snapshot_id, source_file, imported_at
            FROM fba_inventory_imports
            WHERE status = 'SUCCESS'
              AND snapshot_id IS NOT NULL
            ORDER BY imported_at DESC
            LIMIT 1;
        """).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": str(row[0]),
            "source_file": row[1],
            "imported_at": row[2],
        }
    finally:
        conn.close()


def get_inventory_summary(snapshot_id: str) -> dict:
    sql = """
    SELECT
        COUNT(*)                                                          AS total_rows,
        COUNT(DISTINCT sku)                                               AS unique_skus,
        COUNT(DISTINCT asin)                                              AS unique_asins,
        COUNT(DISTINCT sku) FILTER (WHERE afn_total_quantity > 0)         AS skus_with_stock,
        COUNT(DISTINCT sku) FILTER (WHERE afn_total_quantity = 0)         AS skus_without_stock,
        COALESCE(SUM(afn_total_quantity), 0)                              AS total_units,
        COALESCE(SUM(afn_total_quantity * your_price)
                 FILTER (WHERE your_price IS NOT NULL), 0)                AS total_inventory_value
    FROM fba_inventory_snapshots
    WHERE snapshot_id = %s;
    """
    conn = get_connection()
    try:
        row = conn.execute(sql, (snapshot_id,)).fetchone()
        return {
            "total_rows": row[0],
            "unique_skus": row[1],
            "unique_asins": row[2],
            "skus_with_stock": row[3],
            "skus_without_stock": row[4],
            "total_units": row[5],
            "total_inventory_value": row[6],
        }
    finally:
        conn.close()


def get_skus_with_stock(snapshot_id: str, limit: int = 20) -> list[dict]:
    sql = """
    SELECT sku, asin, product_name, afn_total_quantity, your_price
    FROM fba_inventory_snapshots
    WHERE snapshot_id = %s
      AND afn_total_quantity > 0
    ORDER BY afn_total_quantity DESC
    LIMIT %s;
    """
    conn = get_connection()
    try:
        rows = conn.execute(sql, (snapshot_id, limit)).fetchall()
        return [
            {
                "sku": r[0],
                "asin": r[1],
                "product_name": r[2],
                "afn_total_quantity": r[3],
                "your_price": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_zero_stock_skus(snapshot_id: str, limit: int = 20) -> list[dict]:
    sql = """
    SELECT sku, asin, product_name, afn_total_quantity, your_price
    FROM fba_inventory_snapshots
    WHERE snapshot_id = %s
      AND afn_total_quantity = 0
    ORDER BY sku ASC
    LIMIT %s;
    """
    conn = get_connection()
    try:
        rows = conn.execute(sql, (snapshot_id, limit)).fetchall()
        return [
            {
                "sku": r[0],
                "asin": r[1],
                "product_name": r[2],
                "afn_total_quantity": r[3],
                "your_price": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()


def print_inventory_summary() -> None:
    meta = get_latest_snapshot_import()
    if meta is None:
        print(_NO_SNAPSHOT_MSG)
        return

    snapshot_id = meta["snapshot_id"]
    imported_at = meta["imported_at"]
    now_utc = datetime.now(timezone.utc)

    # imported_at may be timezone-aware or naive depending on psycopg3 config
    if imported_at.tzinfo is None:
        imported_at = imported_at.replace(tzinfo=timezone.utc)
    age = now_utc - imported_at
    age_hours, remainder = divmod(int(age.total_seconds()), 3600)
    age_minutes = remainder // 60

    s = get_inventory_summary(snapshot_id)

    print(f"Snapshot ID:            {snapshot_id}")
    print(f"Source file:            {meta['source_file']}")
    print(f"Imported at:            {imported_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Snapshot age:           {age_hours}h {age_minutes}m")
    print(f"Total rows:             {s['total_rows']}")
    print(f"Unique SKUs:            {s['unique_skus']}")
    print(f"Unique ASINs:           {s['unique_asins']}")
    print(f"SKUs with stock:        {s['skus_with_stock']}")
    print(f"SKUs without stock:     {s['skus_without_stock']}")
    print(f"Total units:            {s['total_units']}")
    print(f"Total inventory value:  {s['total_inventory_value']:,.2f}")
