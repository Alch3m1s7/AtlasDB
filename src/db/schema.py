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
    skipped_rows        INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL,
    error_message       TEXT,
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_AUDIT_SCHEMA = "CREATE SCHEMA IF NOT EXISTS audit;"

CREATE_AUDIT_INGESTION_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS audit.ingestion_runs (
    run_id          UUID PRIMARY KEY,
    source          TEXT NOT NULL,
    report_type     TEXT,
    report_id       TEXT,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    source_file     TEXT,
    expected_rows   INTEGER,
    parsed_rows     INTEGER,
    inserted_rows   INTEGER,
    skipped_rows    INTEGER,
    error_message   TEXT,
    snapshot_id     UUID
);
"""

CREATE_REFERENCE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS reference;"

CREATE_REFERENCE_MARKETPLACES_TABLE = """
CREATE TABLE IF NOT EXISTS reference.marketplaces (
    marketplace_id   TEXT PRIMARY KEY,
    marketplace_code TEXT NOT NULL,
    region           TEXT NOT NULL,
    country_code     TEXT NOT NULL,
    currency_code    TEXT NOT NULL,
    marketplace_name TEXT NOT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SEED_REFERENCE_MARKETPLACES = """
INSERT INTO reference.marketplaces (
    marketplace_id, marketplace_code, region, country_code, currency_code, marketplace_name, is_active
) VALUES
    ('A1F83G8C2ARO7P', 'UK', 'EU', 'GB', 'GBP', 'Amazon UK', true)
ON CONFLICT (marketplace_id) DO NOTHING;
"""

CREATE_REFERENCE_FX_RATES_TABLE = """
CREATE TABLE IF NOT EXISTS reference.fx_rates (
    base_currency   TEXT NOT NULL,
    target_currency TEXT NOT NULL,
    rate            NUMERIC(18, 8) NOT NULL,
    rate_type       TEXT NOT NULL DEFAULT 'FIXED_BUSINESS_COMPARISON',
    effective_from  DATE NOT NULL,
    source_note     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (base_currency, target_currency, effective_from),
    CONSTRAINT chk_fx_rate_positive        CHECK (rate > 0),
    CONSTRAINT chk_fx_no_self_conversion   CHECK (base_currency <> target_currency)
);
"""

SEED_REFERENCE_FX_RATES = """
INSERT INTO reference.fx_rates (
    base_currency, target_currency, rate, rate_type, effective_from, source_note, is_active
) VALUES
    ('USD', 'GBP', 0.79000000, 'FIXED_BUSINESS_COMPARISON', '2026-04-26', 'Placeholder fixed business comparison rate - replace with user approved rate', true),
    ('EUR', 'GBP', 0.86000000, 'FIXED_BUSINESS_COMPARISON', '2026-04-26', 'Placeholder fixed business comparison rate - replace with user approved rate', true),
    ('CAD', 'GBP', 0.58000000, 'FIXED_BUSINESS_COMPARISON', '2026-04-26', 'Placeholder fixed business comparison rate - replace with user approved rate', true),
    ('AUD', 'GBP', 0.51000000, 'FIXED_BUSINESS_COMPARISON', '2026-04-26', 'Placeholder fixed business comparison rate - replace with user approved rate', true)
ON CONFLICT (base_currency, target_currency, effective_from) DO NOTHING;
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

CREATE_STAGING_SCHEMA = "CREATE SCHEMA IF NOT EXISTS staging;"

CREATE_KEEPAU_PRICE_FEE_PROBE_TABLE = """
CREATE TABLE IF NOT EXISTS staging.keepau_price_fee_probe (
    id                        BIGSERIAL PRIMARY KEY,
    run_id                    UUID NOT NULL,
    observed_at               TIMESTAMPTZ NOT NULL,
    marketplace_id            TEXT NOT NULL,
    asin                      TEXT NOT NULL,
    title                     TEXT,
    brand                     TEXT,
    featured_price            NUMERIC(12, 4),
    featured_currency         TEXT,
    featured_seller_id        TEXT,
    featured_fulfillment_type TEXT,
    featured_condition        TEXT,
    lowest_price              NUMERIC(12, 4),
    lowest_currency           TEXT,
    lowest_seller_id          TEXT,
    referral_fee              NUMERIC(12, 4),
    referral_fee_rate_pct     NUMERIC(8, 4),
    fba_fee                   NUMERIC(12, 4),
    price_source              TEXT,
    catalog_request_id        TEXT,
    pricing_request_id        TEXT,
    fees_request_id           TEXT,
    raw_catalog_path          TEXT,
    raw_pricing_path          TEXT,
    raw_fees_path             TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_KEEPAU_PRICE_FEE_PROBE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_keepau_probe_asin ON staging.keepau_price_fee_probe (asin);",
    "CREATE INDEX IF NOT EXISTS idx_keepau_probe_observed_at ON staging.keepau_price_fee_probe (observed_at);",
    "CREATE INDEX IF NOT EXISTS idx_keepau_probe_featured_seller ON staging.keepau_price_fee_probe (featured_seller_id);",
    "CREATE INDEX IF NOT EXISTS idx_keepau_probe_marketplace_asin_observed ON staging.keepau_price_fee_probe (marketplace_id, asin, observed_at);",
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
        conn.execute(
            "ALTER TABLE fba_inventory_imports ADD COLUMN IF NOT EXISTS skipped_rows INTEGER NOT NULL DEFAULT 0;"
        )
        conn.execute(CREATE_AUDIT_SCHEMA)
        conn.execute(CREATE_AUDIT_INGESTION_RUNS_TABLE)
        conn.execute(CREATE_REFERENCE_SCHEMA)
        conn.execute(CREATE_REFERENCE_MARKETPLACES_TABLE)
        conn.execute(SEED_REFERENCE_MARKETPLACES)
        conn.execute(CREATE_REFERENCE_FX_RATES_TABLE)
        conn.execute(SEED_REFERENCE_FX_RATES)
        conn.execute(CREATE_STAGING_SCHEMA)
        conn.execute(CREATE_KEEPAU_PRICE_FEE_PROBE_TABLE)
        for stmt in CREATE_KEEPAU_PRICE_FEE_PROBE_INDEXES:
            conn.execute(stmt)
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
        conn.execute(CREATE_AUDIT_SCHEMA)
        conn.execute(CREATE_AUDIT_INGESTION_RUNS_TABLE)
        conn.execute(CREATE_REFERENCE_SCHEMA)
        conn.execute(CREATE_REFERENCE_MARKETPLACES_TABLE)
        conn.execute(SEED_REFERENCE_MARKETPLACES)
        conn.execute(CREATE_REFERENCE_FX_RATES_TABLE)
        conn.execute(SEED_REFERENCE_FX_RATES)
        conn.execute(CREATE_STAGING_SCHEMA)
        conn.execute(CREATE_KEEPAU_PRICE_FEE_PROBE_TABLE)
        for stmt in CREATE_KEEPAU_PRICE_FEE_PROBE_INDEXES:
            conn.execute(stmt)
        conn.commit()
        print("Tables created successfully")
    finally:
        conn.close()


if __name__ == "__main__":
    create_tables()
    run_migrations()
    print("Schema up to date.")
