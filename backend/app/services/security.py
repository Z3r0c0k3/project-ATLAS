from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret: str | None = None) -> None:
        raw_secret = secret or os.getenv("ATLAS_SECRET_KEY", "atlas-local-development-only")
        key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Stored secret cannot be decrypted with ATLAS_SECRET_KEY") from exc


def mask_webhook_url(url: str) -> str:
    if len(url) < 18:
        return "********"
    return f"{url[:12]}...{url[-6:]}"


def sanitize_secret_fields(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    blocked = {"access_token", "refresh_token", "webhook_url", "encrypted_webhook_url", "encrypted_access_token", "encrypted_refresh_token"}
    return {key: ("[REDACTED]" if key in blocked else value) for key, value in payload.items()}
