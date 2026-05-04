from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

@app.route("/api/notifications", methods=["GET"])
def api_notifications_list():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    limit = _parse_int(request.args.get("limit")) or 20
    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    try:
        rows = (
            supabase.table("user_notifications")
            .select("*")
            .eq("user_id", int(user_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
        unread = sum(1 for row in rows if not row.get("is_read"))
        return jsonify({"ok": True, "notifications": rows, "unread_count": unread})
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)[:240]}), 500


@app.route("/api/notifications/unread-count", methods=["GET"])
def api_notifications_unread_count():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Authentication required."}), 401

    try:
        rows = (
            supabase.table("user_notifications")
            .select("id")
            .eq("user_id", int(user_id))
            .eq("is_read", False)
            .execute()
            .data or []
        )
        return jsonify({"ok": True, "unread_count": len(rows)})
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)[:240]}), 500


@app.route("/api/notifications/<signed_id:notification_id>/read", methods=["POST"])
def api_notification_mark_read(notification_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Authentication required."}), 401
    try:
        supabase.table("user_notifications").update({
            "is_read": True,
            "read_at": datetime.utcnow().isoformat(),
        }).eq("id", int(notification_id)).eq("user_id", int(user_id)).execute()
        return jsonify({"ok": True})
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)[:240]}), 500


@app.route("/api/notifications/read-all", methods=["POST"])
def api_notifications_mark_all_read():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Authentication required."}), 401
    try:
        supabase.table("user_notifications").update({
            "is_read": True,
            "read_at": datetime.utcnow().isoformat(),
        }).eq("user_id", int(user_id)).eq("is_read", False).execute()
        return jsonify({"ok": True})
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)[:240]}), 500


@app.route("/api/notifications/broadcast", methods=["POST"])
def api_notifications_broadcast():
    gate = _require_global_admin()
    if gate:
        return jsonify({"ok": False, "message": "Admin access required."}), 403

    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "System Notification").strip()
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "message": "Message is required."}), 400

    role_filter = _normalize_role(payload.get(
        "role")) if payload.get("role") else None
    school_id = _parse_int(payload.get("school_id"))
    high_volume = bool(payload.get("high_volume"))

    try:
        query = supabase.table("users").select("id, role")
        if role_filter:
            query = query.eq("role", role_filter)
        users = query.execute().data or []
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)[:240]}), 500

    sent_count = 0
    for user in users:
        user_id = user.get("id")
        if user_id is None:
            continue
        if school_id is not None:
            profile = _load_role_profile_for_login(user.get("role"), user_id)
            if not profile or _parse_int(profile.get("school_id")) != school_id:
                continue

        notify_user(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="broadcast",
            priority="high" if high_volume else "normal",
            send_email=True,
            send_sms=high_volume,
            meta={"broadcast": True},
        )
        sent_count += 1

    return jsonify({"ok": True, "sent": sent_count})


