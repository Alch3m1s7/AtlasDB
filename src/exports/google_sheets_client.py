import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheets_service():
    """Return an authenticated Google Sheets API service object.

    Token lifecycle:
    - Load saved token from GOOGLE_OAUTH_TOKEN_JSON if the file exists.
    - Refresh automatically when the token is expired and a refresh_token is present.
    - Run InstalledAppFlow (browser) only when no valid token can be produced.
    - Save the (new or refreshed) token back to GOOGLE_OAUTH_TOKEN_JSON.

    Neither token content nor credentials are printed or logged.
    """
    token_path = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    client_secret_path = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_JSON")

    if not token_path:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_JSON is not set in the environment")
    if not client_secret_path:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET_JSON is not set in the environment")
    if not os.path.exists(client_secret_path):
        raise RuntimeError(
            f"OAuth client secret file not found: {client_secret_path}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[sheets] Token refreshed automatically.")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, _SCOPES)
            creds = flow.run_local_server(port=0)
            print("[sheets] OAuth authorisation completed.")

        # Persist token — never log its content
        token_dir = os.path.dirname(token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
        print(f"[sheets] Token saved to {token_path}")

    return build("sheets", "v4", credentials=creds)
