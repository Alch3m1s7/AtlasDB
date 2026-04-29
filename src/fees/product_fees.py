import requests

FALLBACK_PRICE_AUD = 20.00
FALLBACK_LABEL = "(FALLBACK — replace with real price)"


def get_fees_estimate(
    base_url: str,
    access_token: str,
    asin: str,
    marketplace_id: str,
    listing_price: float,
    currency_code: str = "AUD",
) -> dict:
    body = {
        "FeesEstimateRequest": {
            "MarketplaceId": marketplace_id,
            "IsAmazonFulfilled": True,
            "PriceToEstimateFees": {
                "ListingPrice": {
                    "CurrencyCode": currency_code,
                    "Amount": listing_price,
                }
            },
            "Identifier": asin,
        }
    }

    response = requests.post(
        f"{base_url}/products/fees/v0/items/{asin}/feesEstimate",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
            "Content-Type": "application/json",
        },
        json=body,
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"  [fees/estimate] POST {asin} @ {listing_price} {currency_code}  "
          f"HTTP {response.status_code}  RequestId={request_id}")

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        return {"_error": "THROTTLED", "_status": 429, "_asin": asin,
                "_retry_after": retry_after, "_request_id": request_id}

    if not response.ok:
        return {
            "_error": "HTTP_ERROR",
            "_status": response.status_code,
            "_asin": asin,
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
        return {"_error": "JSON_PARSE_ERROR", "_asin": asin, "_detail": str(exc), "_body": response.text[:200]}


def extract_fee_amounts(fees_response: dict) -> dict:
    """Extract referral_fee, fba_fee, total_fee from a fees response dict."""
    out = {"referral_fee": None, "fba_fee": None, "total_fee": None, "currency": None, "status": "error"}
    if "_error" in fees_response:
        return out
    payload = fees_response.get("payload") or {}
    result = payload.get("FeesEstimateResult") or {}
    if result.get("Status") != "Success":
        out["status"] = result.get("Status", "unknown")
        return out
    out["status"] = "success"
    estimate = result.get("FeesEstimate") or {}
    total = estimate.get("TotalFeesEstimate") or {}
    out["total_fee"] = total.get("Amount")
    out["currency"] = total.get("CurrencyCode")
    for fee in estimate.get("FeeDetailList") or []:
        fee_type = fee.get("FeeType", "")
        amt = (fee.get("FinalFee") or fee.get("FeeAmount") or {}).get("Amount")
        if "referral" in fee_type.lower():
            out["referral_fee"] = amt
        elif "fba" in fee_type.lower():
            out["fba_fee"] = amt
    return out


def print_fees_summary(asin: str, fees_response: dict, listing_price: float, price_label: str = "") -> None:
    if "_error" in fees_response:
        print(f"  fees error   : {fees_response}")
        return

    payload = fees_response.get("payload") or {}
    # SP-API Fees v0 wraps results under FeesEstimateResult
    result = payload.get("FeesEstimateResult") or {}
    status = result.get("Status")
    api_error = result.get("Error")

    if api_error:
        print(f"  fees API error: {api_error}")
        return
    if status and status != "Success":
        print(f"  fees status  : {status}")
        return

    estimate = result.get("FeesEstimate") or {}
    total = estimate.get("TotalFeesEstimate") or {}
    print(f"  listing_price    : {listing_price} {total.get('CurrencyCode', 'AUD')}  {price_label}")
    print(f"  totalFeesEstimate: {total.get('Amount')} {total.get('CurrencyCode')}")

    fee_details = estimate.get("FeeDetailList") or []
    fba_amount = None
    referral_amount = None
    for fee in fee_details:
        fee_type = fee.get("FeeType", "")
        fee_amt = (fee.get("FinalFee") or fee.get("FeeAmount") or {}).get("Amount")
        fee_curr = (fee.get("FinalFee") or fee.get("FeeAmount") or {}).get("CurrencyCode", "")
        if fee_amt == 0.0:
            continue
        print(f"  fee              : {fee_type} = {fee_amt} {fee_curr}")
        if "fba" in fee_type.lower():
            fba_amount = fee_amt
        if "referral" in fee_type.lower():
            referral_amount = fee_amt

    if referral_amount is not None and listing_price and listing_price > 0:
        referral_pct = (referral_amount / listing_price) * 100
        print(f"  referral% (derived estimate): {referral_pct:.2f}%  "
              f"[{referral_amount} / {listing_price} * 100]")
    if fba_amount is not None:
        print(f"  FBA fulfilment fee: {fba_amount}")
