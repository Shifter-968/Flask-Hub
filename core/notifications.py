"""Notification engine – email, SMS, in-app notifications."""
from extensions import (
    app, supabase,
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_USE_TLS,
    SMS_PROVIDER, SMS_FROM_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
    SMS_WEBHOOK_URL, SMS_WEBHOOK_TOKEN,
)
import smtplib
import json as std_json
import base64
from email.message import EmailMessage
from urllib import request as urllib_request, error as urllib_error, parse as urllib_parse
from flask import session, jsonify

# Helpers needed by notification functions (imported from helpers to avoid duplication)


def _normalize_role(role):
    return (role or '').strip().lower().replace('-', '_')


def _profile_table_for_role(role):
    return {
        'teacher': 'teachers', 'lecturer': 'lecturers', 'learner': 'learners',
        'student': 'students', 'parent': 'parents', 'staff': 'staff',
        'school_admin': 'school_admins',
    }.get(_normalize_role(role))


def _parse_int(value):
    try:
        if value is None:
            return None
        text = str(value).strip()
        return None if text == '' else int(text)
    except (TypeError, ValueError):
        return None


def _notification_meta(meta):
    if isinstance(meta, dict):
        return meta
    return {}


def _get_user_row(user_id):
    try:
        result = (
            supabase.table("users")
            .select("id, email, username, role")
            .eq("id", int(user_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _get_user_phone(user_id, role=None):
    role = _normalize_role(role)
    table_name = _profile_table_for_role(role) if role else None
    if not table_name:
        user_row = _get_user_row(user_id) or {}
        table_name = _profile_table_for_role(user_row.get("role"))
    if not table_name:
        return None

    for field in ["phone_number", "contact_number", "mobile_number", "phone"]:
        try:
            response = (
                supabase.table(table_name)
                .select(field)
                .eq("user_id", int(user_id))
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if rows and rows[0].get(field):
                return str(rows[0].get(field)).strip()
        except Exception:
            continue
    return None


def _record_delivery_log(user_id, channel, status, detail=None, notification_id=None):
    payload = {
        "user_id": int(user_id),
        "channel": channel,
        "status": status,
        "detail": (detail or "")[:1500],
    }
    if notification_id is not None:
        payload["notification_id"] = int(notification_id)
    try:
        supabase.table("notification_deliveries").insert(payload).execute()
    except Exception:
        pass


def _create_in_app_notification(user_id, title, message, notification_type="general", priority="normal", meta=None):
    payload = {
        "user_id": int(user_id),
        "title": (title or "Notification")[:140],
        "message": (message or "")[:1500],
        "notification_type": (notification_type or "general")[:60],
        "priority": (priority or "normal")[:20],
        "is_read": False,
        "meta_json": _notification_meta(meta),
    }
    try:
        response = supabase.table(
            "user_notifications").insert(payload).execute()
        created = response.data[0] if response.data else None
        notification_id = created.get("id") if created else None
        _record_delivery_log(user_id, "in_app", "sent",
                             "In-app notification created", notification_id)
        return created
    except Exception as error:
        _record_delivery_log(user_id, "in_app", "failed",
                             f"In-app create failed: {str(error)[:300]}")
        return None


def _send_email_notification(to_email, subject, body_text):
    if not to_email:
        return False, "Missing recipient email"
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        return False, "SMTP config missing"

    msg = EmailMessage()
    msg["Subject"] = (subject or "Notification")[:180]
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body_text or "")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True, "Email sent"
    except Exception as error:
        return False, str(error)[:300]


def _send_sms_notification(to_number, message):
    if not to_number:
        return False, "Missing recipient number"

    if SMS_PROVIDER == "twilio":
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not SMS_FROM_NUMBER:
            return False, "Twilio config missing"
        try:
            data = urllib_request.urlencode({
                "To": to_number,
                "From": SMS_FROM_NUMBER,
                "Body": (message or "")[:320],
            }).encode()
            req = urllib_request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
                data=data,
                method="POST",
            )
            basic_token = f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode(
                "utf-8")
            import base64
            req.add_header("Authorization", "Basic " +
                           base64.b64encode(basic_token).decode("utf-8"))
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib_request.urlopen(req, timeout=15):
                return True, "SMS sent"
        except urllib_error.HTTPError as error:
            return False, f"HTTP {error.code}"
        except Exception as error:
            return False, str(error)[:300]

    if SMS_PROVIDER == "webhook":
        if not SMS_WEBHOOK_URL:
            return False, "SMS webhook URL missing"
        try:
            payload = std_json.dumps({
                "to": to_number,
                "message": (message or "")[:320],
                "from": SMS_FROM_NUMBER or None,
            }).encode("utf-8")
            req = urllib_request.Request(
                SMS_WEBHOOK_URL, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            if SMS_WEBHOOK_TOKEN:
                req.add_header("Authorization", f"Bearer {SMS_WEBHOOK_TOKEN}")
            with urllib_request.urlopen(req, timeout=15):
                return True, "SMS webhook sent"
        except Exception as error:
            return False, str(error)[:300]

    return False, "No SMS provider configured"


def _friendly_verification_delivery_error(channel, detail):
    detail_text = (detail or "").strip().lower()
    if channel == "email":
        if "application-specific password" in detail_text or "5.7.9" in detail_text:
            return "Email provider blocked login. Set SMTP_PASSWORD to a Gmail App Password (not your normal password), then redeploy."
        if "authentication" in detail_text or "535" in detail_text:
            return "Email authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD in Render environment variables."
        if "smtp config missing" in detail_text:
            return "Email is not configured yet. Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, and SMTP_USE_TLS in Render."
    if channel == "phone":
        if "twilio config missing" in detail_text or "no sms provider configured" in detail_text:
            return "Phone verification is not configured yet. Set SMS_PROVIDER and SMS credentials in Render."
    return "Verification send failed. Check provider configuration and try again."


def notify_user(user_id, title, message, notification_type="general", priority="normal", send_email=True, send_sms=False, meta=None):
    user_row = _get_user_row(user_id)
    if not user_row:
        return {"ok": False, "reason": "user_not_found"}

    created = _create_in_app_notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        meta=meta,
    )
    notification_id = created.get("id") if created else None

    email_result = {"sent": False, "detail": "skipped"}
    sms_result = {"sent": False, "detail": "skipped"}

    if send_email:
        ok, detail = _send_email_notification(
            user_row.get("email"),
            subject=f"{title}",
            body_text=f"{message}\n\nSent by SmartHub Notifications",
        )
        email_result = {"sent": ok, "detail": detail}
        _record_delivery_log(
            user_id, "email", "sent" if ok else "failed", detail, notification_id)

    # High-volume/high-priority notifications can be escalated to SMS.
    if send_sms:
        phone_number = _get_user_phone(user_id, role=user_row.get("role"))
        ok, detail = _send_sms_notification(phone_number, message)
        sms_result = {"sent": ok, "detail": detail}
        _record_delivery_log(
            user_id, "sms", "sent" if ok else "failed", detail, notification_id)

    return {
        "ok": True,
        "notification_id": notification_id,
        "email": email_result,
        "sms": sms_result,
    }


def _notify_school_admins(school_id, title, message, notification_type="system", priority="high", send_email=True, send_sms=True, meta=None):
    try:
        rows = (
            supabase.table("school_admins")
            .select("user_id")
            .eq("school_id", int(school_id))
            .execute()
            .data or []
        )
    except Exception:
        rows = []

    user_ids = [r.get("user_id") for r in rows if r.get("user_id") is not None]
    for uid in user_ids:
        notify_user(
            user_id=uid,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            send_email=send_email,
            send_sms=send_sms,
            meta=meta,
        )


def _notify_global_admins(title, message, notification_type="system", priority="high", send_email=True, send_sms=True, meta=None):
    try:
        rows = (
            supabase.table("users")
            .select("id")
            .eq("role", "admin")
            .execute()
            .data or []
        )
    except Exception:
        rows = []

    for row in rows:
        uid = row.get("id")
        if uid is None:
            continue
        notify_user(
            user_id=uid,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            send_email=send_email,
            send_sms=send_sms,
            meta=meta,
        )


def _school_user_ids(school_id):
    table_names = [
        "school_admins",
        "teachers",
        "lecturers",
        "students",
        "learners",
        "parents",
        "staff",
    ]
    user_ids = set()
    for table_name in table_names:
        try:
            rows = (
                supabase.table(table_name)
                .select("user_id")
                .eq("school_id", int(school_id))
                .execute()
                .data or []
            )
            for row in rows:
                uid = _parse_int(row.get("user_id"))
                if uid is not None:
                    user_ids.add(uid)
        except Exception:
            continue
    return sorted(user_ids)


def _notify_school_users(school_id, title, message, notification_type="announcement", priority="normal", send_email=True, send_sms=False, meta=None):
    for uid in _school_user_ids(school_id):
        notify_user(
            user_id=uid,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            send_email=send_email,
            send_sms=send_sms,
            meta=meta,
        )


@app.context_processor
def inject_notification_counts():
    user_id = session.get("user_id")
    if not user_id:
        return {"unread_notifications_count": 0}
    try:
        rows = (
            supabase.table("user_notifications")
            .select("id")
            .eq("user_id", int(user_id))
            .eq("is_read", False)
            .execute()
            .data or []
        )
        return {"unread_notifications_count": len(rows)}
    except Exception:
        return {"unread_notifications_count": 0}


@app.context_processor
def inject_school_link_helpers():
    from core.helpers import _school_login_url, _school_public_url, _encode_school_ref
    return {
        "school_login_url": _school_login_url,
        "school_public_url": _school_public_url,
        "school_ref_token": _encode_school_ref,
    }
