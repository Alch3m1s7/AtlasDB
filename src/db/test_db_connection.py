from db.db_connection import get_connection


def test_connection() -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT version()").fetchone()
    print("Database connection OK")
    print(row[0])


if __name__ == "__main__":
    test_connection()
