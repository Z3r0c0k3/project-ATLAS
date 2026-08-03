from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .integrity import canonical_sha256, file_sha256


class WorkbookParseError(ValueError):
    pass


LEDGER_HEADERS = {"날짜", "내용", "수입", "지출"}
BANK_HEADERS = {"거래 일시", "적요", "거래 금액", "거래 후 잔액"}


def _label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = _label(value)
    if not text:
        return None
    for pattern in (
        "%Y.%m.%d %H:%M:%S",
        "%Y. %m. %d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d",
        "%Y. %m. %d",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _money(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(round(value))
    text = _label(value).replace(",", "").replace("원", "").replace("₩", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = int(round(float(text)))
    except ValueError as exc:
        raise WorkbookParseError(f"금액을 숫자로 읽을 수 없습니다: {value}") from exc
    return -number if negative else number


def _find_header(sheet, required: set[str]) -> tuple[int | None, dict[str, int]]:
    for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 60)):
        columns: dict[str, int] = {}
        for cell in row:
            text = _label(cell.value)
            if text:
                columns.setdefault(text, cell.column)
        if required.issubset(columns):
            return row[0].row, columns
    return None, {}


def _open(path: Path):
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise WorkbookParseError(".xlsx 또는 .xlsm 파일만 가져올 수 있습니다.")
    try:
        return load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:
        raise WorkbookParseError(f"Excel 파일을 열 수 없습니다: {path.name}") from exc


def detect_workbook(path: Path) -> dict:
    workbook = _open(path)
    matches: list[dict] = []
    for sheet in workbook.worksheets:
        ledger_row, ledger_columns = _find_header(sheet, LEDGER_HEADERS)
        bank_row, bank_columns = _find_header(sheet, BANK_HEADERS)
        if ledger_row:
            matches.append({"kind": "aegis_ledger", "sheet_name": sheet.title, "header_row": ledger_row, "columns": ledger_columns})
        if bank_row:
            matches.append({"kind": "toss_bank", "sheet_name": sheet.title, "header_row": bank_row, "columns": bank_columns})
    if not matches:
        raise WorkbookParseError("지원하는 Aegis 장부 또는 토스뱅크 거래내역 헤더를 찾지 못했습니다.")
    kinds = {item["kind"] for item in matches}
    return {
        "kind": next(iter(kinds)) if len(kinds) == 1 else "mixed",
        "sha256": file_sha256(path),
        "sheets": matches,
    }


def _category(description: str, method: str) -> str:
    text = f"{description} {method}".lower()
    rules = (
        ("회비", "회비"),
        ("지원금", "지원금"),
        ("이자", "이자"),
        ("도메인", "IT/서버"),
        ("서버", "IT/서버"),
        ("간식", "복리후생"),
        ("총회", "행사"),
        ("mt", "행사"),
        ("마라톤", "행사/상품"),
        ("경품", "행사/상품"),
        ("상품", "행사/상품"),
        ("비품", "비품"),
        ("홍보", "홍보"),
    )
    for keyword, category in rules:
        if keyword in text:
            return category
    return "미분류"


def _counterparty(detail: str) -> str | None:
    for pattern in (r"결제처\s*:\s*([^,]+)", r"입금자(?:명)?\s*:\s*([^,]+)", r"지출자\s*:\s*([^,]+)"):
        match = re.search(pattern, detail)
        if match:
            return match.group(1).strip()
    return None


def parse_aegis_ledger(
    path: Path,
    *,
    period: str,
    opening_balance: int = 0,
    organization_id: str = "aegis",
    account_id: str = "primary",
    sheet_name: str | None = None,
) -> dict:
    workbook = _open(path)
    selected = None
    header_row = None
    columns: dict[str, int] = {}
    for sheet in workbook.worksheets:
        row, found = _find_header(sheet, LEDGER_HEADERS)
        if row and (sheet_name is None or sheet.title == sheet_name):
            selected, header_row, columns = sheet, row, found
            break
    if selected is None or header_row is None:
        raise WorkbookParseError("Aegis 장부 헤더(날짜/내용/수입/지출)를 찾지 못했습니다.")

    running_balance = opening_balance
    transactions: list[dict] = []
    empty_streak = 0
    for row_number in range(header_row + 1, selected.max_row + 1):
        tx_date = _parse_date(selected.cell(row_number, columns["날짜"]).value)
        description = _label(selected.cell(row_number, columns["내용"]).value)
        income = _money(selected.cell(row_number, columns["수입"]).value)
        expense = _money(selected.cell(row_number, columns["지출"]).value)
        if not tx_date and not description and not income and not expense:
            empty_streak += 1
            if transactions and empty_streak >= 50:
                break
            continue
        empty_streak = 0
        if not tx_date:
            continue

        number_column = columns.get("NO") or columns.get("번호")
        raw_number = selected.cell(row_number, number_column).value if number_column else None
        number = _money(raw_number) or len(transactions) + 1
        running_balance += income - expense
        raw_balance = selected.cell(row_number, columns.get("잔액", 0)).value if columns.get("잔액") else None
        if isinstance(raw_balance, (int, float)):
            running_balance = _money(raw_balance)
        method = _label(selected.cell(row_number, columns.get("처리방식", 0)).value) if columns.get("처리방식") else ""
        detail = _label(selected.cell(row_number, columns.get("상세정보", 0)).value) if columns.get("상세정보") else ""
        note = " / ".join(value for value in (method, detail) if value)
        source_row = f"{selected.title}!{row_number}"
        transaction = {
            "organization_id": organization_id,
            "account_id": account_id,
            "period": period,
            "number": number,
            "date": tx_date.date().isoformat(),
            "description": description,
            "income": income,
            "expense": expense,
            "balance": running_balance,
            "category": _category(description, method),
            "counterparty": _counterparty(detail),
            "note": note,
            "source_row": source_row,
        }
        transaction["source_row_hash"] = canonical_sha256(transaction)
        transaction["transaction_id"] = f"tx_{transaction['source_row_hash'][:16]}"
        transactions.append(transaction)

    if not transactions:
        raise WorkbookParseError("장부에서 유효한 거래 행을 찾지 못했습니다.")
    return {
        "kind": "aegis_ledger",
        "filename": path.name,
        "sha256": file_sha256(path),
        "sheet_name": selected.title,
        "header_row": header_row,
        "opening_balance": opening_balance,
        "closing_balance": transactions[-1]["balance"],
        "period_start": transactions[0]["date"],
        "period_end": transactions[-1]["date"],
        "total_income": sum(item["income"] for item in transactions),
        "total_expense": sum(item["expense"] for item in transactions),
        "transaction_count": len(transactions),
        "transactions": transactions,
    }


def parse_toss_bank(path: Path) -> dict:
    workbook = _open(path)
    selected = None
    header_row = None
    columns: dict[str, int] = {}
    for sheet in workbook.worksheets:
        row, found = _find_header(sheet, BANK_HEADERS)
        if row:
            selected, header_row, columns = sheet, row, found
            break
    if selected is None or header_row is None:
        raise WorkbookParseError("토스뱅크 헤더(거래 일시/적요/거래 금액/거래 후 잔액)를 찾지 못했습니다.")

    rows: list[dict] = []
    for row_number in range(header_row + 1, selected.max_row + 1):
        occurred_at = _parse_date(selected.cell(row_number, columns["거래 일시"]).value)
        amount_value = selected.cell(row_number, columns["거래 금액"]).value
        balance_value = selected.cell(row_number, columns["거래 후 잔액"]).value
        if not occurred_at or amount_value in (None, "") or balance_value in (None, ""):
            continue
        row = {
            "occurred_at": occurred_at.isoformat(timespec="seconds"),
            "date": occurred_at.date().isoformat(),
            "description": _label(selected.cell(row_number, columns["적요"]).value),
            "transaction_type": _label(selected.cell(row_number, columns.get("거래 유형", 0)).value) if columns.get("거래 유형") else "",
            "institution": _label(selected.cell(row_number, columns.get("거래 기관", 0)).value) if columns.get("거래 기관") else "",
            "account_number": _label(selected.cell(row_number, columns.get("계좌번호", 0)).value) if columns.get("계좌번호") else "",
            "amount": _money(amount_value),
            "balance": _money(balance_value),
            "memo": _label(selected.cell(row_number, columns.get("메모", 0)).value) if columns.get("메모") else "",
            "source_row": f"{selected.title}!{row_number}",
        }
        row["bank_transaction_id"] = f"bank_{canonical_sha256(row)[:16]}"
        rows.append(row)
    if not rows:
        raise WorkbookParseError("토스뱅크 파일에서 유효한 거래 행을 찾지 못했습니다.")

    if rows[0]["occurred_at"] > rows[-1]["occurred_at"]:
        rows.reverse()
    continuity_failures: list[dict] = []
    for previous, current in zip(rows, rows[1:]):
        expected = previous["balance"] + current["amount"]
        if expected != current["balance"]:
            continuity_failures.append(
                {
                    "previous_id": previous["bank_transaction_id"],
                    "transaction_id": current["bank_transaction_id"],
                    "expected_balance": expected,
                    "reported_balance": current["balance"],
                }
            )
    return {
        "kind": "toss_bank",
        "filename": path.name,
        "sha256": file_sha256(path),
        "sheet_name": selected.title,
        "header_row": header_row,
        "opening_balance": rows[0]["balance"] - rows[0]["amount"],
        "closing_balance": rows[-1]["balance"],
        "period_start": rows[0]["date"],
        "period_end": rows[-1]["date"],
        "total_inflow": sum(max(item["amount"], 0) for item in rows),
        "total_outflow": sum(max(-item["amount"], 0) for item in rows),
        "transaction_count": len(rows),
        "transaction_types": dict(Counter(item["transaction_type"] for item in rows)),
        "continuity_failures": continuity_failures,
        "transactions": rows,
    }


def _subset_sum(candidates: list[dict], target: int) -> list[dict] | None:
    if target <= 0 or not candidates or len(candidates) > 28:
        return None
    states: dict[int, list[int]] = {0: []}
    for index, item in enumerate(candidates):
        value = abs(int(item["amount"]))
        if value <= 0 or value > target:
            continue
        for subtotal, indexes in list(states.items())[::-1]:
            total = subtotal + value
            if total > target or total in states:
                continue
            states[total] = [*indexes, index]
            if total == target:
                return [candidates[position] for position in states[total]]
    return None


def reconcile_ledger_bank(ledger: dict, bank: dict) -> dict:
    ledger_rows = ledger["transactions"]
    bank_rows = bank["transactions"]
    cutoff = max(_parse_date(item["date"]) for item in ledger_rows)
    eligible_bank = [item for item in bank_rows if _parse_date(item["occurred_at"]) <= cutoff.replace(hour=23, minute=59, second=59)]
    available = {item["bank_transaction_id"]: item for item in eligible_bank}
    matches: list[dict] = []
    unmatched_ledger: list[dict] = []

    def consume(ledger_row: dict, bank_matches: list[dict], method: str, confidence: str) -> None:
        for item in bank_matches:
            available.pop(item["bank_transaction_id"], None)
        matches.append(
            {
                "ledger_transaction_id": ledger_row["transaction_id"],
                "ledger_number": ledger_row["number"],
                "bank_transaction_ids": [item["bank_transaction_id"] for item in bank_matches],
                "method": method,
                "confidence": confidence,
                "amount": ledger_row["income"] or -ledger_row["expense"],
            }
        )

    for ledger_row in ledger_rows:
        signed_amount = ledger_row["income"] or -ledger_row["expense"]
        if not signed_amount or "이월" in ledger_row["description"]:
            unmatched_ledger.append(ledger_row)
            continue
        exact = [
            item
            for item in available.values()
            if item["date"] == ledger_row["date"] and item["amount"] == signed_amount
        ]
        if exact:
            consume(ledger_row, [exact[0]], "date_amount", "high")
            continue

        same_day = [
            item
            for item in available.values()
            if item["date"] == ledger_row["date"] and (item["amount"] > 0) == (signed_amount > 0)
        ]
        grouped = _subset_sum(same_day, abs(signed_amount))
        if grouped and len(grouped) > 1:
            consume(ledger_row, grouped, "same_day_aggregate", "high")
            continue

        aggregate_keyword = any(keyword in ledger_row["description"].lower() for keyword in ("회비", "참가비", "일괄", "지원금"))
        ledger_date = _parse_date(ledger_row["date"])
        if aggregate_keyword and ledger_date:
            lookback = [
                item
                for item in available.values()
                if 0 <= (ledger_date.date() - _parse_date(item["date"]).date()).days <= 35
                and (item["amount"] > 0) == (signed_amount > 0)
            ]
            grouped = _subset_sum(lookback, abs(signed_amount))
            if grouped and len(grouped) > 1:
                consume(ledger_row, grouped, "period_aggregate", "medium")
                continue
        unmatched_ledger.append(ledger_row)

    bank_at_cutoff = eligible_bank[-1]["balance"] if eligible_bank else None
    ledger_closing = ledger_rows[-1]["balance"] if ledger_rows else ledger.get("opening_balance", 0)
    balance_delta = None if bank_at_cutoff is None else ledger_closing - bank_at_cutoff
    continuity_failures = [
        issue
        for issue in bank.get("continuity_failures", [])
        if issue["transaction_id"] in {item["bank_transaction_id"] for item in eligible_bank}
    ]
    status = "PASS" if balance_delta == 0 and not continuity_failures else "ERROR"
    return {
        "status": status,
        "cutoff_date": cutoff.date().isoformat(),
        "ledger_closing_balance": ledger_closing,
        "bank_closing_balance": bank_at_cutoff,
        "balance_delta": balance_delta,
        "ledger_transaction_count": len(ledger_rows),
        "bank_transaction_count": len(eligible_bank),
        "matched_ledger_count": len(matches),
        "matched_bank_count": sum(len(item["bank_transaction_ids"]) for item in matches),
        "unmatched_ledger_count": len(unmatched_ledger),
        "unmatched_bank_count": len(available),
        "bank_continuity_failure_count": len(continuity_failures),
        "matches": matches,
        "unmatched_ledger": [
            {
                "transaction_id": item["transaction_id"],
                "number": item["number"],
                "date": item["date"],
                "description": item["description"],
                "amount": item["income"] or -item["expense"],
            }
            for item in unmatched_ledger
        ],
        "unmatched_bank": [
            {
                "bank_transaction_id": item["bank_transaction_id"],
                "date": item["date"],
                "description": item["description"],
                "amount": item["amount"],
                "memo": item["memo"],
            }
            for item in available.values()
        ],
    }


def workbook_preview(path: Path) -> dict:
    detected = detect_workbook(path)
    kind = detected["kind"]
    if kind == "aegis_ledger":
        parsed = parse_aegis_ledger(path, period="미지정")
        return {
            **detected,
            "summary": {
                key: parsed[key]
                for key in ("sheet_name", "transaction_count", "period_start", "period_end", "total_income", "total_expense", "closing_balance")
            },
            "preview": parsed["transactions"][:10],
        }
    if kind == "toss_bank":
        parsed = parse_toss_bank(path)
        return {
            **detected,
            "summary": {
                key: parsed[key]
                for key in ("sheet_name", "transaction_count", "period_start", "period_end", "total_inflow", "total_outflow", "closing_balance")
            },
            "preview": parsed["transactions"][:10],
        }
    return detected
