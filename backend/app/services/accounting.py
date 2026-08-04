from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Iterable

from .integrity import canonical_sha256


VALIDATION_RULE_VERSION = "atlas-ledger-v1.2"


@dataclass(frozen=True)
class Transaction:
    number: int
    date: str
    description: str
    income: int
    expense: int
    balance: int
    note: str = ""
    evidence_id: str | None = None
    source_row: str | None = None
    transaction_id: str | None = None
    organization_id: str = "aegis"
    account_id: str = "primary"
    period: str | None = None
    category: str = "미분류"
    counterparty: str | None = None
    evidence_ids: tuple[str, ...] = ()
    source_row_hash: str | None = None


@dataclass(frozen=True)
class Evidence:
    id: str
    transaction_number: int | None
    filename: str
    kind: str
    account_id: str = "primary"
    url: str | None = None
    local_path: str | None = None
    transaction_ids: tuple[str, ...] = ()
    drive_file_id: str | None = None
    mime_type: str | None = None
    size: int | None = None
    modified_time: str | None = None
    sha256: str | None = None
    amount: int | None = None
    evidence_date: str | None = None
    accessible: bool = True
    last_verified_at: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    status: str
    message: str
    transaction_id: str | None = None
    transaction_number: int | None = None


@dataclass(frozen=True)
class LedgerSummary:
    opening_balance: int
    total_income: int
    total_expense: int
    computed_closing_balance: int
    reported_closing_balance: int | None
    transaction_count: int
    evidence_count: int


def _transaction_identity(row: dict) -> tuple[str, str]:
    row_payload = {
        "number": row.get("number"),
        "date": row.get("date"),
        "description": str(row.get("description") or "").strip(),
        "income": int(row.get("income") or 0),
        "expense": int(row.get("expense") or 0),
        "balance": int(row.get("balance") or 0),
        "source_row": row.get("source_row"),
    }
    row_hash = row.get("source_row_hash") or canonical_sha256(row_payload)
    transaction_id = row.get("transaction_id") or f"tx_{row_hash[:16]}"
    return transaction_id, row_hash


def normalize_transactions(rows: Iterable[dict]) -> list[Transaction]:
    transactions: list[Transaction] = []
    for row in rows:
        transaction_id, row_hash = _transaction_identity(row)
        evidence_ids = [str(item) for item in row.get("evidence_ids") or []]
        if row.get("evidence_id") and row["evidence_id"] not in evidence_ids:
            evidence_ids.append(str(row["evidence_id"]))
        transactions.append(
            Transaction(
                number=int(row["number"]),
                date=str(row["date"]),
                description=str(row["description"]).strip(),
                income=int(row.get("income") or 0),
                expense=int(row.get("expense") or 0),
                balance=int(row["balance"]),
                note=str(row.get("note") or ""),
                evidence_id=row.get("evidence_id"),
                source_row=row.get("source_row"),
                transaction_id=transaction_id,
                organization_id=str(row.get("organization_id") or "aegis"),
                account_id=str(row.get("account_id") or "primary"),
                period=row.get("period"),
                category=str(row.get("category") or "미분류"),
                counterparty=row.get("counterparty"),
                evidence_ids=tuple(evidence_ids),
                source_row_hash=row_hash,
            )
        )
    return transactions


def normalize_evidence(rows: Iterable[dict]) -> list[Evidence]:
    return [
        Evidence(
            id=str(row["id"]),
            transaction_number=row.get("transaction_number"),
            filename=str(row["filename"]),
            kind=str(row.get("kind") or "other"),
            account_id=str(row.get("account_id") or "primary"),
            url=row.get("url"),
            local_path=row.get("local_path"),
            transaction_ids=tuple(str(item) for item in row.get("transaction_ids") or []),
            drive_file_id=row.get("drive_file_id"),
            mime_type=row.get("mime_type"),
            size=row.get("size"),
            modified_time=row.get("modified_time"),
            sha256=row.get("sha256"),
            amount=row.get("amount"),
            evidence_date=row.get("evidence_date"),
            accessible=bool(row.get("accessible", True)),
            last_verified_at=row.get("last_verified_at"),
        )
        for row in rows
    ]


def snapshot_payload(
    organization_id: str,
    account_id: str,
    period: str,
    transactions: list[Transaction],
    evidence: list[Evidence],
    source: dict,
) -> dict:
    data = {
        "organization_id": organization_id,
        "account_id": account_id,
        "period": period,
        "source": source,
        "transactions": [asdict(item) for item in transactions],
        "evidence": [asdict(item) for item in evidence],
    }
    return {**data, "data_hash": canonical_sha256(data)}


def summarize_ledger(
    opening_balance: int,
    transactions: list[Transaction],
    evidence: list[Evidence],
    expected_closing_balance: int | None = None,
) -> LedgerSummary:
    total_income = sum(item.income for item in transactions)
    total_expense = sum(item.expense for item in transactions)
    computed = opening_balance + total_income - total_expense
    reported = expected_closing_balance
    if reported is None and transactions:
        reported = transactions[-1].balance
    return LedgerSummary(
        opening_balance=opening_balance,
        total_income=total_income,
        total_expense=total_expense,
        computed_closing_balance=computed,
        reported_closing_balance=reported,
        transaction_count=len(transactions),
        evidence_count=len(evidence),
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def validate_ledger(
    opening_balance: int,
    transactions: list[Transaction],
    evidence: list[Evidence],
    expected_closing_balance: int | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    reconciliation: dict | None = None,
) -> dict:
    issues: list[ValidationIssue] = []
    seen_numbers: set[int] = set()
    seen_fingerprints: set[str] = set()
    evidence_by_id = {item.id: item for item in evidence}
    transaction_by_number = {item.number: item for item in transactions}
    links: dict[str, set[str]] = {item.id: set(item.transaction_ids) for item in evidence}
    for item in evidence:
        if item.transaction_number in transaction_by_number:
            tx_id = transaction_by_number[item.transaction_number].transaction_id
            if tx_id:
                links[item.id].add(tx_id)
    for tx in transactions:
        for evidence_id in tx.evidence_ids:
            links.setdefault(evidence_id, set()).add(tx.transaction_id or str(tx.number))

    start_date = _parse_date(period_start)
    end_date = _parse_date(period_end)
    previous_balance = opening_balance
    previous_number: int | None = None
    previous_date: date | None = None

    for tx in transactions:
        issue_context = {"transaction_id": tx.transaction_id, "transaction_number": tx.number}
        tx_date = _parse_date(tx.date)
        if tx.number in seen_numbers:
            issues.append(ValidationIssue("DUPLICATE_TRANSACTION_NUMBER", "ERROR", "ERROR", f"{tx.number}번 거래가 중복되었습니다.", **issue_context))
        seen_numbers.add(tx.number)

        fingerprint = canonical_sha256({"date": tx.date, "description": tx.description, "income": tx.income, "expense": tx.expense, "balance": tx.balance})
        if fingerprint in seen_fingerprints:
            issues.append(ValidationIssue("DUPLICATE_TRANSACTION", "ERROR", "ERROR", "동일한 거래 내용이 중복 입력되었습니다.", **issue_context))
        seen_fingerprints.add(fingerprint)

        if previous_number is not None and tx.number <= previous_number:
            issues.append(ValidationIssue("TRANSACTION_ORDER", "ERROR", "ERROR", "거래 번호 순서가 올바르지 않습니다.", **issue_context))
        if tx_date and previous_date and tx_date < previous_date:
            issues.append(ValidationIssue("TRANSACTION_DATE_ORDER", "WARNING", "WARNING", "거래 날짜가 이전 거래보다 빠릅니다.", **issue_context))
        previous_number = tx.number
        previous_date = tx_date or previous_date

        if not tx_date:
            issues.append(ValidationIssue("INVALID_TRANSACTION_DATE", "ERROR", "ERROR", "거래 날짜 형식을 확인해야 합니다.", **issue_context))
        elif (start_date and tx_date < start_date) or (end_date and tx_date > end_date):
            issues.append(ValidationIssue("OUTSIDE_ACCOUNTING_PERIOD", "ERROR", "ERROR", "회계 기간 밖의 거래입니다.", **issue_context))

        if tx.income < 0 or tx.expense < 0:
            issues.append(ValidationIssue("NEGATIVE_AMOUNT", "ERROR", "ERROR", "수입/지출 금액은 음수일 수 없습니다.", **issue_context))
        if tx.income and tx.expense:
            issues.append(ValidationIssue("BOTH_INCOME_AND_EXPENSE", "ERROR", "ERROR", "한 거래에 수입과 지출이 동시에 입력되었습니다.", **issue_context))
        if not tx.income and not tx.expense:
            issues.append(ValidationIssue("MISSING_AMOUNT", "WARNING", "WARNING", "수입 또는 지출 금액이 입력되지 않았습니다.", **issue_context))

        expected_balance = previous_balance + tx.income - tx.expense
        if tx.balance != expected_balance:
            issues.append(ValidationIssue("BALANCE_CONTINUITY", "ERROR", "ERROR", f"장부 잔액 {tx.balance:,}원이 계산 잔액 {expected_balance:,}원과 다릅니다.", **issue_context))
        previous_balance = tx.balance

        linked_ids = set(tx.evidence_ids)
        linked_ids.update(item.id for item in evidence if tx.transaction_id in item.transaction_ids or item.transaction_number == tx.number)
        if tx.expense and not linked_ids:
            issues.append(ValidationIssue("MISSING_EXPENSE_EVIDENCE", "ERROR", "ERROR", "지출 거래에 영수증 또는 소명자료가 연결되지 않았습니다.", **issue_context))
        for evidence_id in linked_ids:
            item = evidence_by_id.get(evidence_id)
            if not item:
                issues.append(ValidationIssue("UNKNOWN_EVIDENCE", "ERROR", "ERROR", f"연결된 증빙자료 {evidence_id}를 찾을 수 없습니다.", **issue_context))
                continue
            if not item.accessible:
                issues.append(ValidationIssue("EVIDENCE_INACCESSIBLE", "ERROR", "ERROR", f"증빙자료 {item.filename}에 접근할 수 없습니다.", **issue_context))
            if item.amount is not None and tx.expense and item.amount != tx.expense:
                issues.append(ValidationIssue("EVIDENCE_AMOUNT_MISMATCH", "WARNING", "WARNING", f"증빙 금액 {item.amount:,}원이 거래 금액 {tx.expense:,}원과 다릅니다.", **issue_context))
            if item.evidence_date and tx_date and _parse_date(item.evidence_date) != tx_date:
                issues.append(ValidationIssue("EVIDENCE_DATE_MISMATCH", "WARNING", "WARNING", f"증빙 날짜 {item.evidence_date}가 거래 날짜 {tx.date}와 다릅니다.", **issue_context))

    for evidence_id, transaction_ids in links.items():
        if len(transaction_ids) > 1:
            issues.append(ValidationIssue("DUPLICATE_EVIDENCE_LINK", "ERROR", "ERROR", f"증빙자료 {evidence_id}가 여러 거래에 중복 연결되었습니다."))

    summary = summarize_ledger(opening_balance, transactions, evidence, expected_closing_balance)
    if summary.reported_closing_balance is not None and summary.computed_closing_balance != summary.reported_closing_balance:
        issues.append(ValidationIssue("CLOSING_BALANCE_MISMATCH", "ERROR", "ERROR", "이전잔액 + 수입총액 - 지출총액이 최종잔액과 일치하지 않습니다."))
    if reconciliation and reconciliation.get("balance_delta") not in (None, 0):
        issues.append(
            ValidationIssue(
                "BANK_BALANCE_MISMATCH",
                "ERROR",
                "ERROR",
                f"장부와 은행 거래내역의 마감잔액이 {abs(int(reconciliation['balance_delta'])):,}원 차이납니다.",
            )
        )
    if reconciliation and reconciliation.get("bank_continuity_failure_count", 0):
        issues.append(ValidationIssue("BANK_BALANCE_CONTINUITY", "ERROR", "ERROR", "은행 거래내역의 거래 후 잔액 연속성이 올바르지 않습니다."))

    error_count = sum(1 for item in issues if item.severity == "ERROR")
    warning_count = sum(1 for item in issues if item.severity == "WARNING")
    status = "ERROR" if error_count else ("WARNING" if warning_count else "PASS")
    return {
        "status": status,
        "rule_version": VALIDATION_RULE_VERSION,
        "summary": asdict(summary),
        "issues": [asdict(item) for item in issues],
        "error_count": error_count,
        "warning_count": warning_count,
        "acknowledged_count": 0,
        "reconciliation": reconciliation,
    }


def acknowledge_issues(validation: dict, issue_codes: set[str], actor: str, note: str) -> dict:
    issues = []
    for item in validation.get("issues", []):
        if item.get("code") in issue_codes and item.get("severity") == "WARNING":
            issues.append({**item, "status": "ACKNOWLEDGED", "acknowledged_by": actor, "acknowledgement_note": note})
        else:
            issues.append(item)
    acknowledged = sum(1 for item in issues if item.get("status") == "ACKNOWLEDGED")
    remaining_warnings = sum(1 for item in issues if item.get("status") == "WARNING")
    result = {**validation, "issues": issues, "acknowledged_count": acknowledged, "warning_count": remaining_warnings}
    if result.get("error_count", 0) == 0:
        result["status"] = "WARNING" if remaining_warnings else "PASS"
    return result


def public_monthly_summary(opening_balance: int, transactions: list[Transaction]) -> dict:
    income_total = sum(item.income for item in transactions)
    expense_total = sum(item.expense for item in transactions)

    def public_item(item: Transaction) -> dict:
        return {
            "number": item.number,
            "date": item.date,
            "description": item.description,
            "category": item.category,
            "income": item.income,
            "expense": item.expense,
            "balance": item.balance,
        }

    categories = {
        "income": [public_item(item) for item in transactions if item.income],
        "expense": [public_item(item) for item in transactions if item.expense],
    }
    return {
        "opening_balance": opening_balance,
        "total_income": income_total,
        "total_expense": expense_total,
        "closing_balance": opening_balance + income_total - expense_total,
        "transaction_count": len(transactions),
        "categories": categories,
    }
