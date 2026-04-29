import requests

_COMPETITIVE_SUMMARY_INCLUDED_DATA = [
    "featuredBuyingOptions",
    "lowestPricedOffers",
    "referencePrices",
]


def get_competitive_summary_batch(
    base_url: str,
    access_token: str,
    asins: list[str],
    marketplace_id: str,
    included_data: list[str] | None = None,
) -> dict:
    if included_data is None:
        included_data = _COMPETITIVE_SUMMARY_INCLUDED_DATA

    body = {
        "requests": [
            {
                "uri": "/products/pricing/2022-05-01/items/competitiveSummary",
                "method": "GET",
                "asin": asin,
                "marketplaceId": marketplace_id,
                "includedData": included_data,
            }
            for asin in asins
        ]
    }

    response = requests.post(
        f"{base_url}/batches/products/pricing/2022-05-01/items/competitiveSummary",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
            "Content-Type": "application/json",
        },
        json=body,
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"  [pricing/competitive] POST batch({len(asins)})  HTTP {response.status_code}  RequestId={request_id}")

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        return {"_error": "THROTTLED", "_status": 429, "_retry_after": retry_after, "_request_id": request_id}

    if not response.ok:
        return {
            "_error": "HTTP_ERROR",
            "_status": response.status_code,
            "_body": response.text[:800],
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


def extract_pricing_by_asin(pricing_response: dict) -> dict[str, dict]:
    """Return a dict keyed by ASIN from a batch competitive summary response."""
    result: dict[str, dict] = {}
    if "_error" in pricing_response:
        return result
    for resp in pricing_response.get("responses") or []:
        if (resp.get("status") or {}).get("statusCode") != 200:
            continue
        body = resp.get("body") or {}
        asin = body.get("asin")
        if asin:
            result[asin] = body
    return result


def extract_featured_offer_price(
    asin_pricing: dict,
) -> tuple[float | None, str | None, str | None, str | None]:
    """Return (price, currency, fulfillment_type, condition) of the first featured Buy Box offer.

    The 2022-05-01 batch API returns segmentedFeaturedOffers with listingPrice
    directly on each offer segment, not nested under featuredOffer.price.listingPrice.
    """
    options = asin_pricing.get("featuredBuyingOptions") or []
    for opt in options:
        for seg in opt.get("segmentedFeaturedOffers") or []:
            listing = seg.get("listingPrice") or {}
            amount = listing.get("amount")
            currency = listing.get("currencyCode")
            if amount is not None:
                return float(amount), currency, seg.get("fulfillmentType"), seg.get("condition")
    return None, None, None, None


def print_pricing_summary(asin: str, asin_pricing: dict) -> None:
    if not asin_pricing:
        print(f"  pricing      : (no data for {asin})")
        return

    errors = asin_pricing.get("errors") or []
    if errors:
        print(f"  pricing errors: {errors}")

    options = asin_pricing.get("featuredBuyingOptions") or []
    if options:
        for opt in options:
            opt_type = opt.get("buyingOptionType", "?")
            print(f"  buyingOptionType : {opt_type}")
            for seg in (opt.get("segmentedFeaturedOffers") or [])[:3]:
                listing = seg.get("listingPrice") or {}
                print(f"  segmentedOffer   : condition={seg.get('condition')}  "
                      f"fulfillment={seg.get('fulfillmentType')}  "
                      f"sellerId={seg.get('sellerId')}")
                print(f"  listingPrice     : {listing.get('amount')} {listing.get('currencyCode')}")
    else:
        print("  featuredBuyingOptions: (none)")

    lowest = asin_pricing.get("lowestPricedOffers") or {}
    summary = lowest.get("offerCountSummary") or {}
    total_offers = summary.get("totalOfferCount")
    if total_offers is not None:
        print(f"  totalOfferCount  : {total_offers}")

    ref_prices = asin_pricing.get("referencePrices") or []
    if ref_prices:
        for rp in ref_prices[:3]:
            print(f"  referencePrice   : type={rp.get('referencePrice')}  "
                  f"amount={rp.get('amount')}  currency={rp.get('currencyCode')}")
