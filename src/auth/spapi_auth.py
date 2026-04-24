import os
import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token(refresh_token: str) -> str:
    client_id = os.getenv("SPAPI_CLIENT_ID")
    client_secret = os.getenv("SPAPI_CLIENT_SECRET")

    if not all([client_id, client_secret, refresh_token]):
        raise EnvironmentError(
            "Missing one or more required env vars: "
            "SPAPI_CLIENT_ID, SPAPI_CLIENT_SECRET, and a refresh token"
        )

    response = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if not response.ok:
        raise RuntimeError(
            f"Failed to obtain access token: {response.status_code} {response.text}"
        )

    return response.json()["access_token"]
