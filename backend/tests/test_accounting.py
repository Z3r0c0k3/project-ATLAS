from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.services.accounting import Evidence, Transaction, public_monthly_summary, validate_ledger
from app.services.documents import build_submission_package


class AccountingValidationTest(unittest.TestCase):
    def test_valid_ledger_passes_balance_and_evidence_checks(self) -> None:
        transactions = [
            Transaction(1, "2026-03-01", "회비", 100_000, 0, 1_100_000),
            Transaction(2, "2026-03-02", "현수막", 0, 20_000, 1_080_000, evidence_id="ev1"),
        ]
        evidence = [Evidence("ev1", 2, "receipt.png", "receipt")]

        result = validate_ledger(1_000_000, transactions, evidence, 1_080_000)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["summary"]["total_income"], 100_000)
        self.assertEqual(result["summary"]["total_expense"], 20_000)

    def test_invalid_ledger_reports_missing_evidence_and_balance_mismatch(self) -> None:
        transactions = [
            Transaction(1, "2026-03-01", "비품", 0, 30_000, 980_000),
        ]

        result = validate_ledger(1_000_000, transactions, [], 960_000)
        codes = {issue["code"] for issue in result["issues"]}

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("BALANCE_CONTINUITY", codes)
        self.assertIn("MISSING_EXPENSE_EVIDENCE", codes)
        self.assertIn("CLOSING_BALANCE_MISMATCH", codes)

    def test_monthly_summary_hides_private_metadata(self) -> None:
        transactions = [
            Transaction(1, "2026-03-01", "회비", 200_000, 0, 1_200_000),
            Transaction(2, "2026-03-10", "간식", 0, 50_000, 1_150_000, note="내부 메모"),
        ]

        summary = public_monthly_summary(1_000_000, transactions)

        self.assertEqual(summary["closing_balance"], 1_150_000)
        self.assertEqual(len(summary["categories"]["income"]), 1)
        self.assertEqual(len(summary["categories"]["expense"]), 1)
        self.assertNotIn("note", summary["categories"]["expense"][0])
        self.assertNotIn("evidence_id", summary["categories"]["expense"][0])


class PackageGenerationTest(unittest.TestCase):
    def test_submission_package_zip_contains_required_artifacts(self) -> None:
        transactions = [
            Transaction(1, "2026-03-01", "회비", 100_000, 0, 1_100_000),
            Transaction(2, "2026-03-02", "현수막", 0, 20_000, 1_080_000, evidence_id="ev1"),
        ]
        evidence = [Evidence("ev1", 2, "receipt.png", "receipt")]

        with tempfile.TemporaryDirectory() as tmp:
            result = build_submission_package(
                Path(tmp),
                "pkg_test",
                "Aegis",
                "2026년 1학기",
                "회계",
                "회장",
                "검토",
                1_000_000,
                1_080_000,
                transactions,
                evidence,
                40,
            )

            self.assertEqual(result["validation"]["status"], "PASS")
            with zipfile.ZipFile(result["zip_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("수입지출관리대장.xlsx", names)
            self.assertIn("영수증_및_소명자료.docx", names)
            self.assertIn("계좌전체내역.docx", names)
            self.assertIn("검증_리포트.html", names)
            self.assertIn("manifest.json", names)
            self.assertEqual(len(result["zip_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
