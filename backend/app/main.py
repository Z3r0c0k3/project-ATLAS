from __future__ import annotations

import secrets
import shutil
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .models import (
    AuthSession,
    DiscordMessageResponse,
    DiscordPreviewRequest,
    DiscordWebhookRequest,
    GoogleConnectRequest,
    LoginRequest,
    MonthlyReportRequest,
    MonthlyReportResponse,
    SubmissionPackageRequest,
    SubmissionPackageResponse,
    Role,
)
from .services.accounting import normalize_evidence, normalize_transactions
from .services.discord import render_monthly_discord_message, send_webhook
from .services.documents import build_monthly_report_payload, build_submission_package
from .services.google import google_connection_status, placeholder_drive_files, placeholder_sheets
from .services.store import JsonStore


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(__file__).resolve().parents[1] / "storage"
UPLOAD_ROOT = DATA_ROOT / "uploads"
OUTPUT_ROOT = DATA_ROOT / "outputs"
PUBLIC_FRONTEND_BASE_URL = os.getenv("PUBLIC_FRONTEND_BASE_URL", "http://localhost:5173")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="ATLAS API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = JsonStore(DATA_ROOT)


def require_roles(*allowed_roles: Role):
    def dependency(x_atlas_token: str | None = Header(default=None, alias="X-ATLAS-Token")) -> dict:
        if not x_atlas_token:
            raise HTTPException(status_code=401, detail="Missing ATLAS session token")
        session = store.get("sessions", x_atlas_token)
        if not session:
            raise HTTPException(status_code=401, detail="Invalid ATLAS session token")
        if session["role"] not in {role.value for role in allowed_roles}:
            raise HTTPException(status_code=403, detail="Role is not allowed for this operation")
        return session

    return dependency


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ATLAS"}


@app.post("/auth/login", response_model=AuthSession)
def login(payload: LoginRequest) -> AuthSession:
    session = store.insert(
        "sessions",
        {"username": payload.username, "role": payload.role.value},
        "sess",
    )
    return AuthSession(token=session["id"], username=payload.username, role=payload.role)


@app.post("/auth/google/connect")
def connect_google(
    payload: GoogleConnectRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    connection = store.insert("google_connections", payload.model_dump(), "goog")
    return google_connection_status(connection)


@app.get("/google/sheets")
def list_google_sheets(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    connections = store.read_collection("google_connections")
    connection = next(iter(connections.values()), None)
    return {
        "connection": google_connection_status(connection),
        "sheets": placeholder_sheets(connection),
    }


@app.get("/google/drive/files")
def list_google_drive_files(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    connections = store.read_collection("google_connections")
    connection = next(iter(connections.values()), None)
    return {
        "connection": google_connection_status(connection),
        "files": placeholder_drive_files(connection),
    }


@app.post("/imports/upload")
def upload_import(
    file: UploadFile = File(...),
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    upload_id = f"upload_{secrets.token_urlsafe(8)}"
    target = UPLOAD_ROOT / upload_id / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        shutil.copyfileobj(file.file, stream)
    row = store.insert(
        "uploads",
        {"filename": file.filename, "content_type": file.content_type, "path": str(target)},
        "upl",
    )
    return row


@app.post("/packages/submission", response_model=SubmissionPackageResponse)
def create_submission_package(
    payload: SubmissionPackageRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> SubmissionPackageResponse:
    package = store.insert(
        "packages",
        {
            "club_name": payload.club_name,
            "semester": payload.semester,
            "status": "building",
        },
        "pkg",
    )
    transactions = normalize_transactions([item.model_dump() for item in payload.transactions])
    evidence = normalize_evidence([item.model_dump() for item in payload.evidence])
    result = build_submission_package(
        OUTPUT_ROOT,
        package["id"],
        payload.club_name,
        payload.semester,
        payload.treasurer_name,
        payload.president_name,
        payload.reviewer_name,
        payload.opening_balance,
        payload.expected_closing_balance,
        transactions,
        evidence,
        payload.row_capacity,
    )
    store.update(
        "packages",
        package["id"],
        {
            "status": "ready",
            "zip_path": result["zip_path"],
            "validation": result["validation"],
            "artifacts": result["artifacts"],
        },
    )
    return SubmissionPackageResponse(
        package_id=package["id"],
        zip_path=result["zip_path"],
        download_url=f"/packages/{package['id']}/download",
        validation=result["validation"],
        artifacts=result["artifacts"],
    )


@app.get("/packages/{package_id}/download")
def download_submission_package(
    package_id: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> FileResponse:
    package = store.get("packages", package_id)
    if not package or not package.get("zip_path"):
        raise HTTPException(status_code=404, detail="Package not found")
    return FileResponse(package["zip_path"], filename=f"{package_id}.zip")


@app.post("/monthly-reports", response_model=MonthlyReportResponse)
def create_monthly_report(
    payload: MonthlyReportRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> MonthlyReportResponse:
    report_id = f"rep_{secrets.token_urlsafe(8)}"
    share_id = secrets.token_urlsafe(12)
    transactions = normalize_transactions([item.model_dump() for item in payload.transactions])
    report = build_monthly_report_payload(
        report_id,
        share_id,
        payload.club_name,
        payload.month,
        payload.opening_balance,
        transactions,
        payload.visible_notes,
    )
    store.insert("monthly_reports", report, "monthly")
    public_url = f"{PUBLIC_FRONTEND_BASE_URL}/public/monthly/{share_id}"
    return MonthlyReportResponse(
        report_id=report_id,
        share_id=share_id,
        public_url=public_url,
        summary=report["summary"],
    )


@app.get("/public/monthly/{share_id}")
def get_public_monthly_report(share_id: str) -> dict:
    report = store.find_one_by("monthly_reports", "share_id", share_id)
    if not report:
        raise HTTPException(status_code=404, detail="Monthly report not found")
    return {
        "club_name": report["club_name"],
        "month": report["month"],
        "share_id": report["share_id"],
        "summary": report["summary"],
        "transactions": report["transactions"],
    }


@app.post("/discord/webhooks")
def create_discord_webhook(
    payload: DiscordWebhookRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    return store.insert("discord_webhooks", payload.model_dump(mode="json"), "webhook")


@app.post("/discord/messages/preview", response_model=DiscordMessageResponse)
def preview_discord_message(
    payload: DiscordPreviewRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> DiscordMessageResponse:
    report = store.find_one_by("monthly_reports", "share_id", payload.share_id)
    webhook = store.get("discord_webhooks", payload.webhook_id)
    if not report:
        raise HTTPException(status_code=404, detail="Monthly report not found")
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    public_url = f"{PUBLIC_FRONTEND_BASE_URL}/public/monthly/{payload.share_id}"
    preview = render_monthly_discord_message(report, public_url)
    message = store.insert(
        "discord_messages",
        {
            "share_id": payload.share_id,
            "webhook_id": payload.webhook_id,
            "status": "pending_approval",
            "preview": preview,
        },
        "msg",
    )
    return DiscordMessageResponse(message_id=message["id"], status=message["status"], preview=preview)


@app.post("/discord/messages/{message_id}/send", response_model=DiscordMessageResponse)
def send_discord_message(
    message_id: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> DiscordMessageResponse:
    message = store.get("discord_messages", message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    webhook = store.get("discord_webhooks", message["webhook_id"])
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    result = send_webhook(webhook["webhook_url"], message["preview"])
    status = "sent" if result.get("ok") else "failed"
    updated = store.update(
        "discord_messages",
        message_id,
        {"status": status, "send_result": result, "sent_at": result.get("sent_at")},
    )
    return DiscordMessageResponse(
        message_id=message_id,
        status=updated["status"],
        preview=updated["preview"],
        sent_at=updated.get("sent_at"),
    )
