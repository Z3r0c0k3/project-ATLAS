from __future__ import annotations

import html
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .accounting import (
    VALIDATION_RULE_VERSION,
    Evidence,
    Transaction,
    public_monthly_summary,
    validate_ledger,
)
from .integrity import canonical_sha256, file_sha256
from .media import image_dimensions, render_media_pages


TEMPLATE_VERSION = "atlas-documents-v1.2-dongyeon-profile"


def _won(value: int) -> str:
    return f"{value:,}원"


def _account_label(account_id: str | None) -> str:
    labels = {
        "primary": "동아리 운영 토스뱅크 main 계좌",
        "dues_intake": "회비입금전용 기업은행 계좌",
    }
    return labels.get(account_id or "primary", account_id or "primary")


def _effective_row_capacity(requested: int, transaction_count: int) -> int:
    required = max(requested, transaction_count)
    for capacity in (40, 80, 120):
        if required <= capacity:
            return capacity
    return required


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
    row_capacity = _effective_row_capacity(row_capacity, len(transactions))
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


def _configure_document(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.6)
        section.right_margin = Cm(1.6)
    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal.font.size = Pt(9)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")


def _shade_cell(cell, color: str = "E9F3DF") -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    properties.append(shading)


def _repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def _set_table_font(table, size: int = 9) -> None:
    for row in table.rows:
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.name = "Malgun Gothic"
                    run.font.size = Pt(size)
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")


def _add_contained_picture(paragraph, image_path: Path, max_width: float, max_height: float) -> None:
    width, height = image_dimensions(image_path)
    scale = min(max_width / width, max_height / height)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run().add_picture(
        str(image_path),
        width=Inches(width * scale),
        height=Inches(height * scale),
    )


def _linked_evidence(tx: Transaction, evidence: list[Evidence]) -> list[Evidence]:
    linked: list[Evidence] = []
    ids = set(tx.evidence_ids)
    if tx.evidence_id:
        ids.add(tx.evidence_id)
    for item in evidence:
        if item.id in ids or item.transaction_number == tx.number or tx.transaction_id in item.transaction_ids:
            if item not in linked:
                linked.append(item)
    return linked


def _add_transaction_metadata(doc: Document, club_name: str, reviewer_name: str | None, tx: Transaction) -> None:
    table = doc.add_table(rows=5, cols=4)
    table.style = "Table Grid"
    values = (
        ("번호", str(tx.number), "날짜", tx.date),
        ("지출자", f"{club_name} 회계담당자 (인)", "검토자", f"{reviewer_name or '-'} (인)"),
        ("사업명", tx.description, "분류", tx.category),
        ("내용 및 특이사항", tx.note or "특이사항 없음", "거래 상대방", tx.counterparty or "-"),
        ("지출 금액", _won(tx.expense), "증빙 상태", "아래 첨부"),
    )
    for row_index, row_values in enumerate(values):
        for column_index, value in enumerate(row_values):
            cell = table.cell(row_index, column_index)
            cell.text = value
            if column_index in {0, 2}:
                _shade_cell(cell)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
    _set_table_font(table)


def generate_evidence_document(
    output_path: Path,
    club_name: str,
    reviewer_name: str | None,
    transactions: list[Transaction],
    evidence: list[Evidence],
) -> dict:
    doc = Document()
    _configure_document(doc)
    title = doc.add_heading(f"{club_name} 영수증 및 소명자료", level=1)
    title.runs[0].font.color.rgb = RGBColor(30, 72, 52)
    doc.add_paragraph("지출항목별 영수증 또는 소명자료 원본을 순서대로 첨부했습니다.")
    render_dir = output_path.parent / ".rendered-evidence"
    expense_rows = [item for item in transactions if item.expense]
    used_evidence: set[str] = set()
    embedded_files = 0
    embedded_pages = 0
    unsupported_files: list[str] = []
    missing_expenses: list[int] = []
    account_breakdown: dict[str, dict[str, int | str]] = {}

    def count_account(item: Evidence, pages: int = 0) -> None:
        row = account_breakdown.setdefault(
            item.account_id,
            {"account_id": item.account_id, "label": _account_label(item.account_id), "files": 0, "pages": 0},
        )
        row["files"] = int(row["files"]) + 1
        row["pages"] = int(row["pages"]) + pages

    if not expense_rows:
        doc.add_paragraph("지출 거래가 없습니다.")
    for tx_index, tx in enumerate(expense_rows):
        if tx_index:
            doc.add_page_break()
        doc.add_heading(f"지출 {tx.number}. {tx.description}", level=2)
        _add_transaction_metadata(doc, club_name, reviewer_name, tx)
        linked = [item for item in _linked_evidence(tx, evidence) if item.kind != "account_capture"]
        if not linked:
            missing_expenses.append(tx.number)
            warning = doc.add_paragraph("연결된 영수증 또는 소명자료가 없습니다.")
            warning.runs[0].font.color.rgb = RGBColor(180, 35, 35)
            continue
        for evidence_index, item in enumerate(linked):
            used_evidence.add(item.id)
            doc.add_paragraph(f"첨부 {evidence_index + 1}: {item.filename} ({item.kind}, {_account_label(item.account_id)})")
            source = Path(item.local_path) if item.local_path else None
            pages = render_media_pages(source, render_dir / item.id) if source and source.exists() else []
            if not pages:
                unsupported_files.append(item.filename)
                count_account(item)
                doc.add_paragraph("문서에 직접 표시할 수 없는 형식입니다. 원본 파일은 제출 ZIP의 증빙자료 폴더에 포함됩니다.")
                if item.url:
                    doc.add_paragraph(item.url)
                continue
            embedded_files += 1
            count_account(item, len(pages))
            for page_index, page in enumerate(pages):
                if page_index:
                    doc.add_page_break()
                    doc.add_heading(f"지출 {tx.number} 증빙 계속 - {item.filename} ({page_index + 1}/{len(pages)})", level=3)
                _add_contained_picture(doc.add_paragraph(), page, max_width=6.6, max_height=7.8)
                embedded_pages += 1

    unlinked = [item for item in evidence if item.kind != "account_capture" and item.id not in used_evidence]
    if unlinked:
        doc.add_page_break()
        doc.add_heading("미연결 증빙자료", level=2)
        doc.add_paragraph("거래 번호가 지정되지 않은 자료입니다. 누락 방지를 위해 원본과 미리보기를 함께 수록합니다.")
        for item in unlinked:
            doc.add_heading(f"{item.filename} - {_account_label(item.account_id)}", level=3)
            source = Path(item.local_path) if item.local_path else None
            pages = render_media_pages(source, render_dir / item.id) if source and source.exists() else []
            if not pages:
                unsupported_files.append(item.filename)
                count_account(item)
                doc.add_paragraph("직접 표시할 수 없는 형식이며 원본은 제출 ZIP에 포함됩니다.")
                continue
            embedded_files += 1
            count_account(item, len(pages))
            for page in pages:
                _add_contained_picture(doc.add_paragraph(), page, max_width=6.6, max_height=8.8)
                embedded_pages += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    shutil.rmtree(render_dir, ignore_errors=True)
    return {
        "expense_count": len(expense_rows),
        "missing_expense_numbers": missing_expenses,
        "embedded_files": embedded_files,
        "embedded_pages": embedded_pages,
        "unsupported_files": sorted(set(unsupported_files)),
        "account_breakdown": list(account_breakdown.values()),
    }


def generate_account_capture_document(
    output_path: Path,
    club_name: str,
    evidence: list[Evidence],
    bank_transactions: list[dict] | None = None,
) -> dict:
    doc = Document()
    _configure_document(doc)
    title = doc.add_heading(f"{club_name} 계좌전체내역", level=1)
    title.runs[0].font.color.rgb = RGBColor(30, 72, 52)
    captures = [item for item in evidence if item.kind == "account_capture"]
    render_dir = output_path.parent / ".rendered-account-captures"
    embedded_pages = 0
    unsupported_files: list[str] = []
    account_breakdown: dict[str, dict[str, int | str]] = {}
    grouped_captures: dict[str, list[Evidence]] = {}
    for item in captures:
        grouped_captures.setdefault(item.account_id, []).append(item)
    section_index = 0
    for account_id, items in grouped_captures.items():
        if section_index:
            doc.add_page_break()
        section_index += 1
        doc.add_heading(_account_label(account_id), level=2)
        breakdown = account_breakdown.setdefault(account_id, {"account_id": account_id, "label": _account_label(account_id), "files": 0, "pages": 0})
        for index, item in enumerate(items, 1):
            doc.add_heading(f"계좌내역 캡처 {index}. {item.filename}", level=3)
            source = Path(item.local_path) if item.local_path else None
            pages = render_media_pages(source, render_dir / item.id) if source and source.exists() else []
            breakdown["files"] = int(breakdown["files"]) + 1
            if not pages:
                unsupported_files.append(item.filename)
                doc.add_paragraph("직접 표시할 수 없는 형식이며 원본은 제출 ZIP에 포함됩니다.")
                if item.url:
                    doc.add_paragraph(item.url)
                continue
            breakdown["pages"] = int(breakdown["pages"]) + len(pages)
            for page_index, page in enumerate(pages):
                if page_index:
                    doc.add_page_break()
                    doc.add_heading(f"{item.filename} ({page_index + 1}/{len(pages)})", level=3)
                _add_contained_picture(doc.add_paragraph(), page, max_width=6.6, max_height=9.0)
                embedded_pages += 1

    bank_rows = bank_transactions or []
    if bank_rows:
        if captures:
            doc.add_page_break()
        doc.add_heading("토스뱅크 전체 거래내역", level=2)
        doc.add_paragraph("업로드된 토스뱅크 원본의 모든 거래를 시간순으로 수록했습니다.")
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        headers = ("거래 일시", "적요 / 메모", "유형", "거래 금액", "거래 후 잔액")
        for index, header in enumerate(headers):
            table.cell(0, index).text = header
            _shade_cell(table.cell(0, index))
        _repeat_header(table.rows[0])
        for item in bank_rows:
            cells = table.add_row().cells
            cells[0].text = str(item.get("occurred_at", "")).replace("T", " ")
            description = str(item.get("description") or "")
            memo = str(item.get("memo") or "")
            cells[1].text = description if not memo else f"{description}\n{memo}"
            cells[2].text = str(item.get("transaction_type") or "")
            cells[3].text = f"{int(item.get('amount') or 0):+,}원"
            cells[4].text = _won(int(item.get("balance") or 0))
        _set_table_font(table, 8)
    elif not captures:
        warning = doc.add_paragraph("계좌전체내역 캡처 또는 은행 거래내역 파일이 연결되지 않았습니다.")
        warning.runs[0].font.color.rgb = RGBColor(180, 35, 35)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    shutil.rmtree(render_dir, ignore_errors=True)
    return {
        "capture_file_count": len(captures),
        "embedded_capture_pages": embedded_pages,
        "bank_transaction_rows": len(bank_rows),
        "unsupported_files": sorted(set(unsupported_files)),
        "account_breakdown": list(account_breakdown.values()),
    }


def generate_validation_report(output_path: Path, validation: dict, reconciliation: dict | None = None) -> None:
    summary = validation["summary"]
    rows = "\n".join(
        f"<li><strong>{html.escape(issue['severity'])}</strong> "
        f"{html.escape(issue['code'])}: {html.escape(issue['message'])}</li>"
        for issue in validation["issues"]
    )
    reconciliation_html = ""
    if reconciliation:
        reconciliation_html = f"""
  <h2>은행 거래내역 대사</h2>
  <table>
    <tr><th>상태</th><td>{html.escape(str(reconciliation.get('status')))}</td></tr>
    <tr><th>대사 기준일</th><td>{html.escape(str(reconciliation.get('cutoff_date')))}</td></tr>
    <tr><th>장부 마감잔액</th><td>{int(reconciliation.get('ledger_closing_balance') or 0):,}원</td></tr>
    <tr><th>은행 마감잔액</th><td>{int(reconciliation.get('bank_closing_balance') or 0):,}원</td></tr>
    <tr><th>잔액 차이</th><td>{int(reconciliation.get('balance_delta') or 0):,}원</td></tr>
    <tr><th>자동 매칭</th><td>장부 {int(reconciliation.get('matched_ledger_count') or 0):,}건 / 은행 {int(reconciliation.get('matched_bank_count') or 0):,}건</td></tr>
    <tr><th>수동 확인 필요</th><td>장부 {int(reconciliation.get('unmatched_ledger_count') or 0):,}건 / 은행 {int(reconciliation.get('unmatched_bank_count') or 0):,}건</td></tr>
  </table>
"""
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
  {reconciliation_html}
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
    created_by: str = "system",
    snapshot_id: str | None = None,
    ledger_data_hash: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    bank_transactions: list[dict] | None = None,
    reconciliation: dict | None = None,
    source_files: list[dict] | None = None,
) -> dict:
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    validation = validate_ledger(
        opening_balance,
        transactions,
        evidence,
        expected_closing_balance,
        period_start,
        period_end,
        reconciliation,
    )

    ledger_path = package_dir / "수입지출관리대장.xlsx"
    evidence_path = package_dir / "영수증_및_소명자료.docx"
    captures_path = package_dir / "계좌전체내역.docx"
    report_path = package_dir / "검증_리포트.html"
    manifest_path = package_dir / "manifest.json"
    zip_path = output_root / f"{package_id}.zip"

    effective_capacity = _effective_row_capacity(row_capacity, len(transactions))
    generate_ledger_workbook(
        ledger_path,
        club_name,
        semester,
        treasurer_name,
        president_name,
        opening_balance,
        transactions,
        effective_capacity,
    )
    evidence_coverage = generate_evidence_document(evidence_path, club_name, reviewer_name, transactions, evidence)
    account_coverage = generate_account_capture_document(captures_path, club_name, evidence, bank_transactions)
    generate_validation_report(report_path, validation, reconciliation)

    copied_evidence: list[dict] = []
    evidence_dir = package_dir / "증빙자료"
    evidence_dir.mkdir(exist_ok=True)
    for item in evidence:
        if item.local_path and Path(item.local_path).exists():
            target = evidence_dir / f"{item.id}_{Path(item.local_path).name}"
            shutil.copy2(item.local_path, target)
            copied_evidence.append(
                {
                    "id": item.id,
                    "filename": target.name,
                    "relative_path": str(target.relative_to(package_dir)),
                    "sha256": file_sha256(target),
                    "transaction_ids": list(item.transaction_ids),
                    "transaction_number": item.transaction_number,
                }
            )

    copied_sources: list[dict] = []
    source_dir = package_dir / "원본자료"
    source_dir.mkdir(exist_ok=True)
    for item in source_files or []:
        source_path = Path(str(item.get("local_path") or ""))
        if not source_path.exists():
            continue
        target = source_dir / f"{item.get('kind', 'source')}_{source_path.name}"
        shutil.copy2(source_path, target)
        copied_sources.append(
            {
                "kind": item.get("kind", "source"),
                "filename": target.name,
                "relative_path": str(target.relative_to(package_dir)),
                "sha256": file_sha256(target),
            }
        )

    generated_paths = [ledger_path, evidence_path, captures_path, report_path]
    file_entries = [
        {
            "relative_path": str(path.relative_to(package_dir)),
            "size": path.stat().st_size,
            "sha256": file_sha256(path),
        }
        for path in generated_paths
    ]
    file_entries.extend(
        {
            "relative_path": item["relative_path"],
            "size": (package_dir / item["relative_path"]).stat().st_size,
            "sha256": item["sha256"],
        }
        for item in copied_evidence
    )
    file_entries.extend(
        {
            "relative_path": item["relative_path"],
            "size": (package_dir / item["relative_path"]).stat().st_size,
            "sha256": item["sha256"],
        }
        for item in copied_sources
    )

    document_coverage = {
        "ledger_transaction_rows": len(transactions),
        "ledger_row_capacity": effective_capacity,
        "evidence_document": evidence_coverage,
        "account_document": account_coverage,
        "copied_evidence_files": len(copied_evidence),
        "copied_source_files": len(copied_sources),
    }

    manifest = {
        "package_id": package_id,
        "club_name": club_name,
        "semester": semester,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": created_by,
        "snapshot_id": snapshot_id,
        "ledger_data_hash": ledger_data_hash,
        "validation_rule_version": VALIDATION_RULE_VERSION,
        "template_version": TEMPLATE_VERSION,
        "document_coverage": document_coverage,
        "validation": validation,
        "reconciliation": reconciliation,
        "evidence": copied_evidence,
        "source_files": copied_sources,
        "files": file_entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir))

    zip_hash = file_sha256(zip_path)
    manifest_hash = file_sha256(manifest_path)

    return {
        "zip_path": str(zip_path),
        "zip_sha256": zip_hash,
        "manifest_sha256": manifest_hash,
        "manifest": manifest,
        "document_coverage": document_coverage,
        "row_capacity": effective_capacity,
        "validation": validation,
        "artifacts": [
            {"kind": "ledger", "path": str(ledger_path), "sha256": file_sha256(ledger_path)},
            {"kind": "evidence", "path": str(evidence_path), "sha256": file_sha256(evidence_path)},
            {"kind": "account_captures", "path": str(captures_path), "sha256": file_sha256(captures_path)},
            {"kind": "validation_report", "path": str(report_path), "sha256": file_sha256(report_path)},
            {"kind": "manifest", "path": str(manifest_path), "sha256": manifest_hash},
            {"kind": "zip", "path": str(zip_path), "sha256": zip_hash},
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
    snapshot_id: str | None = None,
    expires_at: str | None = None,
    allow_download: bool = False,
) -> dict:
    summary = public_monthly_summary(opening_balance, transactions)
    public_transactions = []
    for item in transactions:
        public_transactions.append(
            {
                "number": item.number,
                "date": item.date,
                "description": item.description,
                "category": item.category,
                "income": item.income,
                "expense": item.expense,
                "balance": item.balance,
                "note": item.note if visible_notes else "",
            }
        )
    return {
        "id": report_id,
        "share_id": share_id,
        "snapshot_id": snapshot_id,
        "club_name": club_name,
        "month": month,
        "summary": summary,
        "transactions": public_transactions,
        "status": "active",
        "expires_at": expires_at,
        "allow_download": allow_download,
        "content_hash": canonical_sha256({"summary": summary, "transactions": public_transactions}),
    }
