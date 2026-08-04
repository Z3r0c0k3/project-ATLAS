from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .models import (
    AcknowledgeIssuesRequest,
    AuthSession,
    DiscordMessageResponse,
    DiscordPreviewRequest,
    DiscordWebhookRequest,
    EvidenceAttachRequest,
    GoogleConnectRequest,
    GoogleSheetSnapshotRequest,
    LedgerSnapshotRequest,
    LoginRequest,
    MonthlyReportRequest,
    MonthlyReportResponse,
    PackageJobResponse,
    PackageReviewRequest,
    Role,
    SubmissionPackageRequest,
    TransactionInput,
    TransactionPatchRequest,
    WorkbookSnapshotRequest,
)
from .services.accounting import (
    acknowledge_issues,
    normalize_evidence,
    normalize_transactions,
    snapshot_payload,
)
from .services.discord import render_monthly_discord_message, send_webhook
from .services.documents import build_monthly_report_payload, build_submission_package
from .services.google import (
    GoogleApiError,
    build_authorization_url,
    exchange_authorization_code,
    get_sheet_values,
    google_account_email,
    google_connection_status,
    list_drive_files,
    list_spreadsheets,
    refresh_access_token,
)
from .services.integrity import canonical_sha256, file_sha256
from .services.jobs import JobRunner
from .services.security import SecretBox, mask_webhook_url, sanitize_secret_fields
from .services.store import JsonStore, utc_now
from .services.workbooks import (
    WorkbookParseError,
    parse_aegis_ledger,
    parse_toss_bank,
    reconcile_ledger_bank,
    workbook_preview,
)


DATA_ROOT = Path(__file__).resolve().parents[1] / "storage"
UPLOAD_ROOT = DATA_ROOT / "uploads"
OUTPUT_ROOT = DATA_ROOT / "outputs"
MAX_UPLOAD_BYTES = int(os.getenv("ATLAS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
PUBLIC_FRONTEND_BASE_URL = os.getenv("PUBLIC_FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
ROOT_PATH = os.getenv("ROOT_PATH", "")
LOGIN_PASSWORD = os.getenv("ATLAS_LOGIN_PASSWORD")
try:
    USER_ROLES = json.loads(os.getenv("ATLAS_USER_ROLES", "{}"))
except json.JSONDecodeError as exc:
    raise RuntimeError("ATLAS_USER_ROLES must be a valid JSON object") from exc
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="ATLAS API", version="1.2.0", root_path=ROOT_PATH)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = JsonStore(DATA_ROOT)
secret_box = SecretBox()
jobs = JobRunner(store)


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


def audit(
    session: dict,
    action: str,
    target_type: str,
    target_id: str | None,
    before: dict | None = None,
    after: dict | None = None,
    success: bool = True,
    request: Request | None = None,
) -> dict:
    return store.append_audit(
        {
            "actor": session.get("username"),
            "actor_role": session.get("role"),
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "before": sanitize_secret_fields(before),
            "after": sanitize_secret_fields(after),
            "request_ip": request.client.host if request and request.client else None,
            "session_id": session.get("id"),
            "success": success,
        }
    )


def create_snapshot(
    payload: LedgerSnapshotRequest,
    session: dict,
    source_type: str = "manual",
    source_extra: dict | None = None,
) -> dict:
    transactions = normalize_transactions([item.model_dump() for item in payload.transactions])
    evidence = normalize_evidence([item.model_dump() for item in payload.evidence])
    source = {
        "type": source_type,
        "spreadsheet_id": payload.spreadsheet_id,
        "sheet_name": payload.sheet_name,
        "modified_time": payload.source_modified_time,
        "import_job_id": payload.import_job_id,
        "period_start": payload.period_start,
        "period_end": payload.period_end,
        **(source_extra or {}),
    }
    snapshot = store.insert(
        "ledger_snapshots",
        {
            **snapshot_payload(
                payload.organization_id,
                payload.account_id,
                payload.period,
                transactions,
                evidence,
                source,
            ),
            "imported_by": session.get("username"),
            "imported_role": session.get("role"),
        },
        "snap",
    )
    audit(session, "ledger.snapshot.created", "ledger_snapshot", snapshot["id"], after={"data_hash": snapshot["data_hash"]})
    return snapshot


def snapshot_summary(snapshot: dict) -> dict:
    return {
        "id": snapshot["id"],
        "organization_id": snapshot["organization_id"],
        "account_id": snapshot["account_id"],
        "period": snapshot["period"],
        "data_hash": snapshot["data_hash"],
        "transaction_count": len(snapshot.get("transactions", [])),
        "evidence_count": len(snapshot.get("evidence", [])),
        "source": snapshot.get("source"),
        "imported_by": snapshot.get("imported_by"),
        "created_at": snapshot.get("created_at"),
        "reconciliation": (snapshot.get("source") or {}).get("reconciliation"),
    }


def evidence_transaction_number_from_filename(filename: str) -> tuple[int | None, str, str | None]:
    stem = Path(filename).stem
    dues = re.search(r"^\s*\*\s*(\d{1,6})\s*\*", stem)
    if dues:
        return int(dues.group(1)), "filename_dues_star_id", "dues_intake"
    explicit = re.search(r"#\s*(\d{1,6})\s*#", stem)
    if explicit:
        return int(explicit.group(1)), "filename_hash_id", None
    labeled = re.search(r"(?:^|[ _-])(?:no|tx|ledger|장부)[ ._#-]*(\d{1,6})(?:[ ._#-]|$)", stem, re.IGNORECASE)
    if labeled:
        return int(labeled.group(1)), "filename_labeled_id", None
    return None, "unmatched", None


def create_snapshot_revision(
    current: dict,
    transactions: list[dict],
    evidence: list[dict],
    session: dict,
    mutation: dict,
) -> dict:
    normalized_transactions = normalize_transactions(transactions)
    normalized_evidence = normalize_evidence(evidence)
    source = {**current.get("source", {}), "parent_snapshot_id": current["id"], "mutation": mutation}
    return store.insert(
        "ledger_snapshots",
        {
            **snapshot_payload(
                current["organization_id"],
                current["account_id"],
                current["period"],
                normalized_transactions,
                normalized_evidence,
                source,
            ),
            "imported_by": session["username"],
            "imported_role": session["role"],
        },
        "snap",
    )


def resolve_snapshot_for_package(payload: SubmissionPackageRequest, session: dict) -> dict:
    if payload.snapshot_id:
        snapshot = store.get("ledger_snapshots", payload.snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Ledger snapshot not found")
        return snapshot
    if not payload.transactions:
        raise HTTPException(status_code=422, detail="Transactions are required when snapshot_id is omitted")
    return create_snapshot(
        LedgerSnapshotRequest(
            organization_id=payload.organization_id,
            account_id=payload.account_id,
            spreadsheet_id=payload.spreadsheet_id,
            sheet_name=payload.sheet_name,
            period=payload.semester,
            period_start=payload.period_start,
            period_end=payload.period_end,
            source_modified_time=payload.source_modified_time,
            transactions=payload.transactions,
            evidence=payload.evidence,
        ),
        session,
    )


def current_google_connection() -> dict | None:
    rows = list(store.read_collection("google_connections").values())
    return rows[-1] if rows else None


def google_access_token(connection: dict, force_refresh: bool = False) -> str:
    try:
        token = secret_box.decrypt(connection.get("encrypted_access_token"))
    except ValueError as exc:
        raise GoogleApiError("Stored Google access token cannot be decrypted. Reconnect the Google account after confirming ATLAS_SECRET_KEY.", 409) from exc
    if token and not force_refresh:
        return token
    try:
        refresh_token = secret_box.decrypt(connection.get("encrypted_refresh_token"))
    except ValueError as exc:
        raise GoogleApiError("Stored Google refresh token cannot be decrypted. Reconnect the Google account after confirming ATLAS_SECRET_KEY.", 409) from exc
    if not refresh_token:
        raise GoogleApiError("Google refresh token is not available")
    token = refresh_access_token(refresh_token)
    store.update("google_connections", connection["id"], {"encrypted_access_token": secret_box.encrypt(token)})
    return token


def call_google_api(connection: dict, operation):
    try:
        return operation(google_access_token(connection))
    except GoogleApiError as exc:
        if exc.status_code != 401 or not connection.get("encrypted_refresh_token"):
            raise
    return operation(google_access_token(connection, force_refresh=True))


def raise_google_http_error(exc: GoogleApiError) -> None:
    status_code = exc.status_code if exc.status_code in {400, 401, 403, 409, 429} else 502
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def parse_google_sheet_rows(values: list[list[Any]], opening_balance: int) -> list[dict]:
    if not values:
        return []
    rows = values[1:] if any(str(value) in {"번호", "날짜", "내용"} for value in values[0]) else values

    def number(value: Any) -> int:
        if value in (None, ""):
            return 0
        return int(float(str(value).replace(",", "")))

    parsed: list[dict] = []
    running = opening_balance
    for index, row in enumerate(rows, 1):
        padded = list(row) + [None] * (7 - len(row))
        if not any(value not in (None, "") for value in padded[:7]):
            continue
        income, expense = number(padded[3]), number(padded[4])
        running = number(padded[5]) if padded[5] not in (None, "") else running + income - expense
        parsed.append(
            {
                "number": number(padded[0]) or index,
                "date": str(padded[1]),
                "description": str(padded[2] or ""),
                "income": income,
                "expense": expense,
                "balance": running,
                "note": str(padded[6] or ""),
                "source_row": str(index + 1),
            }
        )
    return parsed


def persist_upload(file: UploadFile, folder: str = "imports") -> tuple[Path, int]:
    upload_id = f"upload_{secrets.token_urlsafe(8)}"
    filename = Path(file.filename or "upload.bin").name
    target = UPLOAD_ROOT / folder / upload_id / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as stream:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
                stream.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, size


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ATLAS",
        "version": app.version,
        "auth_mode": "mapped_password" if LOGIN_PASSWORD and USER_ROLES else ("password" if LOGIN_PASSWORD else "demo"),
    }


@app.post("/auth/login", response_model=AuthSession)
def login(payload: LoginRequest, request: Request) -> AuthSession:
    if LOGIN_PASSWORD and not secrets.compare_digest(payload.password or "", LOGIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid login password")
    if USER_ROLES:
        mapped_role = USER_ROLES.get(payload.username)
        if not mapped_role:
            raise HTTPException(status_code=403, detail="User is not registered in ATLAS_USER_ROLES")
        try:
            effective_role = Role(mapped_role)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Configured user role is invalid") from exc
    else:
        effective_role = payload.role
    session = store.insert("sessions", {"username": payload.username, "role": effective_role.value}, "sess")
    audit(session, "auth.login", "session", session["id"], success=True, request=request)
    return AuthSession(token=session["id"], username=payload.username, role=effective_role)


@app.get("/auth/google/authorize-url")
def google_authorize_url(
    redirect_uri: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    state_row = store.insert("oauth_states", {"session_id": session["id"], "redirect_uri": redirect_uri}, "state")
    try:
        return {"authorization_url": build_authorization_url(redirect_uri, state_row["id"]), "state": state_row["id"]}
    except GoogleApiError as exc:
        raise_google_http_error(exc)


@app.post("/auth/google/connect")
def connect_google(
    payload: GoogleConnectRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    tokens: dict = {}
    if payload.authorization_code:
        if not payload.redirect_uri or not payload.state:
            raise HTTPException(status_code=422, detail="redirect_uri and state are required with authorization_code")
        oauth_state = store.get("oauth_states", payload.state)
        if not oauth_state or oauth_state.get("session_id") != session["id"] or oauth_state.get("redirect_uri") != payload.redirect_uri:
            raise HTTPException(status_code=400, detail="Invalid Google OAuth state")
        if oauth_state.get("consumed_at"):
            raise HTTPException(status_code=409, detail="Google OAuth state was already used")
        try:
            tokens = exchange_authorization_code(payload.authorization_code, payload.redirect_uri)
        except GoogleApiError as exc:
            raise_google_http_error(exc)
        store.update("oauth_states", oauth_state["id"], {"consumed_at": utc_now()})
    access_token = payload.access_token or tokens.get("access_token")
    refresh_token = payload.refresh_token or tokens.get("refresh_token")
    account_email = payload.account_email
    if not account_email and access_token:
        try:
            account_email = google_account_email(access_token)
        except GoogleApiError as exc:
            raise_google_http_error(exc)
    if not account_email:
        raise HTTPException(status_code=422, detail="account_email or a Google authorization code is required")
    connection = store.insert(
        "google_connections",
        {
            "account_email": account_email,
            "encrypted_access_token": secret_box.encrypt(access_token),
            "encrypted_refresh_token": secret_box.encrypt(refresh_token),
            "scopes": payload.scopes or str(tokens.get("scope") or "").split(),
        },
        "goog",
    )
    audit(session, "google.connected", "google_connection", connection["id"], after=connection, request=request)
    return google_connection_status(connection)


@app.get("/auth/google/status")
def google_status(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    return google_connection_status(current_google_connection())


@app.post("/auth/google/disconnect")
def disconnect_google(
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    connection = current_google_connection()
    if not connection:
        return {"connected": False}
    updated = store.update(
        "google_connections",
        connection["id"],
        {"encrypted_access_token": None, "encrypted_refresh_token": None, "disconnected_at": utc_now()},
    )
    audit(session, "google.disconnected", "google_connection", connection["id"], before=connection, after=updated, request=request)
    return {"connected": False}


@app.get("/google/diagnostics")
def google_diagnostics(
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    connection = current_google_connection()
    status_payload = google_connection_status(connection)
    diagnostics = {
        "connection": status_payload,
        "configured": {
            "client_id": bool(os.getenv("GOOGLE_CLIENT_ID")),
            "client_secret": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        },
        "stored_tokens": {
            "access_token": bool(connection and connection.get("encrypted_access_token")),
            "refresh_token": bool(connection and connection.get("encrypted_refresh_token")),
        },
        "checks": [],
    }
    if not connection:
        diagnostics["checks"].append({"name": "connection", "status": "missing", "message": "Google account is not connected."})
        return diagnostics
    try:
        google_access_token(connection)
    except GoogleApiError as exc:
        diagnostics["checks"].append({"name": "access_token", "status": "error", "message": str(exc), "status_code": exc.status_code})
        return diagnostics
    diagnostics["checks"].append({"name": "access_token", "status": "ok"})
    try:
        call_google_api(connection, lambda token: get_sheet_values(token, "invalid-diagnostics-spreadsheet-id", "A1:A1"))
    except GoogleApiError as exc:
        # A Google 400/403 here proves outbound Google API connectivity and credential handling reached Google.
        diagnostics["checks"].append({"name": "google_api_reachable", "status": "ok" if exc.status_code in {400, 403, 404} else "error", "message": str(exc), "status_code": exc.status_code})
        return diagnostics
    diagnostics["checks"].append({"name": "google_api_reachable", "status": "ok"})
    return diagnostics


@app.get("/google/sheets")
def get_google_sheets(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    connection = current_google_connection()
    if not connection or not connection.get("encrypted_refresh_token") and not connection.get("encrypted_access_token"):
        return {"connection": google_connection_status(None), "sheets": []}
    try:
        return {"connection": google_connection_status(connection), "sheets": call_google_api(connection, list_spreadsheets)}
    except GoogleApiError as exc:
        raise_google_http_error(exc)


@app.get("/google/drive/files")
def get_google_drive_files(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    connection = current_google_connection()
    if not connection or not connection.get("encrypted_refresh_token") and not connection.get("encrypted_access_token"):
        return {"connection": google_connection_status(None), "files": []}
    try:
        return {"connection": google_connection_status(connection), "files": call_google_api(connection, list_drive_files)}
    except GoogleApiError as exc:
        raise_google_http_error(exc)


@app.post("/google/sheets/{spreadsheet_id}/snapshot")
def snapshot_google_sheet(
    spreadsheet_id: str,
    payload: GoogleSheetSnapshotRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    connection = current_google_connection()
    if not connection:
        raise HTTPException(status_code=409, detail="Google account is not connected")
    try:
        result = call_google_api(connection, lambda token: get_sheet_values(token, spreadsheet_id, payload.range))
    except GoogleApiError as exc:
        raise_google_http_error(exc)
    transactions = parse_google_sheet_rows(result.get("values", []), payload.opening_balance)
    snapshot = create_snapshot(
        LedgerSnapshotRequest(
            organization_id=payload.organization_id,
            account_id=payload.account_id,
            spreadsheet_id=spreadsheet_id,
            sheet_name=result.get("range"),
            period=payload.period,
            period_start=payload.period_start,
            period_end=payload.period_end,
            transactions=transactions,
        ),
        session,
        "google_sheets",
    )
    return snapshot_summary(snapshot)


@app.post("/imports/upload")
def upload_import(
    request: Request,
    file: UploadFile = File(...),
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    target, size = persist_upload(file)
    analysis = None
    parse_error = None
    if target.suffix.lower() in {".xlsx", ".xlsm"}:
        try:
            analysis = workbook_preview(target)
        except WorkbookParseError as exc:
            parse_error = str(exc)
    row = store.insert(
        "uploads",
        {
            "filename": target.name,
            "content_type": file.content_type,
            "size": size,
            "sha256": file_sha256(target),
            "path": str(target),
            "detected_type": analysis.get("kind") if analysis else None,
            "analysis": analysis,
            "parse_error": parse_error,
        },
        "upl",
    )
    audit(session, "file.uploaded", "upload", row["id"], after=row, request=request)
    return row


@app.post("/evidence/upload")
def upload_evidence(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("other"),
    account_id: str | None = Form(None),
    transaction_number: int | None = Form(None),
    transaction_ids: str = Form(""),
    amount: int | None = Form(None),
    evidence_date: str | None = Form(None),
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    if kind not in {"receipt", "explanation", "account_capture", "other"}:
        raise HTTPException(status_code=422, detail="Unsupported evidence kind")
    target, size = persist_upload(file, "evidence")
    inferred_number = transaction_number
    inferred_account_id = account_id or "primary"
    match_method = "manual" if transaction_number is not None else "unmatched"
    if inferred_number is None:
        inferred_number, match_method, account_hint = evidence_transaction_number_from_filename(target.name)
        if account_hint and not account_id:
            inferred_account_id = account_hint
    row = store.insert(
        "evidence",
        {
            "transaction_number": inferred_number,
            "account_id": inferred_account_id,
            "match_method": match_method,
            "match_confidence": "confirmed" if inferred_number is not None else "unmatched",
            "transaction_ids": [value.strip() for value in transaction_ids.split(",") if value.strip()],
            "filename": target.name,
            "kind": kind,
            "mime_type": file.content_type,
            "size": size,
            "sha256": file_sha256(target),
            "amount": amount,
            "evidence_date": evidence_date,
            "accessible": True,
            "last_verified_at": utc_now(),
            "local_path": str(target),
        },
        "ev",
    )
    audit(session, "evidence.uploaded", "evidence", row["id"], after=row, request=request)
    return row


@app.get("/evidence")
def list_evidence(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> list[dict]:
    return list(reversed(list(store.read_collection("evidence").values())))


@app.post("/imports/workbook-snapshot")
def create_workbook_snapshot(
    payload: WorkbookSnapshotRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    ledger_upload = store.get("uploads", payload.ledger_upload_id)
    if not ledger_upload:
        raise HTTPException(status_code=404, detail="Ledger upload not found")
    ledger_path = Path(ledger_upload["path"])
    try:
        ledger = parse_aegis_ledger(
            ledger_path,
            period=payload.period,
            opening_balance=payload.opening_balance,
            organization_id=payload.organization_id,
            account_id=payload.account_id,
            sheet_name=payload.sheet_name,
        )
    except WorkbookParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    evidence_rows: list[dict] = []
    for evidence_id in payload.evidence_ids:
        item = store.get("evidence", evidence_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Evidence not found: {evidence_id}")
        evidence_rows.append(item)
    evidence_by_number: dict[int, list[str]] = {}
    for item in evidence_rows:
        if item.get("transaction_number") is not None:
            evidence_by_number.setdefault(int(item["transaction_number"]), []).append(item["id"])
    for transaction in ledger["transactions"]:
        transaction["evidence_ids"] = evidence_by_number.get(transaction["number"], [])

    bank = None
    reconciliation = None
    bank_upload = None
    if payload.bank_upload_id:
        bank_upload = store.get("uploads", payload.bank_upload_id)
        if not bank_upload:
            raise HTTPException(status_code=404, detail="Bank upload not found")
        try:
            bank = parse_toss_bank(Path(bank_upload["path"]))
            reconciliation = reconcile_ledger_bank(ledger, bank)
        except WorkbookParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    source_files = [
        {
            "kind": "ledger_workbook",
            "filename": ledger_upload["filename"],
            "local_path": ledger_upload["path"],
            "sha256": ledger_upload["sha256"],
        }
    ]
    if bank_upload:
        source_files.append(
            {
                "kind": "bank_workbook",
                "filename": bank_upload["filename"],
                "local_path": bank_upload["path"],
                "sha256": bank_upload["sha256"],
            }
        )
    snapshot = create_snapshot(
        LedgerSnapshotRequest(
            organization_id=payload.organization_id,
            account_id=payload.account_id,
            sheet_name=ledger["sheet_name"],
            period=payload.period,
            period_start=payload.period_start or ledger["period_start"],
            period_end=payload.period_end or ledger["period_end"],
            import_job_id=ledger_upload["id"],
            transactions=ledger["transactions"],
            evidence=evidence_rows,
        ),
        session,
        "workbook_upload",
        {
            "source_files": source_files,
            "ledger_summary": {key: value for key, value in ledger.items() if key != "transactions"},
            "bank_summary": {key: value for key, value in (bank or {}).items() if key not in {"transactions", "continuity_failures"}} or None,
            "bank_transactions": (bank or {}).get("transactions", []),
            "bank_continuity_failures": (bank or {}).get("continuity_failures", []),
            "reconciliation": reconciliation,
        },
    )
    audit(
        session,
        "workbook.imported",
        "ledger_snapshot",
        snapshot["id"],
        after={"ledger_upload_id": ledger_upload["id"], "bank_upload_id": payload.bank_upload_id, "reconciliation": reconciliation},
        request=request,
    )
    return {
        **snapshot_summary(snapshot),
        "transactions": snapshot["transactions"],
        "evidence": snapshot["evidence"],
        "ledger": {key: value for key, value in ledger.items() if key != "transactions"},
        "bank": {key: value for key, value in (bank or {}).items() if key not in {"transactions", "continuity_failures"}} or None,
        "reconciliation": reconciliation,
    }


@app.post("/ledger-snapshots")
def create_ledger_snapshot(
    payload: LedgerSnapshotRequest,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    return snapshot_summary(create_snapshot(payload, session))


@app.get("/ledger-snapshots")
def list_ledger_snapshots(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> list[dict]:
    return [snapshot_summary(item) for item in reversed(list(store.read_collection("ledger_snapshots").values()))]


@app.get("/ledger-snapshots/{snapshot_id}")
def get_ledger_snapshot(
    snapshot_id: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    snapshot = store.get("ledger_snapshots", snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    return snapshot


@app.post("/ledger-snapshots/{snapshot_id}/transactions")
def add_snapshot_transaction(
    snapshot_id: str,
    payload: TransactionInput,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    current = store.get("ledger_snapshots", snapshot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    transactions = [dict(item) for item in current.get("transactions", [])]
    if any(int(item["number"]) == payload.number for item in transactions):
        raise HTTPException(status_code=409, detail="Transaction number already exists")
    transactions.append(payload.model_dump(mode="json"))
    transactions.sort(key=lambda item: (str(item.get("date") or ""), int(item.get("number") or 0)))
    created = create_snapshot_revision(
        current,
        transactions,
        current.get("evidence", []),
        session,
        {"action": "transaction.created", "transaction_number": payload.number},
    )
    audit(session, "ledger.transaction.created", "ledger_snapshot", created["id"], before={"parent_snapshot_id": snapshot_id}, after={"transaction_number": payload.number}, request=request)
    return created


@app.put("/ledger-snapshots/{snapshot_id}/transactions/{transaction_key}")
def update_snapshot_transaction(
    snapshot_id: str,
    transaction_key: str,
    payload: TransactionPatchRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    current = store.get("ledger_snapshots", snapshot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    patch = payload.model_dump(exclude_none=True, mode="json")
    transactions = [dict(item) for item in current.get("transactions", [])]
    updated_number: int | None = None
    for index, item in enumerate(transactions):
        if item.get("transaction_id") == transaction_key or str(item.get("number")) == transaction_key:
            updated = {**item, **patch}
            updated_number = int(updated["number"])
            transactions[index] = updated
            break
    if updated_number is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    duplicate_numbers = [int(item["number"]) for item in transactions]
    if len(duplicate_numbers) != len(set(duplicate_numbers)):
        raise HTTPException(status_code=409, detail="Transaction number already exists")
    transactions.sort(key=lambda item: (str(item.get("date") or ""), int(item.get("number") or 0)))
    created = create_snapshot_revision(
        current,
        transactions,
        current.get("evidence", []),
        session,
        {"action": "transaction.updated", "transaction_key": transaction_key, "transaction_number": updated_number},
    )
    audit(session, "ledger.transaction.updated", "ledger_snapshot", created["id"], before={"parent_snapshot_id": snapshot_id, "transaction_key": transaction_key}, after={"patch": patch}, request=request)
    return created


@app.delete("/ledger-snapshots/{snapshot_id}/transactions/{transaction_key}")
def delete_snapshot_transaction(
    snapshot_id: str,
    transaction_key: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    current = store.get("ledger_snapshots", snapshot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    transactions = [dict(item) for item in current.get("transactions", [])]
    remaining = [item for item in transactions if item.get("transaction_id") != transaction_key and str(item.get("number")) != transaction_key]
    if len(remaining) == len(transactions):
        raise HTTPException(status_code=404, detail="Transaction not found")
    created = create_snapshot_revision(
        current,
        remaining,
        current.get("evidence", []),
        session,
        {"action": "transaction.deleted", "transaction_key": transaction_key},
    )
    audit(session, "ledger.transaction.deleted", "ledger_snapshot", created["id"], before={"parent_snapshot_id": snapshot_id, "transaction_key": transaction_key}, after={"transaction_count": len(remaining)}, request=request)
    return created


@app.post("/ledger-snapshots/{snapshot_id}/evidence")
def attach_snapshot_evidence(
    snapshot_id: str,
    payload: EvidenceAttachRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    current = store.get("ledger_snapshots", snapshot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    evidence_by_id = {item["id"]: item for item in current.get("evidence", [])}
    for evidence_id in payload.evidence_ids:
        item = store.get("evidence", evidence_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Evidence not found: {evidence_id}")
        evidence_by_id[evidence_id] = item

    transactions = [dict(item) for item in current["transactions"]]
    for transaction in transactions:
        linked = list(transaction.get("evidence_ids") or [])
        for item in evidence_by_id.values():
            if item.get("transaction_number") == transaction["number"] or transaction.get("transaction_id") in item.get("transaction_ids", []):
                if item["id"] not in linked:
                    linked.append(item["id"])
        transaction["evidence_ids"] = linked
    created = create_snapshot_revision(
        current,
        transactions,
        list(evidence_by_id.values()),
        session,
        {"action": "evidence.attached", "evidence_ids": payload.evidence_ids},
    )
    audit(
        session,
        "ledger_snapshot.evidence_attached",
        "ledger_snapshot",
        created["id"],
        before={"parent_snapshot_id": snapshot_id},
        after={"evidence_count": len(evidence_by_id)},
        request=request,
    )
    return created


@app.post(
    "/packages/submission",
    response_model=PackageJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_submission_package(
    payload: SubmissionPackageRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> PackageJobResponse:
    snapshot = resolve_snapshot_for_package(payload, session)
    related = [
        item
        for item in store.read_collection("packages").values()
        if item.get("organization_id") == payload.organization_id and item.get("semester") == payload.semester
    ]
    package = store.insert(
        "packages",
        {
            "organization_id": payload.organization_id,
            "club_name": payload.club_name,
            "semester": payload.semester,
            "version": len(related) + 1,
            "snapshot_id": snapshot["id"],
            "snapshot_hash": snapshot["data_hash"],
            "status": "generating",
            "created_by": session["username"],
        },
        "pkg",
    )
    payload_data = payload.model_dump(mode="json")

    def task() -> dict:
        latest_snapshot = store.get("ledger_snapshots", snapshot["id"])
        if not latest_snapshot:
            raise RuntimeError("Ledger snapshot disappeared before package generation")
        transactions = normalize_transactions(latest_snapshot["transactions"])
        evidence = normalize_evidence(latest_snapshot["evidence"])
        result = build_submission_package(
            OUTPUT_ROOT,
            package["id"],
            payload_data["club_name"],
            payload_data["semester"],
            payload_data["treasurer_name"],
            payload_data["president_name"],
            payload_data.get("reviewer_name"),
            payload_data["opening_balance"],
            payload_data.get("expected_closing_balance"),
            transactions,
            evidence,
            payload_data["row_capacity"],
            session["username"],
            latest_snapshot["id"],
            latest_snapshot["data_hash"],
            payload_data.get("period_start"),
            payload_data.get("period_end"),
            latest_snapshot.get("source", {}).get("bank_transactions", []),
            latest_snapshot.get("source", {}).get("reconciliation"),
            latest_snapshot.get("source", {}).get("source_files", []),
        )
        updated = store.update(
            "packages",
            package["id"],
            {
                "status": "draft",
                "zip_path": result["zip_path"],
                "zip_sha256": result["zip_sha256"],
                "manifest_sha256": result["manifest_sha256"],
                "validation": result["validation"],
                "artifacts": result["artifacts"],
                "document_coverage": result["document_coverage"],
                "row_capacity": result["row_capacity"],
                "generated_at": utc_now(),
            },
        )
        audit(session, "package.generated", "package", package["id"], after={"status": "draft", "zip_sha256": result["zip_sha256"]})
        return {"package_id": package["id"], "status": updated["status"], "download_url": f"/packages/{package['id']}/download"}

    job = jobs.submit("submission_package", session, task)
    store.update("packages", package["id"], {"job_id": job["id"]})
    store.update("jobs", job["id"], {"package_id": package["id"], "snapshot_id": snapshot["id"]})
    audit(session, "package.requested", "package", package["id"], after={"job_id": job["id"], "snapshot_id": snapshot["id"]}, request=request)
    return PackageJobResponse(
        job_id=job["id"],
        package_id=package["id"],
        snapshot_id=snapshot["id"],
        status="pending",
        status_url=f"/jobs/{job['id']}",
    )


@app.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    job = store.get("jobs", job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/packages")
def list_packages(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> list[dict]:
    return list(reversed(list(store.read_collection("packages").values())))


@app.get("/packages/{package_id}")
def get_package(
    package_id: str,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    package = store.get("packages", package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package


@app.post("/packages/{package_id}/acknowledge")
def acknowledge_package_issues(
    package_id: str,
    payload: AcknowledgeIssuesRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> dict:
    package = store.get("packages", package_id)
    if not package or not package.get("validation"):
        raise HTTPException(status_code=404, detail="Package validation not found")
    validation = acknowledge_issues(package["validation"], set(payload.issue_codes), session["username"], payload.note)
    updated = store.update("packages", package_id, {"validation": validation})
    audit(session, "package.issues_acknowledged", "package", package_id, before=package, after={"validation": validation}, request=request)
    return updated


@app.post("/packages/{package_id}/submit-review")
def submit_package_review(
    package_id: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> dict:
    package = store.get("packages", package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if package.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Only draft packages can be submitted for review")
    updated = store.update("packages", package_id, {"status": "pending_review", "submitted_at": utc_now(), "submitted_by": session["username"]})
    audit(session, "package.review_submitted", "package", package_id, before=package, after=updated, request=request)
    return updated


@app.post("/packages/{package_id}/approve")
def approve_package(
    package_id: str,
    payload: PackageReviewRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.president, Role.reviewer)),
) -> dict:
    package = store.get("packages", package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if package.get("status") != "pending_review":
        raise HTTPException(status_code=409, detail="Package is not pending review")
    validation = package.get("validation", {})
    if validation.get("error_count", 0) or validation.get("warning_count", 0):
        raise HTTPException(status_code=409, detail="Errors and unacknowledged warnings must be resolved before approval")
    for previous in store.read_collection("packages").values():
        if previous["id"] != package_id and previous.get("organization_id") == package.get("organization_id") and previous.get("semester") == package.get("semester") and previous.get("status") == "approved":
            store.update("packages", previous["id"], {"status": "superseded", "superseded_by": package_id})
    updated = store.update(
        "packages",
        package_id,
        {"status": "approved", "approved_at": utc_now(), "approved_by": session["username"], "review_note": payload.reason},
    )
    audit(session, "package.approved", "package", package_id, before=package, after=updated, request=request)
    return updated


@app.post("/packages/{package_id}/reject")
def reject_package(
    package_id: str,
    payload: PackageReviewRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.president, Role.reviewer)),
) -> dict:
    package = store.get("packages", package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if package.get("status") != "pending_review":
        raise HTTPException(status_code=409, detail="Package is not pending review")
    updated = store.update("packages", package_id, {"status": "rejected", "rejected_at": utc_now(), "rejected_by": session["username"], "review_note": payload.reason})
    audit(session, "package.rejected", "package", package_id, before=package, after=updated, request=request)
    return updated


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
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> MonthlyReportResponse:
    if payload.snapshot_id:
        snapshot = store.get("ledger_snapshots", payload.snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Ledger snapshot not found")
    else:
        snapshot = create_snapshot(
            LedgerSnapshotRequest(
                organization_id=payload.organization_id,
                account_id=payload.account_id,
                period=payload.month,
                transactions=payload.transactions,
                evidence=payload.evidence,
            ),
            session,
        )
    share_id = secrets.token_urlsafe(32)
    transactions = normalize_transactions(snapshot["transactions"])
    report_payload = build_monthly_report_payload(
        "pending",
        share_id,
        payload.club_name,
        payload.month,
        payload.opening_balance,
        transactions,
        payload.visible_notes,
        snapshot["id"],
        payload.expires_at.isoformat() if payload.expires_at else None,
        payload.allow_download,
    )
    report = store.insert("monthly_reports", report_payload, "rep")
    public_url = f"{PUBLIC_FRONTEND_BASE_URL}/public/monthly/{share_id}"
    audit(session, "monthly_report.created", "monthly_report", report["id"], after={"snapshot_id": snapshot["id"], "expires_at": report.get("expires_at")}, request=request)
    return MonthlyReportResponse(
        report_id=report["id"],
        snapshot_id=snapshot["id"],
        share_id=share_id,
        public_url=public_url,
        expires_at=payload.expires_at,
        summary=report["summary"],
    )


@app.get("/monthly-reports")
def list_monthly_reports(
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president, Role.reviewer)),
) -> list[dict]:
    return list(reversed(list(store.read_collection("monthly_reports").values())))


@app.get("/public/monthly/{share_id}")
def get_public_monthly_report(share_id: str, request: Request) -> JSONResponse:
    report = store.find_one_by("monthly_reports", "share_id", share_id)
    if not report:
        raise HTTPException(status_code=404, detail="Monthly report not found")
    if report.get("status") == "revoked":
        raise HTTPException(status_code=410, detail="This public link has been revoked")
    if report.get("expires_at"):
        expires_at = datetime.fromisoformat(report["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="This public link has expired")
    store.insert(
        "public_access_logs",
        {
            "report_id": report["id"],
            "request_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        },
        "access",
    )
    payload = {
        "club_name": report["club_name"],
        "month": report["month"],
        "share_id": report["share_id"],
        "summary": report["summary"],
        "transactions": report["transactions"],
        "expires_at": report.get("expires_at"),
        "allow_download": report.get("allow_download", False),
    }
    return JSONResponse(payload, headers={"X-Robots-Tag": "noindex, nofollow, noarchive"})


@app.post("/monthly-reports/{report_id}/revoke")
def revoke_monthly_report(
    report_id: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> dict:
    report = store.get("monthly_reports", report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Monthly report not found")
    updated = store.update("monthly_reports", report_id, {"status": "revoked", "revoked_at": utc_now(), "revoked_by": session["username"]})
    audit(session, "monthly_report.revoked", "monthly_report", report_id, before=report, after=updated, request=request)
    return updated


@app.post("/monthly-reports/{report_id}/regenerate-link")
def regenerate_monthly_link(
    report_id: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> dict:
    report = store.get("monthly_reports", report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Monthly report not found")
    share_id = secrets.token_urlsafe(32)
    updated = store.update("monthly_reports", report_id, {"share_id": share_id, "status": "active", "regenerated_at": utc_now()})
    audit(session, "monthly_report.link_regenerated", "monthly_report", report_id, before={"share_id": report["share_id"]}, after={"share_id": share_id}, request=request)
    return {"report_id": report_id, "share_id": share_id, "public_url": f"{PUBLIC_FRONTEND_BASE_URL}/public/monthly/{share_id}", "status": updated["status"]}


@app.post("/discord/webhooks")
def create_discord_webhook(
    payload: DiscordWebhookRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant)),
) -> dict:
    url = str(payload.webhook_url)
    webhook = store.insert(
        "discord_webhooks",
        {"name": payload.name, "encrypted_webhook_url": secret_box.encrypt(url), "masked_url": mask_webhook_url(url)},
        "webhook",
    )
    audit(session, "discord.webhook_created", "discord_webhook", webhook["id"], after=webhook, request=request)
    return {"id": webhook["id"], "name": webhook["name"], "masked_url": webhook["masked_url"]}


@app.post("/discord/messages/preview", response_model=DiscordMessageResponse)
def preview_discord_message(
    payload: DiscordPreviewRequest,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> DiscordMessageResponse:
    report = store.find_one_by("monthly_reports", "share_id", payload.share_id)
    webhook = store.get("discord_webhooks", payload.webhook_id)
    if not report or report.get("status") != "active":
        raise HTTPException(status_code=404, detail="Active monthly report not found")
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    public_url = f"{PUBLIC_FRONTEND_BASE_URL}/public/monthly/{payload.share_id}"
    preview = render_monthly_discord_message(report, public_url)
    message = store.insert(
        "discord_messages",
        {
            "report_id": report["id"],
            "report_content_hash": report["content_hash"],
            "share_id": payload.share_id,
            "webhook_id": payload.webhook_id,
            "status": "pending_approval",
            "preview": preview,
            "preview_hash": canonical_sha256(preview),
            "idempotency_key": secrets.token_urlsafe(18),
            "send_attempts": 0,
        },
        "msg",
    )
    audit(session, "discord.message_previewed", "discord_message", message["id"], after={"status": message["status"], "preview_hash": message["preview_hash"]}, request=request)
    return DiscordMessageResponse(message_id=message["id"], status=message["status"], preview=preview)


@app.post("/discord/messages/{message_id}/approve", response_model=DiscordMessageResponse)
def approve_discord_message(
    message_id: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.president, Role.reviewer)),
) -> DiscordMessageResponse:
    message = store.get("discord_messages", message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    report = store.get("monthly_reports", message["report_id"])
    if not report or report.get("content_hash") != message.get("report_content_hash"):
        raise HTTPException(status_code=409, detail="Report content changed; create and approve a new preview")
    updated = store.update("discord_messages", message_id, {"status": "approved", "approved_at": utc_now(), "approved_by": session["username"]})
    audit(session, "discord.message_approved", "discord_message", message_id, before=message, after=updated, request=request)
    return DiscordMessageResponse(message_id=message_id, status=updated["status"], preview=updated["preview"], approved_at=updated.get("approved_at"))


@app.post("/discord/messages/{message_id}/send", response_model=DiscordMessageResponse)
def send_discord_message(
    message_id: str,
    request: Request,
    session: dict = Depends(require_roles(Role.admin, Role.accountant, Role.president)),
) -> DiscordMessageResponse:
    message = store.get("discord_messages", message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.get("status") == "sent":
        return DiscordMessageResponse(message_id=message_id, status="sent", preview=message["preview"], approved_at=message.get("approved_at"), sent_at=message.get("sent_at"))
    if message.get("status") not in {"approved", "failed"}:
        raise HTTPException(status_code=409, detail="Message must be approved before sending")
    webhook = store.get("discord_webhooks", message["webhook_id"])
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    webhook_url = secret_box.decrypt(webhook.get("encrypted_webhook_url"))
    if not webhook_url:
        raise HTTPException(status_code=409, detail="Webhook secret is unavailable")
    result = send_webhook(webhook_url, message["preview"])
    next_status = "sent" if result.get("ok") else "failed"
    updated = store.update(
        "discord_messages",
        message_id,
        {
            "status": next_status,
            "send_result": result,
            "send_attempts": int(message.get("send_attempts", 0)) + 1,
            "sent_at": result.get("sent_at"),
        },
    )
    audit(session, "discord.message_sent", "discord_message", message_id, before={"status": message.get("status")}, after={"status": next_status}, success=result.get("ok", False), request=request)
    return DiscordMessageResponse(message_id=message_id, status=updated["status"], preview=updated["preview"], approved_at=updated.get("approved_at"), sent_at=updated.get("sent_at"))


@app.get("/audit-logs")
def list_audit_logs(
    session: dict = Depends(require_roles(Role.admin, Role.reviewer)),
) -> dict:
    rows = list(reversed(list(store.read_collection("audit_logs").values())))
    return {"chain": store.verify_audit_chain(), "events": rows[:500]}
