import argparse
import csv
import os
import sys
from dotenv import load_dotenv
from auth.spapi_auth import get_access_token
from reports.report_requests import create_report, get_report_status, get_recent_done_report, EU_UK_MARKETPLACE_ID, REPORT_TYPE
from reports.report_downloads import get_report_document, download_report
from reports.report_parsers import parse_fba_inventory_report
from reports.report_exports import export_rows_to_jsonl
from logs.report_logger import log_report_created, log_status_checked, log_report_downloaded, log_fatal_status, log_ingest_result
from db.inventory_repository import insert_fba_inventory_snapshot_rows
from db.keepau_price_fee_repository import insert_keepau_price_fee_probe_rows
from db.inventory_queries import print_inventory_summary
from db.keepau_queries import print_keepau_latest
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PARSE_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "fba_inventory_uk_20260424_000609.txt")
EXPORT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "fba_inventory_uk_cleaned.jsonl")
EXISTING_REPORT_ID = "2393624020567"
EXISTING_REPORT_DOCUMENT_ID = "amzn1.spdoc.1.4.eu.df8f719b-9c4a-4cdb-9ade-c350072af890.TPG5PTT1VZLV8.2651"

EU_BASE_URL = "https://sellingpartnerapi-eu.amazon.com"


def _load_probe_asins(path: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            asin = line.upper()
            if asin in seen:
                continue
            seen.add(asin)
            if len(asin) != 10:
                print(f"[warn] Skipping invalid ASIN (not 10 chars): {asin!r}")
                continue
            result.append(asin)
    return result


def main():
    parser = argparse.ArgumentParser(description="AtlasDB SP-API tool")
    parser.add_argument(
        "command",
        choices=["create", "status", "document", "download", "parse", "export", "insert", "query", "ingest-local", "ingest-spapi", "ingest-report", "export-sheets", "probe-keepau-catalog", "probe-catalog-marketplaces", "probe-keepau-catalog-search", "probe-keepau-pricing-fees", "probe-marketplace-pricing-fees", "probe-pricing-access", "keepau-latest"],
        help="Command to run",
    )
    parser.add_argument(
        "--marketplace",
        choices=["AU", "US", "CA", "UK", "DE"],
        default="AU",
        help="Marketplace code (default: AU)",
    )
    parser.add_argument(
        "--report",
        choices=["fba-inventory", "orders-30d", "all-listings", "stranded-inventory", "all"],
        default=None,
        help="Report type for ingest-report / export-sheets (use 'all' to run all 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print export plan without authenticating or writing to Sheets",
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

    elif args.command == "ingest-report":
        from reports.report_runner import run_report
        from config.report_types import REPORT_KEYS

        marketplace_code = args.marketplace
        report_arg = args.report

        if not report_arg:
            parser.error("--report is required for ingest-report")

        report_keys = REPORT_KEYS if report_arg == "all" else [report_arg]

        results = []
        for report_key in report_keys:
            print(f"\n{'=' * 60}")
            print(f"ingest-report  marketplace={marketplace_code}  report={report_key}")
            print(f"{'=' * 60}")
            try:
                result = run_report(marketplace_code, report_key)
            except Exception as exc:
                print(f"[{marketplace_code}/{report_key}] UNHANDLED ERROR: {exc}")
                results.append({
                    "marketplace": marketplace_code,
                    "report_key": report_key,
                    "status": "ERROR",
                    "error": str(exc),
                    "row_count": None,
                    "report_id": None,
                    "report_document_id": None,
                    "raw_path": None,
                    "jsonl_path": None,
                })
                continue

            results.append(result)
            print(f"  status     : {result['status']}")
            print(f"  report_id  : {result['report_id']}")
            print(f"  document   : {result['report_document_id']}")
            print(f"  raw        : {result['raw_path']}")
            print(f"  jsonl      : {result['jsonl_path']}")
            print(f"  rows       : {result['row_count']}")
            if result.get("error"):
                print(f"  error      : {result['error']}")

        print(f"\n{'=' * 60}")
        print("SUMMARY")
        print(f"{'=' * 60}")
        for r in results:
            rows_label = str(r.get("row_count")) if r.get("row_count") is not None else "-"
            print(f"  {r['marketplace']}/{r['report_key']}: {r['status']}  rows={rows_label}")
            if r.get("error"):
                print(f"    error: {r['error']}")

    elif args.command == "export-sheets":
        from exports.sheet_exporter import export_report
        from config.report_types import REPORT_KEYS

        marketplace_code = args.marketplace
        report_arg = args.report
        dry_run = args.dry_run

        if not report_arg:
            parser.error("--report is required for export-sheets")

        report_keys = REPORT_KEYS if report_arg == "all" else [report_arg]

        results = []
        for report_key in report_keys:
            print(f"\n{'=' * 60}")
            print(
                f"export-sheets  marketplace={marketplace_code}  "
                f"report={report_key}  dry_run={dry_run}"
            )
            print(f"{'=' * 60}")
            try:
                result = export_report(marketplace_code, report_key, dry_run=dry_run)
            except Exception as exc:
                print(f"  ERROR: {exc}")
                result = {
                    "report_key": report_key,
                    "status": "ERROR",
                    "error": str(exc),
                }
            results.append(result)

            status = result.get("status", "?")
            if status not in ("DRY_RUN",):
                print(f"  status : {status}")
                if result.get("error"):
                    print(f"  error  : {result['error']}")

        if len(results) > 1:
            print(f"\n{'=' * 60}")
            print("SUMMARY")
            print(f"{'=' * 60}")
            for r in results:
                rows_label = (
                    str(r.get("row_count")) if r.get("row_count") is not None else "-"
                )
                print(
                    f"  {marketplace_code}/{r.get('report_key', '?')}: "
                    f"{r.get('status', '?')}  rows={rows_label}"
                )
                if r.get("error"):
                    print(f"    error: {r['error']}")

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
        import uuid

        FEES_INTER_ASIN_DELAY_S = 2

        _marketplace_code = args.marketplace
        _PROBE_CONFIGS = {
            "AU": {
                "marketplace_id": "A39IBJ37TRP1C6",
                "base_url": "https://sellingpartnerapi-fe.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_AU", "SPAPI_REFRESH_TOKEN_FE"],
                "fallback_price": FALLBACK_PRICE_AUD,
                "fallback_currency": "AUD",
            },
            "US": {
                "marketplace_id": "ATVPDKIKX0DER",
                "base_url": "https://sellingpartnerapi-na.amazon.com",
                "token_env_vars": ["SPAPI_REFRESH_TOKEN_NA"],
                "fallback_price": 20.00,
                "fallback_currency": "USD",
            },
        }
        _cfg = _PROBE_CONFIGS[_marketplace_code]
        AU_MARKETPLACE_ID_PROBE = _cfg["marketplace_id"]
        AU_BASE_URL_PROBE = _cfg["base_url"]
        AU_TOKEN_ENV_VARS = _cfg["token_env_vars"]
        AU_FALLBACK_PRICE = _cfg["fallback_price"]
        AU_FALLBACK_CURRENCY = _cfg["fallback_currency"]

        _config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
        if _marketplace_code == "AU":
            _primary_asins_path = os.path.join(_config_dir, "probe_asins_au.txt")
            _fallback_asins_path = os.path.join(_config_dir, "keepau_probe_asins.txt")
            if os.path.exists(_primary_asins_path):
                _PROBE_ASINS_PATH = _primary_asins_path
            else:
                _PROBE_ASINS_PATH = _fallback_asins_path
                print(f"  [warn] probe_asins_au.txt not found — using fallback keepau_probe_asins.txt")
        else:
            _PROBE_ASINS_PATH = os.path.join(_config_dir, f"probe_asins_{_marketplace_code.lower()}.txt")
        AU_PROBE_ASINS = _load_probe_asins(_PROBE_ASINS_PATH)
        _probe_asins_file_used = os.path.abspath(_PROBE_ASINS_PATH)
        print(f"Loaded {len(AU_PROBE_ASINS)} ASINs from {_probe_asins_file_used}")

        probe_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "marketplace_probe")
        os.makedirs(probe_dir, exist_ok=True)
        probe_start_time = datetime.now(timezone.utc)
        observed_at_utc = probe_start_time
        timestamp = f"{observed_at_utc:%Y%m%d_%H%M%S}"
        run_id = str(uuid.uuid4())

        # ASIN validation — invalid ASINs are skipped, not passed to API
        import re as _re
        _ASIN_RE = _re.compile(r"^[A-Z0-9]{10}$")
        seen_asins: set[str] = set()
        duplicates_removed: list[str] = []
        invalid_asins: list[str] = []
        active_asins: list[str] = []
        for _raw in AU_PROBE_ASINS:
            _a = _raw.strip().upper()
            if _a in seen_asins:
                duplicates_removed.append(_a)
                continue
            seen_asins.add(_a)
            if not _ASIN_RE.match(_a):
                invalid_asins.append(_a)
                continue
            active_asins.append(_a)

        print(f"=== {_marketplace_code} Pricing + Fees probe ===")
        print(f"ASIN validation:")
        print(f"  Input              : {len(AU_PROBE_ASINS)}")
        print(f"  Duplicates removed : {len(duplicates_removed)}  {duplicates_removed if duplicates_removed else ''}")
        print(f"  Invalid skipped    : {len(invalid_asins)}  {invalid_asins if invalid_asins else ''}")
        print(f"  Active ASINs       : {len(active_asins)}")
        print(f"Market    : {_marketplace_code}  marketplace_id={AU_MARKETPLACE_ID_PROBE}")
        print(f"Output dir: {os.path.abspath(probe_dir)}")
        print(f"Timestamp : {timestamp}Z")
        print(f"Fees delay: {FEES_INTER_ASIN_DELAY_S}s between ASINs")
        print()
        if _marketplace_code == "US":
            print("=" * 70)
            print("WARNING: US mode is for known-answer validation only.")
            print("It does not validate AU marketplace coverage.")
            print("=" * 70)
            print()

        # Token
        au_refresh_token_probe = next(
            (os.getenv(v) for v in AU_TOKEN_ENV_VARS if os.getenv(v)), None
        )
        au_token_source_probe = next(
            (v for v in AU_TOKEN_ENV_VARS if os.getenv(v)), None
        )
        if not au_refresh_token_probe:
            raise RuntimeError(f"Set one of {AU_TOKEN_ENV_VARS} in .env for {_marketplace_code} marketplace")
        au_token_probe = get_access_token(au_refresh_token_probe)
        print(f"Token     : {au_token_source_probe}  OK")
        print()

        def _log_step(label: str, t_req, t_resp, result: dict) -> None:
            meta = result.get("_meta") or {}
            status = meta.get("status") or result.get("_status", "?")
            rid = meta.get("request_id") or result.get("_request_id", "n/a")
            rl = meta.get("rate_limit") or "n/a"
            latency = f"{(t_resp - t_req).total_seconds():.2f}s"
            print(f"  {label}")
            print(f"    req_utc : {t_req.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z")
            print(f"    resp_utc: {t_resp.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z  latency={latency}")
            print(f"    HTTP={status}  RequestId={rid}  RateLimit={rl}")
            if result.get("_retry_after"):
                print(f"    Retry-After: {result['_retry_after']}")
            if "_error" in result and result.get("_error") != "THROTTLED":
                snippet = result.get("_body") or result.get("_detail") or ""
                print(f"    error: {snippet[:200]}")

        def _extract_featured_full(asin_pricing: dict) -> dict:
            """Return all featured offer fields including sellerId."""
            for opt in asin_pricing.get("featuredBuyingOptions") or []:
                for seg in opt.get("segmentedFeaturedOffers") or []:
                    listing = seg.get("listingPrice") or {}
                    amount = listing.get("amount")
                    if amount is not None:
                        return {
                            "price": float(amount),
                            "currency": listing.get("currencyCode"),
                            "fulfillment_type": seg.get("fulfillmentType"),
                            "condition": seg.get("condition"),
                            "seller_id": seg.get("sellerId"),
                        }
            return {}

        def _extract_lowest_offer(asin_pricing: dict) -> dict:
            """Return the offer with the lowest listingPrice across all lowestPricedOffers groups."""
            best_amount = float("inf")
            best: dict = {}
            for group in asin_pricing.get("lowestPricedOffers") or []:
                for offer in group.get("offers") or []:
                    listing = offer.get("listingPrice") or {}
                    amount = listing.get("amount")
                    if amount is not None and amount < best_amount:
                        best_amount = amount
                        best = {
                            "price": float(amount),
                            "currency": listing.get("currencyCode"),
                            "seller_id": offer.get("sellerId"),
                        }
            return best

        def _extract_weight(cat_item: dict, mkt_id: str) -> dict:
            """Extract weight from catalog dimensions (package first, then item)."""
            dims_list = cat_item.get("dimensions") or []
            dims = next(
                (d for d in dims_list if d.get("marketplaceId") == mkt_id),
                dims_list[0] if dims_list else None,
            )
            if not dims:
                return {}
            for section in ("package", "item"):
                w = (dims.get(section) or {}).get("weight") or {}
                val = w.get("value")
                if val is not None:
                    unit = w.get("unit", "")
                    ul = unit.lower()
                    if "kilogram" in ul or ul == "kg":
                        grams = round(val * 1000, 1)
                    elif ul in ("gram", "grams", "g"):
                        grams = round(float(val), 1)
                    elif "pound" in ul or ul in ("lb", "lbs"):
                        grams = round(val * 453.592, 1)
                    elif "ounce" in ul or ul == "oz":
                        grams = round(val * 28.3495, 1)
                    else:
                        grams = None
                    return {"value": val, "unit": unit, "grams": grams, "section": section}
            return {}

        # --- Step 1: Catalog (summaries + dimensions) — batched, max 10 per call ---
        CATALOG_BATCH_SIZE = 10
        _CATALOG_BACKOFF_S = [5, 15, 30]
        print(f"--- Step 1: Catalog (summaries + dimensions, {CATALOG_BATCH_SIZE}/batch) ---")
        catalog_by_asin: dict[str, dict] = {}
        catalog_rid = "?"
        _catalog_batches = [
            active_asins[i:i + CATALOG_BATCH_SIZE]
            for i in range(0, len(active_asins), CATALOG_BATCH_SIZE)
        ]
        _catalog_raw_batches: list[dict] = []
        _catalog_retry_count = 0
        for _bidx, _batch in enumerate(_catalog_batches):
            _batch_data = None
            for _attempt in range(4):  # 1 original + 3 retries
                if _attempt > 0:
                    _ra = _batch_data.get("_retry_after") if _batch_data else None
                    try:
                        _cat_delay = int(float(_ra)) if _ra else _CATALOG_BACKOFF_S[_attempt - 1]
                    except (ValueError, TypeError):
                        _cat_delay = _CATALOG_BACKOFF_S[_attempt - 1]
                    print(f"      [catalog batch {_bidx + 1} retry {_attempt}/3 — waiting {_cat_delay}s]")
                    time.sleep(_cat_delay)
                    _catalog_retry_count += 1
                t_req = datetime.now(timezone.utc)
                _batch_data = search_catalog_items(
                    base_url=AU_BASE_URL_PROBE,
                    access_token=au_token_probe,
                    asins=_batch,
                    marketplace_id=AU_MARKETPLACE_ID_PROBE,
                    included_data=["summaries", "dimensions"],
                )
                t_resp = datetime.now(timezone.utc)
                _log_step(
                    f"catalog/search batch {_bidx + 1}/{len(_catalog_batches)} ({len(_batch)} ASINs)"
                    + (f" [attempt {_attempt + 1}]" if _attempt > 0 else ""),
                    t_req, t_resp, _batch_data,
                )
                if _batch_data.get("_error") != "THROTTLED":
                    break
            _catalog_raw_batches.append(_batch_data)
            if "_error" not in _batch_data:
                if catalog_rid == "?":
                    catalog_rid = (_batch_data.get("_meta") or {}).get("request_id") or "?"
                for _item in _batch_data.get("items") or []:
                    _k = _item.get("asin")
                    if _k:
                        catalog_by_asin[_k] = _item
        catalog_path = os.path.join(probe_dir, f"{_marketplace_code}_catalog_{timestamp}.json")
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump({"batches": _catalog_raw_batches}, f, indent=2)
        print(f"    saved: {catalog_path}")
        print(f"    catalog items found: {len(catalog_by_asin)}/{len(active_asins)}")
        print()

        # --- Step 2: Competitive pricing (batched ≤20/call — API hard limit) ---
        PRICING_BATCH_SIZE = 20
        PRICING_INTER_BATCH_DELAY_S = 2
        _PRICING_BACKOFF_S = [10, 30, 60]
        _pricing_batches = [
            active_asins[i:i + PRICING_BATCH_SIZE]
            for i in range(0, len(active_asins), PRICING_BATCH_SIZE)
        ]
        print(f"--- Step 2: Competitive pricing ({PRICING_BATCH_SIZE}/batch, {len(_pricing_batches)} batch(es)) ---")
        pricing_by_asin: dict[str, dict] = {}
        pricing_failed_asins: set[str] = set()
        pricing_http: str = "?"
        pricing_rid: str = "?"
        _pricing_raw_batches: list[dict] = []
        _pricing_retry_count = 0
        for _pidx, _pbatch in enumerate(_pricing_batches):
            if _pidx > 0:
                time.sleep(PRICING_INTER_BATCH_DELAY_S)
            _pricing_resp = None
            for _attempt in range(4):  # 1 original + 3 retries
                if _attempt > 0:
                    _ra = _pricing_resp.get("_retry_after") if _pricing_resp else None
                    try:
                        _pr_delay = int(float(_ra)) if _ra else _PRICING_BACKOFF_S[_attempt - 1]
                    except (ValueError, TypeError):
                        _pr_delay = _PRICING_BACKOFF_S[_attempt - 1]
                    print(f"      [pricing batch {_pidx + 1} retry {_attempt}/3 — waiting {_pr_delay}s]")
                    time.sleep(_pr_delay)
                    _pricing_retry_count += 1
                t_req = datetime.now(timezone.utc)
                _pricing_resp = get_competitive_summary_batch(
                    base_url=AU_BASE_URL_PROBE,
                    access_token=au_token_probe,
                    asins=_pbatch,
                    marketplace_id=AU_MARKETPLACE_ID_PROBE,
                )
                t_resp = datetime.now(timezone.utc)
                _log_step(
                    f"pricing batch {_pidx + 1}/{len(_pricing_batches)} ({len(_pbatch)} ASINs)"
                    + (f" [attempt {_attempt + 1}]" if _attempt > 0 else ""),
                    t_req, t_resp, _pricing_resp,
                )
                if _pricing_resp.get("_error") != "THROTTLED":
                    break
            _pricing_raw_batches.append(_pricing_resp)
            _pmeta = _pricing_resp.get("_meta") or {}
            if "_error" not in _pricing_resp:
                if pricing_http == "?":
                    pricing_http = str(_pmeta.get("status", "?"))
                if pricing_rid == "?":
                    pricing_rid = _pmeta.get("request_id") or "?"
                pricing_by_asin.update(extract_pricing_by_asin(_pricing_resp))
            else:
                if pricing_http == "?":
                    pricing_http = str(_pmeta.get("status") or _pricing_resp.get("_status", "?"))
                for _fa in _pbatch:
                    pricing_failed_asins.add(_fa)
                print(f"      [pricing batch {_pidx + 1} FAILED after retries — {len(_pbatch)} ASINs marked PRICING_FAILED]")
        pricing_path = os.path.join(probe_dir, f"{_marketplace_code}_pricing_{timestamp}.json")
        with open(pricing_path, "w", encoding="utf-8") as f:
            json.dump({"batches": _pricing_raw_batches}, f, indent=2)
        print(f"    saved: {pricing_path}")
        print(f"    pricing items found: {len(pricing_by_asin)}/{len(active_asins)}")
        print()

        # --- Step 3: Fees per ASIN (2s between calls) ---
        print("--- Step 3: Fees estimates ---")
        fees_by_asin: dict[str, dict] = {}
        prices_used: dict[str, tuple] = {}
        for _asin_idx, _asin in enumerate(active_asins):
            if _asin_idx > 0:
                time.sleep(FEES_INTER_ASIN_DELAY_S)
            _feat = _extract_featured_full(pricing_by_asin.get(_asin, {}))
            if _feat:
                _listing_price = _feat["price"]
                _fee_currency = _feat["currency"] or AU_FALLBACK_CURRENCY
                _price_src = "REAL"
            elif _asin in pricing_failed_asins:
                _listing_price = AU_FALLBACK_PRICE
                _fee_currency = AU_FALLBACK_CURRENCY
                _price_src = "PRICING_FAILED"
            else:
                _listing_price = AU_FALLBACK_PRICE
                _fee_currency = AU_FALLBACK_CURRENCY
                _price_src = "NO_OFFER"
            prices_used[_asin] = (_listing_price, _fee_currency, _price_src)
            t_req = datetime.now(timezone.utc)
            _fee_resp = get_fees_estimate(
                base_url=AU_BASE_URL_PROBE,
                access_token=au_token_probe,
                asin=_asin,
                marketplace_id=AU_MARKETPLACE_ID_PROBE,
                listing_price=_listing_price,
                currency_code=_fee_currency,
            )
            t_resp = datetime.now(timezone.utc)
            fees_by_asin[_asin] = _fee_resp
            _log_step(
                f"fees/estimate {_asin} @ {_listing_price} {_fee_currency} [{_price_src}]",
                t_req, t_resp, _fee_resp,
            )
        fees_path = os.path.join(probe_dir, f"{_marketplace_code}_fees_{timestamp}.json")
        with open(fees_path, "w", encoding="utf-8") as f:
            json.dump(fees_by_asin, f, indent=2)
        print(f"    saved: {fees_path}")
        print()

        # --- Collect rows ---
        all_rows: list[dict] = []
        for asin in active_asins:
            cat_item = catalog_by_asin.get(asin, {})
            summaries = cat_item.get("summaries") or []
            summary = next(
                (s for s in summaries if s.get("marketplaceId") == AU_MARKETPLACE_ID_PROBE),
                summaries[0] if summaries else {},
            )
            feat = _extract_featured_full(pricing_by_asin.get(asin, {}))
            lowest = _extract_lowest_offer(pricing_by_asin.get(asin, {}))
            weight = _extract_weight(cat_item, AU_MARKETPLACE_ID_PROBE)
            fee_data = extract_fee_amounts(fees_by_asin.get(asin, {}))
            listing_price, fee_currency, price_src = prices_used.get(
                asin, (AU_FALLBACK_PRICE, AU_FALLBACK_CURRENCY, "FALLBACK")
            )
            ref_pct = None
            if fee_data["referral_fee"] is not None and listing_price and listing_price > 0:
                ref_pct = (fee_data["referral_fee"] / listing_price) * 100
            fees_rid = ((fees_by_asin.get(asin, {}).get("_meta") or {}).get("request_id") or "?")
            all_rows.append({
                "asin": asin,
                "title": summary.get("itemName", ""),
                "brand": summary.get("brand", ""),
                "feat_price": feat.get("price"),
                "feat_currency": feat.get("currency"),
                "feat_seller": feat.get("seller_id"),
                "currency": feat.get("currency") or fee_currency,
                "fulfillment": feat.get("fulfillment_type"),
                "condition": feat.get("condition"),
                "low_price": lowest.get("price"),
                "low_currency": lowest.get("currency"),
                "low_seller": lowest.get("seller_id"),
                "referral_fee": fee_data["referral_fee"],
                "referral_pct": ref_pct,
                "fba_fee": fee_data["fba_fee"],
                "weight_val": weight.get("value"),
                "weight_unit": weight.get("unit"),
                "weight_grams": weight.get("grams"),
                "price_src": price_src,
                "catalog_rid": catalog_rid[-8:] if catalog_rid != "?" else "?",
                "pricing_rid": pricing_rid[-8:] if pricing_rid != "?" else "?",
                "fees_rid": fees_rid[-8:] if fees_rid != "?" else "?",
                "catalog_rid_full": catalog_rid if catalog_rid != "?" else None,
                "pricing_rid_full": pricing_rid if pricing_rid != "?" else None,
                "fees_rid_full": fees_rid if fees_rid != "?" else None,
            })

        # --- Compact two-line-per-ASIN table ---
        def _p(v, fmt=".2f", fallback="not returned"):
            return format(v, fmt) if v is not None else fallback

        def _s(v, width=0, fallback="not returned"):
            out = str(v) if v is not None else fallback
            return out[:width] if width else out

        def _pct(v):
            return f"{v:.1f}%" if v is not None else "-"

        print()
        print("=" * 110)
        print(f"{_marketplace_code} PRICING + FEES — compact table (2 lines per ASIN)")
        print("=" * 110)
        h1 = (f"{'ASIN':<12} {'TITLE':<30} {'BRAND':<13} {'FEAT.PRICE':>10} "
              f"{'FEAT.SELLER':<14} {'CURR':<5} {'FUL':<4} {'CND':<4} {'SRC':<8}")
        h2 = (f"{'':12} {'LOW.PRICE':>10} {'LOW.SELLER':<14} {'REF.FEE':>8} {'REF%':>6} "
              f"{'FBA':>8} {'C-RID':<10} {'P-RID':<10} {'F-RID':<10}")
        print(h1)
        print(h2)
        print("-" * 110)
        for row in all_rows:
            feat_price_s = _p(row["feat_price"])
            feat_seller_s = _s(row["feat_seller"], 14)
            low_price_s = _p(row["low_price"])
            low_seller_s = _s(row["low_seller"], 14)
            ref_fee_s = _p(row["referral_fee"])
            fba_s = _p(row["fba_fee"])
            print(
                f"{row['asin']:<12} {row['title'][:30]:<30} {row['brand'][:13]:<13} {feat_price_s:>10} "
                f"{feat_seller_s:<14} {row['currency']:<5} "
                f"{_s(row['fulfillment'],4):<4} {_s(row['condition'],4):<4} {row['price_src']:<8}"
            )
            print(
                f"{'':12} {low_price_s:>10} {low_seller_s:<14} {ref_fee_s:>8} {_pct(row['referral_pct']):>6} "
                f"{fba_s:>8} {row['catalog_rid']:<10} {row['pricing_rid']:<10} {row['fees_rid']:<10}"
            )
        print("=" * 110)

        # --- End-of-probe summary ---
        n = len(active_asins)
        catalog_found = len(catalog_by_asin)
        real_count = sum(1 for r in all_rows if r["price_src"] == "REAL")
        no_offer_count = sum(1 for r in all_rows if r["price_src"] == "NO_OFFER")
        pricing_failed_count = sum(1 for r in all_rows if r["price_src"] == "PRICING_FAILED")
        fallback_count = no_offer_count + pricing_failed_count
        feat_seller_count = sum(1 for r in all_rows if r["feat_seller"] is not None)
        low_price_count = sum(1 for r in all_rows if r["low_price"] is not None)
        low_seller_count = sum(1 for r in all_rows if r["low_seller"] is not None)
        fees_ok = sum(
            1 for a in active_asins
            if (fees_by_asin.get(a, {}).get("_meta") or {}).get("status") == 200
        )
        fees_status_counts: dict[str, int] = {}
        for _a in active_asins:
            _fee_resp = fees_by_asin.get(_a, {})
            if "_error" in _fee_resp:
                _st = "HTTP_ERROR"
            else:
                _payload = _fee_resp.get("payload") or {}
                _result_obj = _payload.get("FeesEstimateResult") or {}
                _st = _result_obj.get("Status") or "NO_PAYLOAD"
            fees_status_counts[_st] = fees_status_counts.get(_st, 0) + 1
        ref_fee_count = sum(1 for r in all_rows if r["referral_fee"] is not None)
        fba_count = sum(1 for r in all_rows if r["fba_fee"] is not None)

        inserted = insert_keepau_price_fee_probe_rows(
            rows=all_rows,
            raw_paths={"catalog": catalog_path, "pricing": pricing_path, "fees": fees_path},
            run_id=run_id,
            observed_at=observed_at_utc,
            marketplace_id=AU_MARKETPLACE_ID_PROBE,
        )
        runtime_s = (datetime.now(timezone.utc) - probe_start_time).total_seconds()

        if n > 0 and pricing_failed_count / n > 0.25:
            print()
            print("=" * 70)
            print("WARNING: This run is NOT suitable for price validation.")
            print(f"Pricing API failed/throttled for {pricing_failed_count}/{n} ASINs "
                  f"({pricing_failed_count / n:.0%}).")
            print("=" * 70)

        # --- Failure / missing-data CSV ---
        _failures_dir = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "probe_failures")
        os.makedirs(_failures_dir, exist_ok=True)
        _fail_csv_filename = f"probe_failures_{_marketplace_code}_{timestamp}.csv"
        _fail_csv_path = os.path.join(_failures_dir, _fail_csv_filename)
        _fail_fields = [
            "run_id", "observed_at", "marketplace_code", "marketplace_id", "asin",
            "catalog_found", "pricing_found", "used_fallback_price", "pricing_status",
            "missing_featured_price", "missing_featured_seller_id",
            "missing_lowest_price", "missing_lowest_seller_id",
            "missing_referral_fee", "missing_fba_fee",
            "fee_status", "fee_error_message",
            "raw_catalog_path", "raw_pricing_path", "raw_fees_path",
            "missing_bsr", "bsr_source", "bsr_error_message",
        ]
        _fail_rows_written = 0
        with open(_fail_csv_path, "w", newline="", encoding="utf-8") as _ff:
            _fail_writer = csv.DictWriter(_ff, fieldnames=_fail_fields)
            _fail_writer.writeheader()
            for _row in all_rows:
                _used_fallback = _row.get("price_src") == "FALLBACK"
                _miss_feat_price = _row.get("feat_price") is None
                _miss_feat_seller = _row.get("feat_seller") is None
                _miss_low_price = _row.get("low_price") is None
                _miss_low_seller = _row.get("low_seller") is None
                _miss_ref_fee = _row.get("referral_fee") is None
                _miss_fba = _row.get("fba_fee") is None
                if not any([_used_fallback, _miss_feat_price, _miss_feat_seller,
                            _miss_low_price, _miss_low_seller, _miss_ref_fee, _miss_fba]):
                    continue
                _cat_found = _row["asin"] in catalog_by_asin
                _fee_r2 = fees_by_asin.get(_row["asin"], {})
                if "_error" in _fee_r2:
                    _fail_fee_status = _fee_r2.get("_error", "HTTP_ERROR")
                    _fail_fee_err = (_fee_r2.get("_body") or "")[:200]
                else:
                    _f2_result = (_fee_r2.get("payload") or {}).get("FeesEstimateResult") or {}
                    _fail_fee_status = _f2_result.get("Status") or "NO_PAYLOAD"
                    _f2_err = _f2_result.get("Error") or {}
                    _fail_fee_err = _f2_err.get("Message", "") if isinstance(_f2_err, dict) else str(_f2_err)
                _fail_writer.writerow({
                    "run_id": run_id,
                    "observed_at": observed_at_utc.isoformat(),
                    "marketplace_code": _marketplace_code,
                    "marketplace_id": AU_MARKETPLACE_ID_PROBE,
                    "asin": _row["asin"],
                    "catalog_found": "TRUE" if _cat_found else "FALSE",
                    "pricing_found": "FALSE" if _used_fallback else "TRUE",
                    "used_fallback_price": "TRUE" if _used_fallback else "FALSE",
                    "pricing_status": _row.get("price_src", ""),
                    "missing_featured_price": "TRUE" if _miss_feat_price else "FALSE",
                    "missing_featured_seller_id": "TRUE" if _miss_feat_seller else "FALSE",
                    "missing_lowest_price": "TRUE" if _miss_low_price else "FALSE",
                    "missing_lowest_seller_id": "TRUE" if _miss_low_seller else "FALSE",
                    "missing_referral_fee": "TRUE" if _miss_ref_fee else "FALSE",
                    "missing_fba_fee": "TRUE" if _miss_fba else "FALSE",
                    "fee_status": _fail_fee_status,
                    "fee_error_message": _fail_fee_err or "",
                    "raw_catalog_path": catalog_path,
                    "raw_pricing_path": pricing_path,
                    "raw_fees_path": fees_path,
                    "missing_bsr": "",
                    "bsr_source": "",
                    "bsr_error_message": "",
                })
                _fail_rows_written += 1

        print()
        print("=" * 70)
        print("END-OF-PROBE SUMMARY")
        print("=" * 70)
        print(f"Marketplace                   : {_marketplace_code}")
        print(f"Marketplace ID                : {AU_MARKETPLACE_ID_PROBE}")
        print(f"ASIN input file               : {_probe_asins_file_used}")
        print(f"Active ASINs                  : {n}  (invalid skipped: {len(invalid_asins)}  dupes: {len(duplicates_removed)})")
        print(f"Catalog 429 retries           : {_catalog_retry_count}")
        print(f"Pricing 429 retries           : {_pricing_retry_count}")
        print(f"Pricing HTTP                  : {pricing_http}")
        print(f"ASINs tested                  : {n}")
        print(f"Catalog items found           : {catalog_found}/{n}")
        print(f"Real featured prices          : {real_count}/{n}")
        print(f"Fallback (no offer)           : {no_offer_count}/{n}")
        print(f"Fallback (pricing failed)     : {pricing_failed_count}/{n}")
        print(f"Featured sellerIds returned   : {feat_seller_count}/{n}")
        print(f"Lowest offer prices returned  : {low_price_count}/{n}")
        print(f"Lowest offer sellerIds        : {low_seller_count}/{n}")
        print(f"Fees HTTP 200                 : {fees_ok}/{n}")
        _fees_success = fees_status_counts.get("Success", 0)
        _fees_server = fees_status_counts.get("ServerError", 0)
        _fees_client = fees_status_counts.get("ClientError", 0)
        _fees_other_total = sum(
            v for k, v in fees_status_counts.items()
            if k not in ("Success", "ServerError", "ClientError")
        )
        print(f"  FeesEstimate Success        : {_fees_success}/{n}")
        print(f"  FeesEstimate ServerError    : {_fees_server}/{n}")
        print(f"  FeesEstimate ClientError    : {_fees_client}/{n}")
        if _fees_other_total:
            _other_keys = [k for k in fees_status_counts
                           if k not in ("Success", "ServerError", "ClientError")]
            print(f"  FeesEstimate other          : {_fees_other_total}  {_other_keys}")
        print(f"Referral fee populated        : {ref_fee_count}/{n}")
        print(f"FBA fee populated             : {fba_count}/{n}")
        print(f"Total runtime                 : {runtime_s:.1f}s")
        print(f"Inserted rows                 : {inserted}  run_id={run_id}")
        print(f"Failure CSV                   : {os.path.abspath(_fail_csv_path)}  ({_fail_rows_written} rows)")
        print()
        print("Missing fields by ASIN:")
        _any_missing = False
        for row in all_rows:
            _missing = []
            if row["feat_price"] is None:
                _missing.append("featured_price")
            if row["feat_seller"] is None:
                _missing.append("feat_seller_id")
            if row["low_price"] is None:
                _missing.append("lowest_price")
            if row["low_seller"] is None:
                _missing.append("low_seller_id")
            if row["referral_fee"] is None:
                _missing.append("referral_fee")
            if row["fba_fee"] is None:
                _missing.append("fba_fee")
            if _missing:
                _any_missing = True
                print(f"  {row['asin']}: {', '.join(_missing)}")
        if not _any_missing:
            print("  (none — all fields present for all ASINs)")
        print()
        print(f"Raw files saved to: {os.path.abspath(probe_dir)}")
        print(f"  {catalog_path}")
        print(f"  {pricing_path}")
        print(f"  {fees_path}")

        # --- CSV validation export ---
        _validation_dir = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "validation")
        os.makedirs(_validation_dir, exist_ok=True)
        _csv_filename = f"{_marketplace_code.lower()}_price_fee_validation_{timestamp}.csv"
        _csv_path = os.path.join(_validation_dir, _csv_filename)
        _csv_fields = [
            "asin", "marketplace_code", "marketplace_id", "title", "brand",
            "featured_price", "featured_currency", "featured_seller_id",
            "lowest_offer_price", "lowest_offer_currency", "lowest_offer_seller_id",
            "referral_fee", "fba_fee", "fee_status", "fee_error_message",
            "pricing_status", "used_fallback_price", "observed_at", "ingestion_run_id",
        ]
        with open(_csv_path, "w", newline="", encoding="utf-8") as _f:
            _writer = csv.DictWriter(_f, fieldnames=_csv_fields)
            _writer.writeheader()
            for _row in all_rows:
                _fee_r = fees_by_asin.get(_row["asin"], {})
                if "_error" in _fee_r:
                    _fee_status = _fee_r.get("_error", "HTTP_ERROR")
                    _fee_err_msg = (_fee_r.get("_body") or "")[:200]
                else:
                    _f_result = (_fee_r.get("payload") or {}).get("FeesEstimateResult") or {}
                    _fee_status = _f_result.get("Status") or "NO_PAYLOAD"
                    _f_err = _f_result.get("Error") or {}
                    _fee_err_msg = _f_err.get("Message", "") if isinstance(_f_err, dict) else str(_f_err)
                _writer.writerow({
                    "asin": _row["asin"],
                    "marketplace_code": _marketplace_code,
                    "marketplace_id": AU_MARKETPLACE_ID_PROBE,
                    "title": _row.get("title") or "",
                    "brand": _row.get("brand") or "",
                    "featured_price": "" if _row.get("feat_price") is None else _row["feat_price"],
                    "featured_currency": _row.get("feat_currency") or "",
                    "featured_seller_id": _row.get("feat_seller") or "",
                    "lowest_offer_price": "" if _row.get("low_price") is None else _row["low_price"],
                    "lowest_offer_currency": _row.get("low_currency") or "",
                    "lowest_offer_seller_id": _row.get("low_seller") or "",
                    "referral_fee": "" if _row.get("referral_fee") is None else _row["referral_fee"],
                    "fba_fee": "" if _row.get("fba_fee") is None else _row["fba_fee"],
                    "fee_status": _fee_status,
                    "fee_error_message": _fee_err_msg or "",
                    "pricing_status": _row.get("price_src", ""),
                    "used_fallback_price": "FALSE" if _row.get("price_src") == "REAL" else "TRUE",
                    "observed_at": observed_at_utc.isoformat(),
                    "ingestion_run_id": run_id,
                })
        print(f"Validation CSV    : {os.path.abspath(_csv_path)}")

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

    elif args.command == "keepau-latest":
        print_keepau_latest()


if __name__ == "__main__":
    main()
