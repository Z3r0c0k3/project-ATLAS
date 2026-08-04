from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class JsonStore:
    """Small deployment-friendly store with atomic writes and process-level locking."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def collection_path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def _read_unlocked(self, collection: str) -> dict[str, Any]:
        path = self.collection_path(collection)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def read_collection(self, collection: str) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked(collection)

    def _write_unlocked(self, collection: str, payload: dict[str, Any]) -> None:
        path = self.collection_path(collection)
        temp_path = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def write_collection(self, collection: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._write_unlocked(collection, payload)

    def insert(self, collection: str, payload: dict[str, Any], prefix: str) -> dict[str, Any]:
        with self._lock:
            rows = self._read_unlocked(collection)
            item_id = f"{prefix}_{secrets.token_urlsafe(8)}"
            item = {**payload, "id": item_id, "created_at": utc_now()}
            rows[item_id] = item
            self._write_unlocked(collection, rows)
            return item

    def get(self, collection: str, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read_unlocked(collection).get(item_id)

    def find_one_by(self, collection: str, field: str, value: Any) -> dict[str, Any] | None:
        with self._lock:
            for row in self._read_unlocked(collection).values():
                if row.get(field) == value:
                    return row
        return None

    def find_all_by(self, collection: str, field: str, value: Any) -> list[dict[str, Any]]:
        with self._lock:
            return [row for row in self._read_unlocked(collection).values() if row.get(field) == value]

    def update(self, collection: str, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._read_unlocked(collection)
            if item_id not in rows:
                raise KeyError(item_id)
            rows[item_id] = {**rows[item_id], **patch, "updated_at": utc_now()}
            self._write_unlocked(collection, rows)
            return rows[item_id]

    def delete(self, collection: str, item_id: str) -> dict[str, Any]:
        with self._lock:
            rows = self._read_unlocked(collection)
            if item_id not in rows:
                raise KeyError(item_id)
            deleted = rows.pop(item_id)
            self._write_unlocked(collection, rows)
            return deleted

    def append_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._read_unlocked("audit_logs")
            previous = list(rows.values())[-1] if rows else None
            item_id = f"audit_{secrets.token_urlsafe(8)}"
            event = {
                **payload,
                "id": item_id,
                "created_at": utc_now(),
                "previous_hash": previous.get("event_hash") if previous else None,
            }
            event["event_hash"] = hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()
            rows[item_id] = event
            self._write_unlocked("audit_logs", rows)
            return event

    def verify_audit_chain(self) -> dict[str, Any]:
        with self._lock:
            previous_hash = None
            for index, event in enumerate(self._read_unlocked("audit_logs").values()):
                stored_hash = event.get("event_hash")
                check = {key: value for key, value in event.items() if key != "event_hash"}
                expected = hashlib.sha256(canonical_json(check).encode("utf-8")).hexdigest()
                if event.get("previous_hash") != previous_hash or stored_hash != expected:
                    return {"valid": False, "invalid_index": index, "event_id": event.get("id")}
                previous_hash = stored_hash
            return {"valid": True, "event_count": len(self._read_unlocked("audit_logs"))}
