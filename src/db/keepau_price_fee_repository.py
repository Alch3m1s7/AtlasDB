from db.db_connection import get_connection

INSERT_KEEPAU_PRICE_FEE_PROBE_SQL = """
INSERT INTO staging.keepau_price_fee_probe (
    run_id, observed_at, marketplace_id, asin,
    title, brand,
    featured_price, featured_currency, featured_seller_id,
    featured_fulfillment_type, featured_condition,
    lowest_price, lowest_currency, lowest_seller_id,
    referral_fee, referral_fee_rate_pct, fba_fee,
    price_source,
    catalog_request_id, pricing_request_id, fees_request_id,
    raw_catalog_path, raw_pricing_path, raw_fees_path
) VALUES (
    %(run_id)s, %(observed_at)s, %(marketplace_id)s, %(asin)s,
    %(title)s, %(brand)s,
    %(featured_price)s, %(featured_currency)s, %(featured_seller_id)s,
    %(featured_fulfillment_type)s, %(featured_condition)s,
    %(lowest_price)s, %(lowest_currency)s, %(lowest_seller_id)s,
    %(referral_fee)s, %(referral_fee_rate_pct)s, %(fba_fee)s,
    %(price_source)s,
    %(catalog_request_id)s, %(pricing_request_id)s, %(fees_request_id)s,
    %(raw_catalog_path)s, %(raw_pricing_path)s, %(raw_fees_path)s
)
"""


def insert_keepau_price_fee_probe_rows(
    rows: list[dict],
    raw_paths: dict,
    run_id: str,
    observed_at,
    marketplace_id: str,
) -> int:
    params_list = [
        {
            "run_id": run_id,
            "observed_at": observed_at,
            "marketplace_id": marketplace_id,
            "asin": row["asin"],
            "title": row.get("title") or None,
            "brand": row.get("brand") or None,
            "featured_price": row.get("feat_price"),
            "featured_currency": row.get("feat_currency"),
            "featured_seller_id": row.get("feat_seller"),
            "featured_fulfillment_type": row.get("fulfillment"),
            "featured_condition": row.get("condition"),
            "lowest_price": row.get("low_price"),
            "lowest_currency": row.get("low_currency"),
            "lowest_seller_id": row.get("low_seller"),
            "referral_fee": row.get("referral_fee"),
            "referral_fee_rate_pct": row.get("referral_pct"),
            "fba_fee": row.get("fba_fee"),
            "price_source": row.get("price_src"),
            "catalog_request_id": row.get("catalog_rid_full"),
            "pricing_request_id": row.get("pricing_rid_full"),
            "fees_request_id": row.get("fees_rid_full"),
            "raw_catalog_path": raw_paths.get("catalog"),
            "raw_pricing_path": raw_paths.get("pricing"),
            "raw_fees_path": raw_paths.get("fees"),
        }
        for row in rows
    ]
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.executemany(INSERT_KEEPAU_PRICE_FEE_PROBE_SQL, params_list)
        conn.commit()
        return len(params_list)
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
