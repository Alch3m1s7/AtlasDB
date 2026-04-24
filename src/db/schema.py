from db.db_connection import get_connection

CREATE_FBA_INVENTORY_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS fba_inventory_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id UUID,

    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    region TEXT NOT NULL,
    marketplace_id TEXT NOT NULL,
    marketplace_code TEXT NOT NULL,

    sku TEXT NOT NULL,
    fnsku TEXT,
    asin TEXT NOT NULL,
    product_name TEXT,
    condition TEXT,

    your_price NUMERIC(12, 2),
    mfn_listing_exists BOOLEAN,
    mfn_fulfillable_quantity INTEGER,
    afn_listing_exists BOOLEAN,

    afn_warehouse_quantity INTEGER,
    afn_fulfillable_quantity INTEGER,
    afn_unsellable_quantity INTEGER,
    afn_reserved_quantity INTEGER,
    afn_total_quantity INTEGER,

    per_unit_volume NUMERIC(12, 2),

    afn_inbound_working_quantity INTEGER,
    afn_inbound_shipped_quantity INTEGER,
    afn_inbound_receiving_quantity INTEGER,
    afn_researching_quantity INTEGER,
    afn_reserved_future_supply INTEGER,
    afn_future_supply_buyable INTEGER,
    afn_fulfillable_quantity_local INTEGER,
    afn_fulfillable_quantity_remote INTEGER,

    source_file TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_FBA_INVENTORY_IMPORTS_TABLE = """
CREATE TABLE IF NOT EXISTS fba_inventory_imports (
    id                  BIGSERIAL PRIMARY KEY,
    snapshot_id         UUID,
    source_file         TEXT NOT NULL UNIQUE,
    region              TEXT NOT NULL,
    marketplace_id      TEXT NOT NULL,
    marketplace_code    TEXT NOT NULL,
    row_count           INTEGER NOT NULL,
    inserted_row_count  INTEGER NOT NULL,
    status              TEXT NOT NULL,
    error_message       TEXT,
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_FBA_INVENTORY_IMPORTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_fba_inventory_imports_marketplace_imported ON fba_inventory_imports (marketplace_id, imported_at);",
]

CREATE_FBA_INVENTORY_SNAPSHOTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_fba_inventory_snapshots_sku ON fba_inventory_snapshots (sku);",
    "CREATE INDEX IF NOT EXISTS idx_fba_inventory_snapshots_asin ON fba_inventory_snapshots (asin);",
    "CREATE INDEX IF NOT EXISTS idx_fba_inventory_snapshots_snapshot_at ON fba_inventory_snapshots (snapshot_at);",
    "CREATE INDEX IF NOT EXISTS idx_fba_inventory_snapshots_marketplace_snapshot ON fba_inventory_snapshots (marketplace_id, snapshot_at);",
]


def run_migrations() -> None:
    """Idempotent: adds columns introduced after the initial schema creation."""
    conn = get_connection()
    try:
        conn.execute(
            "ALTER TABLE fba_inventory_snapshots ADD COLUMN IF NOT EXISTS snapshot_id UUID;"
        )
        conn.execute(
            "ALTER TABLE fba_inventory_imports ADD COLUMN IF NOT EXISTS snapshot_id UUID;"
        )
        conn.commit()
        print("Migrations applied successfully")
    finally:
        conn.close()


def create_tables() -> None:
    conn = get_connection()
    try:
        conn.execute(CREATE_FBA_INVENTORY_SNAPSHOTS_TABLE)
        for stmt in CREATE_FBA_INVENTORY_SNAPSHOTS_INDEXES:
            conn.execute(stmt)
        conn.execute(CREATE_FBA_INVENTORY_IMPORTS_TABLE)
        for stmt in CREATE_FBA_INVENTORY_IMPORTS_INDEXES:
            conn.execute(stmt)
        conn.commit()
        print("Tables created successfully")
    finally:
        conn.close()


if __name__ == "__main__":
    create_tables()
    run_migrations()
    print("Schema up to date.")
