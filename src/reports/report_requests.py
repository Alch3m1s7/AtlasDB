import json

import requests

EU_UK_MARKETPLACE_ID = "A1F83G8C2ARO7P"
REPORT_TYPE = "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA"


def create_report(
    base_url: str,
    access_token: str,
    marketplace_id: str,
    report_type: str,
    data_start_time: str | None = None,
    data_end_time: str | None = None,
) -> str:
    body: dict = {
        "reportType": report_type,
        "marketplaceIds": [marketplace_id],
    }
    if data_start_time is not None:
        body["dataStartTime"] = data_start_time
    if data_end_time is not None:
        body["dataEndTime"] = data_end_time
    print(f"[create_report] POST body: {json.dumps(body)}")

    response = requests.post(
        f"{base_url}/reports/2021-06-30/reports",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
            "Content-Type": "application/json",
        },
        json=body,
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"[create_report] HTTP {response.status_code}  x-amzn-RequestId: {request_id}")

    if not response.ok:
        print(f"[create_report] Error body: {response.text}")
        raise RuntimeError(
            f"Report request failed: {response.status_code} "
            f"x-amzn-RequestId={request_id} {response.text}"
        )

    data = response.json()
    print(f"[create_report] Response: {json.dumps(data)}")
    return data["reportId"]


def get_report_status(base_url: str, access_token: str, report_id: str) -> dict:
    response = requests.get(
        f"{base_url}/reports/2021-06-30/reports/{report_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
        },
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"[get_report_status] HTTP {response.status_code}  x-amzn-RequestId: {request_id}")

    if not response.ok:
        print(f"[get_report_status] Error body: {response.text}")
        raise RuntimeError(
            f"Get report failed: {response.status_code} "
            f"x-amzn-RequestId={request_id} {response.text}"
        )

    data = response.json()
    print(f"[get_report_status] Response: {json.dumps(data)}")
    return data


def get_recent_done_report(
    base_url: str,
    access_token: str,
    report_type: str,
    marketplace_id: str,
    created_since_iso: str,
) -> dict | None:
    print(
        f"[get_recent_done_report] reportTypes={report_type} "
        f"processingStatuses=DONE marketplaceIds={marketplace_id} "
        f"createdSince={created_since_iso} pageSize=10"
    )

    response = requests.get(
        f"{base_url}/reports/2021-06-30/reports",
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-amz-access-token": access_token,
        },
        params={
            "reportTypes": report_type,
            "processingStatuses": "DONE",
            "marketplaceIds": marketplace_id,
            "createdSince": created_since_iso,
            "pageSize": "10",
        },
    )

    request_id = response.headers.get("x-amzn-RequestId", "n/a")
    print(f"[get_recent_done_report] HTTP {response.status_code}  x-amzn-RequestId: {request_id}")

    if not response.ok:
        print(f"[get_recent_done_report] Error body: {response.text}")
        raise RuntimeError(
            f"List reports failed: {response.status_code} "
            f"x-amzn-RequestId={request_id} {response.text}"
        )

    reports = response.json().get("reports", [])
    print(f"[get_recent_done_report] {len(reports)} DONE report(s) found since {created_since_iso}")

    if not reports:
        return None

    reports.sort(key=lambda r: r.get("createdTime", ""), reverse=True)
    newest = reports[0]
    print(
        f"[get_recent_done_report] Using reportId={newest.get('reportId')} "
        f"createdTime={newest.get('createdTime')}"
    )
    return newest
