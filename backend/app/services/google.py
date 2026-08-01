from __future__ import annotations


GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def google_connection_status(connection: dict | None) -> dict:
    if not connection:
        return {
            "connected": False,
            "required_scopes": GOOGLE_SHEETS_SCOPES,
            "message": "Google OAuth credentials are not connected.",
        }
    return {
        "connected": True,
        "account_email": connection["account_email"],
        "scopes": connection.get("scopes", []),
    }


def placeholder_sheets(connection: dict | None) -> list[dict]:
    if not connection:
        return []
    return [
        {
            "id": "google_sheet_placeholder",
            "name": "Aegis 회계 장부",
            "source": "google_sheets",
            "status": "adapter_ready",
        }
    ]


def placeholder_drive_files(connection: dict | None) -> list[dict]:
    if not connection:
        return []
    return [
        {
            "id": "google_drive_folder_placeholder",
            "name": "Aegis 증빙자료",
            "source": "google_drive",
            "status": "adapter_ready",
        }
    ]
