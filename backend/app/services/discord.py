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


def render_package_approval_message(
    package: dict,
    approval_url: str,
    event: str,
    actor: str,
    user_ids: tuple[str, ...] = (),
    role_ids: tuple[str, ...] = (),
    note: str | None = None,
) -> dict:
    labels = {
        "pending_review": ("결재 요청", 0xD99A2B, "동연 패키지 검토와 결재가 필요합니다."),
        "approved": ("결재 승인", 0x3E8A4E, "동연 패키지가 승인되었습니다."),
        "rejected": ("결재 반려", 0xB94848, "동연 패키지가 반려되었습니다."),
    }
    title, color, description = labels[event]
    mentions = [*(f"<@{item}>" for item in user_ids), *(f"<@&{item}>" for item in role_ids)]
    validation = package.get("validation") or {}
    fields = [
        {"name": "회계 기간", "value": str(package.get("semester") or "-"), "inline": True},
        {"name": "버전", "value": f"v{package.get('version', 1)}", "inline": True},
        {"name": "요청·처리자", "value": actor, "inline": True},
        {
            "name": "검증 결과",
            "value": f"오류 {validation.get('error_count', 0)}건 · 경고 {validation.get('warning_count', 0)}건",
            "inline": False,
        },
    ]
    if note:
        fields.append({"name": "결재 의견", "value": note[:1024], "inline": False})
    content = " ".join(mentions)
    if event == "pending_review":
        content = f"{content}\nATLAS에 동연 패키지 결재 요청이 도착했습니다.".strip()
    return {
        "content": content,
        "allowed_mentions": {"parse": [], "users": list(user_ids), "roles": list(role_ids)},
        "embeds": [
            {
                "title": f"[ATLAS] {title}",
                "url": approval_url,
                "description": f"{description}\n[ATLAS에서 결재 처리하기]({approval_url})",
                "color": color,
                "fields": fields,
                "footer": {"text": f"패키지 ID: {package.get('id', '-')}"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def send_webhook(webhook_url: str, content: str | dict) -> dict:
    body = {"content": content} if isinstance(content, str) else content
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        request = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
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
    except ValueError as exc:
        return {"ok": False, "status_code": None, "error": str(exc)}
