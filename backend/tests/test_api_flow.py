from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.services.jobs import JobRunner
from app.services.store import JsonStore


TRANSACTIONS = [
    {"number": 1, "date": "2026-03-01", "description": "회비", "income": 100_000, "expense": 0, "balance": 1_100_000},
    {"number": 2, "date": "2026-03-02", "description": "현수막", "income": 0, "expense": 20_000, "balance": 1_080_000, "evidence_ids": ["ev1"]},
]
EVIDENCE = [
    {"id": "ev1", "transaction_number": 2, "filename": "receipt.png", "kind": "receipt", "accessible": True, "amount": 20_000, "evidence_date": "2026-03-02"}
]


class ApiWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous_store = main.store
        self.previous_jobs = main.jobs
        main.store = JsonStore(Path(self.temp.name))
        main.jobs = JobRunner(main.store, workers=1)
        self.client = TestClient(main.app)
        response = self.client.post("/auth/login", json={"username": "admin", "role": "admin"})
        self.assertEqual(response.status_code, 200)
        self.headers = {"X-ATLAS-Token": response.json()["token"]}

    def tearDown(self) -> None:
        main.jobs.executor.shutdown(wait=True)
        main.store = self.previous_store
        main.jobs = self.previous_jobs
        self.temp.cleanup()

    def test_package_public_link_webhook_and_audit_flow(self) -> None:
        package_response = self.client.post(
            "/packages/submission",
            headers=self.headers,
            json={
                "club_name": "Aegis",
                "semester": "2026년 1학기",
                "period_start": "2026-03-01",
                "period_end": "2026-06-30",
                "treasurer_name": "회계",
                "president_name": "회장",
                "reviewer_name": "검토",
                "opening_balance": 1_000_000,
                "expected_closing_balance": 1_080_000,
                "transactions": TRANSACTIONS,
                "evidence": EVIDENCE,
            },
        )
        self.assertEqual(package_response.status_code, 202)
        created = package_response.json()
        queued = self.client.get(f"/jobs/{created['job_id']}", headers=self.headers).json()
        self.assertEqual(queued["package_id"], created["package_id"])
        self.assertEqual(queued["snapshot_id"], created["snapshot_id"])

        for _ in range(100):
            job = self.client.get(f"/jobs/{created['job_id']}", headers=self.headers).json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "completed")

        package = self.client.get(f"/packages/{created['package_id']}", headers=self.headers).json()
        self.assertEqual(package["status"], "draft")
        self.assertEqual(package["validation"]["status"], "PASS")
        self.assertEqual(len(package["zip_sha256"]), 64)

        submitted = self.client.post(f"/packages/{package['id']}/submit-review", headers=self.headers)
        self.assertEqual(submitted.json()["status"], "pending_review")
        approved = self.client.post(f"/packages/{package['id']}/approve", headers=self.headers, json={"reason": "ok"})
        self.assertEqual(approved.json()["status"], "approved")

        report_response = self.client.post(
            "/monthly-reports",
            headers=self.headers,
            json={
                "club_name": "Aegis",
                "month": "2026년 3월",
                "snapshot_id": created["snapshot_id"],
                "opening_balance": 1_000_000,
            },
        )
        self.assertEqual(report_response.status_code, 200)
        report = report_response.json()
        public = self.client.get(f"/public/monthly/{report['share_id']}")
        self.assertEqual(public.status_code, 200)
        self.assertIn("noindex", public.headers["x-robots-tag"])
        self.assertNotIn("counterparty", public.text)

        webhook = self.client.post(
            "/discord/webhooks",
            headers=self.headers,
            json={"name": "test", "webhook_url": "https://discord.com/api/webhooks/123/secret"},
        )
        self.assertEqual(webhook.status_code, 200)
        stored = list(main.store.read_collection("discord_webhooks").values())[0]
        self.assertNotIn("discord.com", stored["encrypted_webhook_url"])

        revoked = self.client.post(f"/monthly-reports/{report['report_id']}/revoke", headers=self.headers)
        self.assertEqual(revoked.json()["status"], "revoked")
        self.assertEqual(self.client.get(f"/public/monthly/{report['share_id']}").status_code, 410)

        audit = self.client.get("/audit-logs", headers=self.headers).json()
        self.assertTrue(audit["chain"]["valid"])
        self.assertGreaterEqual(audit["chain"]["event_count"], 6)

    def test_google_oauth_state_is_required_and_single_use(self) -> None:
        redirect_uri = "https://atlas.example.com/"
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client"}):
            prepared = self.client.get(
                "/auth/google/authorize-url",
                headers=self.headers,
                params={"redirect_uri": redirect_uri},
            )
        self.assertEqual(prepared.status_code, 200)
        state = prepared.json()["state"]

        missing_state = self.client.post(
            "/auth/google/connect",
            headers=self.headers,
            json={"authorization_code": "code", "redirect_uri": redirect_uri},
        )
        self.assertEqual(missing_state.status_code, 422)

        with patch("app.main.exchange_authorization_code", return_value={"access_token": "access", "refresh_token": "refresh"}), patch(
            "app.main.google_account_email", return_value="aegis@example.com"
        ):
            connected = self.client.post(
                "/auth/google/connect",
                headers=self.headers,
                json={"authorization_code": "code", "redirect_uri": redirect_uri, "state": state},
            )
            replay = self.client.post(
                "/auth/google/connect",
                headers=self.headers,
                json={"authorization_code": "code", "redirect_uri": redirect_uri, "state": state},
            )

        self.assertEqual(connected.status_code, 200)
        self.assertTrue(connected.json()["connected"])
        self.assertEqual(connected.json()["account_email"], "aegis@example.com")
        self.assertEqual(replay.status_code, 409)
        self.assertTrue(self.client.get("/auth/google/status", headers=self.headers).json()["connected"])
        self.assertFalse(self.client.post("/auth/google/disconnect", headers=self.headers).json()["connected"])

    def test_google_api_refreshes_an_expired_access_token(self) -> None:
        connection = main.store.insert(
            "google_connections",
            {
                "account_email": "aegis@example.com",
                "encrypted_access_token": main.secret_box.encrypt("expired-access"),
                "encrypted_refresh_token": main.secret_box.encrypt("refresh-token"),
                "scopes": [],
            },
            "goog",
        )
        expired = main.GoogleApiError("expired", status_code=401)
        with patch("app.main.list_spreadsheets", side_effect=[expired, [{"id": "sheet-1", "name": "Aegis"}]]) as list_mock, patch(
            "app.main.refresh_access_token", return_value="renewed-access"
        ) as refresh_mock:
            response = self.client.get("/google/sheets", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sheets"][0]["id"], "sheet-1")
        self.assertEqual(list_mock.call_count, 2)
        refresh_mock.assert_called_once_with("refresh-token")
        stored = main.store.get("google_connections", connection["id"])
        self.assertEqual(main.secret_box.decrypt(stored["encrypted_access_token"]), "renewed-access")

    def test_google_token_decryption_failure_requests_reconnect(self) -> None:
        foreign_box = main.SecretBox("different-secret")
        main.store.insert(
            "google_connections",
            {
                "account_email": "aegis@example.com",
                "encrypted_access_token": foreign_box.encrypt("access-token"),
                "encrypted_refresh_token": foreign_box.encrypt("refresh-token"),
                "scopes": [],
            },
            "goog",
        )

        response = self.client.get("/google/sheets", headers=self.headers)
        diagnostics = self.client.get("/google/diagnostics", headers=self.headers)

        self.assertEqual(response.status_code, 409)
        self.assertIn("Reconnect the Google account", response.json()["detail"])
        self.assertEqual(diagnostics.status_code, 200)
        self.assertEqual(diagnostics.json()["checks"][0]["status"], "error")

    def test_google_diagnostics_checks_button_queries(self) -> None:
        main.store.insert(
            "google_connections",
            {
                "account_email": "aegis@example.com",
                "encrypted_access_token": main.secret_box.encrypt("access-token"),
                "encrypted_refresh_token": main.secret_box.encrypt("refresh-token"),
                "scopes": [],
            },
            "goog",
        )
        not_found = main.GoogleApiError("not found", status_code=404)
        with patch("app.main.get_sheet_values", side_effect=not_found), patch(
            "app.main.list_spreadsheets", return_value=[{"id": "sheet-1", "name": "Aegis Ledger"}]
        ), patch("app.main.list_drive_files", return_value=[{"id": "file-1", "name": "receipt.pdf"}]):
            response = self.client.get("/google/diagnostics", headers=self.headers)

        checks = {item["name"]: item for item in response.json()["checks"]}
        self.assertEqual(response.status_code, 200)
        self.assertEqual(checks["sheets_list"]["status"], "ok")
        self.assertEqual(checks["sheets_list"]["count"], 1)
        self.assertEqual(checks["drive_files_list"]["status"], "ok")
        self.assertEqual(checks["drive_files_list"]["count"], 1)

    def test_evidence_filename_hash_id_matching_ignores_receipt_dates(self) -> None:
        dated = main.evidence_transaction_number_from_filename("2026. 3. 1. 세미나 영수증.pdf")
        explicit = main.evidence_transaction_number_from_filename("#42# 2026. 3. 1. 세미나 영수증.pdf")
        dues = main.evidence_transaction_number_from_filename("*42* 2026. 3. 1. 회비 환불 소명.pdf")

        self.assertEqual(dated, (None, "unmatched", None))
        self.assertEqual(explicit, (42, "filename_hash_id", None))
        self.assertEqual(dues, (42, "filename_dues_star_id", "dues_intake"))

    def test_transaction_crud_creates_snapshot_revisions(self) -> None:
        snapshot = self.client.post(
            "/ledger-snapshots",
            headers=self.headers,
            json={
                "period": "2026년 3월",
                "transactions": TRANSACTIONS,
                "evidence": EVIDENCE,
            },
        ).json()

        added = self.client.post(
            f"/ledger-snapshots/{snapshot['id']}/transactions",
            headers=self.headers,
            json={"number": 3, "date": "2026-03-03", "description": "간식", "income": 0, "expense": 10_000, "balance": 1_070_000},
        )
        self.assertEqual(added.status_code, 200)
        added_snapshot = added.json()
        self.assertEqual(added_snapshot["source"]["parent_snapshot_id"], snapshot["id"])
        self.assertEqual(added_snapshot["source"]["mutation"]["action"], "transaction.created")

        updated = self.client.put(
            f"/ledger-snapshots/{added_snapshot['id']}/transactions/3",
            headers=self.headers,
            json={"description": "간식 추가 구매", "expense": 12_000, "balance": 1_068_000},
        )
        self.assertEqual(updated.status_code, 200)
        updated_snapshot = updated.json()
        self.assertEqual(updated_snapshot["transactions"][-1]["description"], "간식 추가 구매")

        deleted = self.client.delete(f"/ledger-snapshots/{updated_snapshot['id']}/transactions/3", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(len(deleted.json()["transactions"]), 2)


if __name__ == "__main__":
    unittest.main()
