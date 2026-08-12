from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import fitz
from openpyxl import load_workbook

from .integrity import canonical_sha256, file_sha256
from .naming import normalize_filename


class WorkbookParseError(ValueError):
    pass


LEDGER_HEADERS = {"날짜", "내용", "수입", "지출"}
WOORI_BANK_HEADERS = {"거래일시", "적요", "기재내용", "찾으신금액", "맡기신금액", "거래후 잔액"}


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
        "%Y.%m.%d %H:%M",
        "%Y. %m. %d %H:%M:%S",
        "%Y. %m. %d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
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
    if path.suffix.lower() == ".xls":
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise WorkbookParseError(".xls 파일을 읽으려면 LibreOffice가 필요합니다.")
        try:
            with tempfile.TemporaryDirectory(prefix="atlas-xls-") as temporary:
                subprocess.run(
                    [
                        soffice,
                        f"-env:UserInstallation={Path(temporary, 'profile').as_uri()}",
                        "--headless",
                        "--convert-to",
                        "xlsx",
                        "--outdir",
                        temporary,
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                converted = next(Path(temporary).glob("*.xlsx"), None)
                if not converted:
                    raise WorkbookParseError(f"Excel 파일을 변환할 수 없습니다: {normalize_filename(path.name)}")
                return load_workbook(converted, data_only=True, read_only=False)
        except (subprocess.SubprocessError, OSError) as exc:
            raise WorkbookParseError(f"Excel 파일을 변환할 수 없습니다: {normalize_filename(path.name)}") from exc
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise WorkbookParseError(".xls, .xlsx 또는 .xlsm 파일만 가져올 수 있습니다.")
    try:
        return load_workbook(path, data_only=True, read_only=False)
    except Exception as exc:
        raise WorkbookParseError(f"Excel 파일을 열 수 없습니다: {normalize_filename(path.name)}") from exc


def detect_workbook(path: Path) -> dict:
    workbook = _open(path)
    matches: list[dict] = []
    for sheet in workbook.worksheets:
        ledger_row, ledger_columns = _find_header(sheet, LEDGER_HEADERS)
        woori_row, woori_columns = _find_header(sheet, WOORI_BANK_HEADERS)
        if ledger_row:
            matches.append({"kind": "aegis_ledger", "sheet_name": sheet.title, "header_row": ledger_row, "columns": ledger_columns})
        if woori_row:
            matches.append({"kind": "woori_bank", "sheet_name": sheet.title, "header_row": woori_row, "columns": woori_columns})
    if not matches:
        raise WorkbookParseError("지원하는 Aegis 장부 또는 은행 거래내역 헤더를 찾지 못했습니다.")
    kinds = {item["kind"] for item in matches}
    return {
        "kind": next(iter(kinds)) if len(kinds) == 1 else "mixed",
        "sha256": file_sha256(path),
        "sheets": matches,
    }


IBK_BANK_KEYWORDS = ("거래내역조회_입출식", "기업은행", "IBK간편한통장")


def is_ibk_bank_pdf(path: Path) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    try:
        doc = fitz.open(str(path))
        text = doc[0].get_text()
        doc.close()
        return any(keyword in text for keyword in IBK_BANK_KEYWORDS)
    except Exception:
        return False


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
            "processing_method": method,
            "details": detail,
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
        "filename": normalize_filename(path.name),
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


def parse_woori_bank(path: Path) -> dict:
    workbook = _open(path)
    selected = None
    header_row = None
    columns: dict[str, int] = {}
    for sheet in workbook.worksheets:
        row, found = _find_header(sheet, WOORI_BANK_HEADERS)
        if row:
            selected, header_row, columns = sheet, row, found
            break
    if selected is None or header_row is None:
        raise WorkbookParseError("우리은행 헤더(거래일시/기재내용/찾으신금액/맡기신금액/거래후 잔액)를 찾지 못했습니다.")

    rows: list[dict] = []
    for row_number in range(header_row + 1, selected.max_row + 1):
        occurred_at = _parse_date(selected.cell(row_number, columns["거래일시"]).value)
        withdrawal = _money(selected.cell(row_number, columns["찾으신금액"]).value)
        deposit = _money(selected.cell(row_number, columns["맡기신금액"]).value)
        balance_value = selected.cell(row_number, columns["거래후 잔액"]).value
        if not occurred_at or balance_value in (None, ""):
            continue
        number_column = columns.get("No.") or columns.get("No")
        number_value = selected.cell(row_number, number_column).value if number_column else len(rows) + 1
        row = {
            "occurred_at": occurred_at.isoformat(timespec="seconds"),
            "date": occurred_at.date().isoformat(),
            "description": _label(selected.cell(row_number, columns["기재내용"]).value),
            "transaction_type": _label(selected.cell(row_number, columns["적요"]).value),
            "institution": _label(selected.cell(row_number, columns.get("취급기관", 0)).value) if columns.get("취급기관") else "",
            "withdrawal": withdrawal,
            "deposit": deposit,
            "amount": deposit - withdrawal,
            "balance": _money(balance_value),
            "memo": _label(selected.cell(row_number, columns.get("메모", 0)).value) if columns.get("메모") else "",
            "number": _money(number_value),
            "source_row": f"{selected.title}!{row_number}",
        }
        row["bank_transaction_id"] = f"bank_{canonical_sha256(row)[:16]}"
        rows.append(row)
    if not rows:
        raise WorkbookParseError("우리은행 파일에서 유효한 거래 내역을 찾지 못했습니다.")

    rows.sort(key=lambda item: (item["occurred_at"], item["number"]))
    account_text = _label(selected.cell(2, 1).value)
    period_text = _label(selected.cell(3, 1).value)
    return {
        "kind": "woori_bank",
        "filename": normalize_filename(path.name),
        "sha256": file_sha256(path),
        "sheet_name": selected.title,
        "header_row": header_row,
        "account_number": account_text.split(":", 1)[-1].strip() if ":" in account_text else account_text,
        "query_period": period_text.split(":", 1)[-1].strip() if ":" in period_text else period_text,
        "opening_balance": rows[0]["balance"] - rows[0]["amount"],
        "closing_balance": rows[-1]["balance"],
        "period_start": rows[0]["date"],
        "period_end": rows[-1]["date"],
        "total_inflow": sum(max(item["amount"], 0) for item in rows),
        "total_outflow": sum(max(-item["amount"], 0) for item in rows),
        "transaction_count": len(rows),
        "transaction_types": dict(Counter(item["transaction_type"] for item in rows)),
        "transactions": rows,
    }


def workbook_preview(path: Path) -> dict:
    if is_ibk_bank_pdf(path):
        parsed = parse_ibk_bank_pdf(path)
        return {
            "kind": parsed["kind"],
            "sha256": parsed["sha256"],
            "summary": {
                key: parsed[key]
                for key in ("transaction_count", "period_start", "period_end", "total_inflow", "total_outflow", "closing_balance", "account_number", "account_holder")
            },
            "preview": parsed["transactions"][:10],
        }
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
    if kind == "woori_bank":
        parsed = parse_woori_bank(path)
        return {
            **detected,
            "summary": {
                key: parsed[key]
                for key in ("sheet_name", "transaction_count", "period_start", "period_end", "total_inflow", "total_outflow", "closing_balance", "account_number")
            },
            "preview": parsed["transactions"][:10],
        }
    return detected


def _clean_cell(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def parse_ibk_bank_pdf(path: Path) -> dict:
    if path.suffix.lower() != ".pdf":
        raise WorkbookParseError("PDF 파일만 가능합니다.")
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise WorkbookParseError(f"PDF 파일을 열 수 없습니다: {normalize_filename(path.name)}") from exc

    account_info: dict[str, str] = {}
    all_rows: list[dict] = []

    for page in doc:
        text = page.get_text()
        if not account_info:
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("계좌번호"):
                    account_info["account_number"] = line.split(":", 1)[-1].strip() if ":" in line else line.replace("계좌번호", "").strip()
                elif line.startswith("예금주명"):
                    account_info["account_holder"] = line.split(":", 1)[-1].strip() if ":" in line else line.replace("예금주명", "").strip()
                elif line.startswith("조회시작일자"):
                    account_info["query_start"] = line.split(":", 1)[-1].strip() if ":" in line else line.replace("조회시작일자", "").strip()
                elif line.startswith("조회종료일자"):
                    account_info["query_end"] = line.split(":", 1)[-1].strip() if ":" in line else line.replace("조회종료일자", "").strip()

        tables = page.find_tables()
        if not tables.tables:
            continue
        table = tables.tables[0]
        extracted = table.extract()
        if not extracted:
            continue

        for row in extracted:
            if not row or not row[0]:
                continue
            first_cell = _clean_cell(str(row[0]))
            if first_cell in ("No", "합계"):
                continue
            if not re.fullmatch(r"\d+", first_cell):
                continue

            date_time = _clean_cell(str(row[1])).replace("\n", " ")
            withdrawal = _money(row[2] if len(row) > 2 else 0)
            deposit = _money(row[3] if len(row) > 3 else 0)
            balance = _money(row[4] if len(row) > 4 else 0)
            description = _clean_cell(str(row[5]) if len(row) > 5 else "").replace("\n", "")
            transfer_message = _clean_cell(str(row[6]) if len(row) > 6 else "").replace("\n", "")
            counterparty_account = _clean_cell(str(row[7]) if len(row) > 7 else "").replace("\n", "")
            counterparty_bank = _clean_cell(str(row[8]) if len(row) > 8 else "").replace("\n", "")
            transaction_type = _clean_cell(str(row[9]) if len(row) > 9 else "").replace("\n", "")
            check_amount = _money(row[10] if len(row) > 10 else 0)
            cms_code = _clean_cell(str(row[11]) if len(row) > 11 else "").replace("\n", "")
            counterparty_name = _clean_cell(str(row[12]) if len(row) > 12 else "").replace("\n", "")

            occurred_at = _parse_date(date_time)
            if not occurred_at:
                occurred_at = _parse_date(date_time[:10])

            signed_amount = deposit - withdrawal

            row_data = {
                "occurred_at": occurred_at.isoformat(timespec="seconds") if occurred_at else date_time,
                "date": occurred_at.date().isoformat() if occurred_at else date_time[:10],
                "description": description or counterparty_name or "기업은행 거래",
                "withdrawal": withdrawal,
                "deposit": deposit,
                "amount": signed_amount,
                "balance": balance,
                "transfer_message": transfer_message,
                "counterparty_account": counterparty_account,
                "counterparty_bank": counterparty_bank,
                "transaction_type": transaction_type,
                "check_amount": check_amount,
                "cms_code": cms_code,
                "counterparty_name": counterparty_name,
                "number": int(first_cell),
            }
            row_data["bank_transaction_id"] = f"bank_{canonical_sha256(row_data)[:16]}"
            all_rows.append(row_data)

    doc.close()

    if not all_rows:
        raise WorkbookParseError("기업은행 PDF에서 유효한 거래 내역을 찾지 못했습니다.")

    all_rows.sort(key=lambda row: (row["date"], row["occurred_at"], row["number"]))

    return {
        "kind": "ibk_bank",
        "filename": normalize_filename(path.name),
        "sha256": file_sha256(path),
        "account_number": account_info.get("account_number", ""),
        "account_holder": account_info.get("account_holder", ""),
        "query_start": account_info.get("query_start", ""),
        "query_end": account_info.get("query_end", ""),
        "opening_balance": all_rows[0]["balance"] - all_rows[0]["amount"],
        "closing_balance": all_rows[-1]["balance"],
        "period_start": all_rows[0]["date"],
        "period_end": all_rows[-1]["date"],
        "total_inflow": sum(max(row["amount"], 0) for row in all_rows),
        "total_outflow": sum(max(-row["amount"], 0) for row in all_rows),
        "transaction_count": len(all_rows),
        "transaction_types": dict(Counter(row["transaction_type"] for row in all_rows)),
        "transactions": all_rows,
    }
