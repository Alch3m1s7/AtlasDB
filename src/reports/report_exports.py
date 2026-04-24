import json
import os
from decimal import Decimal


def export_rows_to_jsonl(rows: list[dict], output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=lambda v: str(v) if isinstance(v, Decimal) else v) + "\n")
    return output_path
