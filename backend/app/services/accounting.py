from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


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


@dataclass(frozen=True)
class Evidence:
    id: str
    transaction_number: int | None
    filename: str
    kind: str
    url: str | None = None
    local_path: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
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


def normalize_transactions(rows: Iterable[dict]) -> list[Transaction]:
    transactions: list[Transaction] = []
    for row in rows:
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
            )
        )
    return sorted(transactions, key=lambda item: item.number)


def normalize_evidence(rows: Iterable[dict]) -> list[Evidence]:
    return [
        Evidence(
            id=str(row["id"]),
            transaction_number=row.get("transaction_number"),
            filename=str(row["filename"]),
            kind=str(row.get("kind") or "other"),
            url=row.get("url"),
            local_path=row.get("local_path"),
        )
        for row in rows
    ]


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


def validate_ledger(
    opening_balance: int,
    transactions: list[Transaction],
    evidence: list[Evidence],
    expected_closing_balance: int | None = None,
) -> dict:
    issues: list[ValidationIssue] = []
    seen_numbers: set[int] = set()
    evidence_by_id = {item.id for item in evidence}
    evidence_by_transaction = {
        item.transaction_number for item in evidence if item.transaction_number is not None
    }

    previous_balance = opening_balance
    for tx in transactions:
        if tx.number in seen_numbers:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_TRANSACTION_NUMBER",
                    severity="error",
                    message=f"{tx.number}번 거래가 중복되었습니다.",
                    transaction_number=tx.number,
                )
            )
        seen_numbers.add(tx.number)

        if tx.income < 0 or tx.expense < 0:
            issues.append(
                ValidationIssue(
                    code="NEGATIVE_AMOUNT",
                    severity="error",
                    message="수입/지출 금액은 음수일 수 없습니다.",
                    transaction_number=tx.number,
                )
            )

        if tx.income and tx.expense:
            issues.append(
                ValidationIssue(
                    code="BOTH_INCOME_AND_EXPENSE",
                    severity="error",
                    message="한 거래에 수입과 지출이 동시에 입력되었습니다.",
                    transaction_number=tx.number,
                )
            )

        if not tx.income and not tx.expense:
            issues.append(
                ValidationIssue(
                    code="MISSING_AMOUNT",
                    severity="warning",
                    message="수입 또는 지출 금액이 입력되지 않았습니다.",
                    transaction_number=tx.number,
                )
            )

        expected_balance = previous_balance + tx.income - tx.expense
        if tx.balance != expected_balance:
            issues.append(
                ValidationIssue(
                    code="BALANCE_CONTINUITY",
                    severity="error",
                    message=f"장부 잔액 {tx.balance:,}원이 계산 잔액 {expected_balance:,}원과 다릅니다.",
                    transaction_number=tx.number,
                )
            )
        previous_balance = tx.balance

        if tx.expense and not tx.evidence_id and tx.number not in evidence_by_transaction:
            issues.append(
                ValidationIssue(
                    code="MISSING_EXPENSE_EVIDENCE",
                    severity="error",
                    message="지출 거래에 영수증 또는 소명자료가 연결되지 않았습니다.",
                    transaction_number=tx.number,
                )
            )
        if tx.evidence_id and tx.evidence_id not in evidence_by_id:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_EVIDENCE",
                    severity="error",
                    message=f"연결된 증빙자료 {tx.evidence_id}를 찾을 수 없습니다.",
                    transaction_number=tx.number,
                )
            )

    summary = summarize_ledger(opening_balance, transactions, evidence, expected_closing_balance)
    if summary.reported_closing_balance is not None and (
        summary.computed_closing_balance != summary.reported_closing_balance
    ):
        issues.append(
            ValidationIssue(
                code="CLOSING_BALANCE_MISMATCH",
                severity="error",
                message=(
                    "이전잔액 + 수입총액 - 지출총액이 최종잔액과 일치하지 않습니다: "
                    f"{summary.computed_closing_balance:,}원 != {summary.reported_closing_balance:,}원"
                ),
            )
        )

    error_count = sum(1 for item in issues if item.severity == "error")
    warning_count = sum(1 for item in issues if item.severity == "warning")
    return {
        "status": "passed" if error_count == 0 else "failed",
        "summary": asdict(summary),
        "issues": [asdict(item) for item in issues],
        "error_count": error_count,
        "warning_count": warning_count,
    }


def public_monthly_summary(opening_balance: int, transactions: list[Transaction]) -> dict:
    income_total = sum(item.income for item in transactions)
    expense_total = sum(item.expense for item in transactions)
    def public_item(item: Transaction) -> dict:
        return {
            "number": item.number,
            "date": item.date,
            "description": item.description,
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
