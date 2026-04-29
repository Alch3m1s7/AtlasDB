import json

import requests

# --- Marketplace constants ---

UK_MARKETPLACE_ID = "A1F83G8C2ARO7P"
UK_REGION = "EU"
UK_BASE_URL = "https://sellingpartnerapi-eu.amazon.com"

AU_MARKETPLACE_ID = "A39IBJ37TRP1C6"
AU_REGION = "FE"
AU_BASE_URL = "https://sellingpartnerapi-fe.amazon.com"

CA_MARKETPLACE_ID = "A2EUQ1WTGCTBG2"
CA_REGION = "NA"
CA_BASE_URL = "https://sellingpartnerapi-na.amazon.com"

# MVP probe ASIN list — 20 ASINs for cross-market Catalog + Fees testing
# Original 3-ASIN list: ["B09DPSM7GM", "B003K71VDK", "B01BTZTO24"]
PROBE_ASINS = [
    "B0DGVWT3M5",
    "B08TRMF51Z",
    "B082T3KPJP",
    "B08TRJCS51",
    "B08TRJT6BT",
    "B08TRJQBLF",
    "B01BTZTO24",
    "B0063G80FM",
    "B07CXQTC71",
    "B003K71VDK",
    "B07BL5NKXT",
    "B013SJO2JE",
    "B006ZZ7GV0",
    "B00LSQX0S4",
    "B07FTYT8XT",
    "B079G1HXGC",
    "B0BG91L162",
    "B08PG1C7LL",
    "B086DN2QQ6",
    "B08PG1FRBS",
]

# Cross-market probe config for probe-catalog-marketplaces
# token_env_vars: tried left-to-right; first non-empty value wins
PROBE_MARKETS = {
    "UK": {
        "marketplace_id": UK_MARKETPLACE_ID,
        "base_url": UK_BASE_URL,
        "token_env_vars": ["SPAPI_REFRESH_TOKEN_EU"],
        "asins": [
            "B09DPSM7GM",  
            "B0FFSGMM2H",
            "B01BTZTO24",  
        ],
    },
    "AU": {
        "marketplace_id": AU_MARKETPLACE_ID,
        "base_url": AU_BASE_URL,
        "token_env_vars": ["SPAPI_REFRESH_TOKEN_AU", "SPAPI_REFRESH_TOKEN_FE"],
        "asins": [
            "B09DPSM7GM",
            "B0FFSGMM2H",
            "B01BTZTO24",
        ],
    },
    "CA": {
        "marketplace_id": CA_MARKETPLACE_ID,
        "base_url": CA_BASE_URL,
        "token_env_vars": ["SPAPI_REFRESH_TOKEN_NA"],
        "asins": [
            "B09DPSM7GM",  
            "B0FFSGMM2H", 
            "B01BTZTO24", 
        ],
    },
}

_DEFAULT_INCLUDED_DATA = ["summaries", "attributes", "dimensions", "salesRanks"]


def get_catalog_item(
    base_url: str,
    access_token: str,
    asin: str,
    marketplace_id: str,
    included_data: list[str] | None = None,
) -> dict:
    if included_data is None:
        included_data = _DEFAULT_INCLUDED_DATA

    response = requests.get(
        f"{base_url}/catalog/2022-04-01/items/{asin}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
        },
        params=[("marketplaceIds", marketplace_id)] + [("includedData", d) for d in included_data],
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"  [catalog] GET {asin}  HTTP {response.status_code}  RequestId={request_id}")

    if response.status_code == 404:
        return {"_error": "NOT_FOUND", "_status": 404, "_asin": asin, "_request_id": request_id}

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        return {"_error": "THROTTLED", "_status": 429, "_asin": asin, "_retry_after": retry_after, "_request_id": request_id}

    if not response.ok:
        return {
            "_error": "HTTP_ERROR",
            "_status": response.status_code,
            "_asin": asin,
            "_body": response.text[:500],
            "_request_id": request_id,
        }

    try:
        return response.json()
    except Exception as exc:
        return {"_error": "JSON_PARSE_ERROR", "_asin": asin, "_detail": str(exc), "_body": response.text[:200]}


def search_catalog_items(
    base_url: str,
    access_token: str,
    asins: list[str],
    marketplace_id: str,
    included_data: list[str] | None = None,
) -> dict:
    if included_data is None:
        included_data = _DEFAULT_INCLUDED_DATA

    params = (
        [("identifiers", ",".join(asins)), ("identifiersType", "ASIN"), ("marketplaceIds", marketplace_id)]
        + [("includedData", d) for d in included_data]
    )

    response = requests.get(
        f"{base_url}/catalog/2022-04-01/items",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
        },
        params=params,
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"  [catalog/search] HTTP {response.status_code}  RequestId={request_id}")

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        return {"_error": "THROTTLED", "_status": 429, "_retry_after": retry_after, "_request_id": request_id}

    if not response.ok:
        return {
            "_error": "HTTP_ERROR",
            "_status": response.status_code,
            "_body": response.text[:500],
            "_request_id": request_id,
        }

    try:
        data = response.json()
        data["_meta"] = {
            "request_id": request_id,
            "status": response.status_code,
            "rate_limit": response.headers.get("x-amzn-RateLimit-Limit"),
        }
        return data
    except Exception as exc:
        return {"_error": "JSON_PARSE_ERROR", "_detail": str(exc), "_body": response.text[:200]}


def print_catalog_item_summary(asin: str, data: dict, marketplace_id: str) -> None:
    """Print a compact human-readable summary of a getCatalogItem response."""
    if "_error" in data:
        print(f"  Error: {data}")
        return

    summaries = data.get("summaries") or []
    summary = next(
        (s for s in summaries if s.get("marketplaceId") == marketplace_id),
        summaries[0] if summaries else {},
    )
    print(f"  title        : {summary.get('itemName', '(none)')}")
    print(f"  brand        : {summary.get('brand', '(none)')}")
    print(f"  product_type : {summary.get('productType', '(none)')}")
    classification = summary.get("browseClassification")
    if classification:
        print(f"  classification: {json.dumps(classification)}")

    sales_ranks = data.get("salesRanks") or []
    ranks = next(
        (r for r in sales_ranks if r.get("marketplaceId") == marketplace_id),
        sales_ranks[0] if sales_ranks else None,
    )
    if ranks:
        cr = ranks.get("classificationRanks") or []
        dg = ranks.get("displayGroupRanks") or []
        print(f"  classificationRanks ({len(cr)}):")
        for r in cr[:5]:
            print(f"    rank={r.get('rank')}  title={r.get('title')}  id={r.get('classificationId')}")
        print(f"  displayGroupRanks ({len(dg)}):")
        for r in dg[:5]:
            print(f"    rank={r.get('rank')}  title={r.get('title')}  group={r.get('websiteDisplayGroup')}")
    else:
        print("  salesRanks   : (none returned)")

    dimensions = data.get("dimensions") or []
    dims = next(
        (d for d in dimensions if d.get("marketplaceId") == marketplace_id),
        dimensions[0] if dimensions else None,
    )
    if dims:
        print(f"  dimensions   : {json.dumps(dims)}")
    else:
        print("  dimensions   : (none returned)")
