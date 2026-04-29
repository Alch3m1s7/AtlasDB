import csv

from decimal import Decimal, InvalidOperation
from pathlib import Path


INT_FIELDS = {
    "mfn-fulfillable-quantity",
    "afn-warehouse-quantity",
    "afn-fulfillable-quantity",
    "afn-unsellable-quantity",
    "afn-reserved-quantity",
    "afn-total-quantity",
    "afn-inbound-working-quantity",
    "afn-inbound-shipped-quantity",
    "afn-inbound-receiving-quantity",
    "afn-researching-quantity",
    "afn-reserved-future-supply",
    "afn-future-supply-buyable",
    "afn-fulfillable-quantity-local",
    "afn-fulfillable-quantity-remote",
}

DECIMAL_FIELDS = {
    "your-price",
    "per-unit-volume",
}


def clean_value(value: str):
    value = value.strip() if value is not None else ""
    return None if value == "" else value


def to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return value


def normalize_fba_inventory_row(row: dict) -> dict:
    cleaned = {}

    for key, value in row.items():
        key = key.strip()
        value = clean_value(value)

        if key in INT_FIELDS:
            value = to_int(value)
        elif key in DECIMAL_FIELDS:
            value = to_decimal(value)

        cleaned[key] = value

    cleaned["_is_valid"] = bool(cleaned.get("sku") and cleaned.get("asin"))
    cleaned["_validation_errors"] = []

    if not cleaned.get("sku"):
        cleaned["_validation_errors"].append("missing_sku")

    if not cleaned.get("asin"):
        cleaned["_validation_errors"].append("missing_asin")

    return cleaned


def parse_fba_inventory_report(file_path: str) -> list[dict]:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Report file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return [normalize_fba_inventory_row(row) for row in reader]
