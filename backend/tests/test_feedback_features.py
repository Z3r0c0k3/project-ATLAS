from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.accounting import (
    Evidence,
    Transaction,
    normalize_transactions,
    snapshot_payload,
    validate_ledger,
)
from app.services.security import SecretBox
from app.services.store import JsonStore


class SnapshotAndEvidenceTest(unittest.TestCase):
    def test_snapshot_hash_is_stable_and_rows_receive_identity(self) -> None:
        rows = [
            {
                "number": 1,
                "date": "2026-03-01",
                "description": "회비",
                "income": 100_000,
                "expense": 0,
                "balance": 1_100_000,
                "source_row": "2",
            }
        ]
        transactions = normalize_transactions(rows)
        first = snapshot_payload("aegis", "primary", "2026-1", transactions, [], {"type": "manual"})
        second = snapshot_payload("aegis", "primary", "2026-1", transactions, [], {"type": "manual"})

        self.assertEqual(first["data_hash"], second["data_hash"])
        self.assertTrue(transactions[0].transaction_id.startswith("tx_"))
        self.assertEqual(len(transactions[0].source_row_hash), 64)

    def test_duplicate_evidence_and_inaccessible_file_are_errors(self) -> None:
        transactions = [
            Transaction(1, "2026-03-01", "비품", 0, 10_000, 990_000, evidence_ids=("ev1",), transaction_id="tx1"),
            Transaction(2, "2026-03-02", "간식", 0, 20_000, 970_000, evidence_ids=("ev1",), transaction_id="tx2"),
        ]
        evidence = [Evidence("ev1", None, "receipt.png", "receipt", accessible=False)]

        result = validate_ledger(1_000_000, transactions, evidence, 970_000)
        codes = {item["code"] for item in result["issues"]}

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("DUPLICATE_EVIDENCE_LINK", codes)
        self.assertIn("EVIDENCE_INACCESSIBLE", codes)


class SecurityAndAuditTest(unittest.TestCase):
    def test_secrets_are_encrypted_at_rest(self) -> None:
        box = SecretBox("unit-test-secret")
        original = "https://discord.com/api/webhooks/123/secret"
        encrypted = box.encrypt(original)

        self.assertNotEqual(encrypted, original)
        self.assertNotIn("discord.com", encrypted)
        self.assertEqual(box.decrypt(encrypted), original)

    def test_audit_chain_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.append_audit({"actor": "a", "action": "created"})
            store.append_audit({"actor": "b", "action": "approved"})
            self.assertTrue(store.verify_audit_chain()["valid"])

            path = Path(tmp) / "audit_logs.json"
            rows = json.loads(path.read_text(encoding="utf-8"))
            list(rows.values())[0]["action"] = "tampered"
            path.write_text(json.dumps(rows), encoding="utf-8")
            self.assertFalse(store.verify_audit_chain()["valid"])


if __name__ == "__main__":
    unittest.main()
