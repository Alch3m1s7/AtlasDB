from db.db_connection import get_connection

_RECENT_RUNS_SQL = """
SELECT
    run_id,
    MIN(observed_at)                                    AS observed_at,
    COUNT(*)                                            AS row_count,
    COUNT(featured_price)                               AS real_featured_price_count,
    COUNT(*) FILTER (WHERE price_source = 'FALLBACK')  AS fallback_count,
    COUNT(DISTINCT featured_seller_id)
        FILTER (WHERE featured_seller_id IS NOT NULL)   AS featured_seller_id_count,
    COUNT(lowest_price)                                 AS lowest_price_count,
    COUNT(referral_fee)                                 AS referral_fee_populated_count,
    COUNT(fba_fee)                                      AS fba_fee_populated_count,
    AVG(featured_price)                                 AS avg_featured_price
FROM staging.keepau_price_fee_probe
GROUP BY run_id
ORDER BY MIN(observed_at) DESC
LIMIT 5;
"""

_LATEST_RUN_DETAIL_SQL = """
SELECT
    asin,
    brand,
    featured_price,
    featured_seller_id,
    lowest_price,
    lowest_seller_id,
    referral_fee_rate_pct,
    fba_fee,
    price_source
FROM staging.keepau_price_fee_probe
WHERE run_id = %s
ORDER BY asin;
"""


def get_recent_keepau_runs() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(_RECENT_RUNS_SQL).fetchall()
        return [
            {
                "run_id": str(r[0]),
                "observed_at": r[1],
                "row_count": r[2],
                "real_featured_price_count": r[3],
                "fallback_count": r[4],
                "featured_seller_id_count": r[5],
                "lowest_price_count": r[6],
                "referral_fee_populated_count": r[7],
                "fba_fee_populated_count": r[8],
                "avg_featured_price": float(r[9]) if r[9] is not None else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_keepau_run_detail(run_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(_LATEST_RUN_DETAIL_SQL, (run_id,)).fetchall()
        return [
            {
                "asin": r[0],
                "brand": r[1],
                "featured_price": float(r[2]) if r[2] is not None else None,
                "featured_seller_id": r[3],
                "lowest_price": float(r[4]) if r[4] is not None else None,
                "lowest_seller_id": r[5],
                "referral_fee_rate_pct": float(r[6]) if r[6] is not None else None,
                "fba_fee": float(r[7]) if r[7] is not None else None,
                "price_source": r[8],
            }
            for r in rows
        ]
    finally:
        conn.close()


def print_keepau_latest() -> None:
    runs = get_recent_keepau_runs()
    if not runs:
        print("No KeepAU probe runs found in staging.keepau_price_fee_probe.")
        return

    print("=" * 88)
    print("KEEPAU - LAST 5 RUNS")
    print("=" * 88)
    hdr = (
        f"{'#':<3} {'observed_at':<22} {'rows':>5} {'fall':>5} "
        f"{'feat$':>6} {'feat_sel':>8} {'low$':>5} "
        f"{'ref$':>5} {'fba':>5} {'avg_feat$':>10}  run_id"
    )
    print(hdr)
    print("-" * 88)
    for i, run in enumerate(runs, 1):
        obs = run["observed_at"]
        obs_str = obs.strftime("%Y-%m-%d %H:%M:%S") if obs else "-"
        avg = f"{run['avg_featured_price']:.2f}" if run["avg_featured_price"] is not None else "-"
        print(
            f"{i:<3} {obs_str:<22} {run['row_count']:>5} {run['fallback_count']:>5} "
            f"{run['real_featured_price_count']:>6} {run['featured_seller_id_count']:>8} "
            f"{run['lowest_price_count']:>5} "
            f"{run['referral_fee_populated_count']:>5} {run['fba_fee_populated_count']:>5} "
            f"{avg:>10}  {run['run_id']}"
        )
    print()

    latest_run_id = runs[0]["run_id"]
    detail = get_keepau_run_detail(latest_run_id)

    print("=" * 88)
    print(f"LATEST RUN DETAIL  run_id={latest_run_id}")
    print(f"observed_at={runs[0]['observed_at']}  rows={runs[0]['row_count']}  fallback={runs[0]['fallback_count']}")
    print("=" * 88)

    def _f(v, fmt=".4f"):
        return format(v, fmt) if v is not None else "-"

    def _s(v, width=0):
        if v is None:
            return "-"
        return str(v)[:width] if width else str(v)

    h = (
        f"{'ASIN':<12} {'BRAND':<15} {'FEAT$':>9} {'FEAT_SELLER':<15} "
        f"{'LOW$':>9} {'LOW_SELLER':<15} {'REF%':>6} {'FBA$':>8} {'SRC':<8}"
    )
    print(h)
    print("-" * 105)
    for row in detail:
        print(
            f"{_s(row['asin']):<12} {_s(row['brand'], 15):<15} "
            f"{_f(row['featured_price']):>9} {_s(row['featured_seller_id'], 15):<15} "
            f"{_f(row['lowest_price']):>9} {_s(row['lowest_seller_id'], 15):<15} "
            f"{_f(row['referral_fee_rate_pct'], '.2f'):>6} "
            f"{_f(row['fba_fee'], '.4f'):>8} {_s(row['price_source']):<8}"
        )
    print("=" * 88)
