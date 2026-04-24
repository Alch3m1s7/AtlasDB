from db.db_connection import get_connection


def get_inventory_summary() -> dict:
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
    FROM fba_inventory_snapshots;
    """
    conn = get_connection()
    try:
        row = conn.execute(sql).fetchone()
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


def get_skus_with_stock(limit: int = 20) -> list[dict]:
    sql = """
    SELECT sku, asin, product_name, afn_total_quantity, your_price
    FROM fba_inventory_snapshots
    WHERE afn_total_quantity > 0
    ORDER BY afn_total_quantity DESC
    LIMIT %s;
    """
    conn = get_connection()
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
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


def get_zero_stock_skus(limit: int = 20) -> list[dict]:
    sql = """
    SELECT sku, asin, product_name, afn_total_quantity, your_price
    FROM fba_inventory_snapshots
    WHERE afn_total_quantity = 0
    ORDER BY sku ASC
    LIMIT %s;
    """
    conn = get_connection()
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
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
    s = get_inventory_summary()
    print(f"Total rows:             {s['total_rows']}")
    print(f"Unique SKUs:            {s['unique_skus']}")
    print(f"Unique ASINs:           {s['unique_asins']}")
    print(f"SKUs with stock:        {s['skus_with_stock']}")
    print(f"SKUs without stock:     {s['skus_without_stock']}")
    print(f"Total units:            {s['total_units']}")
    print(f"Total inventory value:  {s['total_inventory_value']:,.2f}")
