import argparse
import os
from dotenv import load_dotenv
from auth.spapi_auth import get_access_token
from reports.report_requests import create_report, get_report_status, get_recent_done_report, EU_UK_MARKETPLACE_ID, REPORT_TYPE
from reports.report_downloads import get_report_document, download_report
from reports.report_parsers import parse_fba_inventory_report
from reports.report_exports import export_rows_to_jsonl
from logs.report_logger import log_report_created, log_status_checked, log_report_downloaded, log_fatal_status
from db.inventory_repository import insert_fba_inventory_snapshot_rows
from db.inventory_queries import print_inventory_summary

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
        choices=["create", "status", "document", "download", "parse", "export", "insert", "query", "ingest-local", "ingest-spapi"],
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
        inserted = insert_fba_inventory_snapshot_rows(
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
        export_rows_to_jsonl(rows, EXPORT_OUTPUT_PATH)
        inserted = insert_fba_inventory_snapshot_rows(
            rows=valid_rows,
            region="EU",
            marketplace_id=EU_UK_MARKETPLACE_ID,
            marketplace_code="UK",
            source_file=PARSE_FILE_PATH,
        )
        print(f"Inserted rows: {inserted}")
        print_inventory_summary()

    elif args.command == "ingest-spapi":
        import json
        import time

        POLL_DELAYS = [30, 45, 60, 90, 120]  # seconds before each poll attempt
        now_utc = datetime.now(timezone.utc)

        # --- Step 1: Check for a recent DONE report before creating a new one ---
        document_id = None
        found_report_id = None

        recent_24h = get_recent_done_report(
            EU_BASE_URL, access_token, REPORT_TYPE, EU_UK_MARKETPLACE_ID,
            created_since_iso=(now_utc - timedelta(hours=24)).isoformat(),
        )

        if recent_24h:
            document_id = recent_24h.get("reportDocumentId")
            found_report_id = recent_24h.get("reportId")
            print(f"Using existing DONE report from last 24h: reportId={found_report_id}")
        else:
            recent_48h = get_recent_done_report(
                EU_BASE_URL, access_token, REPORT_TYPE, EU_UK_MARKETPLACE_ID,
                created_since_iso=(now_utc - timedelta(hours=48)).isoformat(),
            )
            if recent_48h:
                document_id = recent_48h.get("reportDocumentId")
                found_report_id = recent_48h.get("reportId")
                print(
                    f"Using existing DONE report from last 48h; "
                    f"warning: older than preferred freshness: reportId={found_report_id}"
                )
            else:
                # --- Step 2: No recent DONE report — create one ---
                report_id = create_report(EU_BASE_URL, access_token, EU_UK_MARKETPLACE_ID, REPORT_TYPE)
                log_report_created("EU", EU_UK_MARKETPLACE_ID, REPORT_TYPE, report_id)
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

                        fatal = True
                        break

                if not done:
                    if not fatal:
                        print("Report did not complete within polling window; try again later.")
                    return

        # --- Step 3: Download / parse / export / insert / query ---
        if not document_id:
            print("No reportDocumentId available. Aborting.")
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

        inserted = insert_fba_inventory_snapshot_rows(
            rows=valid_rows,
            region="EU",
            marketplace_id=EU_UK_MARKETPLACE_ID,
            marketplace_code="UK",
            source_file=raw_path,
        )
        print(f"Inserted rows: {inserted}")
        print_inventory_summary()


if __name__ == "__main__":
    main()
