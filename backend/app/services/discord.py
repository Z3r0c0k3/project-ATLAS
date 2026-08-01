from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


def render_monthly_discord_message(report: dict, public_url: str) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            f"[ATLAS] {report['club_name']} {report['month']} 회계 투명성 자료",
            f"수입: {summary['total_income']:,}원",
            f"지출: {summary['total_expense']:,}원",
            f"잔액: {summary['closing_balance']:,}원",
            f"상세 공개 페이지: {public_url}",
        ]
    )


def send_webhook(webhook_url: str, content: str) -> dict:
    payload = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": exc.code, "error": exc.reason}
    except urllib.error.URLError as exc:
        return {"ok": False, "status_code": None, "error": str(exc.reason)}
