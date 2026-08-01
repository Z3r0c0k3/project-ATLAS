from __future__ import annotations

import html
import json
import shutil
import zipfile
from pathlib import Path

from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .accounting import Evidence, Transaction, public_monthly_summary, validate_ledger


def _won(value: int) -> str:
    return f"{value:,}원"


def _style_header(cell) -> None:
    cell.fill = PatternFill("solid", fgColor="93C94D")
    cell.font = Font(bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _apply_border(ws, max_row: int, max_col: int) -> None:
    side = Side(style="thin", color="666666")
    for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
        for cell in row:
            cell.border = Border(left=side, right=side, top=side, bottom=side)
            cell.alignment = Alignment(vertical="center", wrap_text=True)


def generate_ledger_workbook(
    output_path: Path,
    club_name: str,
    semester: str,
    treasurer_name: str,
    president_name: str,
    opening_balance: int,
    transactions: list[Transaction],
    row_capacity: int,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "수입지출관리대장"

    ws["A1"] = f"{club_name} 수입지출 관리대장"
    ws["A1"].font = Font(size=18, bold=True)
    ws["A2"] = semester
    ws["F1"] = "담당"
    ws["G1"] = "회장"
    ws["F2"] = f"{treasurer_name} (인)"
    ws["G2"] = f"{president_name} (인)"
    ws["F3"] = "이전 잔액"
    ws["G3"] = opening_balance

    headers = ["번호", "날짜", "내용", "수입금액", "지출금액", "잔액", "비고"]
    start_row = 5
    for col, header in enumerate(headers, 1):
        cell = ws.cell(start_row, col, header)
        _style_header(cell)

    for index in range(row_capacity):
        row = start_row + 1 + index
        if index < len(transactions):
            tx = transactions[index]
            values = [tx.number, tx.date, tx.description, tx.income or None, tx.expense or None, tx.balance, tx.note]
        else:
            values = [index + 1, "", "", None, None, None, ""]
        for col, value in enumerate(values, 1):
            ws.cell(row, col, value)

    total_row = start_row + row_capacity + 2
    ws.cell(total_row, 1, "합계")
    ws.cell(total_row, 4, f"=SUM(D{start_row + 1}:D{start_row + row_capacity})")
    ws.cell(total_row, 5, f"=SUM(E{start_row + 1}:E{start_row + row_capacity})")
    ws.cell(total_row, 6, f"=G3+D{total_row}-E{total_row}")
    ws.cell(total_row + 1, 1, "비고")
    ws.merge_cells(start_row=total_row + 1, start_column=2, end_row=total_row + 1, end_column=7)

    for col in range(1, 8):
        _style_header(ws.cell(total_row, col))
    _style_header(ws.cell(total_row + 1, 1))

    widths = [8, 14, 36, 16, 16, 16, 34]
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = width
    for row in range(1, total_row + 2):
        ws.row_dimensions[row].height = 24

    _apply_border(ws, total_row + 1, 7)
    for row in ws.iter_rows(min_row=start_row + 1, max_row=total_row, min_col=4, max_col=6):
        for cell in row:
            cell.number_format = '#,##0'
    ws["G3"].number_format = '#,##0'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def generate_evidence_document(
    output_path: Path,
    club_name: str,
    reviewer_name: str | None,
    transactions: list[Transaction],
    evidence: list[Evidence],
) -> None:
    doc = Document()
    doc.add_heading(f"{club_name} 영수증 및 소명자료", level=1)
    doc.add_paragraph("* 지출항목에 대한 영수증과 소명자료 중 택1")
    evidence_by_id = {item.id: item for item in evidence}
    evidence_by_tx = {item.transaction_number: item for item in evidence if item.transaction_number is not None}

    expense_rows = [item for item in transactions if item.expense]
    if not expense_rows:
        doc.add_paragraph("지출 거래가 없습니다.")

    for tx in expense_rows:
        item = evidence_by_id.get(tx.evidence_id or "") or evidence_by_tx.get(tx.number)
        table = doc.add_table(rows=6, cols=2)
        table.style = "Table Grid"
        table.cell(0, 0).text = "번호(수입지출관리대장)"
        table.cell(0, 1).text = str(tx.number)
        table.cell(1, 0).text = "날짜"
        table.cell(1, 1).text = tx.date
        table.cell(2, 0).text = "지출자 / 검토자"
        table.cell(2, 1).text = f"지출자: {club_name} 회계담당자 (인) / 검토자: {reviewer_name or '-'} (인)"
        table.cell(3, 0).text = "사업명"
        table.cell(3, 1).text = tx.description
        table.cell(4, 0).text = "내용 & 특이사항"
        table.cell(4, 1).text = tx.note or "특이사항 없음"
        table.cell(5, 0).text = "지출 금액"
        table.cell(5, 1).text = _won(tx.expense)
        doc.add_paragraph(f"증빙자료: {item.filename if item else '미연결'}")
        doc.add_paragraph("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)


def generate_account_capture_document(output_path: Path, club_name: str, evidence: list[Evidence]) -> None:
    doc = Document()
    doc.add_heading(f"{club_name} 계좌전체내역", level=1)
    captures = [item for item in evidence if item.kind == "account_capture"]
    if not captures:
        doc.add_paragraph("계좌전체내역 캡처가 연결되지 않았습니다.")
    for index, item in enumerate(captures, 1):
        doc.add_paragraph(f"<{index}> {item.filename}")
        if item.local_path and Path(item.local_path).exists():
            try:
                doc.add_picture(item.local_path, width=Inches(5.8))
            except Exception:
                doc.add_paragraph("이미지를 문서에 삽입하지 못했습니다. 원본 파일을 제출 ZIP에 포함합니다.")
        elif item.url:
            doc.add_paragraph(item.url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)


def generate_validation_report(output_path: Path, validation: dict) -> None:
    summary = validation["summary"]
    rows = "\n".join(
        f"<li><strong>{html.escape(issue['severity'])}</strong> "
        f"{html.escape(issue['code'])}: {html.escape(issue['message'])}</li>"
        for issue in validation["issues"]
    )
    output_path.write_text(
        f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>ATLAS 검증 리포트</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 40px; color: #172026; }}
    h1 {{ margin-bottom: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
    th, td {{ border: 1px solid #c7d0d9; padding: 10px; text-align: left; }}
    th {{ background: #e9f3df; }}
    .status {{ font-weight: 700; }}
  </style>
</head>
<body>
  <h1>ATLAS 검증 리포트</h1>
  <p class="status">상태: {html.escape(validation['status'])}</p>
  <table>
    <tr><th>이전잔액</th><td>{summary['opening_balance']:,}원</td></tr>
    <tr><th>수입총액</th><td>{summary['total_income']:,}원</td></tr>
    <tr><th>지출총액</th><td>{summary['total_expense']:,}원</td></tr>
    <tr><th>계산 최종잔액</th><td>{summary['computed_closing_balance']:,}원</td></tr>
    <tr><th>장부 최종잔액</th><td>{summary['reported_closing_balance']:,}원</td></tr>
  </table>
  <h2>검증 항목</h2>
  <ul>{rows or '<li>검증 이슈가 없습니다.</li>'}</ul>
</body>
</html>
""",
        encoding="utf-8",
    )


def build_submission_package(
    output_root: Path,
    package_id: str,
    club_name: str,
    semester: str,
    treasurer_name: str,
    president_name: str,
    reviewer_name: str | None,
    opening_balance: int,
    expected_closing_balance: int | None,
    transactions: list[Transaction],
    evidence: list[Evidence],
    row_capacity: int,
) -> dict:
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    validation = validate_ledger(opening_balance, transactions, evidence, expected_closing_balance)

    ledger_path = package_dir / "수입지출관리대장.xlsx"
    evidence_path = package_dir / "영수증_및_소명자료.docx"
    captures_path = package_dir / "계좌전체내역.docx"
    report_path = package_dir / "검증_리포트.html"
    manifest_path = package_dir / "manifest.json"
    zip_path = output_root / f"{package_id}.zip"

    generate_ledger_workbook(
        ledger_path,
        club_name,
        semester,
        treasurer_name,
        president_name,
        opening_balance,
        transactions,
        row_capacity,
    )
    generate_evidence_document(evidence_path, club_name, reviewer_name, transactions, evidence)
    generate_account_capture_document(captures_path, club_name, evidence)
    generate_validation_report(report_path, validation)

    copied_evidence: list[dict] = []
    evidence_dir = package_dir / "증빙자료"
    evidence_dir.mkdir(exist_ok=True)
    for item in evidence:
        if item.local_path and Path(item.local_path).exists():
            target = evidence_dir / Path(item.local_path).name
            shutil.copy2(item.local_path, target)
            copied_evidence.append({"id": item.id, "path": str(target)})

    manifest = {
        "package_id": package_id,
        "club_name": club_name,
        "semester": semester,
        "validation": validation,
        "evidence": copied_evidence,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir))

    return {
        "zip_path": str(zip_path),
        "validation": validation,
        "artifacts": [
            {"kind": "ledger", "path": str(ledger_path)},
            {"kind": "evidence", "path": str(evidence_path)},
            {"kind": "account_captures", "path": str(captures_path)},
            {"kind": "validation_report", "path": str(report_path)},
            {"kind": "zip", "path": str(zip_path)},
        ],
    }


def build_monthly_report_payload(
    report_id: str,
    share_id: str,
    club_name: str,
    month: str,
    opening_balance: int,
    transactions: list[Transaction],
    visible_notes: bool,
) -> dict:
    summary = public_monthly_summary(opening_balance, transactions)
    public_transactions = []
    for item in transactions:
        public_transactions.append(
            {
                "number": item.number,
                "date": item.date,
                "description": item.description,
                "income": item.income,
                "expense": item.expense,
                "balance": item.balance,
                "note": item.note if visible_notes else "",
            }
        )
    return {
        "id": report_id,
        "share_id": share_id,
        "club_name": club_name,
        "month": month,
        "summary": summary,
        "transactions": public_transactions,
    }
