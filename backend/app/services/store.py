from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def collection_path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def read_collection(self, collection: str) -> dict[str, Any]:
        path = self.collection_path(collection)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_collection(self, collection: str, payload: dict[str, Any]) -> None:
        path = self.collection_path(collection)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def insert(self, collection: str, payload: dict[str, Any], prefix: str) -> dict[str, Any]:
        rows = self.read_collection(collection)
        item_id = f"{prefix}_{secrets.token_urlsafe(8)}"
        payload = {
            **payload,
            "id": item_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        rows[item_id] = payload
        self.write_collection(collection, rows)
        return payload

    def get(self, collection: str, item_id: str) -> dict[str, Any] | None:
        return self.read_collection(collection).get(item_id)

    def find_one_by(self, collection: str, field: str, value: str) -> dict[str, Any] | None:
        for row in self.read_collection(collection).values():
            if row.get(field) == value:
                return row
        return None

    def update(self, collection: str, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        rows = self.read_collection(collection)
        if item_id not in rows:
            raise KeyError(item_id)
        rows[item_id] = {**rows[item_id], **patch, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.write_collection(collection, rows)
        return rows[item_id]
