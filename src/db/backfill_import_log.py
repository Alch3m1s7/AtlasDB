from db.db_connection import get_connection


def backfill_existing_fba_inventory_imports() -> None:
    conn = get_connection()
    try:
        (import_count,) = conn.execute("SELECT COUNT(*) FROM fba_inventory_imports;").fetchone()
        if import_count > 0:
            print("Import log already has records, skipping")
            return

        row = conn.execute("""
            SELECT
                MIN(source_file)      AS source_file,
                MIN(region)           AS region,
                MIN(marketplace_id)   AS marketplace_id,
                MIN(marketplace_code) AS marketplace_code,
                COUNT(*)              AS row_count
            FROM fba_inventory_snapshots;
        """).fetchone()

        source_file, region, marketplace_id, marketplace_code, row_count = row

        conn.execute("""
            INSERT INTO fba_inventory_imports (
                source_file, region, marketplace_id, marketplace_code,
                row_count, inserted_row_count, status, error_message
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (source_file, region, marketplace_id, marketplace_code,
              row_count, row_count, "SUCCESS", None))
        conn.commit()
        print("Backfilled import log")
    finally:
        conn.close()


if __name__ == "__main__":
    backfill_existing_fba_inventory_imports()
