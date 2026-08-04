from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Role(str, Enum):
    admin = "admin"
    accountant = "accountant"
    president = "president"
    reviewer = "reviewer"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    role: Role
    password: str | None = None


class AuthSession(BaseModel):
    token: str
    username: str
    role: Role


class GoogleConnectRequest(BaseModel):
    account_email: str | None = None
    authorization_code: str | None = None
    redirect_uri: str | None = None
    state: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    scopes: list[str] = Field(default_factory=list)


class TransactionInput(BaseModel):
    transaction_id: str | None = None
    organization_id: str = "aegis"
    account_id: str = "primary"
    period: str | None = None
    number: int
    date: str
    description: str
    income: int = 0
    expense: int = 0
    balance: int
    category: str = "미분류"
    counterparty: str | None = None
    note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None
    source_row: str | None = None
    source_row_hash: str | None = None


class EvidenceInput(BaseModel):
    id: str
    transaction_ids: list[str] = Field(default_factory=list)
    transaction_number: int | None = None
    account_id: str = "primary"
    drive_file_id: str | None = None
    filename: str
    mime_type: str | None = None
    size: int | None = None
    modified_time: str | None = None
    sha256: str | None = None
    kind: Literal["receipt", "explanation", "account_capture", "other"] = "other"
    amount: int | None = None
    evidence_date: str | None = None
    accessible: bool = True
    last_verified_at: str | None = None
    url: str | None = None
    local_path: str | None = None


class LedgerSnapshotRequest(BaseModel):
    organization_id: str = "aegis"
    account_id: str = "primary"
    spreadsheet_id: str | None = None
    sheet_name: str | None = None
    period: str
    period_start: str | None = None
    period_end: str | None = None
    source_modified_time: str | None = None
    import_job_id: str | None = None
    transactions: list[TransactionInput]
    evidence: list[EvidenceInput] = Field(default_factory=list)


class WorkbookSnapshotRequest(BaseModel):
    ledger_upload_id: str
    bank_upload_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    organization_id: str = "aegis"
    account_id: str = "primary"
    period: str
    period_start: str | None = None
    period_end: str | None = None
    sheet_name: str | None = None
    opening_balance: int = 0


class EvidenceAttachRequest(BaseModel):
    evidence_ids: list[str]


class TransactionPatchRequest(BaseModel):
    number: int | None = None
    date: str | None = None
    description: str | None = None
    income: int | None = None
    expense: int | None = None
    balance: int | None = None
    category: str | None = None
    counterparty: str | None = None
    note: str | None = None
    evidence_ids: list[str] | None = None
    evidence_id: str | None = None


class SubmissionPackageRequest(BaseModel):
    club_name: str = "Aegis"
    organization_id: str = "aegis"
    account_id: str = "primary"
    semester: str
    period_start: str | None = None
    period_end: str | None = None
    spreadsheet_id: str | None = None
    sheet_name: str | None = None
    source_modified_time: str | None = None
    snapshot_id: str | None = None
    treasurer_name: str
    president_name: str
    reviewer_name: str | None = None
    opening_balance: int
    expected_closing_balance: int | None = None
    row_capacity: Literal[40, 80, 120] = 40
    transactions: list[TransactionInput] = Field(default_factory=list)
    evidence: list[EvidenceInput] = Field(default_factory=list)


class PackageJobResponse(BaseModel):
    job_id: str
    package_id: str
    snapshot_id: str
    status: str
    status_url: str


class PackageReviewRequest(BaseModel):
    reason: str | None = None


class AcknowledgeIssuesRequest(BaseModel):
    issue_codes: list[str]
    note: str = ""


class MonthlyReportRequest(BaseModel):
    club_name: str = "Aegis"
    organization_id: str = "aegis"
    account_id: str = "primary"
    month: str
    snapshot_id: str | None = None
    opening_balance: int
    transactions: list[TransactionInput] = Field(default_factory=list)
    evidence: list[EvidenceInput] = Field(default_factory=list)
    visible_notes: bool = False
    expires_at: datetime | None = None
    allow_download: bool = False


class MonthlyReportResponse(BaseModel):
    report_id: str
    snapshot_id: str
    share_id: str
    public_url: str
    expires_at: datetime | None = None
    summary: dict


class DiscordWebhookRequest(BaseModel):
    name: str
    webhook_url: HttpUrl


class DiscordPreviewRequest(BaseModel):
    share_id: str
    webhook_id: str


class DiscordMessageResponse(BaseModel):
    message_id: str
    status: str
    preview: str
    approved_at: str | None = None
    sent_at: str | None = None


class GoogleSheetSnapshotRequest(BaseModel):
    range: str = "A:G"
    period: str
    period_start: str | None = None
    period_end: str | None = None
    organization_id: str = "aegis"
    account_id: str = "primary"
    opening_balance: int = 0


EvidenceKind = Literal["receipt", "explanation", "account_capture", "other"]
