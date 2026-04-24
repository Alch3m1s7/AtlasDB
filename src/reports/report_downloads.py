import gzip
import os
import requests

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")


def get_report_document(base_url: str, access_token: str, report_document_id: str) -> dict:
    response = requests.get(
        f"{base_url}/reports/2021-06-30/documents/{report_document_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
        },
    )

    if not response.ok:
        raise RuntimeError(
            f"Get report document failed: {response.status_code} {response.text}"
        )

    data = response.json()
    return {
        "reportDocumentId": data.get("reportDocumentId"),
        "url": data.get("url"),
        "compressionAlgorithm": data.get("compressionAlgorithm"),
    }


def download_report(url: str, compression_algorithm: str, filename: str) -> str:
    response = requests.get(url)
    if not response.ok:
        raise RuntimeError(f"Download failed: {response.status_code} {response.text}")

    out_path = os.path.join(RAW_DATA_DIR, filename)

    if compression_algorithm == "GZIP":
        content = gzip.decompress(response.content).decode("utf-8")
    else:
        content = response.text

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return os.path.abspath(out_path)
