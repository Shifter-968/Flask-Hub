"""Shared helper functions – imported by all route modules."""
import os
import re
import uuid
import hashlib
import json as std_json
from datetime import datetime, timedelta
from itsdangerous import URLSafeSerializer, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, url_for, request, redirect,
    session, flash, jsonify, json, current_app,
)
from extensions import (
    app, supabase,
    SIGNED_ID_TOKEN_SALT, SCHOOL_LINK_TOKEN_SALT, MEETING_PASSWORD_TOKEN_SALT,
    UPLOAD_FOLDER, APPLY_UPLOAD_FOLDER, ALLOWED_EXTENSIONS,
    SHOW_SCHOOL_ADMIN_ROLE, GOOGLE_CLIENT_ID, AUTH_CODE_TTL_MINUTES,
    _openai_available, _OpenAIClient, _OpenAIConnectionError,
    _OpenAIAuthenticationError, _OpenAIRateLimitError, OPENAI_MODEL,
    INSTRUCTOR_AI_PREMIUM_ENABLED, STUDY_AI_MEDIA_DAILY_LIMIT,
    _httpx_available, _httpx,
)
import re as _re


def _wants_json_response():
    if request.path.startswith("/api/") or request.path.startswith("/ai/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept.lower()


if _httpx_available:
    @app.errorhandler(_httpx.ReadError)
    def handle_httpx_read_error(exc):
        app.logger.warning("Transient network read error: %s", exc)
        if _wants_json_response():
            return jsonify({"error": "Network read error while contacting an external service. Please retry."}), 502
        flash(
            "Network error while contacting an external service. Please try again.", "error")


def _is_placeholder_secret(value):
    value = (value or "").strip()
    if not value:
        return True
    placeholder_tokens = [
        "your_openai_api_key_here",
        "replace_me",
        "paste_key_here",
        "changeme",
    ]
    lowered = value.lower()
    return lowered in placeholder_tokens


def _get_openai_api_key():
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def _openai_is_ready():
    return _openai_available and not _is_placeholder_secret(_get_openai_api_key())


def _build_openai_client():
    api_key = _get_openai_api_key()
    if not _openai_available:
        return None, "OpenAI library is not installed in this environment."
    if _is_placeholder_secret(api_key):
        return None, "OPENAI_API_KEY is missing or still using a placeholder value in .env."
    return _OpenAIClient(api_key=api_key), None


def _log_startup_configuration_warnings():
    if not _openai_available:
        app.logger.warning(
            "AI comments disabled: openai package is not installed in the active Python environment."
        )
        return
    if _is_placeholder_secret(_get_openai_api_key()):
        app.logger.warning(
            "AI comments disabled: OPENAI_API_KEY is missing or still set to a placeholder in the .env file."
        )


# Called at startup in app_new.py
SHOW_SCHOOL_ADMIN_ROLE = os.getenv(
    "SHOW_SCHOOL_ADMIN_ROLE", "false").strip().lower() == "true"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload_file(file):
    if not file or not file.filename or file.filename == "":
        return None, None

    filename = secure_filename(file.filename)
    if not allowed_file(filename):
        return None, None

    stored_name = f"{uuid.uuid4().hex}_{filename}"
    stored_path = os.path.join(UPLOAD_FOLDER, stored_name)
    file.save(stored_path)
    return f"uploads/classroom/{stored_name}", filename


def _is_global_admin_session():
    return _normalize_role(session.get("role")) == "admin"


def _require_global_admin():
    if _is_global_admin_session():
        return None
    flash("Admin access required.", "error")
    return redirect(url_for("login"))


def _validate_password_strength(password):
    if not password:
        return "Password is required."
    if not PASSWORD_POLICY_REGEX.match(password):
        return (
            "Password must be at least 8 characters and include an uppercase letter, "
            "lowercase letter, number, and special character."
        )
    return None


def _is_missing_school_admins_table(error):
    msg = str(error).lower()
    return "school_admins" in msg and (
        "does not exist" in msg or "relation" in msg or "not found" in msg
    )


def _is_missing_staff_schema(error):
    msg = str(error).lower()
    return "staff" in msg and (
        "school_id" in msg or "does not exist" in msg or "relation" in msg or "not found" in msg
    )


# ------------------------------------------------------------------------------------------Notification Engine--------
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int((os.getenv("SMTP_PORT") or "587").strip() or "587")
SMTP_USERNAME = (os.getenv("SMTP_USERNAME") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
SMTP_FROM_EMAIL = (os.getenv("SMTP_FROM_EMAIL") or "").strip()
SMTP_USE_TLS = (os.getenv("SMTP_USE_TLS") or "true").strip().lower() == "true"

SMS_PROVIDER = (os.getenv("SMS_PROVIDER") or "none").strip().lower()
SMS_FROM_NUMBER = (os.getenv("SMS_FROM_NUMBER") or "").strip()
TWILIO_ACCOUNT_SID = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
SMS_WEBHOOK_URL = (os.getenv("SMS_WEBHOOK_URL") or "").strip()
SMS_WEBHOOK_TOKEN = (os.getenv("SMS_WEBHOOK_TOKEN") or "").strip()
GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
try:
    AUTH_CODE_TTL_MINUTES = int(
        (os.getenv("AUTH_CODE_TTL_MINUTES") or "15").strip())
except (TypeError, ValueError):
    AUTH_CODE_TTL_MINUTES = 15
AUTH_CODE_TTL_MINUTES = max(5, AUTH_CODE_TTL_MINUTES)


def _insert_contact_message(payload):
    candidates = [
        payload,
        {k: v for k, v in payload.items() if k not in {"source_scope",
                                                       "source_site", "status", "page_url"}},
        {k: v for k, v in payload.items() if k not in {"source_scope", "source_site"}},
        {k: v for k, v in payload.items() if k not in {"status", "page_url"}},
    ]

    last_error = None
    seen = set()
    for item in candidates:
        key = tuple(sorted(item.keys()))
        if key in seen:
            continue
        seen.add(key)
        try:
            supabase.table("contact_messages").insert(item).execute()
            return True, None
        except Exception as error:
            last_error = error

    return False, last_error


def _load_contact_messages_for_scope(scope="all", school_id=None, limit=500):
    try:
        rows = (
            supabase.table("contact_messages")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
    except Exception:
        return []

    if school_id is not None:
        rows = [r for r in rows if int(
            r.get("school_id") or 0) == int(school_id)]
        return rows

    if scope == "main":
        rows = [r for r in rows if not r.get("school_id")]
    elif scope == "school":
        rows = [r for r in rows if r.get("school_id")]
    return rows


def _get_school_record(school_id):
    response = supabase.table("schools").select(
        "*").eq("id", school_id).execute()
    return response.data[0] if response.data else None


def _normalize_school_type(school_type):
    return (school_type or "").strip().lower()


def _normalize_role(role):
    return (role or "").strip().lower().replace("-", "_")


def _school_type_label(school_type):
    labels = {
        "pre_school": "Pre-School",
        "primary_school": "Primary School",
        "high_school": "High School",
        "tertiary": "Tertiary Institution",
    }
    normalized_type = _normalize_school_type(school_type)
    return labels.get(normalized_type, "School")


def _allowed_roles_for_school_type(school_type):
    normalized_type = _normalize_school_type(school_type)

    if normalized_type == "tertiary":
        return ["student", "lecturer", "parent", "staff"]

    if normalized_type in {"pre_school", "primary_school", "high_school"}:
        return ["learner", "teacher", "parent", "staff"]

    return ["parent", "staff"]


def _role_options_for_school_type(school_type):
    role_labels = {
        "teacher": "Teacher",
        "lecturer": "Lecturer",
        "student": "Student",
        "learner": "Learner",
        "parent": "Parent",
        "staff": "Staff",
        "school_admin": "School Admin",
    }
    options = []
    for role in _allowed_roles_for_school_type(school_type):
        options.append({"value": role, "label": role_labels[role]})
    return options


def _school_allows_role(school, role):
    if not school:
        return False
    normalized_role = _normalize_role(role)
    if normalized_role == "school_admin":
        return True
    return normalized_role in _allowed_roles_for_school_type(school.get("school_type"))


def _school_from_form_or_session(school_id_value):
    if not school_id_value:
        return None

    try:
        return _get_school_record(int(school_id_value))
    except (TypeError, ValueError):
        return None


def _reject_disallowed_role(role, school):
    normalized_role = _normalize_role(role)
    school_label = _school_type_label((school or {}).get("school_type"))
    flash(
        f"{normalized_role.replace('_', ' ').title()} accounts are not allowed for {school_label} registrations.",
        "error",
    )
    if school and school.get("id"):
        return redirect(url_for("register", school_id=school["id"]))
    return redirect(url_for("schools_directory"))


def _table_rows(table_name, school_id, order_by=None, ascending=True):
    builder = supabase.table(table_name).select("*").eq("school_id", school_id)
    if order_by:
        builder = builder.order(order_by, desc=(not ascending))
    response = builder.execute()
    return response.data or []


def _parse_int(value):
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _school_link_serializer():
    return URLSafeSerializer(app.secret_key, salt=SCHOOL_LINK_TOKEN_SALT)


def _signed_id_serializer():
    return URLSafeSerializer(app.secret_key, salt=SIGNED_ID_TOKEN_SALT)


def _meeting_password_serializer():
    return URLSafeSerializer(app.secret_key, salt=MEETING_PASSWORD_TOKEN_SALT)


def _seal_meeting_password(plain_text):
    raw = (plain_text or "").strip()
    if not raw:
        return ""
    try:
        return _meeting_password_serializer().dumps({"p": raw})
    except Exception:
        return ""


def _reveal_meeting_password(sealed_text):
    token = (sealed_text or "").strip()
    if not token:
        return ""
    try:
        payload = _meeting_password_serializer().loads(token)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return (payload.get("p") or "").strip()


def _encode_school_ref(school_id):
    school_id_int = _parse_int(school_id)
    if school_id_int is None:
        return None
    return _school_link_serializer().dumps({"school_id": school_id_int})


def _decode_school_ref(school_ref):
    school_id_int = _parse_int(school_ref)
    if school_id_int is not None:
        return school_id_int

    token = (school_ref or "").strip()
    if not token:
        return None
    try:
        payload = _school_link_serializer().loads(token)
    except BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_int(payload.get("school_id"))


def _encode_signed_id(value):
    id_int = _parse_int(value)
    if id_int is None:
        return None
    try:
        return _signed_id_serializer().dumps({"id": id_int})
    except Exception:
        return None


def _decode_signed_id(value):
    raw_int = _parse_int(value)
    if raw_int is not None:
        return raw_int

    token = (value or "").strip()
    if not token:
        return None
    try:
        payload = _signed_id_serializer().loads(token)
    except BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_int(payload.get("id"))


def _school_login_url(school_id=None):
    school_id_int = _parse_int(school_id)
    if school_id_int is None:
        return url_for("login")
    school_ref = _encode_school_ref(school_id_int)
    if not school_ref:
        return url_for("login")
    return url_for("login", school_ref=school_ref)


def _school_public_url(school_id, page_slug="home"):
    school_id_int = _parse_int(school_id)
    if school_id_int is None:
        return url_for("home")
    return url_for("school_page", school_id=school_id_int, page_slug=page_slug)


def _current_school_dashboard_url():
    role = _normalize_role(session.get("role"))
    school_id = _parse_int(session.get("school_id"))
    if role == "admin":
        return url_for("admin_dashboard")
    if school_id is None:
        return url_for("login")

    route_map = {
        "student": "student_dashboard",
        "learner": "learner_dashboard",
        "teacher": "teacher_dashboard",
        "lecturer": "lecturer_dashboard",
        "parent": "parent_dashboard",
        "staff": "staff_dashboard",
        "school_admin": "school_admin_dashboard",
    }
    endpoint = route_map.get(role)
    if not endpoint:
        return url_for("login")
    return url_for(endpoint, school_id=school_id)


def _require_authenticated_school_context(school_id, allowed_roles=None):
    if not session.get("user_id"):
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    if _is_global_admin_session():
        return None

    current_role = _normalize_role(session.get("role"))
    if allowed_roles:
        normalized_roles = {_normalize_role(role) for role in allowed_roles}
        if current_role not in normalized_roles:
            flash("Access denied for this user role.", "error")
            return redirect(_current_school_dashboard_url())

    current_school_id = _parse_int(session.get("school_id"))
    requested_school_id = _parse_int(school_id)
    if current_school_id is None or requested_school_id is None or current_school_id != requested_school_id:
        flash("Access denied for this school context.", "error")
        return redirect(_current_school_dashboard_url())
    return None


def _parse_iso_date(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except Exception:
        return None


def _announcement_is_active(announcement, today=None):
    today = today or datetime.utcnow().date()
    expires_at = _parse_iso_date(announcement.get("expires_at"))
    if not expires_at:
        return True
    return expires_at >= today


def _load_active_announcements(school_id):
    try:
        rows = (
            supabase.table("announcements")
            .select("*")
            .eq("school_id", school_id)
            .order("created_at", desc=True)
            .execute()
            .data or []
        )
    except Exception:
        return []

    today = datetime.utcnow().date()
    active_rows = [
        row for row in rows if _announcement_is_active(row, today=today)]
    # Sort by newest first, then pin high alerts above normal alerts.
    active_rows.sort(key=lambda row: (
        row.get("created_at") or ""), reverse=True)
    active_rows.sort(key=lambda row: 0 if (
        row.get("alert_level") or "normal") == "high" else 1)
    return active_rows


def _is_missing_school_column_error(error):
    msg = str(error).lower()
    # PGRST204 = column not found in schema cache (PostgREST error)
    missing_col = (
        "column" in msg
        or "does not exist" in msg
        or "unknown" in msg
        or "schema cache" in msg
        or "pgrst204" in msg
    )
    return missing_col


def _select_school_scoped(table_name, school_id=None, order_by=None):
    query = supabase.table(table_name).select("*")
    if school_id is not None:
        query = query.eq("school_id", school_id)
    if order_by:
        query = query.order(order_by)
    try:
        return query.execute().data or []
    except Exception as e:
        # Legacy schemas may still use global records without school_id.
        if school_id is not None and _is_missing_school_column_error(e):
            fallback = supabase.table(table_name).select("*")
            if order_by:
                fallback = fallback.order(order_by)
            return fallback.execute().data or []
        raise


def _insert_school_scoped(table_name, payload, school_id=None):
    scoped_payload = dict(payload or {})
    if school_id is not None and "school_id" not in scoped_payload:
        scoped_payload["school_id"] = school_id
    try:
        return supabase.table(table_name).insert(scoped_payload).execute()
    except Exception as e:
        if school_id is not None and _is_missing_school_column_error(e):
            scoped_payload.pop("school_id", None)
            return supabase.table(table_name).insert(scoped_payload).execute()
        raise


def _parse_money(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    text = text.replace("E", "").replace("$", "")
    if text == "":
        return None
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return None


def _finance_balance_delta(txn_type, amount):
    if txn_type == "payment":
        return -abs(amount)
    if txn_type == "charge":
        return abs(amount)
    return amount


def _finance_get_account_row(school_id, account_id):
    try:
        rows = (
            supabase.table("student_finance_accounts")
            .select("*")
            .eq("school_id", int(school_id))
            .eq("id", int(account_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _finance_recompute_account_balance(school_id, account_id):
    """Recompute current_balance from opening_balance + full ledger transactions."""
    account = _finance_get_account_row(school_id, account_id)
    if not account:
        return {"ok": False, "error": "Finance account not found."}

    opening_balance = _parse_money(account.get("opening_balance")) or 0.0
    try:
        transactions = (
            supabase.table("student_finance_transactions")
            .select("txn_type,amount")
            .eq("school_id", int(school_id))
            .eq("account_id", int(account_id))
            .execute()
            .data
            or []
        )
    except Exception as error:
        return {"ok": False, "error": str(error)}

    recomputed_balance = opening_balance
    for txn in transactions:
        amount = _parse_money(txn.get("amount"))
        if amount is None:
            continue
        recomputed_balance += _finance_balance_delta(
            txn.get("txn_type"), amount)

    recomputed_balance = round(recomputed_balance, 2)

    try:
        supabase.table("student_finance_accounts").update({
            "current_balance": recomputed_balance,
        }).eq("id", int(account_id)).eq("school_id", int(school_id)).execute()
    except Exception as error:
        return {"ok": False, "error": str(error)}

    return {
        "ok": True,
        "balance": recomputed_balance,
        "transaction_count": len(transactions),
    }


def _finance_table_missing_error(error):
    msg = str(error).lower()
    return "student_finance_" in msg and (
        "does not exist" in msg
        or "relation" in msg
        or "not found" in msg
        or "schema cache" in msg
    )


def _today_date_str():
    """Return today's date as YYYY-MM-DD, used for file naming."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def _upsert_profile_for_role(role, user_id, school_id, form_data, mode="create"):
    # Allow callers to pass either request.form or request by mistake.
    if hasattr(form_data, "form"):
        form_data = form_data.form

    if form_data is None:
        form_data = {}

    normalized_role = _normalize_role(role)
    school_id_int = _parse_int(school_id)
    if school_id_int is None:
        raise ValueError("A valid school is required.")

    name = (form_data.get("name") or "").strip()
    phone = (form_data.get("phone_number") or "").strip() or None

    if normalized_role in {"teacher", "lecturer", "learner", "student", "parent", "staff", "school_admin"} and not name:
        raise ValueError("Name is required for this role.")

    payload = {"user_id": int(user_id), "school_id": school_id_int}
    table_name = None

    if normalized_role == "teacher":
        table_name = "teachers"
        payload.update({
            "name": name,
            "phone_number": phone,
            "core_subjects": (form_data.get("core_subjects") or "").strip() or None,
        })
    elif normalized_role == "lecturer":
        table_name = "lecturers"
        payload.update({
            "name": name,
            "phone_number": phone,
            "faculty": (form_data.get("faculty") or "").strip() or None,
        })
    elif normalized_role == "student":
        table_name = "students"
        payload.update({
            "name": name,
            "phone_number": phone,
            "current_residential_address": (form_data.get("current_residential_address") or "").strip() or None,
            "year_of_enrollment": _parse_int(form_data.get("year_of_enrollment")),
            "course_duration": _parse_int(form_data.get("course_duration")),
            "course_id": _parse_int(form_data.get("course_id")),
            "year_of_study": _parse_int(form_data.get("year_of_study")),
            "semester": _parse_int(form_data.get("semester")),
        })
    elif normalized_role == "learner":
        table_name = "learners"
        payload.update({
            "name": name,
            "phone_number": phone,
            "current_residential_address": (form_data.get("current_residential_address") or "").strip() or None,
            "grade": (form_data.get("grade") or "").strip() or None,
            "year_of_study": _parse_int(form_data.get("year_of_study")),
            "classroom_id": None,
        })
    elif normalized_role == "parent":
        table_name = "parents"
        payload.update({
            "name": name,
            "subscription_status": (form_data.get("subscription_status") or "").strip() or None,
        })
    elif normalized_role == "staff":
        table_name = "staff"
        payload.update({
            "name": name,
            "phone_number": phone,
            "department": (form_data.get("department") or "").strip() or None,
        })
    elif normalized_role == "school_admin":
        table_name = "school_admins"
        payload.update({
            "name": name,
            "phone_number": phone,
        })

    if not table_name:
        return None

    if mode == "update":
        existing = supabase.table(table_name).select("id").eq(
            "user_id", int(user_id)).limit(1).execute().data or []
        if existing:
            return supabase.table(table_name).update(payload).eq("user_id", int(user_id)).execute()

    profile_insert = _insert_school_scoped(
        table_name, payload, school_id=school_id_int)

    if normalized_role == "learner":
        learner_id = None
        if getattr(profile_insert, "data", None):
            learner_id = profile_insert.data[0].get("id")
        if learner_id is None:
            learner_rows = supabase.table("learners").select("id").eq(
                "user_id", int(user_id)).order("id", desc=True).limit(1).execute().data or []
            learner_id = learner_rows[0].get("id") if learner_rows else None

        if learner_id is not None:
            if "subject_ids" in form_data:
                selected_subject_ids = [_parse_int(
                    v) for v in form_data.getlist("subject_ids")]
                selected_subject_ids = [
                    v for v in selected_subject_ids if v is not None]
                try:
                    supabase.table("learner_subjects").delete().eq(
                        "learner_id", int(learner_id)).execute()
                except Exception:
                    pass
                for subject_id in selected_subject_ids:
                    supabase.table("learner_subjects").insert({
                        "learner_id": int(learner_id),
                        "subject_id": int(subject_id),
                    }).execute()

    return profile_insert


def _delete_profile_for_role(role, user_id):
    normalized_role = _normalize_role(role)
    table_map = {
        "teacher": "teachers",
        "lecturer": "lecturers",
        "student": "students",
        "learner": "learners",
        "parent": "parents",
        "staff": "staff",
        "school_admin": "school_admins",
    }
    table_name = table_map.get(normalized_role)
    if not table_name:
        return
    if normalized_role == "learner":
        learner_rows = supabase.table("learners").select(
            "id").eq("user_id", int(user_id)).execute().data or []
        for row in learner_rows:
            if row.get("id") is not None:
                supabase.table("learner_subjects").delete().eq(
                    "learner_id", int(row["id"])).execute()
    supabase.table(table_name).delete().eq("user_id", int(user_id)).execute()


def _load_role_profile_for_login(role, user_id):
    normalized_role = _normalize_role(role)
    query_map = {
        "student": ("students", "id, school_id, name"),
        "learner": ("learners", "id, school_id, name"),
        "teacher": ("teachers", "id, school_id, name"),
        "lecturer": ("lecturers", "id, school_id, name"),
        "parent": ("parents", "school_id, name"),
        "staff": ("staff", "school_id, name"),
        "school_admin": ("school_admins", "id, school_id, name"),
    }
    table_config = query_map.get(normalized_role)
    if not table_config:
        return None

    table_name, columns = table_config
    response = supabase.table(table_name).select(columns).eq(
        "user_id", user_id).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


def _role_label(role):
    labels = {
        "admin": "Platform Admins",
        "school_admin": "School Admins",
        "teacher": "Teachers",
        "lecturer": "Lecturers",
        "learner": "Learners",
        "student": "Students",
        "parent": "Parents",
        "staff": "Staff",
    }
    return labels.get(_normalize_role(role), (role or "Users").replace("_", " ").title())


def _role_singular_label(role):
    labels = {
        "admin": "Platform Admin",
        "school_admin": "School Admin",
        "teacher": "Teacher",
        "lecturer": "Lecturer",
        "learner": "Learner",
        "student": "Student",
        "parent": "Parent",
        "staff": "Staff Member",
    }
    return labels.get(_normalize_role(role), (role or "User").replace("_", " ").title())


def _profile_table_for_role(role):
    return {
        "teacher": "teachers",
        "lecturer": "lecturers",
        "learner": "learners",
        "student": "students",
        "parent": "parents",
        "staff": "staff",
        "school_admin": "school_admins",
    }.get(_normalize_role(role))


def _load_users_basic():
    response = supabase.table("users").select("*").order("username").execute()
    return response.data or []


def _find_user_identity_conflicts(email=None, username=None, exclude_user_id=None):
    normalized_email = (email or "").strip().lower()
    normalized_username = (username or "").strip().lower()
    excluded = _parse_int(exclude_user_id)
    conflicts = {"email": None, "username": None}

    for user in _load_users_basic():
        current_user_id = _parse_int(user.get("id"))
        if excluded is not None and current_user_id == excluded:
            continue

        candidate_email = (user.get("email") or "").strip().lower()
        candidate_username = (user.get("username") or "").strip().lower()

        if normalized_email and candidate_email == normalized_email and conflicts["email"] is None:
            conflicts["email"] = user
        if normalized_username and candidate_username == normalized_username and conflicts["username"] is None:
            conflicts["username"] = user

        if conflicts["email"] and conflicts["username"]:
            break

    return conflicts


def _normalize_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits


def _mask_destination(channel, destination):
    text = (destination or "").strip()
    if not text:
        return ""
    if channel == "email" and "@" in text:
        local, domain = text.split("@", 1)
        local_mask = (local[:2] + "***") if len(local) > 2 else "***"
        return f"{local_mask}@{domain}"
    if channel == "phone":
        digits = _normalize_phone(text)
        if len(digits) <= 4:
            return "***"
        return f"***{digits[-4:]}"
    return "***"


def _auth_code_hash(code):
    raw = f"{app.secret_key}|{(code or '').strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _auth_codes_table_missing(error):
    message = str(error).lower()
    return "auth_verification_codes" in message and (
        "does not exist" in message or "relation" in message or "not found" in message
    )


def _store_auth_verification_code(user_id, purpose, channel, destination, code):
    expires_at = (datetime.utcnow() +
                  timedelta(minutes=AUTH_CODE_TTL_MINUTES)).isoformat()
    payload = {
        "user_id": int(user_id),
        "purpose": (purpose or "").strip(),
        "channel": (channel or "").strip(),
        "destination": (destination or "").strip(),
        "code_hash": _auth_code_hash(code),
        "expires_at": expires_at,
        "consumed_at": None,
    }
    return supabase.table("auth_verification_codes").insert(payload).execute()


def _parse_iso_datetime(value):
    text = (value or "").strip()
    if not text:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            parsed = datetime.fromisoformat(text)
        except Exception:
            parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


def _latest_auth_verification_code(user_id, purpose, channel):
    try:
        rows = (
            supabase.table("auth_verification_codes")
            .select("id,code_hash,expires_at,consumed_at")
            .eq("user_id", int(user_id))
            .eq("purpose", (purpose or "").strip())
            .eq("channel", (channel or "").strip())
            .order("id", desc=True)
            .limit(8)
            .execute()
            .data or []
        )
    except Exception:
        return None

    now_utc = datetime.utcnow()
    for row in rows:
        if row.get("consumed_at"):
            continue
        expires_at = _parse_iso_datetime(row.get("expires_at"))
        if not expires_at or expires_at < now_utc:
            continue
        return row
    return None


def _consume_auth_verification_code(code_id):
    if code_id is None:
        return
    try:
        supabase.table("auth_verification_codes").update({
            "consumed_at": datetime.utcnow().isoformat()}).eq("id", int(code_id)).execute()
    except Exception:
        pass


def _lookup_user_by_channel(identifier, channel):
    channel = (channel or "").strip().lower()
    token = (identifier or "").strip()
    if not token:
        return None, None

    if channel == "email":
        normalized_email = token.lower()
        try:
            rows = (
                supabase.table("users")
                .select("id,email,username,role")
                .eq("email", normalized_email)
                .limit(1)
                .execute()
                .data
                or []
            )
            return (rows[0], normalized_email) if rows else (None, None)
        except Exception:
            return None, None

    normalized_phone = _normalize_phone(token)
    if not normalized_phone:
        return None, None

    table_candidates = [
        "teachers", "lecturers", "students", "learners", "staff", "school_admins", "parents"
    ]
    for table_name in table_candidates:
        try:
            rows = (
                supabase.table(table_name)
                .select("user_id,phone_number")
                .limit(1000)
                .execute()
                .data
                or []
            )
        except Exception:
            continue
        for row in rows:
            candidate_phone = _normalize_phone(row.get("phone_number"))
            if candidate_phone and candidate_phone == normalized_phone and row.get("user_id"):
                try:
                    user_rows = (
                        supabase.table("users")
                        .select("id,email,username,role")
                        .eq("id", int(row.get("user_id")))
                        .limit(1)
                        .execute()
                        .data
                        or []
                    )
                    if user_rows:
                        return user_rows[0], token
                except Exception:
                    continue
    return None, None


def _resolve_post_auth_redirect(user, requested_school_id=None, requested_school=None):
    user_role = _normalize_role((user or {}).get("role"))
    if not user_role:
        return {"ok": False, "error": "Unknown role"}

    if user_role == "admin":
        if requested_school_id is not None:
            return {
                "ok": False,
                "error": "Platform admins must use the general login, not a school-specific login page.",
            }
        session.clear()
        session["user_id"] = user.get("id")
        session["role"] = "admin"
        session["username"] = user.get("username")
        session["user_email"] = user.get("email")
        session["admin_logged_in"] = True
        return {"ok": True, "redirect_url": url_for("admin_dashboard")}

    session.clear()
    session["user_id"] = user.get("id")
    session["role"] = user_role
    session["username"] = user.get("username")
    session["user_email"] = user.get("email")

    role_row = _load_role_profile_for_login(user_role, user.get("id"))
    if not role_row:
        return {"ok": False, "error": "No school linked to this account"}

    school_id = role_row.get("school_id")
    school = _get_school_record(school_id)
    if requested_school_id is not None and school_id != requested_school_id:
        scope_label = requested_school.get(
            "name") if requested_school else "this school"
        return {
            "ok": False,
            "error": f"There is no {user_role.replace('_', ' ')} account with those credentials for {scope_label}.",
        }

    if not _school_allows_role(school, user_role):
        return {"ok": False, "error": "This account role is not allowed for the linked school type."}

    session["school_id"] = school_id
    session["school_type"] = school.get("school_type") if school else None
    session["role"] = user_role
    session["user_name"] = role_row.get("name")
    if user_role == "teacher":
        session["teacher_id"] = role_row.get("id")
    elif user_role == "lecturer":
        session["lecturer_id"] = role_row.get("id")
    elif user_role == "school_admin":
        session["school_admin_id"] = role_row.get("id")
    elif user_role == "student":
        session["student_id"] = role_row.get("id")
    elif user_role == "learner":
        session["learner_id"] = role_row.get("id")

    dashboard_urls = {
        "student": url_for("student_dashboard", school_id=school_id),
        "learner": url_for("learner_dashboard", school_id=school_id),
        "teacher": url_for("teacher_dashboard", school_id=school_id),
        "lecturer": url_for("lecturer_dashboard", school_id=school_id),
        "parent": url_for("parent_dashboard", school_id=school_id),
        "staff": url_for("staff_dashboard", school_id=school_id),
        "school_admin": url_for("school_admin_dashboard", school_id=school_id),
    }
    redirect_url = dashboard_urls.get(user_role)
    if not redirect_url:
        return {"ok": False, "error": "Unknown role"}

    return {"ok": True, "redirect_url": redirect_url}


def _verify_google_id_token(id_token):
    if not GOOGLE_CLIENT_ID:
        return None, "Google Sign-In is not configured."
    token = (id_token or "").strip()
    if not token:
        return None, "Missing Google credential token."

    tokeninfo_url = (
        "https://oauth2.googleapis.com/tokeninfo?id_token="
        + urllib_parse.quote(token)
    )
    try:
        with urllib_request.urlopen(tokeninfo_url, timeout=10) as response:
            payload = std_json.loads(response.read().decode("utf-8"))
    except Exception:
        return None, "Google token verification failed."

    if (payload.get("aud") or "").strip() != GOOGLE_CLIENT_ID:
        return None, "Google token audience mismatch."
    verified = str(payload.get("email_verified") or "").strip().lower()
    if verified not in {"true", "1"}:
        return None, "Google account email is not verified."
    if not (payload.get("email") or "").strip():
        return None, "Google account did not return an email."
    return payload, None


def _render_role_registration_step(role, user_id, school_id):
    role = _normalize_role(role)
    if role == "teacher":
        return render_template("register_teacher.html", user_id=user_id, school_id=school_id)
    if role == "student":
        courses = _select_school_scoped(
            "courses", school_id=_parse_int(school_id), order_by="name")
        return render_template("register_student.html", user_id=user_id, school_id=school_id, courses=courses)
    if role == "lecturer":
        return render_template("register_lecturer.html", user_id=user_id, school_id=school_id)
    if role == "learner":
        return render_template("register_learner.html", user_id=user_id, school_id=school_id)
    if role == "parent":
        return render_template("register_parent.html", user_id=user_id, school_id=school_id)
    if role == "staff":
        return render_template("register_staff.html", user_id=user_id, school_id=school_id)
    flash("Unknown role selected.", "error")
    return redirect(url_for("register", school_id=school_id))


def _availability_message(field_name, conflicting_user):
    if not conflicting_user:
        return f"{field_name.title()} is available."

    conflict_role = _role_label(conflicting_user.get("role") or "user")
    conflict_username = conflicting_user.get("username") or "existing user"
    return f"This {field_name} is already linked to {conflict_username} ({conflict_role})."


def _is_duplicate_user_identity_error(error):
    message = str(error).lower()
    return "duplicate" in message or "unique" in message or "already exists" in message


def _safe_select_table(table_name, columns="*", order_by=None):
    try:
        query = supabase.table(table_name).select(columns)
        if order_by:
            query = query.order(order_by)
        response = query.execute()
        return response.data or []
    except Exception:
        return []


def _schools_for_role(role, schools):
    normalized_role = _normalize_role(role)
    if normalized_role in {"admin", "school_admin", "parent", "staff"}:
        return schools

    allowed_school_types = {
        "teacher": {"pre_school", "primary_school", "high_school"},
        "learner": {"pre_school", "primary_school", "high_school"},
        "lecturer": {"tertiary"},
        "student": {"tertiary"},
    }.get(normalized_role)

    if not allowed_school_types:
        return schools

    filtered = []
    for school in schools:
        school_type = _normalize_school_type(school.get("school_type"))
        if school_type in allowed_school_types:
            filtered.append(school)
    return filtered


def _admin_user_form_fields(role, schools, courses):
    shared = [
        {"name": "username", "label": "Username", "type": "text",
            "required": True, "autocomplete": "off", "availability": "username"},
        {"name": "email", "label": "Email", "type": "email",
            "required": True, "autocomplete": "off", "availability": "email"},
    ]

    if role == "admin":
        return shared + [
            {"name": "password", "label": "Password",
                "type": "password", "required": True},
        ]

    fields = shared + [
        {
            "name": "school_id",
            "label": "School",
            "type": "select",
            "required": True,
            "options": [{"value": school.get("id"), "label": school.get("name")} for school in schools],
        },
        {"name": "password", "label": "Password",
            "type": "password", "required": True},
        {"name": "name", "label": "Full Name", "type": "text", "required": True},
    ]

    if role in {"teacher", "lecturer", "learner", "student", "staff", "school_admin"}:
        fields.append(
            {"name": "phone_number", "label": "Phone Number", "type": "text"})

    if role == "teacher":
        fields.append({"name": "core_subjects",
                      "label": "Core Subjects", "type": "text"})
    elif role == "lecturer":
        fields.append({"name": "faculty", "label": "Faculty", "type": "text"})
    elif role == "learner":
        fields.extend([
            {"name": "grade", "label": "Grade", "type": "text"},
            {"name": "year_of_study", "label": "Year Of Study", "type": "number"},
            {"name": "current_residential_address",
                "label": "Residential Address", "type": "text"},
        ])
    elif role == "student":
        fields.extend([
            {
                "name": "course_id",
                "label": "Course",
                "type": "select",
                "options": [{"value": course.get("id"), "label": course.get("name")} for course in courses],
            },
            {"name": "year_of_study", "label": "Year Of Study", "type": "number"},
            {"name": "semester", "label": "Semester", "type": "number"},
            {"name": "year_of_enrollment",
                "label": "Year Of Enrollment", "type": "number"},
            {"name": "course_duration", "label": "Course Duration", "type": "number"},
            {"name": "current_residential_address",
                "label": "Residential Address", "type": "text"},
        ])
    elif role == "parent":
        fields.append({"name": "subscription_status",
                      "label": "Subscription Status", "type": "text"})
    elif role == "staff":
        fields.append(
            {"name": "department", "label": "Department", "type": "text"})

    return fields


def _admin_user_table_columns(role):
    base_columns = [
        {"key": "username", "label": "Username"},
        {"key": "email", "label": "Email"},
    ]

    if role != "admin":
        base_columns.extend([
            {"key": "school_name", "label": "School"},
            {"key": "name", "label": "Full Name"},
        ])

    extras = {
        "teacher": [
            {"key": "core_subjects", "label": "Core Subjects"},
            {"key": "phone_number", "label": "Phone"},
        ],
        "lecturer": [
            {"key": "faculty", "label": "Faculty"},
            {"key": "phone_number", "label": "Phone"},
        ],
        "learner": [
            {"key": "grade", "label": "Grade"},
            {"key": "year_of_study", "label": "Year"},
            {"key": "phone_number", "label": "Phone"},
        ],
        "student": [
            {"key": "course_name", "label": "Course"},
            {"key": "year_semester", "label": "Year / Semester"},
            {"key": "phone_number", "label": "Phone"},
        ],
        "parent": [
            {"key": "subscription_status", "label": "Subscription"},
        ],
        "staff": [
            {"key": "department", "label": "Department"},
            {"key": "phone_number", "label": "Phone"},
        ],
        "school_admin": [
            {"key": "phone_number", "label": "Phone"},
        ],
        "admin": [
            {"key": "role_display", "label": "Role"},
        ],
    }

    return base_columns + extras.get(role, [])


def _build_admin_user_management_data(selected_tab=None):
    users = _load_users_basic()
    schools = _safe_select_table(
        "schools", columns="id,name,school_type", order_by="name")
    courses = _safe_select_table("courses", columns="id,name", order_by="name")

    school_map = {school.get("id"): school for school in schools}
    course_map = {course.get("id"): course.get("name") for course in courses}

    profile_tables = {
        role: _safe_select_table(table_name, order_by="id")
        for role, table_name in {
            "teacher": "teachers",
            "lecturer": "lecturers",
            "learner": "learners",
            "student": "students",
            "parent": "parents",
            "staff": "staff",
            "school_admin": "school_admins",
        }.items()
    }

    profile_maps = {
        role: {row.get("user_id"): row for row in rows if row.get(
            "user_id") is not None}
        for role, rows in profile_tables.items()
    }

    role_sequence = [
        "teacher",
        "lecturer",
        "learner",
        "student",
        "staff",
        "parent",
        "school_admin",
        "admin",
    ]

    grouped_rows = {role: [] for role in role_sequence}
    for user in users:
        role = _normalize_role(user.get("role"))
        if role not in grouped_rows:
            grouped_rows[role] = []
        profile = profile_maps.get(role, {}).get(user.get("id"), {})
        school = school_map.get(profile.get("school_id")) or {}
        grouped_rows[role].append({
            "id": user.get("id"),
            "role": role,
            "role_display": _role_label(role),
            "username": user.get("username") or "",
            "email": user.get("email") or "",
            "school_id": profile.get("school_id") or "",
            "school_name": school.get("name") or "",
            "name": profile.get("name") or "",
            "phone_number": profile.get("phone_number") or "",
            "core_subjects": profile.get("core_subjects") or "",
            "faculty": profile.get("faculty") or "",
            "grade": profile.get("grade") or "",
            "year_of_study": profile.get("year_of_study") or "",
            "semester": profile.get("semester") or "",
            "year_of_enrollment": profile.get("year_of_enrollment") or "",
            "course_duration": profile.get("course_duration") or "",
            "course_id": profile.get("course_id") or "",
            "course_name": course_map.get(profile.get("course_id")) or "",
            "current_residential_address": profile.get("current_residential_address") or "",
            "subscription_status": profile.get("subscription_status") or "",
            "department": profile.get("department") or "",
            "year_semester": (
                f"Y{profile.get('year_of_study') or '-'} / S{profile.get('semester') or '-'}"
                if role == "student" else "-"
            ),
        })

    role_tabs = []
    available_roles = [role for role in role_sequence if role in grouped_rows]
    active_tab = selected_tab if selected_tab in available_roles else "teacher"

    for role in role_sequence:
        rows = grouped_rows.get(role, [])
        role_tabs.append({
            "value": role,
            "label": _role_label(role),
            "singular_label": _role_singular_label(role),
            "description": f"Create and manage {_role_label(role).lower()} from one place.",
            "rows": rows,
            "columns": _admin_user_table_columns(role),
            "form_fields": _admin_user_form_fields(role, _schools_for_role(role, schools), courses),
        })

    return {
        "users": users,
        "role_tabs": role_tabs,
        "active_tab": active_tab,
    }


def _resolve_school_template(school):
    layout_template = (school or {}).get("layout_template")
    template_by_layout = {
        "premium_university_v2": "school_site_university_v2.html",
    }

    if layout_template in template_by_layout:
        return template_by_layout[layout_template]

    school_type = ((school or {}).get("school_type") or "").strip().lower()
    if school_type in {"tertiary", "college", "university", "higher_education"}:
        return "school_site_university_v2.html"

    # Fallback for legacy/dirty records where school_type is not normalized.
    school_name = ((school or {}).get("name") or "").strip().lower()
    if any(keyword in school_name for keyword in ["college", "university", "institute"]):
        return "school_site_university_v2.html"

    return "school_site_page.html"


def _require_school_admin(school_id):
    if session.get("role") != "school_admin" or int(session.get("school_id") or 0) != school_id:
        flash("School admin access required.", "error")
        return redirect(url_for("login"))
    return None


def _require_admin_or_school_admin_for_school(school_id):
    if _is_global_admin_session():
        return None
    if session.get("role") == "school_admin" and int(session.get("school_id") or 0) == int(school_id):
        return None
    flash("Admin access required.", "error")
    return redirect(url_for("login"))


def _require_school_admin_tertiary(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    if (school or {}).get("school_type", "").strip().lower() != "tertiary":
        flash("This section is available for tertiary schools only.", "error")
        return redirect(url_for("school_admin_dashboard", school_id=school_id))
    return None


def _load_dashboard_virtual_calls(classrooms, actor_id=""):
    """Fetch all virtual calls across a list of classrooms, enriched with classroom name."""
    if not classrooms:
        return []
    classroom_map = {c["id"]: c.get("name", "Classroom") for c in classrooms}
    classroom_ids = list(classroom_map.keys())
    try:
        posts_resp = supabase.table("classroom_posts").select(
            "id,classroom_id,content,author_name,created_at"
        ).in_("classroom_id", classroom_ids).eq("role", "virtual_call").execute()
        posts = posts_resp.data or []
    except Exception:
        return []
    result = []
    for post in posts:
        payload = _virtual_call_payload_decode(post.get("content"))
        if not payload:
            continue
        post_id = post.get("id")
        host_id = str(payload.get("created_by_id") or "")
        actor_key = str(actor_id or "")
        is_host = bool(host_id and actor_key and host_id == actor_key)
        has_access = bool(session.get(f"virtual_call_access_{post_id}"))
        if not (is_host or has_access):
            continue
        result.append({
            "post_id": post_id,
            "classroom_id": post.get("classroom_id"),
            "classroom_name": classroom_map.get(post.get("classroom_id"), "Classroom"),
            "title": payload.get("title") or "Classroom Call",
            "created_by": payload.get("created_by") or post.get("author_name") or "Host",
            "created_at": payload.get("created_at") or post.get("created_at"),
            "scheduled_start": payload.get("scheduled_start"),
            "scheduled_end": payload.get("scheduled_end"),
            "status": _virtual_call_status(payload),
            "meeting_code": (payload.get("meeting_code") or "").strip(),
            "is_host": is_host,
        })
    result.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return result


def _virtual_call_payload_decode(content_text):
    raw = (content_text or "").strip()
    marker = "VCALL::"
    if not raw.startswith(marker):
        return None
    try:
        payload = std_json.loads(raw[len(marker):])
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("room_name") or not payload.get("password_hash"):
        return None
    return payload


def _virtual_call_password_hash(plain_text):
    return hashlib.sha256((plain_text or "").encode("utf-8")).hexdigest()


def _virtual_meeting_code():
    return uuid.uuid4().hex[:8].upper()


def _virtual_call_payload_encode(payload):
    return "VCALL::" + std_json.dumps(payload or {})


def _virtual_call_parse_iso(value):
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _virtual_call_status(payload):
    started_at = _virtual_call_parse_iso(payload.get("scheduled_start") or "")
    ended_at = _virtual_call_parse_iso(payload.get("ended_at") or "")
    if ended_at is not None:
        return "ended"
    if started_at is not None:
        now = datetime.now(
            started_at.tzinfo) if started_at.tzinfo else datetime.utcnow()
        if started_at > now:
            return "scheduled"
    return "live"


def _load_global_virtual_meetings(school_id, actor_id=""):
    school_id_int = _parse_int(school_id)
    if school_id_int is None:
        return []
    try:
        resp = supabase.table("global_virtual_meetings").select(
            "id,school_id,title,room_name,password_hash,password_sealed,meeting_code,created_by,created_by_role,created_by_id,created_at,scheduled_start,scheduled_end,ended_at"
        ).eq("school_id", school_id_int).order("created_at", desc=True).limit(300).execute()
        rows = resp.data or []
    except Exception:
        return []

    actor_key = str(actor_id or "")
    meetings = []
    for row in rows:
        host_id = str(row.get("created_by_id") or "")
        meeting_id = row.get("id")
        is_host = bool(host_id and actor_key and host_id == actor_key)
        has_access = bool(session.get(
            f"global_virtual_meeting_access_{meeting_id}"))
        if not (is_host or has_access):
            continue
        payload = {
            "scheduled_start": row.get("scheduled_start"),
            "ended_at": row.get("ended_at"),
        }
        meetings.append({
            "id": meeting_id,
            "title": row.get("title") or "Global Meeting",
            "meeting_code": (row.get("meeting_code") or "").strip(),
            "created_by": row.get("created_by") or "Host",
            "created_at": row.get("created_at"),
            "scheduled_start": row.get("scheduled_start"),
            "scheduled_end": row.get("scheduled_end"),
            "status": _virtual_call_status(payload),
            "is_host": is_host,
            "creator_password": _reveal_meeting_password(row.get("password_sealed") or "") if is_host else "",
        })
    return meetings


def _virtual_call_get_post(classroom_id, call_post_id):
    try:
        call_resp = supabase.table("classroom_posts").select(
            "id,classroom_id,user_id,author_name,role,content,created_at").eq("id", call_post_id).eq("classroom_id", classroom_id).limit(1).execute()
        return call_resp.data[0] if call_resp and call_resp.data else None
    except Exception:
        return None


def _virtual_call_update_post_payload(classroom_id, call_post_id, payload):
    try:
        supabase.table("classroom_posts").update({
            "content": _virtual_call_payload_encode(payload),
        }).eq("id", call_post_id).eq("classroom_id", classroom_id).execute()
        return True
    except Exception:
        return False


def _virtual_call_log_attendance(classroom_id, call_post_id, event_type, actor_id, actor_role, actor_name):
    row = {
        "classroom_id": classroom_id,
        "call_post_id": call_post_id,
        "actor_id": actor_id,
        "actor_role": (actor_role or "member")[:30],
        "actor_name": (actor_name or "Participant")[:140],
        "event_type": (event_type or "join")[:20],
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        supabase.table("virtual_call_attendance_logs").insert(row).execute()
        return True
    except Exception:
        return False


def _virtual_call_attendance_snapshot(classroom_id, call_ids):
    ids = [cid for cid in (call_ids or []) if cid is not None]
    if not ids:
        return {}
    try:
        logs = supabase.table("virtual_call_attendance_logs").select(
            "call_post_id,actor_id,actor_name,event_type,created_at").eq("classroom_id", classroom_id).in_("call_post_id", ids).order("created_at", desc=False).execute().data or []
    except Exception:
        logs = []

    grouped = {}
    for log in logs:
        key = str(log.get("call_post_id"))
        grouped.setdefault(key, []).append(log)

    snapshot = {}
    for cid in ids:
        key = str(cid)
        events = grouped.get(key, [])
        participants = set()
        joins = 0
        leaves = 0
        for ev in events:
            ev_type = (ev.get("event_type") or "").strip().lower()
            actor_key = str(ev.get("actor_id") or ev.get(
                "actor_name") or "unknown")
            if ev_type == "join":
                joins += 1
                participants.add(actor_key)
            elif ev_type == "leave":
                leaves += 1
        snapshot[key] = {
            "joins": joins,
            "leaves": leaves,
            "unique_participants": len(participants),
            "events": len(events),
        }
    return snapshot


def _get_session_member_record():
    if session.get("user_id"):
        try:
            student_resp = supabase.table("students").select("id").eq(
                "user_id", session["user_id"]).limit(1).execute()
            if student_resp and student_resp.data:
                return {"student_id": student_resp.data[0].get("id")}
        except Exception:
            pass
        try:
            learner_resp = supabase.table("learners").select("id").eq(
                "user_id", session["user_id"]).limit(1).execute()
            if learner_resp and learner_resp.data:
                return {"learner_id": learner_resp.data[0].get("id")}
        except Exception:
            pass
    if session.get("teacher_id"):
        return {"teacher_id": session.get("teacher_id")}
    if session.get("lecturer_id"):
        return {"lecturer_id": session.get("lecturer_id")}
    return {}


def _session_is_classroom_member(classroom_id):
    record = _get_session_member_record()
    if not record:
        return False
    try:
        query = supabase.table("classroom_members").select("id").eq(
            "classroom_id", classroom_id)
        for key, value in record.items():
            query = query.eq(key, value)
        resp = query.limit(1).execute()
        return bool(resp and resp.data)
    except Exception:
        return False


def _normalize_classroom_code(value):
    raw = str(value or "").strip().upper()
    compact = "".join(ch for ch in raw if ch.isalnum())
    return raw, compact


def _get_classroom_join_code(classroom):
    if not classroom:
        return None
    return (classroom.get("class_code") or classroom.get("code") or "").strip() or None


def _find_classroom_by_code(code, school_id=None):
    exact_code, compact_code = _normalize_classroom_code(code)
    if not exact_code:
        return None

    for col in ("class_code", "code"):
        try:
            query = supabase.table("classrooms").select(
                "*").eq(col, exact_code)
            if school_id is not None:
                query = query.eq("school_id", school_id)
            resp = query.limit(1).execute()
            if resp and resp.data:
                return resp.data[0]
        except Exception:
            continue

    try:
        query = supabase.table("classrooms").select("*")
        if school_id is not None:
            query = query.eq("school_id", school_id)
        classrooms = query.limit(500).execute().data or []
    except Exception:
        classrooms = []

    for classroom in classrooms:
        _, row_compact = _normalize_classroom_code(
            _get_classroom_join_code(classroom))
        if row_compact and row_compact == compact_code:
            return classroom
    return None


def _select_classrooms_by_ids(class_ids):
    if not class_ids:
        return []

    select_variants = [
        "id,name,class_code,code",
        "id,name,class_code",
        "id,name,code",
        "id,name",
    ]
    classrooms = []
    for select_clause in select_variants:
        try:
            classrooms = supabase.table("classrooms").select(select_clause).in_(
                "id", class_ids).execute().data or []
            break
        except Exception:
            classrooms = []

    by_id = {}
    for classroom in classrooms:
        classroom["join_code"] = _get_classroom_join_code(classroom)
        by_id[classroom.get("id")] = classroom
    return [by_id[class_id] for class_id in class_ids if class_id in by_id]


def _find_existing_classroom_membership(classroom_id, member_col, member_val, user_id=None):
    candidate_checks = [(member_col, member_val)]
    if user_id is not None:
        candidate_checks.append(("user_id", user_id))

    for col, value in candidate_checks:
        try:
            existing = supabase.table("classroom_members").select("id").eq(
                "classroom_id", classroom_id).eq(col, value).limit(1).execute()
            if existing and existing.data:
                return existing.data[0]
        except Exception:
            continue
    return None


def _insert_classroom_membership(classroom_id, member_col, member_val, member_role, user_id=None):
    base_payload = {
        "classroom_id": classroom_id,
        member_col: member_val,
        "role": member_role,
    }
    candidate_payloads = [base_payload]

    if member_role != "member":
        candidate_payloads.append({**base_payload, "role": "member"})

    if user_id is not None:
        candidate_payloads.append({**base_payload, "user_id": user_id})
        if member_role != "member":
            candidate_payloads.append(
                {**base_payload, "user_id": user_id, "role": "member"})

    last_error = None
    seen_keys = set()
    for payload in candidate_payloads:
        payload_key = tuple(sorted(payload.items()))
        if payload_key in seen_keys:
            continue
        seen_keys.add(payload_key)
        try:
            supabase.table("classroom_members").insert(payload).execute()
            return True, None
        except Exception as error:
            last_error = error

    return False, last_error


# ---------------------------------------------------------Update classrooms


def _redirect_to_user_dashboard():
    school_id = session.get("school_id")
    if session.get("teacher_id"):
        return redirect(url_for("teacher_dashboard", school_id=school_id))
    elif session.get("lecturer_id"):
        return redirect(url_for("lecturer_dashboard", school_id=school_id))
    elif session.get("role") == "student":
        return redirect(url_for("student_dashboard", school_id=school_id))
    elif session.get("role") == "learner":
        return redirect(url_for("learner_dashboard", school_id=school_id))
    elif session.get("role") == "school_admin":
        return redirect(url_for("school_admin_dashboard", school_id=school_id))
    return redirect(url_for("login"))


# ====================================================================================SEARCH ENROLLEES (teacher/lecturer live search)==

def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_iso_date(value):
    if not value:
        return ""
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def get_school_record(school_id):
    try:
        resp = supabase.table("schools").select(
            "*").eq("id", school_id).execute()
        return resp.data[0] if resp.data else {}
    except Exception:
        return {}


def get_cycle_meta(school, actor_type):
    now = datetime.utcnow()
    school_type = (school.get("school_type") or "").strip().lower()
    is_tertiary = actor_type == "lecturer" or school_type == "tertiary"

    year = str(school.get("active_academic_year")
               or school.get("academic_year") or now.year)

    if is_tertiary:
        cycle_label = school.get(
            "active_semester") or school.get("current_semester")
        if not cycle_label:
            cycle_label = "Semester 1" if now.month <= 6 else "Semester 2"
    else:
        cycle_label = school.get("active_term") or school.get("current_term")
        if not cycle_label:
            if now.month <= 4:
                cycle_label = "Term 1"
            elif now.month <= 8:
                cycle_label = "Term 2"
            else:
                cycle_label = "Term 3"

    marks_open = _to_bool(school.get("portal_marks_open"), default=True)
    reports_open = _to_bool(school.get("portal_reports_open"), default=True)

    return {
        "is_tertiary": is_tertiary,
        "cycle_label": cycle_label,
        "academic_year": year,
        "marks_open": marks_open,
        "reports_open": reports_open,
    }


def resolve_student_subjects(student_id, student_type, actor_type):
    """Resolve allowed subjects/modules for one student based on assignment tables."""
    options = []

    try:
        if actor_type == "lecturer":
            mappings = supabase.table("student_modules").select(
                "module_id").eq("student_id", student_id).execute().data or []
            module_ids = [m.get("module_id")
                          for m in mappings if m.get("module_id") is not None]
            if module_ids:
                modules = supabase.table("modules").select(
                    "id,name").in_("id", module_ids).execute().data or []
                options = [{"id": m.get("id"), "name": m.get(
                    "name"), "kind": "module"} for m in modules if m.get("name")]
            if not options:
                fallback = supabase.table("modules").select(
                    "id,name").execute().data or []
                options = [{"id": m.get("id"), "name": m.get(
                    "name"), "kind": "module"} for m in fallback if m.get("name")]
        else:
            if student_type == "learner":
                mappings = supabase.table("learner_subjects").select(
                    "subject_id").eq("learner_id", student_id).execute().data or []
                subject_ids = [m.get("subject_id") for m in mappings if m.get(
                    "subject_id") is not None]
                if subject_ids:
                    subjects = supabase.table("subjects").select(
                        "id,name").in_("id", subject_ids).execute().data or []
                    options = [{"id": s.get("id"), "name": s.get(
                        "name"), "kind": "subject"} for s in subjects if s.get("name")]
            if not options:
                fallback = supabase.table("subjects").select(
                    "id,name").execute().data or []
                options = [{"id": s.get("id"), "name": s.get(
                    "name"), "kind": "subject"} for s in fallback if s.get("name")]
    except Exception:
        options = []

    # De-duplicate while preserving order.
    seen = set()
    unique_options = []
    for opt in options:
        key = (opt.get("kind"), opt.get("id"), opt.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique_options.append(opt)
    return unique_options


def render_report_payload(term_rows):
    lines = []
    for row in term_rows:
        subject_name = row.get("subject_name", "Subject")
        pct = _to_float(row.get("percentage"), 0.0)
        symbol = row.get("symbol") or "F"
        lines.append({
            "subject_name": subject_name,
            "percentage": round(pct, 2),
            "symbol": symbol,
            "comment": row.get("teacher_comment") or "",
        })
    return lines


def calc_symbol(pct, is_tertiary=False):
    """Convert percentage to letter grade symbol."""
    if is_tertiary:
        if pct >= 75:
            return "HD"
        if pct >= 65:
            return "D"
        if pct >= 55:
            return "CR"
        if pct >= 45:
            return "P"
        return "F"
    else:
        if pct >= 80:
            return "A"
        if pct >= 70:
            return "B"
        if pct >= 60:
            return "C"
        if pct >= 50:
            return "D"
        return "F"


def symbol_to_gpa(symbol):
    """Convert letter symbol to GPA point value."""
    gpa_map = {"A": 4.0, "HD": 4.0, "B": 3.0, "D": 3.0,
               "C": 2.0, "CR": 2.0, "P": 1.0, "F": 0.0}
    return gpa_map.get(symbol, 0.0)


# ====================================================================================PORTAL DASHBOARD====================

def _get_apply_ref(school_id):
    return session.get(f"apply_{school_id}")


def _set_apply_ref(school_id, ref):
    session[f"apply_{school_id}"] = ref


def _clear_apply_ref(school_id):
    session.pop(f"apply_{school_id}", None)


def _get_draft_application(ref):
    if not ref:
        return None
    try:
        result = (
            supabase.table("online_applications")
            .select("*")
            .eq("ref", ref)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def _generate_app_ref():
    import random
    import string
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"EMRC-{code}"


def _apply_school_menu(school_id):
    return (
        supabase.table("school_menu")
        .select("*")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .order("display_order")
        .execute()
        .data or []
    )


def _school_application_enabled(school):
    if not school:
        return False

    explicit_flags = [
        school.get("application_enabled"),
        school.get("online_application_enabled"),
        school.get("has_online_application"),
    ]
    for flag in explicit_flags:
        if flag is not None:
            return _to_bool(flag, default=False)

    # Default legacy fallback: only EMRC is enabled until other schools are onboarded.
    school_name = (school.get("name") or "").strip().lower()
    return (
        "emergency medical rescue" in school_name
        or "emr college" in school_name
        or school_name.startswith("emrc")
        or school_name.startswith("emr")
    )


def _apply_unavailable_redirect(school_id):
    flash(
        "Online application is not available for this school yet. Please check back soon.",
        "info",
    )
    return redirect(url_for("school_page", school_id=school_id, page_slug="admissions"))


def _is_missing_application_screenings_table(error):
    msg = str(error).lower()
    return "application_screenings" in msg and (
        "does not exist" in msg or "relation" in msg or "not found" in msg
    )


def _application_screening_list(value, fallback=None):
    fallback = fallback or []
    if isinstance(value, list):
        cleaned = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text[:220])
        return cleaned or fallback
    if isinstance(value, str) and value.strip():
        return [value.strip()[:220]]
    return fallback


def _application_screening_label(key):
    return APPLICATION_SCREENING_RECOMMENDATION_LABELS.get(key, "Review")


def _get_latest_application_screening(application_ref):
    if not application_ref:
        return None
    try:
        result = (
            supabase.table("application_screenings")
            .select("*")
            .eq("application_ref", application_ref)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        if not _is_missing_application_screenings_table(exc):
            app.logger.warning(
                "Could not load latest application screening: %s", exc)
        return None


def _get_latest_application_screenings_for_school(school_id):
    try:
        rows = (
            supabase.table("application_screenings")
            .select("*")
            .eq("school_id", school_id)
            .order("created_at", desc=True)
            .limit(300)
            .execute()
            .data or []
        )
    except Exception as exc:
        if not _is_missing_application_screenings_table(exc):
            app.logger.warning(
                "Could not load application screenings for school %s: %s", school_id, exc)
        return {}

    latest = {}
    for row in rows:
        ref_value = row.get("application_ref")
        if ref_value and ref_value not in latest:
            latest[ref_value] = row
    return latest


def _build_application_screening_prompt(school, application, docs, baseline):
    applicant_name = " ".join(filter(None, [
        application.get("title"),
        application.get("surname"),
        application.get("first_names"),
    ])).strip() or "Applicant"
    doc_lines = "\n".join(
        f"- {APPLICATION_SCREENING_DOC_LABELS.get(doc.get('doc_type'), doc.get('doc_type') or 'Document')}: uploaded"
        for doc in docs
    ) or "- No supporting documents uploaded"
    missing_lines = "\n".join(
        f"- {item}" for item in baseline["missing_items"]) or "- No major missing items"
    concern_lines = "\n".join(
        f"- {item}" for item in baseline["concerns"]) or "- No major concerns"
    strength_lines = "\n".join(
        f"- {item}" for item in baseline["strengths"]) or "- No confirmed strengths yet"

    return (
        "You are an admissions screening assistant for a school administrator. "
        "Review this application and return JSON only with keys summary, strengths, concerns, missing_items. "
        "summary must be 2-4 concise sentences. strengths, concerns, and missing_items must each be arrays of short strings with a maximum of 4 items. "
        "Do not invent facts that are not present in the application data.\n\n"
        f"School: {(school or {}).get('name') or 'School'}\n"
        f"Applicant: {applicant_name}\n"
        f"Application reference: {application.get('ref') or ''}\n"
        f"Programme: {application.get('qualification') or 'Not provided'}\n"
        f"Academic year: {application.get('academic_year') or 'Not provided'}\n"
        f"Study mode: {application.get('section') or 'Not provided'}\n"
        f"Highest qualification: {application.get('highest_qualification') or 'Not provided'}\n"
        f"Institution attended: {application.get('institution_attended') or 'Not provided'}\n"
        f"Year completed: {application.get('year_completed') or 'Not provided'}\n"
        f"Subjects passed: {application.get('subjects_passed') or 'Not provided'}\n"
        f"RPL requested: {'Yes' if application.get('has_rpl') else 'No'}\n"
        f"RPL details: {application.get('rpl_details') or 'Not provided'}\n"
        f"Payment reference: {application.get('payment_reference') or 'Not provided'}\n"
        f"Payment date: {application.get('payment_date') or 'Not provided'}\n"
        f"Applicant email: {application.get('email') or 'Not provided'}\n"
        f"Guardian email: {application.get('payer_email') or 'Not provided'}\n\n"
        f"Uploaded documents:\n{doc_lines}\n\n"
        f"Current rules-based screening score: {baseline['screening_score']}/100\n"
        f"Current rules-based recommendation: {_application_screening_label(baseline['recommendation'])}\n"
        f"Rules-based strengths:\n{strength_lines}\n\n"
        f"Rules-based concerns:\n{concern_lines}\n\n"
        f"Rules-based missing items:\n{missing_lines}\n"
    )


def _build_rules_based_application_screening(school, application, docs):
    doc_map = {doc.get("doc_type"): doc for doc in docs if doc.get("doc_type")}
    missing_items = []
    strengths = []
    concerns = []
    score = 100

    for field_name, label in APPLICATION_SCREENING_REQUIRED_FIELDS:
        value = application.get(field_name)
        if value is None or str(value).strip() == "":
            missing_items.append(label)
            score -= 5

    for doc_type, label in APPLICATION_SCREENING_DOC_LABELS.items():
        if doc_type not in doc_map:
            missing_items.append(label)
            score -= 7

    if application.get("has_rpl") and not (application.get("rpl_details") or "").strip():
        concerns.append(
            "RPL was selected but the supporting details are missing.")
        score -= 6

    if (application.get("subjects_passed") or "").strip():
        strengths.append("Academic subject history has been provided.")
    else:
        concerns.append("Academic subject history is not yet clear.")
        score -= 4

    if application.get("highest_qualification") and application.get("institution_attended"):
        strengths.append("Previous academic background is documented.")

    if application.get("payment_reference") and application.get("payment_date"):
        strengths.append("Application payment details are present.")
    else:
        concerns.append("Payment details still need verification.")

    if len(doc_map) == len(APPLICATION_SCREENING_DOC_LABELS):
        strengths.append(
            "All standard supporting documents appear to be uploaded.")
    elif len(doc_map) >= 2:
        strengths.append("Some supporting documents are already uploaded.")

    score = max(0, min(100, score))
    if missing_items or score < 60:
        recommendation = "needs_info"
    elif score >= 85 and len(concerns) <= 1:
        recommendation = "recommended"
    else:
        recommendation = "review"

    applicant_name = " ".join(filter(None, [
        application.get("surname"),
        application.get("first_names"),
    ])).strip() or "This applicant"

    summary = (
        f"{applicant_name} currently scores {score}/100 on the admissions readiness check for "
        f"{(school or {}).get('name') or 'this school'}. "
        f"The file is rated {_application_screening_label(recommendation).lower()} based on the current form completeness, payment details, and supporting documents."
    )
    if missing_items:
        summary += f" Main gaps: {', '.join(missing_items[:3])}."
    elif strengths:
        summary += f" Key positives: {strengths[0]}"

    return {
        "application_ref": application.get("ref"),
        "school_id": application.get("school_id"),
        "screening_score": float(score),
        "recommendation": recommendation,
        "summary": summary[:1400],
        "strengths": _application_screening_list(strengths[:4]),
        "concerns": _application_screening_list(concerns[:4]),
        "missing_items": _application_screening_list(missing_items[:6]),
        "screening_source": "rules_only",
        "model": "rules-only",
    }


def _generate_application_screening(school, application, docs):
    baseline = _build_rules_based_application_screening(
        school, application, docs)
    client, config_error = _build_openai_client()
    if config_error:
        return baseline

    prompt = _build_application_screening_prompt(
        school, application, docs, baseline)
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You screen school applications for admissions teams. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0.2,
        )
        content = (
            (response.choices[0].message.content if response.choices else "") or "").strip()
        payload = std_json.loads(content) if content else {}
        summary = str(payload.get("summary")
                      or baseline["summary"]).strip()[:1400]
        strengths = _application_screening_list(
            payload.get("strengths"), baseline["strengths"])
        concerns = _application_screening_list(
            payload.get("concerns"), baseline["concerns"])
        missing_items = _application_screening_list(
            payload.get("missing_items"), baseline["missing_items"])
        merged = dict(baseline)
        merged.update({
            "summary": summary,
            "strengths": strengths[:4],
            "concerns": concerns[:4],
            "missing_items": missing_items[:6],
            "screening_source": "ai_plus_rules",
            "model": OPENAI_MODEL,
        })
        return merged
    except (_OpenAIAuthenticationError, _OpenAIRateLimitError, _OpenAIConnectionError, ValueError) as exc:
        app.logger.warning(
            "Application screening AI fallback triggered for %s: %s", application.get("ref"), exc)
        return baseline
    except Exception:
        app.logger.exception(
            "Unexpected application screening AI error for %s", application.get("ref"))
        return baseline


def _save_application_screening(screening, created_by=None):
    payload = dict(screening or {})
    payload["created_by"] = (created_by or "admin")[:100]
    payload["created_at"] = datetime.utcnow().isoformat()
    try:
        supabase.table("application_screenings").insert(payload).execute()
        return None
    except Exception as exc:
        return exc


# --- Admin: Applications Management ---

def _instructor_ai_identity():
    role = _normalize_role(session.get("role"))
    if role not in {"teacher", "lecturer"}:
        return None, "Access denied. Teacher or lecturer account required."
    return {
        "role": role,
        "user_id": session.get("user_id"),
        "school_id": session.get("school_id"),
        "teacher_id": session.get("teacher_id"),
        "lecturer_id": session.get("lecturer_id"),
        "name": (session.get("user_name") or session.get("username") or role.title()).strip(),
    }, None


def _instructor_ai_read_static_text(file_path, max_chars=9000):
    if not file_path:
        return ""
    normalized = str(file_path).replace("\\", "/").lstrip("/")
    if not normalized.startswith("uploads/"):
        return ""
    ext = os.path.splitext(normalized)[1].lower()
    readable_exts = {".txt", ".md", ".csv",
                     ".json", ".py", ".html", ".htm", ".log"}
    if ext not in readable_exts:
        return ""
    abs_path = os.path.join(app.root_path, "static", normalized)
    if not os.path.isfile(abs_path):
        return ""
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(max_chars)
    except Exception:
        return ""


def _instructor_ai_parse_uploaded_files(files, max_chars=9000):
    assets = []
    for uploaded in files or []:
        if not uploaded or not uploaded.filename:
            continue
        stored_path, stored_name = save_upload_file(uploaded)
        if not stored_path:
            continue
        ext = os.path.splitext(stored_name or "")[1].lower()
        text_preview = _instructor_ai_read_static_text(
            stored_path, max_chars=max_chars)
        image_data_url = None
        if (uploaded.mimetype or "").startswith("image/"):
            try:
                with open(os.path.join(app.root_path, "static", stored_path), "rb") as imgf:
                    image_blob = imgf.read()
                if image_blob and len(image_blob) <= 5 * 1024 * 1024:
                    image_data_url = f"data:{uploaded.mimetype};base64,{base64.b64encode(image_blob).decode('ascii')}"
            except Exception:
                image_data_url = None
        assets.append({
            "name": stored_name,
            "path": stored_path,
            "ext": ext,
            "mimetype": uploaded.mimetype,
            "text": text_preview,
            "image_data_url": image_data_url,
        })
    return assets


def _instructor_ai_get_classroom_bundle(classroom_id):
    try:
        classroom = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).limit(1).execute().data
        classroom = classroom[0] if classroom else None
    except Exception:
        classroom = None

    if not classroom:
        return None

    try:
        posts = supabase.table("classroom_posts").select("author_name,content,created_at").eq(
            "classroom_id", classroom_id).order("created_at", desc=True).limit(80).execute().data or []
    except Exception:
        posts = []

    try:
        materials = supabase.table("classroom_materials").select("title,description,file_name,file_path,created_at").eq(
            "classroom_id", classroom_id).order("created_at", desc=True).limit(80).execute().data or []
    except Exception:
        materials = []

    try:
        assignments = supabase.table("classroom_assignments").select("id,title,description,due_date,file_name,created_at").eq(
            "classroom_id", classroom_id).order("created_at", desc=True).limit(80).execute().data or []
    except Exception:
        assignments = []

    try:
        submissions = supabase.table("assignment_submissions").select(
            "id,assignment_id,submitted_by_name,submission_text,file_name,file_path,submitted_at").eq(
            "classroom_id", classroom_id).order("submitted_at", desc=True).limit(200).execute().data or []
    except Exception:
        submissions = []

    for submission in submissions:
        submission["file_text"] = _instructor_ai_read_static_text(
            submission.get("file_path"), max_chars=7000)
    return {
        "classroom": classroom,
        "posts": posts,
        "materials": materials,
        "assignments": assignments,
        "submissions": submissions,
    }


def _instructor_ai_similarity_report(submissions):
    rows = []
    for item in submissions or []:
        base_text = ((item.get("submission_text") or "") + "\n" +
                     (item.get("file_text") or "")).strip()
        if base_text:
            rows.append({
                "id": item.get("id"),
                "assignment_id": item.get("assignment_id"),
                "student": item.get("submitted_by_name") or "Student",
                "text": base_text,
            })

    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i].get("assignment_id") != rows[j].get("assignment_id"):
                continue
            a_text = rows[i].get("text") or ""
            b_text = rows[j].get("text") or ""
            if len(a_text) < 40 or len(b_text) < 40:
                continue
            sim_pct = round(difflib.SequenceMatcher(
                None, a_text, b_text).ratio() * 100, 1)
            if sim_pct < 45:
                continue
            pairs.append({
                "assignment_id": rows[i].get("assignment_id"),
                "submission_a_id": rows[i].get("id"),
                "submission_b_id": rows[j].get("id"),
                "student_a": rows[i].get("student"),
                "student_b": rows[j].get("student"),
                "similarity_pct": sim_pct,
                "risk": "high" if sim_pct >= 75 else "medium",
            })
    pairs.sort(key=lambda p: p["similarity_pct"], reverse=True)
    return pairs[:20]


def _instructor_ai_prompt_context(bundle, uploaded_assets):
    posts = bundle.get("posts") or []
    materials = bundle.get("materials") or []
    assignments = bundle.get("assignments") or []
    submissions = bundle.get("submissions") or []

    post_lines = [
        f"- {p.get('author_name') or 'Teacher'}: {(p.get('content') or '').strip().replace(chr(10), ' ')[:220]}"
        for p in posts[:20] if (p.get("content") or "").strip()
    ]
    material_lines = [
        f"- {(m.get('title') or m.get('file_name') or 'Material').strip()}: {(m.get('description') or '').strip().replace(chr(10), ' ')[:180]}"
        for m in materials[:20]
    ]
    assignment_lines = [
        f"- {(a.get('title') or 'Assignment').strip()} (due {a.get('due_date') or 'TBD'})"
        for a in assignments[:20]
    ]
    asset_lines = []
    for asset in uploaded_assets or []:
        text_bits = (asset.get("text") or "").strip().replace("\n", " ")[:300]
        asset_lines.append(
            f"- {asset.get('name')} ({asset.get('mimetype') or asset.get('ext') or 'file'}): {text_bits}"
        )

    return (
        "CLASSROOM POSTS:\n" + "\n".join(post_lines) + "\n\n"
        "MATERIALS:\n" + "\n".join(material_lines) + "\n\n"
        "ASSIGNMENTS:\n" + "\n".join(assignment_lines) + "\n\n"
        "SUBMISSION COUNT: " + str(len(submissions)) + "\n\n"
        "UPLOADED NOTES/MEDIA:\n" + "\n".join(asset_lines)
    )[:18000]


def _instructor_ai_ai_content_fallback(text):
    cleaned = (text or "").strip()
    if not cleaned:
        return 0.0, ["No text available for analysis."]
    words = re.findall(r"[A-Za-z0-9']+", cleaned.lower())
    if not words:
        return 0.0, ["No usable words in submission."]
    unique_ratio = len(set(words)) / max(1, len(words))
    repeated_phrase_flag = 1 if re.search(
        r"\b(in conclusion|furthermore|moreover|therefore)\b", cleaned.lower()) else 0
    score = 15 + (1 - unique_ratio) * 60 + repeated_phrase_flag * 8
    score = max(0.0, min(100.0, score))
    cues = [f"Lexical diversity ratio: {round(unique_ratio, 3)}"]
    if repeated_phrase_flag:
        cues.append(
            "Contains formulaic transitional patterns that can correlate with generated writing.")
    return round(score, 1), cues


def _instructor_dashboard_requires_premium(message):
    lowered = (message or "").strip().lower()
    if not lowered:
        return False
    premium_markers = [
        "how many students submitted",
        "submitted out of",
        "submission rate",
        "who submitted",
        "ai content",
        "plagiarism",
        "similarity",
        "mark all",
        "bulk mark",
        "auto mark",
    ]
    return any(marker in lowered for marker in premium_markers)


def _instructor_dashboard_context(identity, classroom_id=None, include_analytics=False):
    role = identity.get("role")
    school_id = identity.get("school_id")
    teacher_id = identity.get("teacher_id")
    lecturer_id = identity.get("lecturer_id")

    try:
        school_classrooms = supabase.table("classrooms").select("id,name,school_id").eq(
            "school_id", school_id).execute().data or []
    except Exception:
        school_classrooms = []

    try:
        owned_query = supabase.table("classrooms").select(
            "id,name,school_id,teacher_id,lecturer_id")
        if role == "teacher" and teacher_id:
            owned_query = owned_query.eq("teacher_id", teacher_id)
        elif role == "lecturer" and lecturer_id:
            owned_query = owned_query.eq("lecturer_id", lecturer_id)
        elif school_id:
            owned_query = owned_query.eq("school_id", school_id)
        owned_classrooms = owned_query.order(
            "id", desc=True).limit(80).execute().data or []
    except Exception:
        owned_classrooms = []

    selected_classrooms = owned_classrooms
    if classroom_id is not None:
        selected_classrooms = [
            row for row in owned_classrooms if str(row.get("id")) == str(classroom_id)
        ]

    class_ids = [row.get("id")
                 for row in selected_classrooms if row.get("id") is not None]
    if not class_ids:
        return {
            "counts": {
                "school_classrooms": len(school_classrooms),
                "owned_classrooms": len(owned_classrooms),
                "selected_classrooms": 0,
                "assignments": 0,
                "submissions": 0,
            },
            "classroom_lines": [],
            "latest_assignment_lines": [],
            "analytics_lines": [],
        }

    try:
        assignments = supabase.table("classroom_assignments").select(
            "id,classroom_id,title,description,due_date,created_at").in_(
            "classroom_id", class_ids).order("created_at", desc=True).limit(240).execute().data or []
    except Exception:
        assignments = []

    try:
        submissions = supabase.table("assignment_submissions").select(
            "id,classroom_id,assignment_id,submitted_by_user_id,submitted_by_name,submitted_at").in_(
            "classroom_id", class_ids).order("submitted_at", desc=True).limit(500).execute().data or []
    except Exception:
        submissions = []

    members_by_class = {}
    for class_id in class_ids:
        try:
            members = supabase.table("classroom_members").select(
                "student_id,learner_id,role,teacher_id,lecturer_id,user_id").eq("classroom_id", class_id).execute().data or []
        except Exception:
            members = []
        student_like = []
        for row in members:
            if row.get("student_id") or row.get("learner_id"):
                student_like.append(row)
                continue
            role_name = (row.get("role") or "").strip().lower()
            if role_name == "member" and not row.get("teacher_id") and not row.get("lecturer_id"):
                student_like.append(row)
        members_by_class[str(class_id)] = len(student_like)

    class_map = {str(row.get("id")): row for row in selected_classrooms}
    classroom_lines = []
    for row in selected_classrooms[:20]:
        cid = str(row.get("id"))
        classroom_lines.append(
            f"- {row.get('name') or 'Class'} (ID {row.get('id')}), student members: {members_by_class.get(cid, 0)}"
        )

    latest_assignment_lines = []
    for row in assignments[:20]:
        class_name = (class_map.get(str(row.get("classroom_id")))
                      or {}).get("name") or "Class"
        latest_assignment_lines.append(
            f"- [{class_name}] {row.get('title') or 'Assignment'} (due {row.get('due_date') or 'TBD'})"
        )

    analytics_lines = []
    if include_analytics:
        submissions_by_assignment = {}
        for sub in submissions:
            aid = sub.get("assignment_id")
            if aid is None:
                continue
            bucket = submissions_by_assignment.setdefault(str(aid), set())
            user_key = sub.get("submitted_by_user_id")
            if user_key is None:
                user_key = (sub.get("submitted_by_name")
                            or "unknown").strip().lower()
            bucket.add(str(user_key))
        for assignment in assignments[:20]:
            aid_key = str(assignment.get("id"))
            class_id_key = str(assignment.get("classroom_id"))
            class_name = (class_map.get(class_id_key)
                          or {}).get("name") or "Class"
            submitted = len(submissions_by_assignment.get(aid_key, set()))
            total_students = members_by_class.get(class_id_key, 0)
            analytics_lines.append(
                f"- [{class_name}] {assignment.get('title') or 'Assignment'}: {submitted} submitted out of {total_students}"
            )

    return {
        "counts": {
            "school_classrooms": len(school_classrooms),
            "owned_classrooms": len(owned_classrooms),
            "selected_classrooms": len(selected_classrooms),
            "assignments": len(assignments),
            "submissions": len(submissions),
        },
        "classroom_lines": classroom_lines,
        "latest_assignment_lines": latest_assignment_lines,
        "analytics_lines": analytics_lines,
    }


def _student_ai_identity():
    role = _normalize_role(session.get("role"))
    if role not in {"student", "learner"}:
        return None, "Access denied. Student or learner account required."

    identity = {
        "role": role,
        "user_id": session.get("user_id"),
        "school_id": session.get("school_id"),
        "student_id": session.get("student_id") if role == "student" else session.get("learner_id"),
        "name": (session.get("user_name") or session.get("username") or "Student").strip(),
    }

    if identity["student_id"]:
        return identity, None

    if not identity.get("user_id"):
        return None, "Session is missing user information. Please log in again."

    profile_table = "students" if role == "student" else "learners"
    try:
        profile_resp = supabase.table(profile_table).select("id, school_id, name").eq(
            "user_id", identity["user_id"]).limit(1).execute()
        profile = profile_resp.data[0] if profile_resp and profile_resp.data else None
    except Exception:
        profile = None

    if not profile:
        return None, "Could not resolve your student profile."

    identity["student_id"] = profile.get("id")
    identity["school_id"] = identity.get(
        "school_id") or profile.get("school_id")
    if profile.get("name"):
        identity["name"] = profile.get("name")
    return identity, None


def _student_ai_classroom_ids(identity):
    classroom_ids = []
    member_col = "student_id" if identity.get(
        "role") == "student" else "learner_id"
    try:
        membership_rows = supabase.table("classroom_members").select("classroom_id").eq(
            member_col, identity.get("student_id")).execute().data or []
        classroom_ids = [row.get("classroom_id") for row in membership_rows if row.get(
            "classroom_id") is not None]
    except Exception:
        classroom_ids = []

    if not classroom_ids and identity.get("school_id"):
        try:
            fallback_rows = supabase.table("classrooms").select("id").eq(
                "school_id", identity.get("school_id")).limit(30).execute().data or []
            classroom_ids = [
                row.get("id") for row in fallback_rows if row.get("id") is not None]
        except Exception:
            classroom_ids = []

    deduped = []
    seen = set()
    for value in classroom_ids:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped[:30]


def _student_ai_compute_weaknesses(perf_rows):
    subject_scores = {}
    for row in perf_rows or []:
        subject = (row.get("subject_name") or row.get(
            "subject") or "General").strip() or "General"
        pct = _to_float(row.get("percentage"), None)
        if pct is None:
            continue
        subject_scores.setdefault(subject, []).append(float(pct))

    ranked = []
    for subject, marks in subject_scores.items():
        if not marks:
            continue
        avg = sum(marks) / len(marks)
        ranked.append({
            "subject": subject,
            "average": round(avg, 1),
            "attempts": len(marks),
        })
    ranked.sort(key=lambda item: item["average"])
    return ranked[:5]


def _student_ai_select_classrooms(identity, preferred_classroom_id=None, strict_preferred=False):
    class_ids = _student_ai_classroom_ids(identity)
    if not class_ids:
        return [], []

    allowed_ids = set(str(value) for value in class_ids)
    selected_ids = class_ids
    if preferred_classroom_id is not None:
        if str(preferred_classroom_id) in allowed_ids:
            selected_ids = [preferred_classroom_id]
        elif strict_preferred:
            return [], []

    try:
        class_rows = supabase.table("classrooms").select("id,name,school_id,class_code,code").in_(
            "id", selected_ids).execute().data or []
    except Exception:
        class_rows = []

    if not class_rows:
        try:
            class_rows = supabase.table("classrooms").select("id,name,school_id").in_(
                "id", selected_ids).execute().data or []
        except Exception:
            class_rows = []

    order_map = {str(class_id): idx for idx,
                 class_id in enumerate(selected_ids)}
    class_rows.sort(key=lambda row: order_map.get(str(row.get("id")), 9999))
    return selected_ids, class_rows


def _student_ai_fetch_context(identity, preferred_classroom_id=None, strict_preferred=False):
    selected_ids, class_rows = _student_ai_select_classrooms(
        identity,
        preferred_classroom_id=preferred_classroom_id,
        strict_preferred=strict_preferred,
    )

    if not selected_ids:
        return {
            "classrooms": [],
            "posts": [],
            "materials": [],
            "assignments": [],
            "submissions": [],
            "performance": [],
            "weaknesses": [],
        }

    try:
        posts = supabase.table("classroom_posts").select("classroom_id,author_name,content,created_at").in_(
            "classroom_id", selected_ids).order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        posts = []

    try:
        materials = supabase.table("classroom_materials").select("classroom_id,title,description,file_name,created_at").in_(
            "classroom_id", selected_ids).order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        materials = []

    try:
        assignments = supabase.table("classroom_assignments").select("id,classroom_id,title,description,due_date,file_name,created_at").in_(
            "classroom_id", selected_ids).order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        assignments = []

    submissions = []
    if identity.get("user_id"):
        try:
            submissions = supabase.table("assignment_submissions").select("classroom_id,assignment_id,submission_text,file_name,submitted_at").eq(
                "submitted_by_user_id", identity.get("user_id")).in_("classroom_id", selected_ids).order("submitted_at", desc=True).limit(80).execute().data or []
        except Exception:
            submissions = []

    try:
        perf_rows = supabase.table("performance_records").select("classroom_id,subject_name,assignment_type,percentage,feedback,created_at").eq(
            "student_id", identity.get("student_id")).eq("student_type", identity.get("role")).in_("classroom_id", selected_ids).order("created_at", desc=True).limit(120).execute().data or []
    except Exception:
        perf_rows = []

    return {
        "classrooms": class_rows,
        "posts": posts,
        "materials": materials,
        "assignments": assignments,
        "submissions": submissions,
        "performance": perf_rows,
        "weaknesses": _student_ai_compute_weaknesses(perf_rows),
    }


def _student_ai_context_snapshot(context_bundle):
    classrooms = context_bundle.get("classrooms") or []
    posts = context_bundle.get("posts") or []
    materials = context_bundle.get("materials") or []
    assignments = context_bundle.get("assignments") or []
    submissions = context_bundle.get("submissions") or []
    weaknesses = context_bundle.get("weaknesses") or []

    class_map = {}
    for classroom in classrooms:
        class_map[str(classroom.get("id"))] = classroom.get(
            "name") or f"Class {classroom.get('id')}"

    post_lines = []
    for post in posts[:25]:
        class_name = class_map.get(str(post.get("classroom_id")), "Classroom")
        content = (post.get("content") or "").strip().replace("\n", " ")
        if content:
            post_lines.append(
                f"[{class_name}] {post.get('author_name') or 'Teacher'}: {content[:240]}")

    material_lines = []
    for material in materials[:25]:
        class_name = class_map.get(
            str(material.get("classroom_id")), "Classroom")
        title = (material.get("title") or material.get(
            "file_name") or "Untitled material").strip()
        desc = (material.get("description") or "").strip().replace("\n", " ")
        material_lines.append(f"[{class_name}] {title} - {desc[:180]}")

    assignment_lines = []
    for assignment in assignments[:20]:
        class_name = class_map.get(
            str(assignment.get("classroom_id")), "Classroom")
        title = (assignment.get("title") or "Assignment").strip()
        due = assignment.get("due_date") or "TBD"
        desc = (assignment.get("description") or "").strip().replace("\n", " ")
        assignment_lines.append(
            f"[{class_name}] {title} (due: {due}) - {desc[:180]}")

    submission_lines = []
    for row in submissions[:20]:
        submission_lines.append(
            f"Assignment ID {row.get('assignment_id')}: {(row.get('submission_text') or '').strip()[:220]}"
        )

    weakness_lines = []
    for item in weaknesses[:5]:
        weakness_lines.append(
            f"{item.get('subject')}: average {item.get('average')}% over {item.get('attempts')} assessments"
        )

    return {
        "counts": {
            "classrooms": len(classrooms),
            "posts": len(posts),
            "materials": len(materials),
            "assignments": len(assignments),
            "submissions": len(submissions),
            "weaknesses": len(weaknesses),
        },
        "posts": post_lines,
        "materials": material_lines,
        "assignments": assignment_lines,
        "submissions": submission_lines,
        "weaknesses": weakness_lines,
    }


def _student_ai_fallback_answer(task, message, snapshot):
    counts = snapshot.get("counts") or {}
    weaknesses = snapshot.get("weaknesses") or []
    weak_text = "\n".join(
        f"- {line}" for line in weaknesses[:3]) if weaknesses else "- No scored weaknesses yet."

    if task == "quiz":
        topic = message or "your classroom notes"
        return {
            "reply": (
                f"I could not reach OpenAI right now, but here is a quick offline quiz starter for {topic}:\n"
                "1) Summarize the core idea from lecture 1 in your own words.\n"
                "2) Compare two key concepts from your latest class notes.\n"
                "3) Solve one example problem and explain each step.\n"
                "4) Identify one common mistake and how to avoid it.\n"
                "5) Teach the topic to a friend in under 2 minutes."
            ),
            "used_context": counts,
        }

    return {
        "reply": (
            "I could not reach OpenAI right now, but I can still guide your revision using classroom data.\n\n"
            f"Message received: {message or 'study help'}\n"
            f"Loaded context: {counts.get('posts', 0)} posts, {counts.get('materials', 0)} materials, "
            f"{counts.get('assignments', 0)} assignments.\n\n"
            "Current weakness focus:\n"
            f"{weak_text}\n\n"
            "Next steps:\n"
            "1) Review teacher instructions mentioning lecture targets first.\n"
            "2) Do active recall from materials before re-reading notes.\n"
            "3) Practice at least 10 mixed questions and mark yourself."
        ),
        "used_context": counts,
    }


def _student_ai_week_key(dt=None):
    dt = dt or datetime.utcnow()
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _student_ai_save_chat_history(identity, task, prompt, response_text, response_mode, used_context, classroom_id=None, has_image=False, image_name=None):
    payload = {
        "school_id": identity.get("school_id"),
        "student_type": identity.get("role"),
        "student_id": identity.get("student_id"),
        "user_id": identity.get("user_id"),
        "classroom_id": classroom_id,
        "task": (task or "chat")[:40],
        "prompt": (prompt or "")[:4000],
        "response_text": (response_text or "")[:12000],
        "response_mode": (response_mode or "ai")[:40],
        "used_context": std_json.dumps(used_context or {}),
        "has_image": bool(has_image),
        "image_name": (image_name or "")[:240] or None,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        supabase.table("student_ai_chat_history").insert(payload).execute()
        return True
    except Exception:
        return False


def _student_ai_get_history(identity, classroom_id=None, limit=12):
    limit = max(1, min(50, _parse_int(limit) or 12))
    try:
        query = supabase.table("student_ai_chat_history").select(
            "id,task,prompt,response_text,response_mode,created_at,classroom_id,has_image,image_name"
        ).eq("student_type", identity.get("role")).eq("student_id", identity.get("student_id"))
        if classroom_id is not None:
            query = query.eq("classroom_id", classroom_id)
        rows = query.order("created_at", desc=True).limit(
            limit).execute().data or []
        return rows, True
    except Exception:
        return [], False


def _student_ai_count_media_today(identity):
    day_start = datetime.utcnow().strftime("%Y-%m-%dT00:00:00")
    try:
        rows = supabase.table("student_ai_chat_history").select("id").eq(
            "student_type", identity.get("role")
        ).eq("student_id", identity.get("student_id")).eq("has_image", True).gte("created_at", day_start).execute().data or []
        return len(rows), True
    except Exception:
        return 0, False


def _student_ai_get_weekly_quiz(identity, week_key, classroom_id=None):
    try:
        query = supabase.table("student_ai_weekly_quizzes").select(
            "id,week_key,classroom_id,quiz_payload,created_at"
        ).eq("student_type", identity.get("role")).eq("student_id", identity.get("student_id")).eq("week_key", week_key)
        if classroom_id is not None:
            query = query.eq("classroom_id", classroom_id)
        row = query.order("created_at", desc=True).limit(1).execute().data
        return (row[0] if row else None), True
    except Exception:
        return None, False


def _student_ai_save_weekly_quiz(identity, week_key, quiz_payload, classroom_id=None):
    payload = {
        "school_id": identity.get("school_id"),
        "student_type": identity.get("role"),
        "student_id": identity.get("student_id"),
        "user_id": identity.get("user_id"),
        "classroom_id": classroom_id,
        "week_key": week_key,
        "quiz_payload": std_json.dumps(quiz_payload or {}),
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        inserted = supabase.table(
            "student_ai_weekly_quizzes").insert(payload).execute()
        row = inserted.data[0] if inserted and inserted.data else None
        return row, True
    except Exception:
        return None, False


def _student_ai_save_quiz_attempt(identity, weekly_quiz_id, classroom_id, score, total_questions, answers_payload=None, feedback=None):
    payload = {
        "school_id": identity.get("school_id"),
        "student_type": identity.get("role"),
        "student_id": identity.get("student_id"),
        "user_id": identity.get("user_id"),
        "weekly_quiz_id": weekly_quiz_id,
        "classroom_id": classroom_id,
        "score": score,
        "total_questions": total_questions,
        "answers_payload": std_json.dumps(answers_payload or {}),
        "feedback": (feedback or "")[:2000] or None,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        supabase.table("student_ai_quiz_attempts").insert(payload).execute()
        return True
    except Exception:
        return False


def _student_ai_parse_quiz_payload(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return std_json.loads(value)
    except Exception:
        return {}


# Expose all symbols (including _private names) to wildcard imports
__all__ = [name for name in list(
    globals().keys()) if not name.startswith('__')]
