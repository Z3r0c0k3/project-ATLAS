from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


GOOGLE_SHEETS_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def google_connection_status(connection: dict | None) -> dict:
    if not connection or connection.get("disconnected_at") or not (
        connection.get("encrypted_access_token") or connection.get("encrypted_refresh_token")
    ):
        return {
            "connected": False,
            "required_scopes": GOOGLE_SHEETS_SCOPES,
            "message": "Google OAuth credentials are not connected.",
        }
    return {
        "id": connection.get("id"),
        "connected": True,
        "account_email": connection["account_email"],
        "scopes": connection.get("scopes", []),
        "has_refresh_token": bool(connection.get("encrypted_refresh_token")),
    }


def google_account_email(access_token: str) -> str:
    result = _api_get("https://openidconnect.googleapis.com/v1/userinfo", access_token)
    email = str(result.get("email") or "").strip()
    if not email:
        raise GoogleApiError("Google account email was not returned")
    return email


def build_authorization_url(redirect_uri: str, state: str) -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise GoogleApiError("GOOGLE_CLIENT_ID is not configured")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SHEETS_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def _token_request(payload: dict) -> dict:
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleApiError(f"Google OAuth request failed: {exc.code} {detail}", exc.code) from exc
    except urllib.error.URLError as exc:
        raise GoogleApiError(f"Google OAuth connection failed: {exc.reason}") from exc


def exchange_authorization_code(code: str, redirect_uri: str) -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GoogleApiError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
    return _token_request(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )


def refresh_access_token(refresh_token: str) -> str:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise GoogleApiError("Google OAuth client credentials are not configured")
    result = _token_request(
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }
    )
    if not result.get("access_token"):
        raise GoogleApiError("Google did not return an access token")
    return result["access_token"]


def _api_get(url: str, access_token: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleApiError(f"Google API request failed: {exc.code} {detail}", exc.code) from exc
    except urllib.error.URLError as exc:
        raise GoogleApiError(f"Google API connection failed: {exc.reason}") from exc


def list_spreadsheets(access_token: str) -> list[dict]:
    result = _api_get(
        "https://www.googleapis.com/drive/v3/files",
        access_token,
        {
            "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            "fields": "files(id,name,modifiedTime,webViewLink,owners(displayName,emailAddress))",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
        },
    )
    return result.get("files", [])


def list_drive_files(access_token: str) -> list[dict]:
    result = _api_get(
        "https://www.googleapis.com/drive/v3/files",
        access_token,
        {
            "q": "trashed=false",
            "fields": "files(id,name,mimeType,size,modifiedTime,md5Checksum,webViewLink)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
        },
    )
    return result.get("files", [])


def get_sheet_values(access_token: str, spreadsheet_id: str, range_name: str) -> dict:
    encoded_range = urllib.parse.quote(range_name, safe="")
    return _api_get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{encoded_range}",
        access_token,
        {"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
    )
