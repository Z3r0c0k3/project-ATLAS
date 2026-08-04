from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any


def normalize_nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def normalize_filename(value: str | None, default: str = "upload.bin") -> str:
    raw = (value or default).replace("\\", "/")
    filename = normalize_nfc(Path(raw).name).replace("\x00", "")
    return filename if filename.strip() not in {"", ".", ".."} else default


def normalize_relative_path(path: Path) -> str:
    return "/".join(normalize_nfc(part) for part in path.parts)


def normalize_file_record_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**row, "name": normalize_nfc(str(row.get("name") or ""))}
        if "name" in row
        else row
        for row in rows
    ]
