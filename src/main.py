import argparse
import os
from dotenv import load_dotenv
from auth.spapi_auth import get_access_token
from reports.report_requests import create_report, get_report_status, get_recent_done_report, EU_UK_MARKETPLACE_ID, REPORT_TYPE
from reports.report_downloads import get_report_document, download_report
from reports.report_parsers import parse_fba_inventory_report
from reports.report_exports import export_rows_to_jsonl
from logs.report_logger import log_report_created, log_status_checked, log_report_downloaded, log_fatal_status, log_ingest_result
from db.inventory_repository import insert_fba_inventory_snapshot_rows
from db.inventory_queries import print_inventory_summary
from db.audit_runs import start_ingestion_run, finish_ingestion_run, fail_ingestion_run
from catalog.catalog_items import (
    AU_BASE_URL, AU_MARKETPLACE_ID, PROBE_ASINS,
    PROBE_MARKETS, get_catalog_item, search_catalog_items, print_catalog_item_summary,
)
from pricing.product_pricing import (
    get_competitive_summary_batch, extract_pricing_by_asin,
    extract_featured_offer_price, print_pricing_summary,
)
from fees.product_fees import get_fees_estimate, print_fees_summary, extract_fee_amounts, FALLBACK_PRICE_AUD

load_dotenv()

PARSE_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "fba_inventory_uk_20260424_000609.txt")
EXPORT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "fba_inventory_uk_cleaned.jsonl")
EXISTING_REPORT_ID = "2393624020567"
EXISTING_REPORT_DOCUMENT_ID = "amzn1.spdoc.1.4.eu.df8f719b-9c4a-4cdb-9ade-c350072af890.TPG5PTT1VZLV8.2651"

EU_BASE_URL = "https://sellingpartnerapi-eu.amazon.com"


def main():
    parser = argparse.ArgumentParser(description="AtlasDB SP-API tool")
    parser.add_argument(
        "command",
        choices=["create", "status", "document", "download", "parse", "export", "insert", "query", "ingest-local", "ingest-spapi", "probe-keepau-catalog", "probe-catalog-marketplaces", "probe-keepau-catalog-search", "probe-keepau-pricing-fees", "probe-marketplace-pricing-fees", "probe-pricing-access"],
        help="Command to run",
    )
    args = parser.parse_args()

    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    if args.command in ["create", "status", "document", "download", "ingest-spapi"]:
        refresh_token = os.getenv("SPAPI_REFRESH_TOKEN_EU")
        if not refresh_token:
            raise RuntimeError("SPAPI_REFRESH_TOKEN_EU is not set")
        access_token = get_access_token(refresh_token)

    if args.command in ["probe-keepau-catalog", "probe-keepau-catalog-search", "probe-keepau-pricing-fees"]:
        # AU is in the FE region; prefer SPAPI_REFRESH_TOKEN_AU if set, else fall back to SPAPI_REFRESH_TOKEN_FE
        au_refresh_token = os.getenv("SPAPI_REFRESH_TOKEN_AU") or os.getenv("SPAPI_REFRESH_TOKEN_FE")
        if not au_refresh_token:
            raise RuntimeError("Set SPAPI_REFRESH_TOKEN_AU or SPAPI_REFRESH_TOKEN_FE in .env")
        au_access_token = get_access_token(au_refresh_token)

    if args.command == "create":
        report_id = create_report(EU_BASE_URL, access_token, EU_UK_MARKETPLACE_ID, REPORT_TYPE)
        log_report_created("EU", EU_UK_MARKETPLACE_ID, REPORT_TYPE, report_id)
        print(f"reportId: {report_id}")

    elif args.command == "status":
        if not EXISTING_REPORT_ID:
            raise RuntimeError("EXISTING_REPORT_ID must be set")

        import time
        time.sleep(150)  # initial wait before first status check

        for attempt in range(10):
            status = get_report_status(EU_BASE_URL, access_token, EXISTING_REPORT_ID)
            processing_status = status.get("processingStatus")
            document_id = status.get("reportDocumentId")

            log_status_checked(EXISTING_REPORT_ID, processing_status, document_id)

            print(f"Attempt {attempt + 1}: {processing_status}")

            if processing_status == "DONE":
                print(f"reportDocumentId: {document_id}")
                break

            if processing_status in ["FATAL", "CANCELLED"]:
                import json
                print(json.dumps(status, indent=2))
                raise RuntimeError(f"Report failed: {processing_status}")

            time.sleep(30)

    elif args.command == "document":
        if not EXISTING_REPORT_DOCUMENT_ID:
            raise RuntimeError("EXISTING_REPORT_DOCUMENT_ID must be set when ACTION is 'document'")
        doc = get_report_document(EU_BASE_URL, access_token, EXISTING_REPORT_DOCUMENT_ID)
        print(f"reportDocumentId:     {doc.get('reportDocumentId')}")
        print(f"url:                  {doc.get('url')}")
        print(f"compressionAlgorithm: {doc.get('compressionAlgorithm')}")

    elif args.command == "download":
        if not EXISTING_REPORT_DOCUMENT_ID:
            raise RuntimeError("EXISTING_REPORT_DOCUMENT_ID must be set when ACTION is 'download'")
        doc = get_report_document(EU_BASE_URL, access_token, EXISTING_REPORT_DOCUMENT_ID)
        saved_path = download_report(
            url=doc["url"],
            compression_algorithm=doc.get("compressionAlgorithm"),
            filename=f"fba_inventory_uk_{datetime.now(ZoneInfo('Europe/London')):%Y%m%d_%H%M_%S}.txt",
        )
        log_report_downloaded(EXISTING_REPORT_DOCUMENT_ID, saved_path)
        print(f"Saved: {saved_path}")

    elif args.command == "parse":
        rows = parse_fba_inventory_report(PARSE_FILE_PATH)
        columns = list(rows[0].keys()) if rows else []
        invalid_rows = [row for row in rows if not row["_is_valid"]]

        print(f"Total rows: {len(rows)}")
        print(f"Valid rows: {len(rows) - len(invalid_rows)}")
        print(f"Invalid rows: {len(invalid_rows)}")
        print(f"Columns: {columns}")

        print("First 3 cleaned rows:")
        for row in rows[:3]:
            print(row)

        if invalid_rows:
            print("First 3 invalid rows:")
            for row in invalid_rows[:3]:
                print(row)

    elif args.command == "export":
        rows = parse_fba_inventory_report(PARSE_FILE_PATH)
        saved_path = export_rows_to_jsonl(rows, EXPORT_OUTPUT_PATH)
        print(f"Saved: {saved_path}")
        print(f"Rows exported: {len(rows)}")

        print(f"Unique ASINs: {len({r['asin'] for r in rows if r.get('asin')})}")
        print(f"Unique SKUs:  {len({r['sku'] for r in rows if r.get('sku')})}")

        qty_vals = [r["afn-total-quantity"] for r in rows if isinstance(r.get("afn-total-quantity"), int)]
        print(f"afn-total-quantity  min={min(qty_vals, default=None)}  max={max(qty_vals, default=None)}")

        price_vals = [r["your-price"] for r in rows if r.get("your-price") is not None]
        print(f"your-price          min={min(price_vals, default=None)}  max={max(price_vals, default=None)}")

        print(f"Rows with afn-total-quantity > 0: {sum(1 for r in rows if isinstance(r.get('afn-total-quantity'), int) and r['afn-total-quantity'] > 0)}")
        print(f"Rows with your-price = None:      {sum(1 for r in rows if r.get('your-price') is None)}")

    elif args.command == "insert":
        rows = parse_fba_inventory_report(PARSE_FILE_PATH)
        valid_rows = [row for row in rows if row["_is_valid"]]
        inserted, _ = insert_fba_inventory_snapshot_rows(
            rows=valid_rows,
            region="EU",
            marketplace_id=EU_UK_MARKETPLACE_ID,
            marketplace_code="UK",
            source_file=PARSE_FILE_PATH,
        )
        print(f"Inserted rows: {inserted}")

    elif args.command == "query":
        print_inventory_summary()

    elif args.command == "ingest-local":
        rows = parse_fba_inventory_report(PARSE_FILE_PATH)
        valid_rows = [row for row in rows if row["_is_valid"]]
        expected = len(valid_rows)
        export_rows_to_jsonl(rows, EXPORT_OUTPUT_PATH)
        inserted, _ = insert_fba_inventory_snapshot_rows(
            rows=valid_rows,
            region="EU",
            marketplace_id=EU_UK_MARKETPLACE_ID,
            marketplace_code="UK",
            source_file=PARSE_FILE_PATH,
        )
        print(f"Inserted rows: {inserted}")
        if expected > 0 and inserted == 0:
            ingest_status = "SKIPPED_DUPLICATE"
        elif inserted == expected:
            ingest_status = "SUCCESS"
        elif inserted > 0:
            ingest_status = "PARTIAL"
        else:
            ingest_status = "FAILED"
        log_ingest_result(
            source_file=PARSE_FILE_PATH,
            status=ingest_status,
            expected_rows=expected,
            inserted_rows=inserted,
            skipped_rows=expected - inserted,
        )
        print_inventory_summary()

    elif args.command == "ingest-spapi":
        import json
        import time

        POLL_DELAYS = [30, 45, 60, 90, 120]  # seconds before each poll attempt
        now_utc = datetime.now(timezone.utc)

        run_id = start_ingestion_run(source="ingest-spapi", report_type=REPORT_TYPE)

        # --- Step 1: Check for a recent DONE report before creating a new one ---
        document_id = None
        found_report_id = None
        ingest_report_id = None
        reused_existing_report = False

        recent_24h = get_recent_done_report(
            EU_BASE_URL, access_token, REPORT_TYPE, EU_UK_MARKETPLACE_ID,
            created_since_iso=(now_utc - timedelta(hours=24)).isoformat(),
        )

        if recent_24h:
            document_id = recent_24h.get("reportDocumentId")
            found_report_id = recent_24h.get("reportId")
            ingest_report_id = found_report_id
            reused_existing_report = True
            print(f"Using existing DONE report from last 24h: reportId={found_report_id}")
        else:
            recent_48h = get_recent_done_report(
                EU_BASE_URL, access_token, REPORT_TYPE, EU_UK_MARKETPLACE_ID,
                created_since_iso=(now_utc - timedelta(hours=48)).isoformat(),
            )
            if recent_48h:
                document_id = recent_48h.get("reportDocumentId")
                found_report_id = recent_48h.get("reportId")
                ingest_report_id = found_report_id
                reused_existing_report = True
                print(
                    f"Using existing DONE report from last 48h; "
                    f"warning: older than preferred freshness: reportId={found_report_id}"
                )
            else:
                # --- Step 2: No recent DONE report — create one ---
                report_id = create_report(EU_BASE_URL, access_token, EU_UK_MARKETPLACE_ID, REPORT_TYPE)
                log_report_created("EU", EU_UK_MARKETPLACE_ID, REPORT_TYPE, report_id)
                ingest_report_id = report_id
                reused_existing_report = False
                print(f"New report created: {report_id}")

                done = False
                fatal = False

                for attempt, delay in enumerate(POLL_DELAYS):
                    print(f"Waiting {delay}s before poll {attempt + 1}/{len(POLL_DELAYS)}...")
                    time.sleep(delay)

                    status = get_report_status(EU_BASE_URL, access_token, report_id)
                    processing_status = status.get("processingStatus")
                    document_id = status.get("reportDocumentId")

                    log_status_checked(report_id, processing_status, document_id)
                    print(f"Poll {attempt + 1}/{len(POLL_DELAYS)}: {processing_status}")

                    if processing_status == "DONE":
                        print(f"reportDocumentId: {document_id}")
                        done = True
                        break

                    if processing_status in ["FATAL", "CANCELLED"]:
                        print(f"Report {processing_status}. Full status:")
                        print(json.dumps(status, indent=2))
                        log_fatal_status(report_id, processing_status, status)

                        if document_id:
                            print(f"Fetching error document: {document_id}")
                            try:
                                err_doc = get_report_document(EU_BASE_URL, access_token, document_id)
                                err_path = download_report(
                                    url=err_doc["url"],
                                    compression_algorithm=err_doc.get("compressionAlgorithm"),
                                    filename=f"fatal_report_{report_id}.txt",
                                )
                                print(f"Error document saved: {err_path}")
                            except Exception as e:
                                print(f"Could not download error document: {e}")
                        else:
                            print("No reportDocumentId returned for FATAL/CANCELLED")

                        fail_ingestion_run(
                            run_id=run_id,
                            error_message=f"Report {processing_status}: {report_id}",
                            report_id=report_id,
                        )
                        fatal = True
                        break

                if not done:
                    if not fatal:
                        print("Report did not complete within polling window; try again later.")
                        fail_ingestion_run(
                            run_id=run_id,
                            error_message="Polling window exceeded without DONE status",
                            report_id=ingest_report_id,
                        )
                    return

        # --- Step 3: Download / parse / export / insert / query ---
        if not document_id:
            print("No reportDocumentId available. Aborting.")
            fail_ingestion_run(
                run_id=run_id,
                error_message="No reportDocumentId available after polling",
                report_id=ingest_report_id,
            )
            return

        timestamp = f"{datetime.now(ZoneInfo('Europe/London')):%Y%m%d_%H%M%S}"
        doc = get_report_document(EU_BASE_URL, access_token, document_id)
        raw_path = download_report(
            url=doc["url"],
            compression_algorithm=doc.get("compressionAlgorithm"),
            filename=f"fba_inventory_uk_{timestamp}.txt",
        )
        log_report_downloaded(document_id, raw_path)
        print(f"Downloaded: {raw_path}")

        rows = parse_fba_inventory_report(raw_path)
        valid_rows = [row for row in rows if row["_is_valid"]]

        jsonl_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "processed",
            f"fba_inventory_uk_{timestamp}.jsonl",
        )
        export_rows_to_jsonl(rows, jsonl_path)
        print(f"Exported: {jsonl_path}")

        expected = len(valid_rows)
        inserted, inserted_snapshot_id = insert_fba_inventory_snapshot_rows(
            rows=valid_rows,
            region="EU",
            marketplace_id=EU_UK_MARKETPLACE_ID,
            marketplace_code="UK",
            source_file=raw_path,
        )
        print(f"Inserted rows: {inserted}")
        if expected > 0 and inserted == 0:
            ingest_status = "SKIPPED_DUPLICATE"
        elif inserted == expected:
            ingest_status = "SUCCESS"
        elif inserted > 0:
            ingest_status = "PARTIAL"
        else:
            ingest_status = "FAILED"
        finish_ingestion_run(
            run_id=run_id,
            status=ingest_status,
            report_id=ingest_report_id,
            source_file=raw_path,
            parsed_rows=len(rows),
            expected_rows=expected,
            inserted_rows=inserted,
            skipped_rows=expected - inserted,
            snapshot_id=inserted_snapshot_id,
        )
        log_ingest_result(
            source_file=raw_path,
            status=ingest_status,
            expected_rows=expected,
            inserted_rows=inserted,
            skipped_rows=expected - inserted,
            report_id=ingest_report_id,
            report_document_id=document_id,
            marketplace_id=EU_UK_MARKETPLACE_ID,
            report_type=REPORT_TYPE,
            reused_existing_report=reused_existing_report,
        )
        print_inventory_summary()

    elif args.command == "probe-keepau-catalog":
        import json
        import time

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "catalog_probe")
        os.makedirs(probe_dir, exist_ok=True)

        print(f"AU Catalog probe — marketplace: {AU_MARKETPLACE_ID}  base_url: {AU_BASE_URL}")
        print(f"ASINs to probe: {PROBE_ASINS}")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print()

        timestamp = f"{datetime.now(ZoneInfo('Europe/London')):%Y%m%d_%H%M%S}"

        for i, asin in enumerate(PROBE_ASINS):
            if i > 0:
                time.sleep(1)
            print(f"--- ASIN {i + 1}/{len(PROBE_ASINS)}: {asin} ---")
            data = get_catalog_item(
                base_url=AU_BASE_URL,
                access_token=au_access_token,
                asin=asin,
                marketplace_id=AU_MARKETPLACE_ID,
            )

            top_keys = [k for k in data.keys() if not k.startswith("_")]
            has_sales_ranks = "salesRanks" in data
            print(f"  top-level keys : {top_keys}")
            print(f"  salesRanks key : {'YES' if has_sales_ranks else 'NO'}")

            filename = f"catalog_au_{asin}_{timestamp}.json"
            save_path = os.path.join(probe_dir, filename)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"  saved          : {save_path}")

            print_catalog_item_summary(asin, data, AU_MARKETPLACE_ID)
            print()

    elif args.command == "probe-catalog-marketplaces":
        import time

        print("=== Cross-market Catalog Items probe: UK / AU / CA ===")
        print()

        for market_code, cfg in PROBE_MARKETS.items():
            marketplace_id = cfg["marketplace_id"]
            base_url = cfg["base_url"]
            asins = cfg["asins"]

            # Resolve refresh token: first env var with a non-empty value wins
            refresh_token = next(
                (os.getenv(v) for v in cfg["token_env_vars"] if os.getenv(v)),
                None,
            )
            token_source = next(
                (v for v in cfg["token_env_vars"] if os.getenv(v)),
                None,
            )
            if not refresh_token:
                print(f"[{market_code}] SKIP — none of {cfg['token_env_vars']} set in .env")
                print()
                continue

            print(f"[{market_code}] marketplace={marketplace_id}  base_url={base_url}  token={token_source}")
            try:
                access_token_market = get_access_token(refresh_token)
                print(f"[{market_code}] access token obtained")
            except Exception as exc:
                print(f"[{market_code}] AUTH FAILED: {exc}")
                print()
                continue

            for i, asin in enumerate(asins):
                if i > 0:
                    time.sleep(1)
                print(f"  --- {market_code} ASIN {i + 1}/{len(asins)}: {asin} ---")
                data = get_catalog_item(
                    base_url=base_url,
                    access_token=access_token_market,
                    asin=asin,
                    marketplace_id=marketplace_id,
                )
                print_catalog_item_summary(asin, data, marketplace_id)
                print()

            print()

    elif args.command == "probe-keepau-catalog-search":
        import json

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "catalog_probe")
        os.makedirs(probe_dir, exist_ok=True)

        timestamp = f"{datetime.now(ZoneInfo('Europe/London')):%Y%m%d_%H%M%S}"
        print(f"AU Catalog search probe — marketplace: {AU_MARKETPLACE_ID}")
        print(f"ASINs: {PROBE_ASINS}")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print()

        data = search_catalog_items(
            base_url=AU_BASE_URL,
            access_token=au_access_token,
            asins=PROBE_ASINS,
            marketplace_id=AU_MARKETPLACE_ID,
        )

        if "_error" in data:
            print(f"Error: {data}")
        else:
            top_keys = list(data.keys())
            items = data.get("items") or []
            print(f"top-level keys : {top_keys}")
            print(f"items returned : {len(items)}")
            print()

            for item in items:
                asin = item.get("asin", "(unknown)")
                item_keys = [k for k in item.keys() if not k.startswith("_")]
                has_sales_ranks = "salesRanks" in item
                print(f"--- ASIN: {asin} ---")
                print(f"  top-level keys : {item_keys}")
                print(f"  salesRanks key : {'YES' if has_sales_ranks else 'NO'}")
                print_catalog_item_summary(asin, item, AU_MARKETPLACE_ID)
                print()

            save_path = os.path.join(probe_dir, f"catalog_au_search_{timestamp}.json")
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"Saved: {save_path}")

    elif args.command == "probe-keepau-pricing-fees":
        import json
        import time

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "keepau_probe")
        os.makedirs(probe_dir, exist_ok=True)
        timestamp = f"{datetime.now(ZoneInfo('Europe/London')):%Y%m%d_%H%M%S}"

        print(f"=== KeepAU Pricing + Fees probe  marketplace={AU_MARKETPLACE_ID} ===")
        print(f"ASINs: {PROBE_ASINS}")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print()

        # --- Step 1: Catalog (title / brand / classification) ---
        print("--- Step 1: Catalog Items (summaries) ---")
        catalog_data = search_catalog_items(
            base_url=AU_BASE_URL,
            access_token=au_access_token,
            asins=PROBE_ASINS,
            marketplace_id=AU_MARKETPLACE_ID,
            included_data=["summaries"],
        )
        catalog_path = os.path.join(probe_dir, f"keepau_catalog_{timestamp}.json")
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog_data, f, indent=2)
        print(f"  Saved: {catalog_path}")
        print()

        catalog_by_asin: dict[str, dict] = {}
        if "_error" not in catalog_data:
            for item in catalog_data.get("items") or []:
                asin_key = item.get("asin")
                if asin_key:
                    catalog_by_asin[asin_key] = item

        # --- Step 2: Competitive pricing (Buy Box / featured offer) ---
        print("--- Step 2: Competitive Pricing (competitive summary batch) ---")
        pricing_data = get_competitive_summary_batch(
            base_url=AU_BASE_URL,
            access_token=au_access_token,
            asins=PROBE_ASINS,
            marketplace_id=AU_MARKETPLACE_ID,
        )
        pricing_path = os.path.join(probe_dir, f"keepau_pricing_{timestamp}.json")
        with open(pricing_path, "w", encoding="utf-8") as f:
            json.dump(pricing_data, f, indent=2)
        print(f"  Saved: {pricing_path}")
        print()

        pricing_by_asin = extract_pricing_by_asin(pricing_data)

        # --- Step 3: Fees estimates (per ASIN) ---
        print("--- Step 3: Product Fees estimates ---")
        fees_by_asin: dict[str, dict] = {}
        prices_used: dict[str, tuple[float, str]] = {}
        for i, asin in enumerate(PROBE_ASINS):
            if i > 0:
                time.sleep(1)
            featured_price, featured_currency, feat_fulfillment, feat_condition = (
                extract_featured_offer_price(pricing_by_asin.get(asin, {}))
            )
            if featured_price is not None:
                listing_price = featured_price
                currency = featured_currency or "AUD"
                price_label = (
                    f"REAL  {listing_price} {currency}"
                    f"  fulfillment={feat_fulfillment}  condition={feat_condition}"
                )
            else:
                listing_price = FALLBACK_PRICE_AUD
                currency = "AUD"
                price_label = "FALLBACK  (no featured offer price found)"
            prices_used[asin] = (listing_price, price_label)
            fees_by_asin[asin] = get_fees_estimate(
                base_url=AU_BASE_URL,
                access_token=au_access_token,
                asin=asin,
                marketplace_id=AU_MARKETPLACE_ID,
                listing_price=listing_price,
                currency_code=currency,
            )

        fees_path = os.path.join(probe_dir, f"keepau_fees_{timestamp}.json")
        with open(fees_path, "w", encoding="utf-8") as f:
            json.dump(fees_by_asin, f, indent=2)
        print(f"  Saved: {fees_path}")
        print()

        # --- Compact summary per ASIN ---
        print("=" * 60)
        print("COMPACT SUMMARY PER ASIN")
        print("=" * 60)
        for asin in PROBE_ASINS:
            print(f"\n>>> {asin}")
            print_catalog_item_summary(asin, catalog_by_asin.get(asin, {}), AU_MARKETPLACE_ID)
            print("  --- pricing ---")
            print_pricing_summary(asin, pricing_by_asin.get(asin, {}))
            print("  --- fees ---")
            lp, label = prices_used.get(asin, (FALLBACK_PRICE_AUD, ""))
            print_fees_summary(asin, fees_by_asin.get(asin, {}), lp, label)

    elif args.command == "probe-marketplace-pricing-fees":
        import json
        import time

        PRICING_INTERMARKET_DELAY_S = 37  # conservative; default competitiveSummary rate is ~0.5 rps burst

        PROBE_CONFIG = {
            "AU": {
                "marketplace_id": "A39IBJ37TRP1C6",
                "base_url": "https://sellingpartnerapi-fe.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_AU", "SPAPI_REFRESH_TOKEN_FE"],
                "fallback_price": 69.69,
                "fallback_currency": "AUD",
            },
            "UK": {
                "marketplace_id": "A1F83G8C2ARO7P",
                "base_url": "https://sellingpartnerapi-eu.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_EU"],
                "fallback_price": 69.69,
                "fallback_currency": "GBP",
            },
            "CA": {
                "marketplace_id": "A2EUQ1WTGCTBG2",
                "base_url": "https://sellingpartnerapi-na.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_NA"],
                "fallback_price": 69.69,
                "fallback_currency": "CAD",
            },
        }

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "marketplace_probe")
        os.makedirs(probe_dir, exist_ok=True)
        timestamp = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"

        print(f"=== Cross-market Pricing + Fees probe ===")

        # 3-ASIN test set — expand to full PROBE_ASINS when validated
        PROBE_ASINS_RUN = ["B003K71VDK", "B01BTZTO24", "B0063G80FM"]

        # --- ASIN validation ---
        seen_asins: set[str] = set()
        duplicates_removed: list[str] = []
        invalid_asins: list[str] = []
        active_asins: list[str] = []
        for _raw in PROBE_ASINS_RUN:
            _a = _raw.strip().upper()
            if _a in seen_asins:
                duplicates_removed.append(_a)
                continue
            seen_asins.add(_a)
            if len(_a) != 10:
                invalid_asins.append(_a)
            active_asins.append(_a)

        print(f"ASIN validation:")
        print(f"  Input              : {len(PROBE_ASINS_RUN)}")
        print(f"  After dedup        : {len(active_asins)}")
        print(f"  Duplicates removed : {duplicates_removed if duplicates_removed else 'none'}")
        print(f"  Invalid (!=10 chars): {invalid_asins if invalid_asins else 'none'}")
        print(f"  Active ASINs       : {active_asins}")
        print(f"Markets   : {list(PROBE_CONFIG.keys())}")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print(f"Timestamp : {timestamp}Z")
        print()

        def _log_call(market: str, endpoint: str, t_req, t_resp, result: dict) -> None:
            meta = result.get("_meta") or {}
            status = meta.get("status") or result.get("_status", "?")
            rid = meta.get("request_id") or result.get("_request_id", "n/a")
            rl = meta.get("rate_limit") or "n/a"
            latency = f"{(t_resp - t_req).total_seconds():.2f}s"
            print(f"  [{market}] {endpoint}")
            print(f"    req_utc : {t_req.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z")
            print(f"    resp_utc: {t_resp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z  latency={latency}")
            print(f"    HTTP={status}  RequestId={rid}  RateLimit={rl}")
            if result.get("_retry_after"):
                print(f"    Retry-After: {result['_retry_after']}")
            if "_error" in result and result["_error"] != "THROTTLED":
                body_snippet = result.get("_body") or result.get("_detail") or ""
                print(f"    error: {body_snippet[:200]}")

        all_rows: list[dict] = []  # collected for comparison table
        pricing_status_by_market: dict[str, str] = {}

        for market_idx, (market_code, cfg) in enumerate(PROBE_CONFIG.items()):
            marketplace_id = cfg["marketplace_id"]
            base_url = cfg["base_url"]
            fallback_price = cfg["fallback_price"]
            fallback_currency = cfg["fallback_currency"]

            print(f"{'=' * 55}")
            print(f"MARKET: {market_code}  marketplace_id={marketplace_id}")
            print(f"{'=' * 55}")

            # --- Token ---
            refresh_token = next(
                (os.getenv(v) for v in cfg["token_env_vars"] if os.getenv(v)), None
            )
            token_source = next(
                (v for v in cfg["token_env_vars"] if os.getenv(v)), None
            )
            if not refresh_token:
                print(f"  SKIP: none of {cfg['token_env_vars']} set in .env")
                print()
                continue
            try:
                market_token = get_access_token(refresh_token)
                print(f"  Token: {token_source}  OK")
            except Exception as exc:
                print(f"  Token: FAILED — {exc}")
                print()
                continue

            # --- Step 1: Catalog ---
            t_req = datetime.now(timezone.utc)
            catalog_data = search_catalog_items(
                base_url=base_url,
                access_token=market_token,
                asins=active_asins,
                marketplace_id=marketplace_id,
                included_data=["summaries"],
            )
            t_resp = datetime.now(timezone.utc)
            _log_call(market_code, "catalog/search (GET)", t_req, t_resp, catalog_data)
            catalog_path = os.path.join(probe_dir, f"{market_code}_catalog_{timestamp}.json")
            with open(catalog_path, "w", encoding="utf-8") as f:
                json.dump(catalog_data, f, indent=2)
            print(f"    saved: {catalog_path}")

            catalog_by_asin: dict[str, dict] = {}
            if "_error" not in catalog_data:
                for item in catalog_data.get("items") or []:
                    k = item.get("asin")
                    if k:
                        catalog_by_asin[k] = item
            print()

            # --- Step 2: Competitive pricing (rate-limit guard between markets) ---
            if market_idx > 0:
                print(f"  [rate limit] Waiting {PRICING_INTERMARKET_DELAY_S}s before pricing call ({market_code})...")
                time.sleep(PRICING_INTERMARKET_DELAY_S)

            t_req = datetime.now(timezone.utc)
            pricing_data = get_competitive_summary_batch(
                base_url=base_url,
                access_token=market_token,
                asins=active_asins,
                marketplace_id=marketplace_id,
            )
            t_resp = datetime.now(timezone.utc)
            _log_call(market_code, "pricing/competitiveSummary (POST batch)", t_req, t_resp, pricing_data)
            pricing_path = os.path.join(probe_dir, f"{market_code}_pricing_{timestamp}.json")
            with open(pricing_path, "w", encoding="utf-8") as f:
                json.dump(pricing_data, f, indent=2)
            print(f"    saved: {pricing_path}")

            pricing_by_asin = extract_pricing_by_asin(pricing_data)
            pricing_status_by_market[market_code] = str(
                (pricing_data.get("_meta") or {}).get("status") or pricing_data.get("_status", "?")
            )
            print()

            # --- Step 3: Fees per ASIN ---
            fees_by_asin: dict[str, dict] = {}
            for asin_idx, asin in enumerate(active_asins):
                if asin_idx > 0:
                    time.sleep(1)
                featured_price, featured_currency, feat_fulfillment, feat_condition = (
                    extract_featured_offer_price(pricing_by_asin.get(asin, {}))
                )
                if featured_price is not None:
                    listing_price = featured_price
                    fee_currency = featured_currency or fallback_currency
                    price_label = (
                        f"REAL  {listing_price} {fee_currency}"
                        f"  fulfillment={feat_fulfillment}  condition={feat_condition}"
                    )
                else:
                    listing_price = fallback_price
                    fee_currency = fallback_currency
                    price_label = f"FALLBACK  {fallback_price} {fallback_currency}  (no featured offer)"

                t_req = datetime.now(timezone.utc)
                fee_resp = get_fees_estimate(
                    base_url=base_url,
                    access_token=market_token,
                    asin=asin,
                    marketplace_id=marketplace_id,
                    listing_price=listing_price,
                    currency_code=fee_currency,
                )
                t_resp = datetime.now(timezone.utc)
                fees_by_asin[asin] = fee_resp
                _log_call(market_code, f"fees/estimate {asin} @ {listing_price} {fee_currency} {price_label}",
                          t_req, t_resp, fee_resp)

            fees_path = os.path.join(probe_dir, f"{market_code}_fees_{timestamp}.json")
            with open(fees_path, "w", encoding="utf-8") as f:
                json.dump(fees_by_asin, f, indent=2)
            print(f"    saved: {fees_path}")
            print()

            # --- Collect rows for comparison table ---
            catalog_meta = (catalog_data.get("_meta") or {})
            pricing_meta = (pricing_data.get("_meta") or {})

            for asin in active_asins:
                cat_item = catalog_by_asin.get(asin, {})
                summaries = cat_item.get("summaries") or []
                summary = next(
                    (s for s in summaries if s.get("marketplaceId") == marketplace_id),
                    summaries[0] if summaries else {},
                )
                classification = (summary.get("browseClassification") or {}).get("displayName", "")

                feat_price, feat_curr, _, _ = extract_featured_offer_price(pricing_by_asin.get(asin, {}))
                fee_data = extract_fee_amounts(fees_by_asin.get(asin, {}))

                ref_pct = None
                lp_for_pct = feat_price
                if lp_for_pct is None:
                    lp_for_pct = fallback_price
                if fee_data["referral_fee"] is not None and lp_for_pct:
                    ref_pct = (fee_data["referral_fee"] / lp_for_pct) * 100

                pricing_http = (pricing_data.get("_meta") or {}).get("status") or pricing_data.get("_status", "?")
                fees_http = (fees_by_asin.get(asin, {}).get("_meta") or {}).get("status") or \
                            fees_by_asin.get(asin, {}).get("_status", "?")

                all_rows.append({
                    "market": market_code,
                    "asin": asin,
                    "title": summary.get("itemName", "")[:35],
                    "brand": summary.get("brand", "")[:15],
                    "classification": classification[:18],
                    "pricing_http": pricing_http,
                    "featured_price": f"{feat_price} {feat_curr}" if feat_price else "-",
                    "fees_http": fees_http,
                    "referral_fee": fee_data["referral_fee"],
                    "referral_pct": f"{ref_pct:.1f}%" if ref_pct is not None else "-",
                    "fba_fee": fee_data["fba_fee"],
                    "currency": fee_data["currency"] or fallback_currency,
                    "catalog_rid": catalog_meta.get("request_id", "?")[-8:] if catalog_meta.get("request_id") else "?",
                    "pricing_rid": pricing_meta.get("request_id", "?")[-8:] if pricing_meta.get("request_id") else "?",
                    "fees_rid": ((fees_by_asin.get(asin, {}).get("_meta") or {}).get("request_id") or "?")[-8:],
                })

        # --- Final comparison table ---
        print()
        print("=" * 120)
        print("CROSS-MARKET COMPARISON TABLE")
        print("=" * 120)
        hdr = (f"{'MKT':<4} {'ASIN':<12} {'TITLE':<36} {'BRAND':<16} {'CATEGORY':<19} "
               f"{'P-HTTP':<7} {'FEAT.PRICE':<14} {'F-HTTP':<7} "
               f"{'REF.FEE':<9} {'REF%':<8} {'FBA.FEE':<9} {'CURR':<5} "
               f"{'CAT-RID':<9} {'PRC-RID':<9} {'FEE-RID':<9}")
        print(hdr)
        print("-" * 120)
        for row in all_rows:
            ref_fee_str = f"{row['referral_fee']:.2f}" if row['referral_fee'] is not None else "-"
            fba_fee_str = f"{row['fba_fee']:.2f}" if row['fba_fee'] is not None else "-"
            print(
                f"{row['market']:<4} {row['asin']:<12} {row['title']:<36} {row['brand']:<16} "
                f"{row['classification']:<19} {str(row['pricing_http']):<7} {row['featured_price']:<14} "
                f"{str(row['fees_http']):<7} {ref_fee_str:<9} {row['referral_pct']:<8} "
                f"{fba_fee_str:<9} {row['currency']:<5} "
                f"{row['catalog_rid']:<9} {row['pricing_rid']:<9} {row['fees_rid']:<9}"
            )

        # --- End-of-probe summary ---
        from collections import defaultdict
        tested_markets = list(dict.fromkeys(r["market"] for r in all_rows))
        total_combos = len(all_rows)
        catalog_success = sum(1 for r in all_rows if r["title"])
        fees_ok = sum(1 for r in all_rows if r["fees_http"] == 200)
        asins_missing_fba = sorted({r["asin"] for r in all_rows if r["fba_fee"] is None})
        asins_missing_ref = sorted({r["asin"] for r in all_rows if r["referral_fee"] is None})

        ref_pcts_by_market: dict = defaultdict(set)
        fba_fees_by_market: dict = defaultdict(set)
        for r in all_rows:
            if r["referral_pct"] != "-":
                ref_pcts_by_market[r["market"]].add(r["referral_pct"])
            if r["fba_fee"] is not None:
                fba_fees_by_market[r["market"]].add(round(r["fba_fee"], 2))

        print()
        print("=" * 80)
        print("END-OF-PROBE SUMMARY")
        print("=" * 80)
        print(f"Markets run                   : {tested_markets}")
        print(f"ASINs per market              : {len(active_asins)}")
        print(f"Total ASIN-market combos      : {total_combos}")
        print(f"Catalog found                 : {catalog_success}/{total_combos}")
        print(f"Fees success (HTTP 200)        : {fees_ok}/{total_combos}  fail={total_combos - fees_ok}")
        print()
        print("Pricing HTTP status by market:")
        for mkt, status in pricing_status_by_market.items():
            print(f"  {mkt}: HTTP {status}")
        print()
        print(f"ASINs with missing FBA fee     ({len(asins_missing_fba)}): "
              f"{asins_missing_fba if asins_missing_fba else 'none'}")
        print(f"ASINs with missing referral fee ({len(asins_missing_ref)}): "
              f"{asins_missing_ref if asins_missing_ref else 'none'}")
        print()
        print("Distinct referral fee % by market (derived estimate — not official schedule):")
        for mkt in tested_markets:
            pcts = sorted(ref_pcts_by_market.get(mkt, set()))
            print(f"  {mkt}: {pcts if pcts else 'no data'}")
        print()
        print("Distinct FBA fee values by market:")
        for mkt in tested_markets:
            fees_set = sorted(fba_fees_by_market.get(mkt, set()))
            print(f"  {mkt}: {fees_set if fees_set else 'no data'}")

    elif args.command == "probe-pricing-access":
        import json
        import time
        import requests as _requests

        DIAGNOSTIC_ASIN = "B003K71VDK"
        INTER_REQUEST_DELAY_S = 37
        INCLUDED_DATA = ["featuredBuyingOptions", "lowestPricedOffers", "referencePrices"]
        BATCH_PATH = "/batches/products/pricing/2022-05-01/items/competitiveSummary"

        PRICING_MARKETS = {
            "AU": {
                "marketplace_id": "A39IBJ37TRP1C6",
                "base_url": "https://sellingpartnerapi-fe.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_AU", "SPAPI_REFRESH_TOKEN_FE"],
            },
            "UK": {
                "marketplace_id": "A1F83G8C2ARO7P",
                "base_url": "https://sellingpartnerapi-eu.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_EU"],
            },
            "CA": {
                "marketplace_id": "A2EUQ1WTGCTBG2",
                "base_url": "https://sellingpartnerapi-na.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_NA"],
            },
        }

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "pricing_access_probe")
        os.makedirs(probe_dir, exist_ok=True)
        timestamp = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"

        print("=== Product Pricing competitiveSummary A/B/C diagnostics ===")
        print(f"ASIN      : {DIAGNOSTIC_ASIN}")
        print(f"Markets   : {list(PRICING_MARKETS.keys())}")
        print(f"Endpoint  : POST {BATCH_PATH}")
        print(f"Formats   : FORMAT_A (flat), FORMAT_B (nested method/uri), FORMAT_C (ASIN in path) if B fails")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print(f"Timestamp : {timestamp}Z")
        print(f"Delay     : {INTER_REQUEST_DELAY_S}s between every pricing request")
        print()

        request_count = [0]

        def _build_body(fmt: str, marketplace_id: str) -> dict:
            if fmt == "FORMAT_A":
                return {
                    "requests": [{
                        "asin": DIAGNOSTIC_ASIN,
                        "marketplaceId": marketplace_id,
                        "includedData": INCLUDED_DATA,
                    }]
                }
            if fmt == "FORMAT_B":
                return {
                    "requests": [{
                        "method": "GET",
                        "uri": "/products/pricing/2022-05-01/items/competitiveSummary",
                        "marketplaceId": marketplace_id,
                        "asin": DIAGNOSTIC_ASIN,
                        "includedData": INCLUDED_DATA,
                    }]
                }
            # FORMAT_C: ASIN embedded in the item-level URI
            return {
                "requests": [{
                    "method": "GET",
                    "uri": f"/products/pricing/2022-05-01/items/{DIAGNOSTIC_ASIN}/competitiveSummary",
                    "marketplaceId": marketplace_id,
                    "includedData": INCLUDED_DATA,
                }]
            }

        def _probe_one(
            market_code: str, marketplace_id: str, base_url: str,
            token_source: str, access_token: str, fmt: str,
        ) -> dict:
            if request_count[0] > 0:
                print(f"  [rate limit] Waiting {INTER_REQUEST_DELAY_S}s before next request...")
                time.sleep(INTER_REQUEST_DELAY_S)
            request_count[0] += 1

            body = _build_body(fmt, marketplace_id)
            endpoint_url = f"{base_url}{BATCH_PATH}"
            req_headers = {
                "Authorization": f"Bearer {access_token}",
                "x-amz-access-token": access_token,
                "Content-Type": "application/json",
            }

            t_req = datetime.now(timezone.utc)
            response = _requests.post(endpoint_url, headers=req_headers, json=body)
            t_resp = datetime.now(timezone.utc)

            request_id = response.headers.get("x-amzn-RequestId", "n/a")
            rate_limit = response.headers.get("x-amzn-RateLimit-Limit", "n/a")
            latency_s = (t_resp - t_req).total_seconds()

            try:
                raw_json = response.json()
            except Exception:
                raw_json = {"_raw_text": response.text[:2000]}

            inner_status = None
            inner_body_keys = None
            error_body = None
            is_invalid_uri = False

            if response.ok:
                responses = raw_json.get("responses") or []
                if responses:
                    first = responses[0]
                    inner_status = (first.get("status") or {}).get("statusCode")
                    inner_body = first.get("body") or {}
                    inner_body_keys = [k for k in inner_body.keys() if not k.startswith("_")]
                    if inner_body.get("errors"):
                        for e in inner_body["errors"]:
                            if (e.get("code") or "").upper() == "INVALID_URI":
                                is_invalid_uri = True
                        error_body = inner_body["errors"]
            else:
                errors = raw_json.get("errors") or []
                error_body = errors or raw_json
                for e in (errors or []):
                    if (e.get("code") or "").upper() == "INVALID_URI":
                        is_invalid_uri = True

            print(f"  [{market_code}] {fmt}")
            print(f"    token_env : {token_source}")
            print(f"    url       : {endpoint_url}")
            print(f"    req_utc   : {t_req.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z")
            print(f"    resp_utc  : {t_resp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z  latency={latency_s:.2f}s")
            print(f"    HTTP      : {response.status_code}")
            print(f"    RequestId : {request_id}")
            print(f"    RateLimit : {rate_limit}")
            top_keys = list(raw_json.keys()) if isinstance(raw_json, dict) else []
            print(f"    resp keys : {top_keys}")
            if inner_status is not None:
                print(f"    inner HTTP: {inner_status}")
            if inner_body_keys is not None:
                print(f"    inner keys: {inner_body_keys}")
            if error_body:
                print(f"    errors    : {json.dumps(error_body, separators=(',', ':'))}")

            # Sanitized JSON — tokens never written
            save_data = dict(raw_json) if isinstance(raw_json, dict) else {"_raw": raw_json}
            save_data["_diagnostic"] = {
                "market": market_code,
                "format": fmt,
                "marketplace_id": marketplace_id,
                "asin": DIAGNOSTIC_ASIN,
                "token_env": token_source,
                "endpoint_url": endpoint_url,
                "http_status": response.status_code,
                "request_id": request_id,
                "rate_limit": rate_limit,
                "req_utc": t_req.isoformat(),
                "resp_utc": t_resp.isoformat(),
                "latency_s": round(latency_s, 3),
                "inner_status": inner_status,
            }
            json_filename = f"{market_code}_{fmt}_pricing_access_{timestamp}.json"
            json_path = os.path.join(probe_dir, json_filename)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2)
            print(f"    json saved: {json_path}")

            # TXT diagnostic — redact Authorization and x-amz-access-token
            redacted_req_headers = {
                k: ("Bearer REDACTED" if k == "Authorization" else ("REDACTED" if k == "x-amz-access-token" else v))
                for k, v in req_headers.items()
            }
            resp_headers_dict = dict(response.headers)
            txt_lines = [
                f"=== {market_code} {fmt} ===",
                "",
                "=== REQUEST ===",
                f"URL: {endpoint_url}",
                "",
                "Request Headers:",
                *[f"  {k}: {v}" for k, v in redacted_req_headers.items()],
                "",
                "Request Body:",
                json.dumps(body, indent=2),
                "",
                "=== RESPONSE ===",
                f"req_utc : {t_req.isoformat()}",
                f"resp_utc: {t_resp.isoformat()}",
                f"latency : {latency_s:.3f}s",
                "",
                "Response Headers:",
                *[f"  {k}: {v}" for k, v in resp_headers_dict.items()],
                "",
                "Response Body:",
                json.dumps(raw_json, indent=2),
            ]
            txt_filename = f"{market_code}_{fmt}_pricing_access_{timestamp}.txt"
            txt_path = os.path.join(probe_dir, txt_filename)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(txt_lines))
            print(f"    txt saved : {txt_path}")
            print()

            return {
                "market": market_code,
                "format": fmt,
                "outer_http": response.status_code,
                "inner_status": inner_status,
                "request_id": request_id,
                "rate_limit": rate_limit,
                "is_invalid_uri": is_invalid_uri,
                "error_body": error_body,
            }

        result_rows = []

        for market_code, cfg in PRICING_MARKETS.items():
            print(f"{'=' * 60}")
            print(f"MARKET: {market_code}  marketplace_id={cfg['marketplace_id']}")
            print(f"{'=' * 60}")

            refresh_token = next((os.getenv(v) for v in cfg["token_env_vars"] if os.getenv(v)), None)
            token_source = next((v for v in cfg["token_env_vars"] if os.getenv(v)), None)
            if not refresh_token:
                print(f"  SKIP: none of {cfg['token_env_vars']} set in .env")
                print()
                continue

            try:
                mkt_token = get_access_token(refresh_token)
                print(f"  token: {token_source}  OK")
            except Exception as exc:
                print(f"  token: FAILED — {exc}")
                print()
                continue

            print()
            result_a = _probe_one(
                market_code, cfg["marketplace_id"], cfg["base_url"], token_source, mkt_token, "FORMAT_A"
            )
            result_rows.append(result_a)

            result_b = _probe_one(
                market_code, cfg["marketplace_id"], cfg["base_url"], token_source, mkt_token, "FORMAT_B"
            )
            result_rows.append(result_b)

            if result_b["is_invalid_uri"]:
                print(f"  FORMAT_B returned INVALID_URI — testing FORMAT_C")
                result_c = _probe_one(
                    market_code, cfg["marketplace_id"], cfg["base_url"], token_source, mkt_token, "FORMAT_C"
                )
                result_rows.append(result_c)

        # Result table
        print()
        print("=" * 115)
        print("RESULT TABLE")
        print("=" * 115)
        hdr = (
            f"{'MARKET':<7} {'FORMAT':<10} {'OUTER_HTTP':<11} {'INNER_STATUS':<13} "
            f"{'REQUEST_ID':<40} {'RATE_LIMIT':<12} RESULT"
        )
        print(hdr)
        print("-" * 115)
        for row in result_rows:
            outer = str(row["outer_http"])
            inner = str(row["inner_status"]) if row["inner_status"] is not None else "-"
            rid = row["request_id"]
            rl = str(row["rate_limit"])
            if row["outer_http"] == 200 and row["inner_status"] == 200:
                label = "SUCCESS"
            elif row["is_invalid_uri"]:
                label = "INVALID_URI"
            elif row["outer_http"] == 200 and row["inner_status"] is not None:
                label = f"INNER_{row['inner_status']}"
            elif row["outer_http"] == 429:
                label = "THROTTLED"
            elif row["outer_http"] == 403:
                label = "FORBIDDEN"
            elif row["outer_http"] == 400:
                label = "BAD_REQUEST"
            else:
                label = f"HTTP_{row['outer_http']}"
            print(f"{row['market']:<7} {row['format']:<10} {outer:<11} {inner:<13} {rid:<40} {rl:<12} {label}")

        # Analysis & recommendation
        print()
        print("=" * 80)
        print("ANALYSIS & NEXT RECOMMENDATION")
        print("=" * 80)
        success_rows = [r for r in result_rows if r["outer_http"] == 200 and r["inner_status"] == 200]
        if success_rows:
            working_formats = list(dict.fromkeys(r["format"] for r in success_rows))
            print(f"Working format(s): {working_formats}")
            print()
            for fmt in working_formats:
                markets_ok = [r["market"] for r in success_rows if r["format"] == fmt]
                print(f"  {fmt} succeeded for markets: {markets_ok}")
            print()
            print(f"RECOMMENDATION: Adopt {working_formats[0]} in get_competitive_summary_batch().")
        else:
            forbidden = [r for r in result_rows if r["outer_http"] == 403]
            throttled = [r for r in result_rows if r["outer_http"] == 429]
            invalid_uri = [r for r in result_rows if r["is_invalid_uri"]]
            outer_200 = [r for r in result_rows if r["outer_http"] == 200]
            tested_fmts = {r["format"] for r in result_rows}

            print("No format returned outer HTTP 200 + inner 200 for any market.")
            print()
            if forbidden:
                print(f"  HTTP 403 on {len(forbidden)} request(s).")
                print("  The SP-API application is missing the 'Product Pricing' role, or the refresh")
                print("  token does not belong to a seller account that has this ASIN in their catalog.")
                print("  ACTION: In Seller Central > Apps & Services > Develop Apps, grant 'Product Pricing'.")
            elif throttled:
                print(f"  HTTP 429 on {len(throttled)} request(s) — rate limited.")
                print("  ACTION: Increase delay between requests and retry.")
            elif invalid_uri:
                if "FORMAT_C" not in tested_fmts:
                    print(f"  INVALID_URI on {len(invalid_uri)} request(s). FORMAT_C was not triggered because")
                    print("  FORMAT_B did not set is_invalid_uri=True at the outer level. Retry manually with FORMAT_C.")
                else:
                    print(f"  INVALID_URI on {len(invalid_uri)} request(s) including FORMAT_C.")
                    print("  ACTION: Contact Amazon Support with the x-amzn-RequestId values below.")
            elif outer_200:
                inner_error_codes = {
                    e.get("code") for r in outer_200 for e in (r["error_body"] or []) if isinstance(e, dict)
                }
                print(f"  Outer HTTP 200 on {len(outer_200)} request(s) but inner status was not 200.")
                print(f"  Inner error codes observed: {inner_error_codes}")
                print("  ACTION: Review the .txt diagnostic files for the full inner error bodies.")
            else:
                print("  ACTION: Review the diagnostic files for details.")

            print()
            if result_rows:
                print("x-amzn-RequestId values for Amazon Support:")
                for r in result_rows:
                    print(f"  {r['market']} {r['format']}: {r['request_id']}")

        print()
        print(f"Files saved: {len(result_rows) * 2} ({len(result_rows)} JSON + {len(result_rows)} TXT)")
        print(f"Directory  : {os.path.abspath(probe_dir)}")


if __name__ == "__main__":
    main()
