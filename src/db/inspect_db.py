from db.db_connection import get_connection


def list_tables() -> None:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;"
        ).fetchall()
        if rows:
            for (table_name,) in rows:
                print(table_name)
        else:
            print("No tables found in public schema.")
    finally:
        conn.close()


def count_inventory_rows() -> None:
    conn = get_connection()
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM fba_inventory_snapshots;").fetchone()
        print(f"Inventory rows: {count}")
    finally:
        conn.close()


def count_import_rows() -> None:
    conn = get_connection()
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM fba_inventory_imports;").fetchone()
        print(f"Inventory imports: {count}")
    finally:
        conn.close()


if __name__ == "__main__":
    list_tables()
    count_inventory_rows()
    count_import_rows()
