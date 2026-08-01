from __future__ import annotations

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


class AuthSession(BaseModel):
    token: str
    username: str
    role: Role


class GoogleConnectRequest(BaseModel):
    account_email: str
    access_token: str | None = None
    refresh_token: str | None = None
    scopes: list[str] = []


class TransactionInput(BaseModel):
    number: int
    date: str
    description: str
    income: int = 0
    expense: int = 0
    balance: int
    note: str = ""
    evidence_id: str | None = None
    source_row: str | None = None


class EvidenceInput(BaseModel):
    id: str
    transaction_number: int | None = None
    filename: str
    kind: Literal["receipt", "explanation", "account_capture", "other"] = "other"
    url: str | None = None
    local_path: str | None = None


class SubmissionPackageRequest(BaseModel):
    club_name: str = "Aegis"
    semester: str
    treasurer_name: str
    president_name: str
    reviewer_name: str | None = None
    opening_balance: int
    expected_closing_balance: int | None = None
    row_capacity: Literal[40, 80, 120] = 40
    transactions: list[TransactionInput]
    evidence: list[EvidenceInput] = []


class SubmissionPackageResponse(BaseModel):
    package_id: str
    zip_path: str
    download_url: str
    validation: dict
    artifacts: list[dict]


class MonthlyReportRequest(BaseModel):
    club_name: str = "Aegis"
    month: str
    opening_balance: int
    transactions: list[TransactionInput]
    visible_notes: bool = False


class MonthlyReportResponse(BaseModel):
    report_id: str
    share_id: str
    public_url: str
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
    sent_at: str | None = None
