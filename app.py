from werkzeug.routing import BaseConverter as _BaseConverter
from werkzeug.routing import ValidationError as _RoutingValidationError
from imports import *
from datetime import timedelta
import supabase
from supabase import create_client
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import os
import smtplib
import json as std_json
import base64
import difflib
import hashlib
from email.message import EmailMessage
from urllib import request as urllib_request
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from itsdangerous import URLSafeSerializer, BadSignature
try:
    import httpx as _httpx
    _httpx_available = True
except ImportError:
    _httpx = None
    _httpx_available = False
try:
    from openai import OpenAI as _OpenAIClient
    from openai import APIConnectionError as _OpenAIConnectionError
    from openai import AuthenticationError as _OpenAIAuthenticationError
    from openai import RateLimitError as _OpenAIRateLimitError
    _openai_available = True
except ImportError:
    _openai_available = False
    _OpenAIConnectionError = Exception
    _OpenAIAuthenticationError = Exception
    _OpenAIRateLimitError = Exception

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallbacksecret")
SIGNED_ID_TOKEN_SALT = "signed-id-v1"
SCHOOL_LINK_TOKEN_SALT = "school-link-v1"
MEETING_PASSWORD_TOKEN_SALT = "meeting-password-v1"


# URL converters — registered early so all routes can reference them.
# The to_python/to_url methods call helper functions (_decode_signed_id etc.)
# which are defined later; that is fine because the methods are only *called*
# at request time, by which point all helpers are already defined.
class _SchoolRefConverter(_BaseConverter):
    regex = r"[^/]+"

    def to_python(self, value):
        result = _decode_school_ref(value)
        if result is None:
            raise _RoutingValidationError()
        return result

    def to_url(self, value):
        encoded = _encode_school_ref(value)
        return encoded if encoded else str(value)


class _SignedIdConverter(_BaseConverter):
    regex = r"[^/]+"

    def to_python(self, value):
        result = _decode_signed_id(value)
        if result is None:
            raise _RoutingValidationError()
        return result

    def to_url(self, value):
        encoded = _encode_signed_id(value)
        return encoded if encoded else str(value)


app.url_map.converters["school_ref"] = _SchoolRefConverter
app.url_map.converters["signed_id"] = _SignedIdConverter


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
        return redirect(request.referrer or url_for("home"))

load_dotenv()
# -----------------------------------------------------------------------------------------Supabase setup ------------------------
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
INSTRUCTOR_AI_PREMIUM_ENABLED = (
    os.getenv("INSTRUCTOR_AI_PREMIUM_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"}
)
try:
    STUDY_AI_MEDIA_DAILY_LIMIT = int(
        (os.getenv("STUDY_AI_MEDIA_DAILY_LIMIT") or "3").strip())
except (TypeError, ValueError):
    STUDY_AI_MEDIA_DAILY_LIMIT = 3
STUDY_AI_MEDIA_DAILY_LIMIT = max(0, STUDY_AI_MEDIA_DAILY_LIMIT)

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "classroom")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
APPLY_UPLOAD_FOLDER = os.path.join(
    app.root_path, "static", "uploads", "applications")
os.makedirs(APPLY_UPLOAD_FOLDER, exist_ok=True)


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


_log_startup_configuration_warnings()
ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "rar", "mp4", "mp3", "txt"
}
SHOW_SCHOOL_ADMIN_ROLE = os.getenv(
    "SHOW_SCHOOL_ADMIN_ROLE", "false").strip().lower() == "true"
PASSWORD_POLICY_REGEX = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$"
)


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

# -------------------------------------------------------------------------------------------SMART HUB INDEX--------------


@app.route("/")
def home():
    return render_template("home.html")


# --------------------------------------------------------------------------------------------services-----------------
@app.route("/services")
def services():
    return render_template("services.html")


# ----------------------------------------------------------------------------------------------About-------------
@app.route("/about")
def about():
    return render_template("about.html")

# ----------------------------------------------------------------------------------------------Contact---------


@app.route("/contact")
def contact():
    return render_template("contact.html")


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


@app.route("/contact/send", methods=["POST"])
def submit_main_contact_message():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip() or None
    message = (request.form.get("message") or "").strip()

    if not name or not email or not message:
        flash("Name, email, and message are required.", "error")
        return redirect(url_for("contact"))

    payload = {
        "school_id": None,
        "source_scope": "main_hub",
        "source_site": "Smart School Hub",
        "sender_name": name,
        "sender_email": email,
        "sender_phone": phone,
        "message": message,
        "status": "new",
        "page_url": request.referrer,
    }

    ok, error = _insert_contact_message(payload)
    if not ok:
        flash(
            f"Could not send your message right now: {str(error)[:120] if error else 'unknown error'}", "error")
        return redirect(url_for("contact"))

    _notify_global_admins(
        title="New Smart School Hub Contact Message",
        message=f"{name} ({email}) sent a new contact message.",
        notification_type="contact",
        priority="normal",
        send_email=True,
        send_sms=False,
        meta={"event": "hub_contact_message", "sender_email": email},
    )

    flash("Message sent successfully. We will get back to you soon.", "success")
    return redirect(url_for("contact"))


@app.route("/school/<signed_id:school_id>/contact/send", methods=["POST"])
def submit_school_contact_message(school_id):
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip() or None
    message = (request.form.get("message") or "").strip()

    if not name or not email or not message:
        flash("Name, email, and message are required.", "error")
        return redirect(request.referrer or url_for("school_page", school_id=school_id, page_slug="home"))

    payload = {
        "school_id": school_id,
        "source_scope": "school_site",
        "source_site": school.get("name") or "School Website",
        "sender_name": name,
        "sender_email": email,
        "sender_phone": phone,
        "message": message,
        "status": "new",
        "page_url": request.referrer,
    }

    ok, error = _insert_contact_message(payload)
    if not ok:
        flash(
            f"Could not send your message right now: {str(error)[:120] if error else 'unknown error'}", "error")
        return redirect(request.referrer or url_for("school_page", school_id=school_id, page_slug="home"))

    _notify_school_admins(
        school_id=school_id,
        title="New School Website Contact Message",
        message=f"{name} ({email}) sent a new website enquiry.",
        notification_type="contact",
        priority="normal",
        send_email=True,
        send_sms=False,
        meta={"event": "school_contact_message",
              "school_id": school_id, "sender_email": email},
    )

    flash("Message sent successfully. The school admin will respond soon.", "success")
    return redirect(request.referrer or url_for("school_page", school_id=school_id, page_slug="home"))


@app.route("/admin/contact-messages")
def admin_contact_messages():
    gate = _require_global_admin()
    if gate:
        return gate

    scope_filter = (request.args.get("scope") or "all").strip().lower()
    if scope_filter not in {"all", "main", "school"}:
        scope_filter = "all"

    selected_school_id = _parse_int(request.args.get("school_id"))
    if selected_school_id is not None:
        messages = _load_contact_messages_for_scope(
            school_id=selected_school_id)
    else:
        messages = _load_contact_messages_for_scope(scope=scope_filter)

    schools = _select_school_scoped("schools", order_by="name")
    school_map = {s.get("id"): s.get("name") for s in schools}
    for msg in messages:
        sid = msg.get("school_id")
        msg["school_name"] = school_map.get(sid) if sid else "Smart School Hub"

    return render_template(
        "admin_contact_messages.html",
        messages=messages,
        is_global=True,
        scope_filter=scope_filter,
        selected_school_id=selected_school_id,
        schools=schools,
        school=None,
    )


@app.route("/school/<signed_id:school_id>/admin/contact-messages")
def school_admin_contact_messages(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("school_admin_dashboard", school_id=school_id))

    messages = _load_contact_messages_for_scope(school_id=school_id)
    for msg in messages:
        msg["school_name"] = school.get("name")

    return render_template(
        "admin_contact_messages.html",
        messages=messages,
        is_global=False,
        scope_filter="school",
        selected_school_id=school_id,
        schools=[],
        school=school,
    )

# ------------------------------------------------------------------------------------------Admin Dashboard-------------------


@app.route("/admin")
def admin_dashboard():
    gate = _require_global_admin()
    if gate:
        return gate
    return render_template("admin_dashboard.html")

# -------------------------------------------------------------------------------------------Admin Login-------------------


@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    flash("Use the main login form for admin access.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------------------------ADMIN LOGOUT-----------------
@app.route("/admin_logout")
def admin_logout():
    # Clear the admin session
    session.pop("admin_logged_in", None)
    flash("You have been logged out.", "info")
    # Redirect back to your school hub index
    return redirect(url_for("home"))


# --------------------------------------------------------------------------------------------Manage Users------------------


@app.route("/admin_users")
def admin_users():
    gate = _require_global_admin()
    if gate:
        return gate
    selected_tab = _normalize_role(request.args.get("tab"))
    admin_user_data = _build_admin_user_management_data(selected_tab)
    users = admin_user_data["users"]
    schools = supabase.table("schools").select(
        "id,name").order("name").execute().data or []
    courses = _select_school_scoped("courses", order_by="name")
    subjects = _select_school_scoped("subjects", order_by="name")
    return render_template(
        "admin_users.html",
        users=users,
        schools=schools,
        courses=courses,
        subjects=subjects,
        role_tabs=admin_user_data["role_tabs"],
        active_tab=admin_user_data["active_tab"],
    )


@app.route("/admin_users/check_availability")
def admin_user_availability():
    gate = _require_global_admin()
    if gate:
        return jsonify({"ok": False, "message": "Admin access required."}), 403

    email = (request.args.get("email") or "").strip()
    username = (request.args.get("username") or "").strip()
    exclude_user_id = _parse_int(request.args.get("user_id"))

    checks = _find_user_identity_conflicts(
        email=email,
        username=username,
        exclude_user_id=exclude_user_id,
    )

    email_conflict = checks.get("email")
    username_conflict = checks.get("username")
    payload = {
        "ok": True,
        "email": {
            "checked": bool(email),
            "available": email_conflict is None,
            "message": _availability_message("email", email_conflict),
        },
        "username": {
            "checked": bool(username),
            "available": username_conflict is None,
            "message": _availability_message("username", username_conflict),
        },
    }
    return jsonify(payload)


# -----------------------------------------------------------------------------------------------Add User --------------
@app.route("/add_user", methods=["GET", "POST"])
def add_user():
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        role = _normalize_role(request.form["role"])
        active_tab = _normalize_role(
            request.form.get("active_tab")) or role or "teacher"
        username = (request.form["username"] or "").strip()
        email = (request.form["email"] or "").strip().lower()
        role = _normalize_role(request.form["role"])
        password = request.form["password"]
        school_id = _parse_int(request.form.get("school_id"))

        if not username or not email:
            flash("Username and email are required.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        conflicts = _find_user_identity_conflicts(
            email=email, username=username)
        if conflicts.get("email"):
            flash(_availability_message("email", conflicts["email"]), "error")
            return redirect(url_for("admin_users", tab=active_tab))
        if conflicts.get("username"):
            flash(_availability_message(
                "username", conflicts["username"]), "error")
            return redirect(url_for("admin_users", tab=active_tab))

        if role != "admin" and school_id is None:
            flash("Please select a school for this user.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        school = _get_school_record(
            school_id) if school_id is not None else None
        if role not in {"admin", "school_admin"} and not _school_allows_role(school, role):
            flash("Selected role is not valid for the selected school type.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        password_error = _validate_password_strength(password)
        if password_error:
            flash(password_error, "error")
            return redirect(url_for("admin_users", tab=active_tab))

        # Hash password before storing
        from werkzeug.security import generate_password_hash
        password_hash = generate_password_hash(password)

        try:
            user_resp = supabase.table("users").insert({
                "username": username,
                "email": email,
                "password": password_hash,
                "role": role
            }).execute()
        except Exception as error:
            if _is_duplicate_user_identity_error(error):
                flash(
                    "That email or username is already in use. Pick another one or edit the existing account.", "error")
            else:
                flash(
                    f"Failed to create user account: {str(error)[:120]}", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        if not getattr(user_resp, "data", None):
            flash("Failed to create user account.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        user_id = user_resp.data[0]["id"]
        try:
            if role != "admin":
                _upsert_profile_for_role(
                    role, user_id, school_id, request.form, mode="create")
        except Exception as e:
            try:
                supabase.table("users").delete().eq(
                    "id", int(user_id)).execute()
            except Exception:
                pass
            flash(f"User profile creation failed: {str(e)[:120]}", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        notify_user(
            user_id=user_id,
            title="Welcome to SmartHub",
            message=(
                "Your account has been created successfully. "
                "Login to view your dashboard and notifications."
            ),
            notification_type="account",
            priority="normal",
            send_email=True,
            send_sms=False,
            meta={"event": "account_created"},
        )

        flash("User added successfully!", "success")
        return redirect(url_for("admin_users", tab=active_tab))

    return redirect(url_for("admin_users"))

# ------------------------------------------------------------------------------------------------Edit User -----------------


@app.route("/edit_user/<signed_id:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        active_tab = _normalize_role(
            request.form.get("active_tab")) or "teacher"
        username = (request.form["username"] or "").strip()
        email = (request.form["email"] or "").strip().lower()
        role = _normalize_role(request.form["role"])
        school_id = _parse_int(request.form.get("school_id"))

        if not username or not email:
            flash("Username and email are required.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        current_user_resp = supabase.table("users").select(
            "id,role").eq("id", user_id).limit(1).execute().data or []
        if not current_user_resp:
            flash("User not found.", "error")
            return redirect(url_for("admin_users", tab=active_tab))
        current_role = _normalize_role(current_user_resp[0].get("role"))

        conflicts = _find_user_identity_conflicts(
            email=email,
            username=username,
            exclude_user_id=user_id,
        )
        if conflicts.get("email"):
            flash(_availability_message("email", conflicts["email"]), "error")
            return redirect(url_for("admin_users", tab=active_tab))
        if conflicts.get("username"):
            flash(_availability_message(
                "username", conflicts["username"]), "error")
            return redirect(url_for("admin_users", tab=active_tab))

        if role != "admin" and school_id is None:
            flash("Please select a school for this user.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        school = _get_school_record(
            school_id) if school_id is not None else None
        if role not in {"admin", "school_admin"} and not _school_allows_role(school, role):
            flash("Selected role is not valid for the selected school type.", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        try:
            supabase.table("users").update({
                "username": username,
                "email": email,
                "role": role
            }).eq("id", user_id).execute()
        except Exception as error:
            if _is_duplicate_user_identity_error(error):
                flash(
                    "That email or username is already in use. Pick another one or edit the existing account.", "error")
            else:
                flash(f"Failed to update user: {str(error)[:120]}", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        try:
            if current_role != role and current_role != "admin":
                _delete_profile_for_role(current_role, user_id)
            if role != "admin":
                _upsert_profile_for_role(
                    role, user_id, school_id, request.form, mode="update")
        except Exception as e:
            flash(
                f"User updated but profile update failed: {str(e)[:120]}", "error")
            return redirect(url_for("admin_users", tab=active_tab))

        flash("User updated successfully!", "success")
        return redirect(url_for("admin_users", tab=active_tab))

    return redirect(url_for("admin_users"))

# -----------------------------------------------------------------------------------------------Delete User --------------


@app.route("/delete_user/<signed_id:user_id>")
def delete_user(user_id):
    gate = _require_global_admin()
    if gate:
        return gate
    active_tab = _normalize_role(request.args.get("tab")) or "teacher"
    try:
        u = supabase.table("users").select("role").eq(
            "id", user_id).limit(1).execute().data or []
        if u:
            _delete_profile_for_role(u[0].get("role"), user_id)
    except Exception:
        pass
    supabase.table("users").delete().eq("id", user_id).execute()
    flash("User deleted successfully!", "success")
    return redirect(url_for("admin_users", tab=active_tab))


# -------------------User Profile-----------------------


# @app.route("/user/<signed_id:user_id>", methods=["GET", "POST"])
# def user_profile(user_id):


# -------------------------------------------------------------------------------------------------Manage Schools------------

@app.route("/admin_schools", methods=["GET", "POST"])
def admin_schools():
    gate = _require_global_admin()
    if gate:
        return gate
    response = supabase.table("schools").select("*").execute()
    schools = response.data
    return render_template("admin_schools.html", users=[], schools=schools)

# --------------------------------------------------------------------------------------------------Add School----------


@app.route("/add_school", methods=["GET", "POST"])
def add_school():
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        name = request.form["name"]
        school_type = request.form["school_type"]
        location = request.form["location"]
        logo = request.form["logo"]
        contact_number = request.form["contact_number"]
        contact_email = request.form["contact_email"]

        supabase.table("schools").insert({
            "name": name,
            "school_type": school_type,
            "location": location,
            "logo": logo,
            "contact_number": contact_number,
            "contact_email": contact_email
        }).execute()

        flash("School added successfully!", "success")
        return redirect(url_for("admin_schools"))

    return render_template("admin_schools.html")

# -------------------------------------------------------------------------------------------------------Edit School------------


@app.route("/edit_school/<signed_id:school_id>", methods=["GET", "POST"])
def edit_school(school_id):
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        name = request.form["name"]
        school_type = request.form["school_type"]
        location = request.form["location"]
        logo = request.form["logo"]
        contact_number = request.form["contact_number"]
        contact_email = request.form["contact_email"]

        supabase.table("schools").update({
            "name": name,
            "school_type": school_type,
            "location": location,
            "logo": logo,
            "contact_number": contact_number,
            "contact_email": contact_email
        }).eq("id", school_id).execute()

        flash("School updated successfully!", "success")
        return redirect(url_for("admin_schools"))

    response = supabase.table("schools").select(
        "*").eq("id", school_id).execute()
    school = response.data[0] if response.data else None
    return render_template("admin_schools.html", school=school)

# ------------------------------------------------------------------------------------------------------- Delete School---------------


@app.route("/delete_school/<signed_id:school_id>")
def delete_school(school_id):
    gate = _require_global_admin()
    if gate:
        return gate
    supabase.table("schools").delete().eq("id", school_id).execute()
    flash("School deleted successfully!", "success")
    return redirect(url_for("admin_schools"))


# ----------------------------------------------------------------------------------------------------------School Index----------


@app.route("/school/<signed_id:school_id>")
def school_index(school_id):
    return redirect(url_for("school_page", school_id=school_id, page_slug="home"))


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


@app.context_processor
def inject_school_link_helpers():
    return {
        "school_login_url": _school_login_url,
        "school_public_url": _school_public_url,
        "school_ref_token": _encode_school_ref,
    }


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


@app.route("/school/<signed_id:school_id>/vacancies/<news_slug>")
def school_news_detail(school_id, news_slug):
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))

    menu_response = (
        supabase.table("school_menu")
        .select("*")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .order("display_order")
        .execute()
    )
    menu_items = menu_response.data or []

    news_response = (
        supabase.table("school_news")
        .select("*")
        .eq("school_id", school_id)
        .eq("slug", news_slug)
        .limit(1)
        .execute()
    )
    news_item = news_response.data[0] if news_response.data else None

    if not news_item:
        flash("Vacancy not found.", "error")
        return redirect(url_for("school_page", school_id=school_id, page_slug="vacancies"))

    return render_template(
        "school_news_detail.html",
        school=school,
        menu_items=menu_items,
        news_item=news_item,
        back_url=url_for("school_page", school_id=school_id,
                         page_slug="vacancies"),
    )


@app.route("/school/<signed_id:school_id>/<page_slug>")
def school_page(school_id, page_slug):
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))

    menu_response = (
        supabase.table("school_menu")
        .select("*")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .order("display_order")
        .execute()
    )
    menu_items = menu_response.data or []

    if not menu_items:
        menu_items = [
            {"label": "Home", "slug": "home",
                "is_external": False, "external_url": None},
            {"label": "About", "slug": "about",
                "is_external": False, "external_url": None},
            {"label": "Academics", "slug": "academics",
                "is_external": False, "external_url": None},
            {"label": "Admissions", "slug": "admissions",
                "is_external": False, "external_url": None},
            {"label": "Staff", "slug": "staff",
                "is_external": False, "external_url": None},
            {"label": "Gallery", "slug": "gallery",
                "is_external": False, "external_url": None},
            {"label": "News", "slug": "news",
                "is_external": False, "external_url": None},
            {"label": "Contact", "slug": "contact",
                "is_external": False, "external_url": None},
        ]

    page_response = (
        supabase.table("school_pages")
        .select("*")
        .eq("school_id", school_id)
        .eq("slug", page_slug)
        .eq("is_published", True)
        .execute()
    )
    page = page_response.data[0] if page_response.data else None

    if not page and page_slug != "home":
        return redirect(url_for("school_page", school_id=school_id, page_slug="home"))

    if page:
        sections_response = (
            supabase.table("school_sections")
            .select("*")
            .eq("page_id", page["id"])
            .eq("is_visible", True)
            .order("display_order")
            .execute()
        )
        sections = sections_response.data or []

        page_media_response = (
            supabase.table("school_media")
            .select("*")
            .eq("school_id", school_id)
            .eq("page_id", page["id"])
            .order("display_order")
            .execute()
        )
        page_media = page_media_response.data or []
    else:
        flash(
            "Using a default landing page because this school's website content has not been seeded yet.",
            "info",
        )
        school_label = school.get("name") or "This institution"
        school_label_lc = school_label.lower()
        is_emr_school = (
            "emergency medical rescue" in school_label_lc
            or "emr college" in school_label_lc
            or school_label_lc.startswith("emr")
        )
        motto = (school.get("motto") or school.get("tagline") or "").strip()
        if not motto and is_emr_school:
            motto = "We Train The Brave"

        intro_heading = "Welcome"
        intro_body = (
            f"<p><strong>{school_label}</strong> is now live on the tertiary website template. "
            "Full website pages and section content can be added from the school content seed script "
            "or the admin content manager.</p>"
        )
        admissions_body = "<p>Admissions details can be published under the <strong>admissions</strong> page once content is seeded.</p>"
        contact_body = "<p>Use the contact information below to reach the institution.</p>"

        if is_emr_school:
            # Apply EMR brand colors when school record is incomplete.
            if not (school.get("primary_color") or "").strip():
                school["primary_color"] = "#0B4EA2"  # blue
            if not (school.get("accent_color") or "").strip():
                school["accent_color"] = "#F58220"  # orange

            intro_heading = "WE TRAIN THE BRAVE"
            intro_body = (
                f"<p><strong>{school_label}</strong> tertiary landing page is now active.</p>"
                f"<p><strong>{motto or 'We Train The Brave'}</strong></p>"
                "<p>This temporary EMR landing page will be replaced automatically when the full school website content seed is applied.</p>"
            )
            admissions_body = (
                "<p>Emergency Medical Rescue programmes and application details can be published under "
                "the <strong>admissions</strong> page after content seeding.</p>"
            )
            contact_body = (
                "<p>For current application enquiries, contact <strong>hroemrc@gmail.com</strong>. "
                "Additional phone and location details can be published once EMR content is fully seeded.</p>"
            )

        page = {
            "id": None,
            "slug": "home",
            "title": f"{school_label}",
            "hero_image_url": school.get("hero_image_url"),
        }
        sections = [
            {
                "id": "fallback-intro",
                "section_type": "text_block",
                "heading": intro_heading,
                "body_html": intro_body,
            },
            {
                "id": "fallback-apply",
                "section_type": "text_block",
                "heading": "Admissions",
                "body_html": admissions_body,
            },
            {
                "id": "fallback-contact",
                "section_type": "contact_map",
                "heading": "Contact",
                "body_html": contact_body,
            },
        ]
        page_media = []

    staff = _table_rows("school_staff", school_id, order_by="display_order")
    albums = _table_rows("school_gallery_albums",
                         school_id, order_by="display_order")
    # Show vacancies/news in reverse-chronological order by publish date.
    news_items = _table_rows("school_news", school_id,
                             order_by="published_at", ascending=False)
    events = _table_rows("school_events", school_id, order_by="event_date")
    testimonials = _table_rows(
        "school_testimonials", school_id, order_by="display_order")
    downloads = _table_rows("school_downloads", school_id)
    social_links = _table_rows(
        "school_social_links", school_id, order_by="display_order")

    contact_response = (
        supabase.table("school_contact_info")
        .select("*")
        .eq("school_id", school_id)
        .execute()
    )
    contact_info = contact_response.data[0] if contact_response.data else None
    application_enabled = _school_application_enabled(school)

    return render_template(
        _resolve_school_template(school),
        school=school,
        page=page,
        menu_items=menu_items,
        sections=sections,
        page_media=page_media,
        staff=staff,
        albums=albums,
        news_items=news_items,
        events=events,
        testimonials=testimonials,
        downloads=downloads,
        social_links=social_links,
        contact_info=contact_info,
        application_enabled=application_enabled,
    )


# -----------------------------------------------------------------------------------------------------------Schools Page-----
@app.route("/schools")
def schools_directory():
    # Fetch all schools from Supabase
    response = supabase.table("schools").select("*").execute()
    schools = response.data or []

    # Pass schools into the template
    return render_template("schools.html", schools=schools)

# ================================================================================================Schools Live Search (for AJAX requests from the frontend)----------------


@app.route("/schools/live-search")
def schools_live_search():
    """Live search endpoint for schools directory (name, contact number, email)."""
    query = request.args.get("q", "").strip()

    try:
        builder = supabase.table("schools").select("*")
        if query:
            safe_query = query.replace(",", " ")
            builder = builder.or_(
                f"name.ilike.%{safe_query}%,contact_number.ilike.%{safe_query}%,contact_email.ilike.%{safe_query}%"
            )
        response = builder.execute()
        return jsonify({"schools": response.data or []})
    except Exception as error:
        return jsonify({"schools": [], "error": str(error)}), 500

# ==========================================================================================================ADMIN Courses, Modules======================

# ----------------------------------------------------------SUBJECTS


@app.route("/admin/subjects", methods=["GET", "POST"])
def admin_subjects():
    gate = _require_global_admin()
    if gate:
        return gate

    if request.method == "POST":
        school_id = _parse_int(request.form.get("school_id"))
        if school_id is None:
            flash("Please select a school before creating a subject.", "error")
            return redirect(url_for("admin_subjects"))
        try:
            _insert_school_scoped("subjects", {
                "name": (request.form.get("name") or "").strip(),
                "code": (request.form.get("code") or "").strip() or None,
            }, school_id=school_id)
            flash("Subject added!", "success")
        except Exception as e:
            flash(f"Failed to add subject: {str(e)[:120]}", "error")
        return redirect(url_for("admin_subjects"))

    schools = supabase.table("schools").select(
        "id,name").order("name").execute().data or []
    subjects = _select_school_scoped("subjects", order_by="name")
    return render_template("admin_subjects.html", subjects=subjects, schools=schools)


@app.route("/admin/subjects/edit/<signed_id:subject_id>", methods=["POST"])
def edit_subject(subject_id):
    gate = _require_global_admin()
    if gate:
        return gate

    school_id = _parse_int(request.form.get("school_id"))
    if school_id is None:
        flash("Please select a school.", "error")
        return redirect(url_for("admin_subjects"))

    try:
        supabase.table("subjects").update({
            "school_id": school_id,
            "name": (request.form.get("name") or "").strip(),
            "code": (request.form.get("code") or "").strip() or None,
        }).eq("id", subject_id).execute()
    except Exception as e:
        if _is_missing_school_column_error(e):
            supabase.table("subjects").update({
                "name": (request.form.get("name") or "").strip(),
                "code": (request.form.get("code") or "").strip() or None,
            }).eq("id", subject_id).execute()
        else:
            flash(f"Failed to update subject: {str(e)[:120]}", "error")
            return redirect(url_for("admin_subjects"))

    flash("Subject updated!", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/admin/subjects/delete/<signed_id:subject_id>")
def delete_subject(subject_id):
    gate = _require_global_admin()
    if gate:
        return gate
    supabase.table("subjects").delete().eq("id", subject_id).execute()
    flash("Subject deleted!", "success")
    return redirect(url_for("admin_subjects"))

# ----------------------------------------------------------COURSES


@app.route("/admin/courses", methods=["GET", "POST"])
def admin_courses():
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        school_id = _parse_int(request.form.get("school_id"))
        if school_id is None:
            flash("Please select a school before creating a course.", "error")
            return redirect(url_for("admin_courses"))
        _insert_school_scoped("courses", {
            "name": request.form["name"],
            "code": request.form["code"]
        }, school_id=school_id)
        flash("Course added!", "success")
    schools = supabase.table("schools").select(
        "id,name").order("name").execute().data or []
    courses = _select_school_scoped("courses", order_by="name")
    return render_template("admin_courses.html", courses=courses, schools=schools)


@app.route("/admin/courses/edit/<signed_id:course_id>", methods=["POST"])
def edit_course(course_id):
    gate = _require_global_admin()
    if gate:
        return gate
    school_id = _parse_int(request.form.get("school_id"))
    if school_id is None:
        flash("Please select a school.", "error")
        return redirect(url_for("admin_courses"))

    try:
        supabase.table("courses").update({
            "school_id": school_id,
            "name": request.form["name"],
            "code": request.form["code"]
        }).eq("id", course_id).execute()
    except Exception as e:
        if _is_missing_school_column_error(e):
            supabase.table("courses").update({
                "name": request.form["name"],
                "code": request.form["code"]
            }).eq("id", course_id).execute()
        else:
            raise
    flash("Course updated!", "success")
    return redirect(url_for("admin_courses"))


@app.route("/admin/courses/delete/<signed_id:course_id>")
def delete_course(course_id):
    gate = _require_global_admin()
    if gate:
        return gate
    supabase.table("courses").delete().eq("id", course_id).execute()
    flash("Course deleted!", "success")
    return redirect(url_for("admin_courses"))


# -------------------------------------------------------modules


@app.route("/admin/modules", methods=["GET", "POST"])
def admin_modules():
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        school_id = _parse_int(request.form.get("school_id"))
        if school_id is None:
            flash("Please select a school before creating a module.", "error")
            return redirect(url_for("admin_modules"))
        _insert_school_scoped("modules", {
            "name": request.form["name"],
            "module_code": request.form["module_code"],
            "description": request.form.get("description"),
            "credits": request.form.get("credits"),
            "faculty": request.form.get("faculty")
        }, school_id=school_id)
        flash("Module added!", "success")
    schools = supabase.table("schools").select(
        "id,name").order("name").execute().data or []
    modules = _select_school_scoped("modules", order_by="name")
    return render_template("admin_modules.html", modules=modules, schools=schools)


@app.route("/admin/modules/edit/<signed_id:module_id>", methods=["POST"])
def edit_module(module_id):
    gate = _require_global_admin()
    if gate:
        return gate
    school_id = _parse_int(request.form.get("school_id"))
    if school_id is None:
        flash("Please select a school.", "error")
        return redirect(url_for("admin_modules"))

    try:
        supabase.table("modules").update({
            "school_id": school_id,
            "name": request.form["name"],
            "module_code": request.form["module_code"],
            "description": request.form.get("description"),
            "credits": request.form.get("credits"),
            "faculty": request.form.get("faculty")
        }).eq("id", module_id).execute()
    except Exception as e:
        if _is_missing_school_column_error(e):
            supabase.table("modules").update({
                "name": request.form["name"],
                "module_code": request.form["module_code"],
                "description": request.form.get("description"),
                "credits": request.form.get("credits"),
                "faculty": request.form.get("faculty")
            }).eq("id", module_id).execute()
        else:
            raise
    flash("Module updated!", "success")
    return redirect(url_for("admin_modules"))


@app.route("/admin/modules/delete/<signed_id:module_id>")
def delete_module(module_id):
    gate = _require_global_admin()
    if gate:
        return gate
    supabase.table("modules").delete().eq("id", module_id).execute()
    flash("Module deleted!", "success")
    return redirect(url_for("admin_modules"))


# -------------------------------------------------------MixCurriculum


@app.route("/admin/curriculum", methods=["GET", "POST"])
def admin_curriculum():
    gate = _require_global_admin()
    if gate:
        return gate
    if request.method == "POST":
        school_id = _parse_int(request.form.get("school_id"))
        if school_id is None:
            flash("Please select a school before creating a mapping.", "error")
            return redirect(url_for("admin_curriculum"))
        _insert_school_scoped("course_modules", {
            "course_id": request.form["course_id"],
            "module_id": request.form["module_id"],
            "year": request.form["year"],
            "semester": request.form["semester"]
        }, school_id=school_id)
        flash("Mapping added!", "success")
    schools = supabase.table("schools").select(
        "id,name").order("name").execute().data or []
    courses = _select_school_scoped("courses", order_by="name")
    modules = _select_school_scoped("modules", order_by="name")
    mappings = _select_school_scoped("course_modules", order_by="id")
    return render_template("admin_curriculum.html",
                           schools=schools,
                           courses=courses,
                           modules=modules,
                           mappings=mappings)


@app.route("/admin/curriculum/edit/<signed_id:mapping_id>", methods=["POST"])
def edit_mapping(mapping_id):
    gate = _require_global_admin()
    if gate:
        return gate
    school_id = _parse_int(request.form.get("school_id"))
    if school_id is None:
        flash("Please select a school.", "error")
        return redirect(url_for("admin_curriculum"))

    try:
        supabase.table("course_modules").update({
            "school_id": school_id,
            "course_id": request.form["course_id"],
            "module_id": request.form["module_id"],
            "year": request.form["year"],
            "semester": request.form["semester"]
        }).eq("id", mapping_id).execute()
    except Exception as e:
        if _is_missing_school_column_error(e):
            supabase.table("course_modules").update({
                "course_id": request.form["course_id"],
                "module_id": request.form["module_id"],
                "year": request.form["year"],
                "semester": request.form["semester"]
            }).eq("id", mapping_id).execute()
        else:
            raise
    flash("Mapping updated!", "success")
    return redirect(url_for("admin_curriculum"))


@app.route("/admin/curriculum/delete/<signed_id:mapping_id>")
def delete_mapping(mapping_id):
    gate = _require_global_admin()
    if gate:
        return gate
    supabase.table("course_modules").delete().eq("id", mapping_id).execute()
    flash("Mapping deleted!", "success")
    return redirect(url_for("admin_curriculum"))


# -------------------------------------------------------------------------------------------------------REGISTRATION MANAGEMENT--------------
@app.route("/school/<signed_id:school_id>/register", methods=["GET", "POST"])
def register(school_id):
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))

    allowed_roles = _role_options_for_school_type(school.get("school_type"))

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        role = _normalize_role(request.form["role"])

        if role == "admin":
            flash(
                "Admin accounts are provisioned manually in the database.", "error")
            return redirect(url_for("register", school_id=school_id))

        if role == "school_admin":
            flash(
                "School admin accounts can only be created by the global admin.", "error")
            return redirect(url_for("register", school_id=school_id))

        password_error = _validate_password_strength(password)
        if password_error:
            flash(password_error, "error")
            return redirect(url_for("register", school_id=school_id))

        if not _school_allows_role(school, role):
            return _reject_disallowed_role(role, school)

        # --------------------------------------------------------------------------Insert into users table---------------------------

        hashed_pw = generate_password_hash(password)

        try:
            response = supabase.table("users").insert({
                "username": username,
                "email": email,
                "password": hashed_pw,   # <-- hashed value
                "role": role
            }).execute()
        except Exception as e:
            flash(
                f"Registration failed: account may already exist. ({str(e)[:120]})", "error")
            return redirect(url_for("register", school_id=school_id))

        if not getattr(response, "data", None):
            flash("Registration failed: could not create user account. The username or email may already be taken.", "error")
            return redirect(url_for("register", school_id=school_id))

        user_id = response.data[0]["id"]
        session["user_id"] = user_id
        session["school_id"] = school_id
        session["role"] = role
        session["school_type"] = school.get("school_type")
        return _render_role_registration_step(role, user_id=user_id, school_id=school_id)

    return render_template(
        "register_user.html",
        school_id=school_id,
        school=school,
        allowed_roles=allowed_roles,
        school_type_label=_school_type_label(school.get("school_type")),
    )


# ---------------------------------------------------------------------------------------------------------- Teacher---------------

@app.route("/register/teacher", methods=["POST"])
def register_teacher():
    school = _school_from_form_or_session(request.form.get("school_id"))
    if not _school_allows_role(school, "teacher"):
        return _reject_disallowed_role("teacher", school)

    supabase.table("teachers").insert({
        "user_id": request.form["user_id"],
        "school_id": request.form["school_id"],
        "name": request.form["name"],
        "phone_number": request.form["phone_number"],
        "core_subjects": request.form["core_subjects"]
    }).execute()
    flash("Teacher registered successfully!", "success")
    return redirect(url_for("login"))


# -----------------------------------------------------------------------------------------------------------Student---------------
@app.route("/register/student", methods=["GET", "POST"])
def register_student():

    def parse_int(value):
        return int(value) if value and str(value).strip() != "" else None

    if request.method == "POST":
        user_id = request.form.get("user_id") or session.get("user_id")
        school_id = request.form.get("school_id") or session.get("school_id")
        school = _school_from_form_or_session(school_id)
        if not _school_allows_role(school, "student"):
            return _reject_disallowed_role("student", school)

        course_id = parse_int(request.form.get("course_id"))
        year_of_study = parse_int(request.form.get("year_of_study"))
        semester = parse_int(request.form.get("semester"))
        year_of_enrollment = parse_int(request.form.get("year_of_enrollment"))
        course_duration = parse_int(request.form.get("course_duration"))

        if not user_id or not school_id or course_id is None or year_of_study is None or semester is None:
            flash(
                "Please complete all required student fields before submitting.", "error")
            return redirect(url_for("register_student"))

        try:
            supabase.table("students").insert({
                "user_id": parse_int(user_id),
                "school_id": parse_int(school_id),
                "name": request.form.get("name"),
                "phone_number": request.form.get("phone_number"),
                "current_residential_address": request.form.get("current_residential_address"),
                "year_of_enrollment": year_of_enrollment,
                "course_duration": course_duration,
                "course_id": course_id,
                "year_of_study": year_of_study,
                "semester": semester
            }).execute()
        except Exception as e:
            flash(f"Failed to save student profile: {str(e)[:120]}", "error")
            return redirect(url_for("register_student"))

        student = None
        try:
            student = supabase.table("students").select("id,course_id,year_of_study,semester").eq(
                "user_id", parse_int(user_id)).order("id", desc=True).limit(1).execute().data
            student = student[0] if student else None
        except Exception:
            student = None

        if not student:
            flash(
                "Student profile saved but could not retrieve ID - modules may not be auto-assigned.", "warning")
            return redirect(url_for("login"))

        student_id = student["id"]

        # Automation: assign modules
        mappings = supabase.table("course_modules").select("*") \
            .eq("course_id", student["course_id"]) \
            .eq("year", student["year_of_study"]) \
            .eq("semester", student["semester"]) \
            .execute().data

        for mapping in mappings:
            supabase.table("student_modules").insert({
                "student_id": student_id,
                "module_id": mapping["module_id"]
            }).execute()

        flash("Student registered successfully! Modules auto-assigned.", "success")
        return redirect(url_for("login"))

    school = _school_from_form_or_session(session.get("school_id"))
    if school and not _school_allows_role(school, "student"):
        return _reject_disallowed_role("student", school)

    courses = _select_school_scoped(
        "courses", school_id=_parse_int(session.get("school_id")), order_by="name")

    # GET request -> render form with courses
    return render_template("register_student.html",
                           user_id=session.get("user_id"),
                           school_id=session.get("school_id"),
                           courses=courses
                           )


# @app.route("/select_course", methods=["GET", "POST"])
# def select_course():
    # Pull courses from Supabase
#    courses = supabase.table("courses").select("*").execute().data

#   if request.method == "POST":
#       # Store selected course in session
#       course_id = request.form["course_id"]
#       session["selected_course_id"] = course_id
#       return redirect(url_for("register_student"))

    # GET request -> show dropdown
#   return render_template("select_course.html", courses=courses)


# =========================================STUDENT MODULES=======================================
"""
@app.route("/register/student/modules", methods=["GET", "POST"])
def register_student_modules():
    if request.method == "POST":
        student_id = request.form.get("student_id")
        if not student_id:
            flash("Missing student ID", "error")
            return redirect(url_for("register_student"))

        selected_modules = request.form.getlist("modules")
        for module_id in selected_modules:
            supabase.table("student_modules").insert({
                "student_id": int(student_id),
                "module_id": int(module_id)
            }).execute()

        flash("Modules assigned successfully!", "success")
        return redirect(url_for("login"))

    # GET -> show available modules
    student_id = request.args.get("student_id")  # comes from redirect
    modules = supabase.table("modules").select("*").execute().data
    return render_template("student_modules.html",
                           modules=modules,
                           student_id=student_id)

"""
# -----------------------------------------------------------------------------------------------------------Lecturer-----------


@app.route("/register/lecturer", methods=["POST"])
def register_lecturer():
    school = _school_from_form_or_session(request.form.get("school_id"))
    if not _school_allows_role(school, "lecturer"):
        return _reject_disallowed_role("lecturer", school)

    supabase.table("lecturers").insert({
        "user_id": request.form["user_id"],
        "school_id": request.form["school_id"],
        "name": request.form["name"],
        "faculty": request.form["faculty"],
        "phone_number": request.form["phone_number"]
    }).execute()
    flash("Lecturer registered successfully!", "success")
    return redirect(url_for("login"))


# ------------------------------------------------------------------------------------------------------------Learner-----------

@app.route("/register/learner", methods=["GET", "POST"])
def register_learner():
    if request.method == "POST":
        school = _school_from_form_or_session(request.form.get("school_id"))
        if not _school_allows_role(school, "learner"):
            return _reject_disallowed_role("learner", school)

        learner = supabase.table("learners").insert({
            "user_id": request.form["user_id"],
            "school_id": request.form["school_id"],
            "classroom_id": None,
            "name": request.form["name"],
            "grade": request.form["grade"],
            "year_of_study": request.form["year_of_study"],
            "phone_number": request.form["phone_number"],
            "current_residential_address": request.form["current_residential_address"]
        }).execute()

        learner_resp = supabase.table("learners").select("id").eq(
            "user_id", request.form["user_id"]).order("id", desc=True).limit(1).execute()
        if not getattr(learner_resp, "data", None):
            flash("Learner profile saved but could not retrieve ID.", "warning")
            return redirect(url_for("login"))

        learner_id = learner_resp.data[0]["id"]

        flash("Learner registered successfully! Now select subjects.", "success")
        return redirect(url_for("register_learner_subjects", learner_id=learner_id))

    # GET request -> just render the learner details form
    school = _school_from_form_or_session(session.get("school_id"))
    if school and not _school_allows_role(school, "learner"):
        return _reject_disallowed_role("learner", school)

    return render_template("register_learner.html",
                           user_id=session.get("user_id"),
                           school_id=session.get("school_id"))


# ===============================================LEARNER SUBJECTS=================================================
@app.route("/register/learner/subjects", methods=["GET", "POST"])
def register_learner_subjects():
    if request.method == "POST":
        learner_id = request.form.get("learner_id")
        if not learner_id:
            flash("Missing learner ID", "error")
            return redirect(url_for("register_learner"))

        selected_subjects = request.form.getlist("subjects")
        for subject_id in selected_subjects:
            supabase.table("learner_subjects").insert({
                "learner_id": int(learner_id),
                "subject_id": int(subject_id)
            }).execute()

        flash("Subjects assigned successfully!", "success")
        return redirect(url_for("login"))

    # GET -> show available subjects
    learner_id = request.args.get("learner_id")  # comes from redirect
    subjects = supabase.table("subjects").select("*").execute().data
    return render_template("learner_subjects.html",
                           subjects=subjects,
                           learner_id=learner_id)


# ----------------------------------------------------------------------------------------------------------------Parent-------------
@app.route("/register/parent", methods=["POST"])
def register_parent():
    school = _school_from_form_or_session(request.form.get("school_id"))
    if not _school_allows_role(school, "parent"):
        return _reject_disallowed_role("parent", school)

    supabase.table("parents").insert({
        "user_id": request.form["user_id"],
        "school_id": request.form["school_id"],
        "name": request.form["name"],
        "subscription_status": request.form["subscription_status"]
    }).execute()
    flash("Parent registered successfully!", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------------------------------------------- Staff-------------
@app.route("/register/staff", methods=["POST"])
def register_staff():
    school = _school_from_form_or_session(request.form.get("school_id"))
    if not _school_allows_role(school, "staff"):
        return _reject_disallowed_role("staff", school)

    user_id = request.form.get("user_id")
    school_id = request.form.get("school_id")

    try:
        supabase.table("staff").insert({
            "user_id": int(user_id),
            "school_id": int(school_id) if school_id else None,
            "name": request.form["name"],
            "department": request.form["department"],
            "phone_number": request.form["phone_number"]
        }).execute()
    except Exception as e:
        if _is_missing_staff_schema(e):
            try:
                if user_id:
                    supabase.table("users").delete().eq(
                        "id", int(user_id)).execute()
            except Exception:
                pass
            flash(
                "Database staff schema is missing or outdated. Run schema_staff.sql in Supabase SQL Editor, then try staff registration again.",
                "error",
            )
            return redirect(url_for("register", school_id=school.get("id")) if school else url_for("login"))

        flash(f"Staff registration failed: {str(e)[:120]}", "error")
        return redirect(url_for("register", school_id=school.get("id")) if school else url_for("login"))

    flash("Staff registered successfully!", "success")
    return redirect(url_for("login"))


@app.route("/school_admin/register", methods=["GET"])
def register_school_admin_init():
    flash("Public school admin registration has been disabled. Use global admin user management.", "error")
    return redirect(url_for("login"))


@app.route("/school_admin/register/create", methods=["POST"])
def register_school_admin_handler():
    flash("Public school admin registration has been disabled. Use global admin user management.", "error")
    return redirect(url_for("login"))


@app.route("/register/school_admin", methods=["POST"])
def register_school_admin():
    gate = _require_global_admin()
    if gate:
        return gate

    user_id = request.form.get("user_id")
    school_id = request.form.get("school_id")
    name = (request.form.get("name") or "").strip()
    phone_number = (request.form.get("phone_number") or "").strip()

    if not user_id or not school_id or not name:
        flash("Please provide name and valid registration details.", "error")
        return redirect(url_for("login"))

    try:
        supabase.table("school_admins").insert({
            "user_id": int(user_id),
            "school_id": int(school_id),
            "name": name,
            "phone_number": phone_number or None,
        }).execute()
    except Exception as e:
        if _is_missing_school_admins_table(e):
            flash(
                "Database table 'school_admins' is missing. Run schema_school_admin.sql in Supabase SQL Editor, then try again.",
                "error",
            )
            return redirect(url_for("register_school_admin_init"))
        flash(
            f"Failed to register school admin profile: {str(e)[:120]}", "error")
        return redirect(url_for("login"))

    flash("School Admin registered successfully! Please login.", "success")
    return redirect(url_for("login"))


@app.route("/success")
def success():
    return "Registration successful!"

# ---------------------------------------------------------------------------------------------------------------- LOGIN ----------


@app.route("/login", methods=["GET", "POST"])
@app.route("/login/<school_ref>", methods=["GET", "POST"])
def login(school_ref=None):
    if request.method == "POST":
        requested_scope = request.form.get(
            "school_ref") or request.form.get("school_id")
    else:
        requested_scope = school_ref or request.args.get(
            "school_ref") or request.args.get("school_id")

    requested_school_id = _decode_school_ref(requested_scope)
    requested_school = _get_school_record(
        requested_school_id) if requested_school_id is not None else None
    requested_school_ref = _encode_school_ref(requested_school_id)

    if request.method == "POST":
        email = (request.form["email"] or "").strip().lower()
        password = request.form["password"]

        # ------------------------------------------------------Fetch user by email
        response = supabase.table("users").select(
            "*").eq("email", email).execute()
        if not response.data:
            flash("Invalid email or password", "error")
            return redirect(_school_login_url(requested_school_id))

        user = response.data[0]

        # Verify password
        if check_password_hash(user["password"], password):
            auth_result = _resolve_post_auth_redirect(
                user,
                requested_school_id=requested_school_id,
                requested_school=requested_school,
            )
            if auth_result.get("ok"):
                return redirect(auth_result.get("redirect_url"))
            flash(auth_result.get("error") or "Login failed.", "error")
            return redirect(_school_login_url(requested_school_id))
        else:
            flash("Invalid email or password", "error")
            return redirect(_school_login_url(requested_school_id))

    return render_template(
        "login.html",
        school=requested_school,
        school_id=requested_school_id,
        school_ref=requested_school_ref,
        google_client_id=GOOGLE_CLIENT_ID,
    )


@app.route("/auth/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        method = (request.form.get("method") or "email").strip().lower()
        identifier = (request.form.get("identifier") or "").strip()
        if method not in {"email", "phone"}:
            flash("Select email or phone for verification.", "error")
            return redirect(url_for("forgot_password"))
        if not identifier:
            flash("Enter your email or phone number.", "error")
            return redirect(url_for("forgot_password"))

        user_row, destination = _lookup_user_by_channel(identifier, method)
        # Avoid account enumeration in public responses.
        generic_message = "If an account exists, a verification code has been sent."
        if not user_row:
            flash(generic_message, "success")
            return redirect(url_for("reset_password_verify"))

        code = f"{uuid.uuid4().int % 1000000:06d}"
        try:
            _store_auth_verification_code(
                user_id=user_row.get("id"),
                purpose="password_reset",
                channel=method,
                destination=destination,
                code=code,
            )
        except Exception as error:
            if _auth_codes_table_missing(error):
                flash(
                    "Auth verification schema is missing. Run schema_auth_security.sql in Supabase SQL Editor.", "error")
            else:
                flash("Could not issue verification code. Please try again.", "error")
            return redirect(url_for("forgot_password"))

        if method == "email":
            sent, detail = _send_email_notification(
                destination,
                "Smart School Hub password reset code",
                (
                    "Use this verification code to reset your password: "
                    f"{code}\n\n"
                    f"The code expires in {AUTH_CODE_TTL_MINUTES} minutes."
                ),
            )
        else:
            sent, detail = _send_sms_notification(
                destination,
                f"Smart School Hub reset code: {code}. Expires in {AUTH_CODE_TTL_MINUTES} minutes.",
            )
        if not sent:
            app.logger.warning(
                "Verification delivery failed (%s): %s", method, detail)
            flash(_friendly_verification_delivery_error(method, detail), "error")
            return redirect(url_for("forgot_password"))

        session["password_reset_user_id"] = user_row.get("id")
        session["password_reset_channel"] = method
        session["password_reset_masked_destination"] = _mask_destination(
            method, destination)
        flash(generic_message, "success")
        return redirect(url_for("reset_password_verify"))

    return render_template("forgot_password.html", auth_code_ttl_minutes=AUTH_CODE_TTL_MINUTES)


@app.route("/auth/reset-password/verify", methods=["GET", "POST"])
def reset_password_verify():
    reset_user_id = _parse_int(session.get("password_reset_user_id"))
    reset_channel = (session.get("password_reset_channel")
                     or "").strip().lower()

    if request.method == "POST":
        if reset_user_id is None or reset_channel not in {"email", "phone"}:
            flash("Reset session expired. Start password reset again.", "error")
            return redirect(url_for("forgot_password"))

        code = (request.form.get("verification_code") or "").strip()
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not code or not code.isdigit() or len(code) != 6:
            flash("Enter the 6-digit verification code.", "error")
            return redirect(url_for("reset_password_verify"))
        password_error = _validate_password_strength(new_password)
        if password_error:
            flash(password_error, "error")
            return redirect(url_for("reset_password_verify"))
        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_password_verify"))

        latest_code = _latest_auth_verification_code(
            user_id=reset_user_id,
            purpose="password_reset",
            channel=reset_channel,
        )
        if not latest_code or latest_code.get("code_hash") != _auth_code_hash(code):
            flash("Invalid or expired verification code.", "error")
            return redirect(url_for("reset_password_verify"))

        try:
            supabase.table("users").update({
                "password": generate_password_hash(new_password)
            }).eq("id", reset_user_id).execute()
        except Exception:
            flash("Could not reset password. Please try again.", "error")
            return redirect(url_for("reset_password_verify"))

        _consume_auth_verification_code(latest_code.get("id"))
        session.pop("password_reset_user_id", None)
        session.pop("password_reset_channel", None)
        session.pop("password_reset_masked_destination", None)
        flash("Password reset successful. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template(
        "reset_password_verify.html",
        masked_destination=session.get("password_reset_masked_destination"),
        channel=reset_channel,
        auth_code_ttl_minutes=AUTH_CODE_TTL_MINUTES,
    )


@app.route("/auth/google-token-login", methods=["POST"])
def google_token_login():
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}

    requested_school_id = _decode_school_ref(
        payload.get("school_ref") or payload.get("school_id")
    )
    requested_school = _get_school_record(
        requested_school_id) if requested_school_id is not None else None
    claims, error_message = _verify_google_id_token(payload.get("credential"))
    if error_message:
        return jsonify({"error": error_message}), 400

    email = (claims.get("email") or "").strip().lower()
    user_rows = supabase.table("users").select(
        "*").eq("email", email).limit(1).execute().data or []

    if not user_rows:
        session["google_signup_claims"] = {
            "email": email,
            "name": (claims.get("name") or "").strip(),
            "sub": (claims.get("sub") or "").strip(),
        }
        return jsonify({"ok": True, "need_signup": True, "redirect": url_for("google_complete_signup")})

    auth_result = _resolve_post_auth_redirect(
        user_rows[0],
        requested_school_id=requested_school_id,
        requested_school=requested_school,
    )
    if not auth_result.get("ok"):
        return jsonify({"error": auth_result.get("error") or "Google sign-in failed."}), 400
    return jsonify({"ok": True, "redirect": auth_result.get("redirect_url")})


@app.route("/auth/google/complete-signup", methods=["GET", "POST"])
def google_complete_signup():
    claims = session.get("google_signup_claims") or {}
    if not claims.get("email"):
        flash("Google sign-up session expired. Please sign in with Google again.", "error")
        return redirect(url_for("login"))

    schools = _safe_select_table(
        "schools", "id,name,school_type", order_by="name")

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        role = _normalize_role(request.form.get("role"))
        school_id = _parse_int(request.form.get("school_id"))
        school = _get_school_record(
            school_id) if school_id is not None else None

        if not username or not role or not school:
            flash("Username, role, and school are required.", "error")
            return redirect(url_for("google_complete_signup"))
        if role in {"admin", "school_admin"}:
            flash("This signup path does not allow admin roles.", "error")
            return redirect(url_for("google_complete_signup"))
        if not _school_allows_role(school, role):
            return _reject_disallowed_role(role, school)

        conflicts = _find_user_identity_conflicts(
            email=claims.get("email"), username=username)
        if conflicts.get("email"):
            flash(
                "An account with this Google email already exists. Use login instead.", "error")
            return redirect(url_for("login"))
        if conflicts.get("username"):
            flash("Username is already taken. Choose another.", "error")
            return redirect(url_for("google_complete_signup"))

        random_password_hash = generate_password_hash(uuid.uuid4().hex)
        try:
            response = supabase.table("users").insert({
                "username": username,
                "email": claims.get("email"),
                "password": random_password_hash,
                "role": role,
            }).execute()
        except Exception as error:
            if _is_duplicate_user_identity_error(error):
                flash(
                    "Registration failed because this account identity already exists.", "error")
            else:
                flash("Google sign-up failed. Please try again.", "error")
            return redirect(url_for("google_complete_signup"))

        if not getattr(response, "data", None):
            flash("Google sign-up failed. Please try again.", "error")
            return redirect(url_for("google_complete_signup"))

        user_id = response.data[0].get("id")
        session["google_signup_claims"] = None
        session["user_id"] = user_id
        session["school_id"] = school_id
        session["role"] = role
        session["school_type"] = school.get("school_type")
        session["username"] = username
        session["user_email"] = claims.get("email")
        return _render_role_registration_step(role, user_id=user_id, school_id=school_id)

    school_role_map = {}
    for school in schools:
        school_role_map[school.get("id")] = _role_options_for_school_type(
            school.get("school_type"))

    return render_template(
        "google_complete_signup.html",
        google_claims=claims,
        schools=schools,
        school_role_map=school_role_map,
    )


@app.route("/school/<signed_id:school_id>/admin")
def school_admin_dashboard(school_id):
    if session.get("role") != "school_admin" or int(session.get("school_id") or 0) != school_id:
        flash("School admin access required.", "error")
        return redirect(url_for("login"))

    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))

    is_tertiary = (school.get("school_type") or "").lower() == "tertiary"

    # Summary counts for dashboard cards
    def _count(table, **filters):
        try:
            q = supabase.table(table).select(
                "id", count="exact").eq("school_id", school_id)
            for col, val in filters.items():
                q = q.eq(col, val)
            resp = q.execute()
            return resp.count if hasattr(resp, "count") and resp.count is not None else len(resp.data or [])
        except Exception:
            return 0

    classroom_count = 0
    try:
        raw_classrooms = supabase.table("classrooms").select(
            "id,teacher_id,lecturer_id").eq("school_id", school_id).execute().data or []
        if is_tertiary:
            classroom_count = len([c for c in raw_classrooms if c.get(
                "lecturer_id") and not c.get("teacher_id")])
        else:
            classroom_count = len([c for c in raw_classrooms if c.get(
                "teacher_id") and not c.get("lecturer_id")])
    except Exception:
        classroom_count = 0

    stats = {
        "students":   _count("students") if is_tertiary else 0,
        "learners":   _count("learners") if not is_tertiary else 0,
        "teachers":   _count("teachers") if not is_tertiary else 0,
        "lecturers":  _count("lecturers") if is_tertiary else 0,
        "classrooms": classroom_count,
    }

    portal_settings = {
        "marks_open": _to_bool(school.get("portal_marks_open"), default=True),
        "reports_open": _to_bool(school.get("portal_reports_open"), default=True),
    }

    return render_template("school_admin_dashboard.html", school=school, stats=stats, is_tertiary=is_tertiary, portal_settings=portal_settings)


# ==========================================================================================SCHOOL ADMIN - MANAGE ENROLLEES=======

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


@app.route("/school/<signed_id:school_id>/admin/students", methods=["GET", "POST"])
def admin_manage_students(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    is_tertiary = (school.get("school_type") or "").lower() == "tertiary"
    table = "students" if is_tertiary else "learners"

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Name is required.", "error")
                return redirect(url_for("admin_manage_students", school_id=school_id))
            payload = {
                "name": name,
                "school_id": school_id,
                "user_id": None,   # no account required - admin-registered
            }
            if is_tertiary:
                payload["year_of_study"] = request.form.get(
                    "year_of_study") or None
                payload["semester"] = request.form.get("semester") or None
                payload["course_id"] = int(request.form.get("course_id")) if (
                    request.form.get("course_id") or "").strip().isdigit() else None
                payload["year_of_enrollment"] = request.form.get(
                    "year_of_enrollment") or None
                payload["phone_number"] = request.form.get(
                    "phone_number") or None
            else:
                payload["grade"] = request.form.get("grade") or None
                payload["year_of_study"] = request.form.get(
                    "year_of_study") or None
                payload["phone_number"] = request.form.get(
                    "phone_number") or None
            try:
                supabase.table(table).insert(payload).execute()
                flash(
                    f"{'Student' if is_tertiary else 'Learner'} '{name}' added successfully.", "success")
            except Exception as e:
                flash(f"Failed to add record: {str(e)[:120]}", "error")

        elif action == "delete":
            record_id_raw = request.form.get("record_id", "").strip()
            if not record_id_raw.isdigit():
                flash("Invalid record.", "error")
            else:
                try:
                    supabase.table(table).delete().eq("id", int(record_id_raw)).eq(
                        "school_id", school_id).execute()
                    flash("Record deleted.", "success")
                except Exception as e:
                    flash(f"Failed to delete: {str(e)[:80]}", "error")

        return redirect(url_for("admin_manage_students", school_id=school_id))

    # GET - load list
    enrollees = []
    try:
        enrollees = supabase.table(table).select(
            "*").eq("school_id", school_id).order("name").execute().data or []
    except Exception:
        enrollees = []

    courses = []
    if is_tertiary:
        try:
            courses = _select_school_scoped(
                "courses", school_id=school_id, order_by="name")
        except Exception:
            pass

    return render_template(
        "admin_manage_students.html",
        school=school,
        enrollees=enrollees,
        is_tertiary=is_tertiary,
        courses=courses,
        school_id=school_id,
    )


@app.route("/school/<signed_id:school_id>/admin/classrooms", methods=["GET", "POST"])
def admin_manage_classrooms(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    is_tertiary = (school.get("school_type") or "").lower() == "tertiary"

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            cid = request.form.get("classroom_id", "").strip()
            if cid.isdigit():
                try:
                    supabase.table("classrooms").delete().eq(
                        "id", int(cid)).eq("school_id", school_id).execute()
                    flash("Classroom deleted.", "success")
                except Exception as e:
                    flash(f"Failed: {str(e)[:80]}", "error")
        return redirect(url_for("admin_manage_classrooms", school_id=school_id))

    # GET
    classrooms = []
    try:
        classrooms = supabase.table("classrooms").select(
            "*").eq("school_id", school_id).order("name").execute().data or []
    except Exception:
        classrooms = []

    # Strictly show only role-matching classrooms for the school type.
    if is_tertiary:
        classrooms = [c for c in classrooms if c.get(
            "lecturer_id") and not c.get("teacher_id")]
    else:
        classrooms = [c for c in classrooms if c.get(
            "teacher_id") and not c.get("lecturer_id")]

    # Annotate each classroom with member count
    for cls in classrooms:
        try:
            resp = supabase.table("classroom_members").select(
                "id", count="exact").eq("classroom_id", cls["id"]).execute()
            cls["_member_count"] = resp.count if hasattr(
                resp, "count") and resp.count is not None else len(resp.data or [])
        except Exception:
            cls["_member_count"] = 0

    return render_template(
        "admin_manage_classrooms.html",
        school=school,
        classrooms=classrooms,
        is_tertiary=is_tertiary,
        school_id=school_id,
    )


@app.route("/school/<signed_id:school_id>/admin/staff", methods=["GET"])
def admin_manage_staff(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    is_tertiary = (school.get("school_type") or "").lower() == "tertiary"
    teacher_table = "lecturers" if is_tertiary else "teachers"

    staff = []
    try:
        staff = supabase.table(teacher_table).select(
            "*").eq("school_id", school_id).order("name").execute().data or []
    except Exception:
        staff = []

    return render_template(
        "admin_manage_staff.html",
        school=school,
        staff=staff,
        is_tertiary=is_tertiary,
        school_id=school_id,
    )


@app.route("/school/<signed_id:school_id>/admin/subjects", methods=["GET", "POST"])
def admin_manage_subjects(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    is_tertiary = (school.get("school_type")
                   or "").strip().lower() == "tertiary"
    if is_tertiary:
        flash("Subjects are not used for tertiary schools. Use Courses/Modules instead.", "info")
        return redirect(url_for("school_admin_dashboard", school_id=school_id))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        try:
            if action == "add":
                name = (request.form.get("name") or "").strip()
                code = (request.form.get("code") or "").strip() or None
                if not name:
                    flash("Subject name is required.", "error")
                else:
                    _insert_school_scoped(
                        "subjects", {"name": name, "code": code}, school_id=school_id)
                    flash("Subject added.", "success")
            elif action == "delete":
                subject_id = _parse_int(request.form.get("subject_id"))
                if subject_id is None:
                    flash("Invalid subject.", "error")
                else:
                    try:
                        supabase.table("subjects").delete().eq(
                            "id", subject_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("subjects").delete().eq(
                                "id", subject_id).execute()
                        else:
                            raise
                    flash("Subject deleted.", "success")
            elif action == "edit":
                subject_id = _parse_int(request.form.get("subject_id"))
                name = (request.form.get("name") or "").strip()
                code = (request.form.get("code") or "").strip() or None
                if subject_id is None or not name:
                    flash("Subject name is required.", "error")
                else:
                    try:
                        supabase.table("subjects").update({
                            "school_id": school_id,
                            "name": name,
                            "code": code,
                        }).eq("id", subject_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("subjects").update({
                                "name": name,
                                "code": code,
                            }).eq("id", subject_id).execute()
                        else:
                            raise
                    flash("Subject updated.", "success")
        except Exception as e:
            flash(f"Subject action failed: {str(e)[:120]}", "error")

        return redirect(url_for("admin_manage_subjects", school_id=school_id))

    subjects = _select_school_scoped(
        "subjects", school_id=school_id, order_by="name")
    return render_template("admin_manage_subjects.html", school=school, school_id=school_id, subjects=subjects)


def _require_school_admin_tertiary(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    if (school or {}).get("school_type", "").strip().lower() != "tertiary":
        flash("This section is available for tertiary schools only.", "error")
        return redirect(url_for("school_admin_dashboard", school_id=school_id))
    return None


@app.route("/school/<signed_id:school_id>/admin/courses", methods=["GET", "POST"])
def school_admin_courses(school_id):
    gate = _require_school_admin_tertiary(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        try:
            if action == "add":
                _insert_school_scoped("courses", {
                    "name": (request.form.get("name") or "").strip(),
                    "code": (request.form.get("code") or "").strip(),
                }, school_id=school_id)
                flash("Course added.", "success")
            elif action == "edit":
                course_id = _parse_int(request.form.get("course_id"))
                if course_id is None:
                    flash("Invalid course.", "error")
                else:
                    try:
                        supabase.table("courses").update({
                            "school_id": school_id,
                            "name": (request.form.get("name") or "").strip(),
                            "code": (request.form.get("code") or "").strip(),
                        }).eq("id", course_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("courses").update({
                                "name": (request.form.get("name") or "").strip(),
                                "code": (request.form.get("code") or "").strip(),
                            }).eq("id", course_id).execute()
                        else:
                            raise
                    flash("Course updated.", "success")
            elif action == "delete":
                course_id = _parse_int(request.form.get("course_id"))
                if course_id is not None:
                    try:
                        supabase.table("courses").delete().eq(
                            "id", course_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("courses").delete().eq(
                                "id", course_id).execute()
                        else:
                            raise
                    flash("Course deleted.", "success")
        except Exception as e:
            flash(f"Course action failed: {str(e)[:120]}", "error")

        return redirect(url_for("school_admin_courses", school_id=school_id))

    courses = _select_school_scoped(
        "courses", school_id=school_id, order_by="name")
    return render_template("admin_manage_courses.html", school=school, school_id=school_id, courses=courses)


@app.route("/school/<signed_id:school_id>/admin/modules", methods=["GET", "POST"])
def school_admin_modules(school_id):
    gate = _require_school_admin_tertiary(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        try:
            if action == "add":
                _insert_school_scoped("modules", {
                    "name": (request.form.get("name") or "").strip(),
                    "module_code": (request.form.get("module_code") or "").strip(),
                    "description": (request.form.get("description") or "").strip() or None,
                    "credits": _parse_int(request.form.get("credits")),
                    "faculty": (request.form.get("faculty") or "").strip() or None,
                }, school_id=school_id)
                flash("Module added.", "success")
            elif action == "edit":
                module_id = _parse_int(request.form.get("module_id"))
                if module_id is None:
                    flash("Invalid module.", "error")
                else:
                    update_payload = {
                        "school_id": school_id,
                        "name": (request.form.get("name") or "").strip(),
                        "module_code": (request.form.get("module_code") or "").strip(),
                        "description": (request.form.get("description") or "").strip() or None,
                        "credits": _parse_int(request.form.get("credits")),
                        "faculty": (request.form.get("faculty") or "").strip() or None,
                    }
                    try:
                        supabase.table("modules").update(update_payload).eq(
                            "id", module_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            update_payload.pop("school_id", None)
                            supabase.table("modules").update(
                                update_payload).eq("id", module_id).execute()
                        else:
                            raise
                    flash("Module updated.", "success")
            elif action == "delete":
                module_id = _parse_int(request.form.get("module_id"))
                if module_id is not None:
                    try:
                        supabase.table("modules").delete().eq(
                            "id", module_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("modules").delete().eq(
                                "id", module_id).execute()
                        else:
                            raise
                    flash("Module deleted.", "success")
        except Exception as e:
            flash(f"Module action failed: {str(e)[:120]}", "error")

        return redirect(url_for("school_admin_modules", school_id=school_id))

    modules = _select_school_scoped(
        "modules", school_id=school_id, order_by="name")
    return render_template("admin_manage_modules.html", school=school, school_id=school_id, modules=modules)


@app.route("/school/<signed_id:school_id>/admin/curriculum", methods=["GET", "POST"])
def school_admin_curriculum(school_id):
    gate = _require_school_admin_tertiary(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        try:
            if action == "add":
                _insert_school_scoped("course_modules", {
                    "course_id": _parse_int(request.form.get("course_id")),
                    "module_id": _parse_int(request.form.get("module_id")),
                    "year": _parse_int(request.form.get("year")),
                    "semester": _parse_int(request.form.get("semester")),
                }, school_id=school_id)
                flash("Mapping added.", "success")
            elif action == "edit":
                mapping_id = _parse_int(request.form.get("mapping_id"))
                if mapping_id is None:
                    flash("Invalid mapping.", "error")
                else:
                    update_payload = {
                        "school_id": school_id,
                        "course_id": _parse_int(request.form.get("course_id")),
                        "module_id": _parse_int(request.form.get("module_id")),
                        "year": _parse_int(request.form.get("year")),
                        "semester": _parse_int(request.form.get("semester")),
                    }
                    try:
                        supabase.table("course_modules").update(update_payload).eq(
                            "id", mapping_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            update_payload.pop("school_id", None)
                            supabase.table("course_modules").update(
                                update_payload).eq("id", mapping_id).execute()
                        else:
                            raise
                    flash("Mapping updated.", "success")
            elif action == "delete":
                mapping_id = _parse_int(request.form.get("mapping_id"))
                if mapping_id is not None:
                    try:
                        supabase.table("course_modules").delete().eq(
                            "id", mapping_id).eq("school_id", school_id).execute()
                    except Exception as e:
                        if _is_missing_school_column_error(e):
                            supabase.table("course_modules").delete().eq(
                                "id", mapping_id).execute()
                        else:
                            raise
                    flash("Mapping deleted.", "success")
        except Exception as e:
            flash(f"Mapping action failed: {str(e)[:120]}", "error")

        return redirect(url_for("school_admin_curriculum", school_id=school_id))

    courses = _select_school_scoped(
        "courses", school_id=school_id, order_by="name")
    modules = _select_school_scoped(
        "modules", school_id=school_id, order_by="name")
    mappings = _select_school_scoped(
        "course_modules", school_id=school_id, order_by="id")
    return render_template(
        "admin_manage_curriculum.html",
        school=school,
        school_id=school_id,
        courses=courses,
        modules=modules,
        mappings=mappings,
    )


@app.route("/school/<signed_id:school_id>/admin/portal-settings", methods=["POST"])
def admin_update_portal_settings(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    marks_open = (request.form.get("portal_marks_open")
                  or "").strip() in {"1", "true", "on", "yes"}
    reports_open = (request.form.get("portal_reports_open")
                    or "").strip() in {"1", "true", "on", "yes"}

    desired_values = {
        "portal_marks_open": marks_open,
        "portal_reports_open": reports_open,
    }

    try:
        supabase.table("schools").update(
            desired_values).eq("id", school_id).execute()
        flash("Portal section settings updated.", "success")
    except Exception as e:
        if _is_missing_school_column_error(e):
            updated_columns = []
            for column_name, column_value in desired_values.items():
                try:
                    supabase.table("schools").update(
                        {column_name: column_value}
                    ).eq("id", school_id).execute()
                    updated_columns.append(column_name)
                except Exception as single_error:
                    if not _is_missing_school_column_error(single_error):
                        app.logger.warning(
                            "Portal settings update failed for school %s (%s): %s",
                            school_id,
                            column_name,
                            single_error,
                        )

            if updated_columns:
                flash(
                    "Portal settings were partially updated. Run schema_portal_results.sql to enable all toggles.",
                    "warning",
                )
            else:
                flash(
                    "Portal settings columns are missing in the schools table. Run schema_portal_results.sql, then try again.",
                    "error",
                )
        else:
            flash(f"Could not update portal settings: {str(e)[:120]}", "error")

    return redirect(url_for("school_admin_dashboard", school_id=school_id))


@app.route("/school/<signed_id:school_id>/admin/announcements", methods=["GET", "POST"])
def admin_manage_announcements(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            title = (request.form.get("title") or "").strip()
            content = (request.form.get("content") or "").strip()
            alert_level = (request.form.get("alert_level")
                           or "normal").strip().lower()
            expires_at = (request.form.get("expires_at") or "").strip() or None
            if not title or not content:
                flash("Title and content are required.", "error")
                return redirect(url_for("admin_manage_announcements", school_id=school_id))

            if alert_level not in {"normal", "high"}:
                flash("Alert level must be normal or high.", "error")
                return redirect(url_for("admin_manage_announcements", school_id=school_id))

            if expires_at:
                expiry_date = _parse_iso_date(expires_at)
                if not expiry_date:
                    flash("Expiry date is invalid.", "error")
                    return redirect(url_for("admin_manage_announcements", school_id=school_id))
                if expiry_date < datetime.utcnow().date():
                    flash("Expiry date cannot be in the past.", "error")
                    return redirect(url_for("admin_manage_announcements", school_id=school_id))

            try:
                supabase.table("announcements").insert({
                    "school_id": school_id,
                    "title": title,
                    "content": content,
                    "alert_level": alert_level,
                    "expires_at": expires_at,
                    "created_by": _parse_int(session.get("school_admin_id")),
                    "created_at": None  # Auto-timestamp on backend
                }).execute()

                school_name = (school or {}).get("name") or "School"
                message = f"{title}: {content[:240]}"
                _notify_school_users(
                    school_id=school_id,
                    title=f"[{school_name}] {title}",
                    message=message,
                    notification_type="announcement",
                    priority="high" if alert_level == "high" else "normal",
                    send_email=True,
                    send_sms=(alert_level == "high"),
                    meta={
                        "event": "announcement_created",
                        "school_id": school_id,
                        "alert_level": alert_level,
                        "expires_at": expires_at,
                    },
                )

                flash(
                    f"Announcement '{title}' created successfully.", "success")
            except Exception as e:
                flash(
                    f"Failed to create announcement: {str(e)[:120]}", "error")

        elif action == "delete":
            ann_id = request.form.get("announcement_id", "").strip()
            if ann_id.isdigit():
                try:
                    supabase.table("announcements").delete().eq(
                        "id", int(ann_id)).eq("school_id", school_id).execute()
                    flash("Announcement deleted.", "success")
                except Exception as e:
                    flash(f"Failed to delete: {str(e)[:80]}", "error")

        return redirect(url_for("admin_manage_announcements", school_id=school_id))

    # GET - load list
    announcements = []
    try:
        announcements = supabase.table("announcements").select(
            "*").eq("school_id", school_id).order("created_at", desc=True).execute().data or []
    except Exception:
        announcements = []

    return render_template(
        "admin_manage_announcements.html",
        school=school,
        announcements=announcements,
        school_id=school_id,
    )


@app.route("/school/<signed_id:school_id>/admin/events", methods=["GET", "POST"])
def admin_manage_events(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            title = (request.form.get("title") or "").strip()
            event_date = request.form.get("event_date", "").strip()
            description = (request.form.get("description") or "").strip()

            if not title or not event_date:
                flash("Title and date are required.", "error")
                return redirect(url_for("admin_manage_events", school_id=school_id))

            try:
                supabase.table("events").insert({
                    "school_id": school_id,
                    "title": title,
                    "event_date": event_date,
                    "description": description or None,
                    "created_by": _parse_int(session.get("school_admin_id")),
                    "created_at": None  # Auto-timestamp on backend
                }).execute()
                flash(f"Event '{title}' created successfully.", "success")
            except Exception as e:
                flash(f"Failed to create event: {str(e)[:120]}", "error")

        elif action == "delete":
            event_id = request.form.get("event_id", "").strip()
            if event_id.isdigit():
                try:
                    supabase.table("events").delete().eq(
                        "id", int(event_id)).eq("school_id", school_id).execute()
                    flash("Event deleted.", "success")
                except Exception as e:
                    flash(f"Failed to delete: {str(e)[:80]}", "error")

        return redirect(url_for("admin_manage_events", school_id=school_id))

    # GET - load list
    events = []
    try:
        events = supabase.table("events").select(
            "*").eq("school_id", school_id).order("event_date", desc=False).execute().data or []
    except Exception:
        events = []

    return render_template(
        "admin_manage_events.html",
        school=school,
        events=events,
        school_id=school_id,
    )


@app.route("/profile")
def user_profile():
    if not session.get("user_id") and not session.get("teacher_id") and not session.get("lecturer_id"):
        flash("Please log in to view your profile.", "error")
        return redirect(url_for("login"))

    # Get user information based on role
    user_info = {}
    profile_data = {}
    profile_role = session.get("role")

    if session.get("user_id"):
        # Student or learner
        user_resp = supabase.table("users").select(
            "*").eq("id", session["user_id"]).execute()
        if user_resp.data:
            user_info = user_resp.data[0]

            if user_info["role"] == "student":
                profile_resp = supabase.table("students").select(
                    "*").eq("user_id", session["user_id"]).execute()
                if profile_resp.data:
                    profile_data = profile_resp.data[0]
                    profile_data["role_display"] = "Student"
                    profile_role = "student"
                    # Fetch course name if course_id exists
                    if profile_data.get("course_id"):
                        course_resp = supabase.table("courses").select(
                            "name").eq("id", profile_data["course_id"]).execute()
                        if course_resp.data:
                            profile_data["course_name"] = course_resp.data[0]["name"]
            elif user_info["role"] == "learner":
                profile_resp = supabase.table("learners").select(
                    "*").eq("user_id", session["user_id"]).execute()
                if profile_resp.data:
                    profile_data = profile_resp.data[0]
                    profile_data["role_display"] = "Learner"
                    profile_role = "learner"
            elif user_info["role"] == "parent":
                profile_resp = supabase.table("parents").select(
                    "*").eq("user_id", session["user_id"]).execute()
                if profile_resp.data:
                    profile_data = profile_resp.data[0]
                    profile_data["role_display"] = "Parent"
                    profile_role = "parent"
            elif user_info["role"] == "staff":
                profile_resp = supabase.table("staff").select(
                    "*").eq("user_id", session["user_id"]).execute()
                if profile_resp.data:
                    profile_data = profile_resp.data[0]
                    profile_data["role_display"] = "Staff"
                    profile_role = "staff"
    elif session.get("teacher_id"):
        # Teacher
        profile_resp = supabase.table("teachers").select(
            "*").eq("id", session["teacher_id"]).execute()
        if profile_resp.data:
            profile_data = profile_resp.data[0]
            profile_data["role_display"] = "Teacher"
            profile_role = "teacher"
            # Get user account info
            user_resp = supabase.table("users").select("username, email, role").eq(
                "id", profile_data["user_id"]).execute()
            if user_resp.data:
                user_info = user_resp.data[0]
                profile_data["email"] = user_info.get("email")
    elif session.get("lecturer_id"):
        # Lecturer
        profile_resp = supabase.table("lecturers").select(
            "*").eq("id", session["lecturer_id"]).execute()
        if profile_resp.data:
            profile_data = profile_resp.data[0]
            profile_data["role_display"] = "Lecturer"
            profile_role = "lecturer"
            # Get user account info
            user_resp = supabase.table("users").select("username, email, role").eq(
                "id", profile_data["user_id"]).execute()
            if user_resp.data:
                user_info = user_resp.data[0]
                profile_data["email"] = user_info.get("email")

    # Optional school name lookup for roles with school_id
    if profile_data.get("school_id"):
        try:
            school_resp = supabase.table("schools").select("name").eq(
                "id", profile_data["school_id"]).execute()
            if school_resp.data:
                profile_data["school_name"] = school_resp.data[0].get("name")
        except Exception:
            pass

    return render_template(
        "my_profile.html",
        user_info=user_info,
        profile_data=profile_data,
        profile_role=profile_role
    )

# ------------------------------------------------------------------------------------------ LOGOUT ----------------


@app.route("/logout")
def logout():
    school_id = session.get("school_id")
    session.clear()
    if school_id:
        return redirect(url_for("school_index", school_id=school_id))
    return redirect(url_for("schools_directory"))  # fallback neutral index


# =========================================================================================LECTURER DASHBOARD=============
@app.route("/lecturer/dashboard/<school_ref:school_id>")
def lecturer_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"lecturer"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    # Pull classrooms for this school
    classrooms = supabase.table("classrooms").select(
        "*").eq("school_id", school_id).execute().data

    # Pull virtual calls for all classrooms in this school
    dashboard_virtual_calls = _load_dashboard_virtual_calls(
        classrooms,
        actor_id=str(session.get("user_id") or session.get(
            "teacher_id") or session.get("lecturer_id") or ""),
    )

    return render_template(
        "lecturer_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events,
        classrooms=classrooms,
        dashboard_virtual_calls=dashboard_virtual_calls,
        instructor_ai_enabled=INSTRUCTOR_AI_PREMIUM_ENABLED,
    )
# ==========================================================================================STUDENT DASHBOARD=============


@app.route("/student/dashboard/<school_ref:school_id>")
def student_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"student"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    # Pull classrooms for this school
    classrooms = supabase.table("classrooms").select(
        "*").eq("school_id", school_id).execute().data

    return render_template(
        "student_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events,
        classrooms=classrooms
    )


# =============================================================================================LEARNER DASHBOARD==========
@app.route("/learner/dashboard/<school_ref:school_id>")
def learner_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"learner"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    # Pull classrooms for this school
    classrooms = supabase.table("classrooms").select(
        "*").eq("school_id", school_id).execute().data

    return render_template(
        "learner_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events,
        classrooms=classrooms
    )

# ================================================================================================TEACHER DASHBOARD=======


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


@app.route("/teacher/dashboard/<school_ref:school_id>")
def teacher_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    # Pull classrooms for this school
    classrooms = supabase.table("classrooms").select(
        "*").eq("school_id", school_id).execute().data

    # Pull virtual calls for all classrooms in this school
    dashboard_virtual_calls = _load_dashboard_virtual_calls(
        classrooms,
        actor_id=str(session.get("user_id") or session.get(
            "teacher_id") or session.get("lecturer_id") or ""),
    )

    return render_template(
        "teacher_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events,
        classrooms=classrooms,
        dashboard_virtual_calls=dashboard_virtual_calls,
        instructor_ai_enabled=INSTRUCTOR_AI_PREMIUM_ENABLED,
    )


@app.route("/virtual-meetings/<school_ref:school_id>", methods=["GET", "POST"])
def global_virtual_meetings(school_id):
    gate = _require_authenticated_school_context(
        school_id,
        allowed_roles={"teacher", "lecturer", "student",
                       "learner", "parent", "staff", "school_admin"},
    )
    if gate:
        return gate

    actor_id = str(session.get("user_id") or session.get(
        "teacher_id") or session.get("lecturer_id") or "")
    actor_name = session.get("user_name") or session.get(
        "username") or (session.get("role") or "member").title()
    actor_role = session.get("role") or "member"

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()

        if action == "create_global_virtual_meeting":
            title = (request.form.get("meeting_title") or "").strip()
            password = (request.form.get("meeting_password") or "").strip()
            scheduled_start_raw = (request.form.get(
                "meeting_scheduled_start") or "").strip()
            scheduled_end_raw = (request.form.get(
                "meeting_scheduled_end") or "").strip()
            if not title:
                flash("Meeting title is required.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            if len(password) < 4:
                flash("Meeting password must be at least 4 characters.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            start_dt = _virtual_call_parse_iso(scheduled_start_raw)
            end_dt = _virtual_call_parse_iso(scheduled_end_raw)
            if start_dt and end_dt and end_dt <= start_dt:
                flash("Scheduled end time must be after start time.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            meeting_code = _virtual_meeting_code()
            room_name = f"flaskhub-global-{school_id}-{uuid.uuid4().hex[:8]}"
            row = {
                "school_id": school_id,
                "title": title,
                "room_name": room_name,
                "meeting_code": meeting_code,
                "password_hash": _virtual_call_password_hash(password),
                "password_sealed": _seal_meeting_password(password),
                "created_by": actor_name,
                "created_by_role": actor_role,
                "created_by_id": actor_id,
                "scheduled_start": start_dt.isoformat() if start_dt else None,
                "scheduled_end": end_dt.isoformat() if end_dt else None,
                "created_at": datetime.utcnow().isoformat(),
                "ended_at": None,
            }
            try:
                resp = supabase.table(
                    "global_virtual_meetings").insert(row).execute()
                created = resp.data[0] if resp and resp.data else None
                created_id = created.get("id") if isinstance(
                    created, dict) else None
                if created_id:
                    session[f"global_virtual_meeting_access_{created_id}"] = datetime.utcnow(
                    ).isoformat()
                flash(
                    f"Global meeting created. Meeting code: {meeting_code}", "success")
            except Exception:
                flash(
                    "Unable to create global meeting right now. Ensure global_virtual_meetings table exists.", "error")
            return redirect(url_for("global_virtual_meetings", school_id=school_id))

        if action == "join_global_virtual_meeting":
            meeting_code = (request.form.get(
                "meeting_code") or "").strip().upper()
            password = (request.form.get("meeting_password") or "").strip()
            if not meeting_code:
                flash("Meeting code is required.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            if not password:
                flash("Meeting password is required.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            try:
                resp = supabase.table("global_virtual_meetings").select(
                    "id,school_id,title,room_name,password_hash,meeting_code,ended_at,created_by_id"
                ).eq("school_id", school_id).order("created_at", desc=True).limit(300).execute()
                rows = resp.data or []
            except Exception:
                rows = []

            meeting = None
            for row in rows:
                if (row.get("meeting_code") or "").strip().upper() == meeting_code:
                    meeting = row
                    break

            if not meeting:
                flash("Meeting not found for this code.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            if _virtual_call_parse_iso(meeting.get("ended_at") or "") is not None:
                flash("This meeting has ended.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            if _virtual_call_password_hash(password) != (meeting.get("password_hash") or ""):
                flash("Incorrect meeting password.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))

            meeting_id = meeting.get("id")
            session[f"global_virtual_meeting_access_{meeting_id}"] = datetime.utcnow(
            ).isoformat()
            return redirect(url_for("global_virtual_meeting_room", school_id=school_id, meeting_id=meeting_id))

        if action == "end_global_virtual_meeting":
            meeting_id = _parse_int(request.form.get("meeting_id"))
            if meeting_id is None:
                flash("Invalid meeting.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            try:
                resp = supabase.table("global_virtual_meetings").select(
                    "id,school_id,created_by_id,ended_at"
                ).eq("id", meeting_id).eq("school_id", school_id).limit(1).execute()
                meeting = resp.data[0] if resp and resp.data else None
            except Exception:
                meeting = None
            if not meeting:
                flash("Meeting not found.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            host_id = str(meeting.get("created_by_id") or "")
            if host_id and host_id != actor_id:
                flash("Only the host can end this meeting.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            try:
                supabase.table("global_virtual_meetings").update({
                    "ended_at": datetime.utcnow().isoformat(),
                }).eq("id", meeting_id).eq("school_id", school_id).execute()
                flash("Meeting ended.", "success")
            except Exception:
                flash("Unable to end meeting.", "error")
            return redirect(url_for("global_virtual_meetings", school_id=school_id))

        if action == "rotate_global_virtual_meeting_password":
            meeting_id = _parse_int(request.form.get("meeting_id"))
            new_password = (request.form.get(
                "new_meeting_password") or "").strip()
            if meeting_id is None:
                flash("Invalid meeting.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            if len(new_password) < 4:
                flash("New meeting password must be at least 4 characters.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            try:
                resp = supabase.table("global_virtual_meetings").select(
                    "id,school_id,created_by_id"
                ).eq("id", meeting_id).eq("school_id", school_id).limit(1).execute()
                meeting = resp.data[0] if resp and resp.data else None
            except Exception:
                meeting = None
            if not meeting:
                flash("Meeting not found.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            host_id = str(meeting.get("created_by_id") or "")
            if host_id and host_id != actor_id:
                flash("Only the host can rotate this password.", "error")
                return redirect(url_for("global_virtual_meetings", school_id=school_id))
            try:
                supabase.table("global_virtual_meetings").update({
                    "password_hash": _virtual_call_password_hash(new_password),
                    "password_sealed": _seal_meeting_password(new_password),
                    "password_rotated_at": datetime.utcnow().isoformat(),
                }).eq("id", meeting_id).eq("school_id", school_id).execute()
                session[f"global_virtual_meeting_access_{meeting_id}"] = datetime.utcnow(
                ).isoformat()
                flash("Meeting password updated.", "success")
            except Exception:
                flash("Unable to update meeting password.", "error")
            return redirect(url_for("global_virtual_meetings", school_id=school_id))

        flash("Unsupported meeting action.", "error")
        return redirect(url_for("global_virtual_meetings", school_id=school_id))

    meetings = _load_global_virtual_meetings(school_id, actor_id=actor_id)
    return render_template(
        "global_virtual_meetings.html",
        school_id=school_id,
        meetings=meetings,
    )


@app.route("/virtual-meetings/<school_ref:school_id>/call/<signed_id:meeting_id>")
def global_virtual_meeting_room(school_id, meeting_id):
    gate = _require_authenticated_school_context(
        school_id,
        allowed_roles={"teacher", "lecturer", "student",
                       "learner", "parent", "staff", "school_admin"},
    )
    if gate:
        return gate
    if not session.get(f"global_virtual_meeting_access_{meeting_id}"):
        flash("Enter meeting code and password first.", "error")
        return redirect(url_for("global_virtual_meetings", school_id=school_id))

    try:
        resp = supabase.table("global_virtual_meetings").select(
            "id,school_id,title,room_name,created_by,created_by_id,created_at,scheduled_start,scheduled_end,ended_at"
        ).eq("id", meeting_id).eq("school_id", school_id).limit(1).execute()
        meeting = resp.data[0] if resp and resp.data else None
    except Exception:
        meeting = None
    if not meeting:
        flash("Meeting not found.", "error")
        return redirect(url_for("global_virtual_meetings", school_id=school_id))

    actor_id = str(session.get("user_id") or session.get(
        "teacher_id") or session.get("lecturer_id") or "")
    host_id = str(meeting.get("created_by_id") or "")
    is_host = bool(host_id and actor_id and host_id == actor_id)
    call_status = _virtual_call_status({
        "scheduled_start": meeting.get("scheduled_start"),
        "ended_at": meeting.get("ended_at"),
    })
    return render_template(
        "virtual_global_call.html",
        school_id=school_id,
        meeting_id=meeting_id,
        call_title=meeting.get("title") or "Global Meeting",
        room_name=meeting.get("room_name"),
        host_name=meeting.get("created_by") or "Host",
        created_at=meeting.get("created_at"),
        scheduled_start=meeting.get("scheduled_start"),
        scheduled_end=meeting.get("scheduled_end"),
        call_status=call_status,
        is_call_host=is_host,
    )

# ===================================================================CLASSROOM DETAILS=====


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


@app.route("/classroom/<signed_id:classroom_id>", methods=["GET", "POST"])
def classroom_detail(classroom_id):
    classroom_resp = supabase.table("classrooms").select(
        "*").eq("id", classroom_id).execute()
    classroom = classroom_resp.data[0] if classroom_resp.data else None
    if not classroom:
        flash("Classroom not found.", "error")
        return redirect(url_for("login"))

    school_name = None
    try:
        school_resp = supabase.table("schools").select(
            "name").eq("id", classroom["school_id"]).execute()
        school_name = school_resp.data[0]["name"] if school_resp.data else None
    except Exception:
        school_name = None

    created_by = None
    try:
        if classroom.get("teacher_id"):
            creator_resp = supabase.table("teachers").select(
                "name").eq("id", classroom["teacher_id"]).execute()
            created_by = creator_resp.data[0]["name"] if creator_resp.data else "Teacher"
        elif classroom.get("lecturer_id"):
            creator_resp = supabase.table("lecturers").select(
                "name").eq("id", classroom["lecturer_id"]).execute()
            created_by = creator_resp.data[0]["name"] if creator_resp.data else "Lecturer"
    except Exception:
        created_by = None

    def current_user_name():
        if session.get("teacher_id"):
            resp = supabase.table("teachers").select("name").eq(
                "id", session["teacher_id"]).execute()
            return resp.data[0]["name"] if resp.data else "Teacher"
        if session.get("lecturer_id"):
            resp = supabase.table("lecturers").select("name").eq(
                "id", session["lecturer_id"]).execute()
            return resp.data[0]["name"] if resp.data else "Lecturer"
        if session.get("user_id"):
            resp = supabase.table("students").select("id, name").eq(
                "user_id", session["user_id"]).execute()
            if resp.data:
                return resp.data[0]["name"]
            learner_resp = supabase.table("learners").select(
                "id, name").eq("user_id", session["user_id"]).execute()
            if learner_resp.data:
                return learner_resp.data[0]["name"]
        return session.get("role", "Guest").title()

    def get_user_role_record():
        if session.get("user_id"):
            resp = supabase.table("students").select("id").eq(
                "user_id", session["user_id"]).execute()
            if resp.data:
                return {"student_id": resp.data[0]["id"]}
            resp = supabase.table("learners").select("id").eq(
                "user_id", session["user_id"]).execute()
            if resp.data:
                return {"learner_id": resp.data[0]["id"]}
        if session.get("teacher_id"):
            return {"teacher_id": session["teacher_id"]}
        if session.get("lecturer_id"):
            return {"lecturer_id": session["lecturer_id"]}
        return {}

    def is_classroom_member():
        role_record = get_user_role_record()
        if not role_record:
            return False
        query = supabase.table("classroom_members").select("*").eq(
            "classroom_id", classroom_id)
        for key, value in role_record.items():
            query = query.eq(key, value)
        try:
            resp = query.execute()
            return bool(resp.data)
        except Exception:
            return False

# ============================================================Classroom member addition
    def add_classroom_member():
        role_record = get_user_role_record()
        if not role_record:
            return False

        # Check if user is already a member
        if is_classroom_member():
            return True  # Already a member, no need to add again

        member_payload = {
            "classroom_id": classroom_id,
            "role": session.get("role", "member")
        }
        member_payload.update(role_record)
        try:
            supabase.table("classroom_members").insert(
                member_payload).execute()
            return True
        except Exception:
            return False

    def cleanup_duplicate_members():
        """Remove duplicate classroom member entries for the same user."""
        try:
            # Get all member records for this classroom
            member_records = supabase.table("classroom_members").select(
                "*").eq("classroom_id", classroom_id).execute().data

            if not member_records:
                return

            # Group by user type and ID to find duplicates
            seen_users = {}
            duplicates_to_remove = []

            for member in member_records:
                user_key = None
                if member.get("teacher_id"):
                    user_key = f"teacher_{member['teacher_id']}"
                elif member.get("lecturer_id"):
                    user_key = f"lecturer_{member['lecturer_id']}"
                elif member.get("student_id"):
                    user_key = f"student_{member['student_id']}"
                elif member.get("learner_id"):
                    user_key = f"learner_{member['learner_id']}"

                if user_key:
                    if user_key in seen_users:
                        # This is a duplicate, mark for removal
                        duplicates_to_remove.append(member['id'])
                    else:
                        seen_users[user_key] = member['id']

            # Remove duplicates (keep the first occurrence)
            for duplicate_id in duplicates_to_remove:
                supabase.table("classroom_members").delete().eq(
                    "id", duplicate_id).execute()

        except Exception:
            # Silently fail cleanup - not critical
            pass

    if request.method == "POST":
        action = request.form.get("action")
        user_id = session.get("user_id")
        author_name = current_user_name()
        role_name = session.get("role")
        effective_user_id = user_id or session.get(
            "teacher_id") or session.get("lecturer_id")


# =========================================================Posting to classroom stream
        if action == "post_stream":
            content = request.form.get("content", "").strip()
            attachment = request.files.get("attachment")
            attachment_path, attachment_name = save_upload_file(attachment)
            if not content and not attachment_path:
                flash("Add text or attach a file before posting.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            payload = {
                "classroom_id": classroom_id,
                "user_id": effective_user_id,
                "author_name": author_name,
                "role": role_name,
                "content": content,
                "attachment_path": attachment_path,
                "attachment_name": attachment_name,
                "created_at": datetime.utcnow().isoformat()
            }
            try:
                supabase.table("classroom_posts").insert(payload).execute()
                flash("Posted to classroom stream.", "success")
            except Exception:
                flash(
                    "Unable to save classroom post. Make sure classroom_posts table exists.", "error")


# ========================================================================uploading materials
        elif action == "upload_classroom_resource":
            upload_type = (request.form.get(
                "upload_type") or "").strip().lower()
            title = request.form.get("resource_title", "").strip()
            description = request.form.get("resource_description", "").strip()
            due_date = request.form.get("resource_due_date")
            resource_file = request.files.get("resource_file")
            file_path, file_name = save_upload_file(resource_file)

            if upload_type not in {"material", "assignment"}:
                flash(
                    "Choose what you are uploading: Assignment or Learning Material.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            if upload_type == "assignment":
                if not title:
                    flash("Assignment title is required.", "error")
                    return redirect(url_for("classroom_detail", classroom_id=classroom_id))

                payload = {
                    "classroom_id": classroom_id,
                    "creator_id": effective_user_id,
                    "creator_name": author_name,
                    "title": title,
                    "description": description,
                    "due_date": due_date,
                    "file_path": file_path,
                    "file_name": file_name,
                    "created_at": datetime.utcnow().isoformat()
                }
                try:
                    supabase.table("classroom_assignments").insert(
                        payload).execute()
                    flash("Assignment created successfully.", "success")
                except Exception:
                    flash(
                        "Unable to create assignment. Make sure classroom_assignments table exists.", "error")
            else:
                if not title and not file_path:
                    flash("Provide a title or upload a file for the material.", "error")
                    return redirect(url_for("classroom_detail", classroom_id=classroom_id))

                payload = {
                    "classroom_id": classroom_id,
                    "uploader_id": effective_user_id,
                    "uploader_name": author_name,
                    "title": title or file_name,
                    "description": description,
                    "file_path": file_path,
                    "file_name": file_name,
                    "created_at": datetime.utcnow().isoformat()
                }
                try:
                    supabase.table("classroom_materials").insert(
                        payload).execute()
                    flash("Material uploaded successfully.", "success")
                except Exception:
                    flash(
                        "Unable to save material. Make sure classroom_materials table exists.", "error")

        # Keep legacy actions for backwards compatibility with older forms.
        elif action == "upload_material":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            material_file = request.files.get("material_file")
            file_path, file_name = save_upload_file(material_file)
            if not title and not file_path:
                flash("Provide a title or upload a file for the material.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            payload = {
                "classroom_id": classroom_id,
                "uploader_id": effective_user_id,
                "uploader_name": author_name,
                "title": title or file_name,
                "description": description,
                "file_path": file_path,
                "file_name": file_name,
                "created_at": datetime.utcnow().isoformat()
            }
            try:
                supabase.table("classroom_materials").insert(payload).execute()
                flash("Material uploaded successfully.", "success")
            except Exception:
                flash(
                    "Unable to save material. Make sure classroom_materials table exists.", "error")


# =============================================================================creating assignments
        elif action == "create_assignment":
            title = request.form.get("assignment_title", "").strip()
            description = request.form.get(
                "assignment_description", "").strip()
            due_date = request.form.get("due_date")
            assignment_file = request.files.get("assignment_file")
            file_path, file_name = save_upload_file(assignment_file)
            if not title:
                flash("Assignment title is required.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            payload = {
                "classroom_id": classroom_id,
                "creator_id": effective_user_id,
                "creator_name": author_name,
                "title": title,
                "description": description,
                "due_date": due_date,
                "file_path": file_path,
                "file_name": file_name,
                "created_at": datetime.utcnow().isoformat()
            }
            try:
                supabase.table("classroom_assignments").insert(
                    payload).execute()
                flash("Assignment created successfully.", "success")
            except Exception:
                flash(
                    "Unable to create assignment. Make sure classroom_assignments table exists.", "error")


# ===================================================================Submitting assignments
        elif action == "submit_assignment":
            assignment_id = request.form.get("assignment_id")
            try:
                assignment_id = int(assignment_id) if assignment_id else None
            except ValueError:
                assignment_id = None
            submission_text = request.form.get("submission_text", "").strip()
            submission_file = request.files.get("submission_file")
            file_path, file_name = save_upload_file(submission_file)
            if not assignment_id:
                flash("Select an assignment before submitting.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            if not submission_text and not file_path:
                flash("Add text or upload a file for your submission.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            assignment_title = "Assignment"
            try:
                assignment_resp = supabase.table("classroom_assignments").select(
                    "title").eq("id", assignment_id).execute()
                if assignment_resp.data and assignment_resp.data[0].get("title"):
                    assignment_title = assignment_resp.data[0]["title"]
            except Exception:
                pass

            if not submission_text:
                submission_text = f"{assignment_title} submission"

            payload = {
                "classroom_id": classroom_id,
                "assignment_id": assignment_id,
                "submitted_by_user_id": effective_user_id,
                "submitted_by_name": author_name,
                "submission_text": submission_text,
                "file_path": file_path,
                "file_name": file_name,
                "submitted_at": datetime.utcnow().isoformat()
            }
            try:
                supabase.table("assignment_submissions").insert(
                    payload).execute()
                flash("Assignment submitted successfully.", "success")
            except Exception:
                flash(
                    "Unable to submit assignment. Make sure assignment_submissions table exists.", "error")

        elif action == "create_virtual_call":
            if not is_classroom_member():
                flash(
                    "Join the classroom first before creating a virtual call.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            # One active call at a time per classroom
            try:
                existing_posts_resp = supabase.table("classroom_posts").select(
                    "id,content").eq("classroom_id", classroom_id).eq("role", "virtual_call").execute()
                existing_posts = existing_posts_resp.data or []
            except Exception:
                existing_posts = []
            for _ep in existing_posts:
                _ep_payload = _virtual_call_payload_decode(_ep.get("content"))
                if _ep_payload and _virtual_call_status(_ep_payload) != "ended":
                    flash(
                        "There is already an active call in this classroom. End it before starting a new one.", "error")
                    return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            call_title = (request.form.get("call_title") or "").strip()
            call_password = (request.form.get("call_password") or "").strip()
            scheduled_start = (request.form.get(
                "call_scheduled_start") or "").strip()
            scheduled_end = (request.form.get(
                "call_scheduled_end") or "").strip()
            if not call_title:
                flash("Call title is required.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            if len(call_password) < 4:
                flash("Call password must be at least 4 characters.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            start_dt = _virtual_call_parse_iso(scheduled_start)
            end_dt = _virtual_call_parse_iso(scheduled_end)
            if start_dt and end_dt and end_dt <= start_dt:
                flash("Scheduled end time must be after start time.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            meeting_code = _virtual_meeting_code()
            room_name = f"flaskhub-{classroom_id}-{uuid.uuid4().hex[:8]}"
            payload = {
                "title": call_title,
                "room_name": room_name,
                "meeting_code": meeting_code,
                "password_hash": _virtual_call_password_hash(call_password),
                "password_sealed": _seal_meeting_password(call_password),
                "created_by": author_name,
                "created_by_role": role_name,
                "created_by_id": str(effective_user_id or ""),
                "scheduled_start": start_dt.isoformat() if start_dt else None,
                "scheduled_end": end_dt.isoformat() if end_dt else None,
                "created_at": datetime.utcnow().isoformat(),
                "ended_at": None,
            }
            post_payload = {
                "classroom_id": classroom_id,
                "user_id": effective_user_id,
                "author_name": author_name,
                "role": "virtual_call",
                "content": _virtual_call_payload_encode(payload),
                "attachment_path": None,
                "attachment_name": None,
                "created_at": datetime.utcnow().isoformat(),
            }
            try:
                insert_resp = supabase.table("classroom_posts").insert(
                    post_payload).execute()
                created_post = insert_resp.data[0] if insert_resp and insert_resp.data else None
                created_post_id = created_post.get(
                    "id") if isinstance(created_post, dict) else None
                if created_post_id:
                    session[f"virtual_call_access_{created_post_id}"] = datetime.utcnow(
                    ).isoformat()
                flash(
                    f"Virtual classroom call created. Meeting code: {meeting_code}. Share code + password with participants.", "success")
            except Exception:
                flash("Unable to create virtual call link right now.", "error")

        elif action == "join_virtual_call":
            if not is_classroom_member():
                flash("Join the classroom first before joining a virtual call.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            call_post_id = _parse_int(request.form.get("call_post_id"))
            call_code = (request.form.get("call_code") or "").strip().upper()
            call_password = (request.form.get("call_password") or "").strip()
            if call_post_id is None and not call_code:
                flash("Enter meeting code to join.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))
            if not call_password:
                flash("Enter the call password to join.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            call_post = None
            if call_post_id is not None:
                try:
                    call_resp = supabase.table("classroom_posts").select(
                        "id,classroom_id,content,created_at,author_name").eq("id", call_post_id).eq("classroom_id", classroom_id).limit(1).execute()
                    call_post = call_resp.data[0] if call_resp and call_resp.data else None
                except Exception:
                    call_post = None
            elif call_code:
                try:
                    call_resp = supabase.table("classroom_posts").select(
                        "id,classroom_id,content,created_at,author_name").eq("classroom_id", classroom_id).eq("role", "virtual_call").order("created_at", desc=True).limit(300).execute()
                    for row in (call_resp.data or []):
                        payload = _virtual_call_payload_decode(
                            row.get("content"))
                        if payload and (payload.get("meeting_code") or "").strip().upper() == call_code:
                            call_post = row
                            call_post_id = row.get("id")
                            break
                except Exception:
                    call_post = None

            if not call_post:
                flash("Call link not found.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            call_payload = _virtual_call_payload_decode(
                call_post.get("content"))
            if not call_payload:
                flash("This call entry is invalid.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            if _virtual_call_status(call_payload) == "ended":
                flash("This call has ended.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            expected_hash = call_payload.get("password_hash") or ""
            if _virtual_call_password_hash(call_password) != expected_hash:
                flash("Incorrect call password.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            session[f"virtual_call_access_{call_post_id}"] = datetime.utcnow(
            ).isoformat()
            _virtual_call_log_attendance(
                classroom_id,
                call_post_id,
                "join",
                str(effective_user_id or ""),
                role_name,
                author_name,
            )
            return redirect(url_for("classroom_virtual_call", classroom_id=classroom_id, call_post_id=call_post_id))

        elif action == "virtual_call_end":
            call_post_id = _parse_int(request.form.get("call_post_id"))
            call_post = _virtual_call_get_post(
                classroom_id, call_post_id) if call_post_id is not None else None
            payload = _virtual_call_payload_decode(
                (call_post or {}).get("content")) if call_post else None
            if not call_post or not payload:
                flash("Call not found.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            actor_id = str(effective_user_id or "")
            host_id = str(payload.get("created_by_id") or "")
            if host_id and actor_id != host_id:
                flash("Only the host can end this call.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            payload["ended_at"] = datetime.utcnow().isoformat()
            if _virtual_call_update_post_payload(classroom_id, call_post_id, payload):
                _virtual_call_log_attendance(
                    classroom_id,
                    call_post_id,
                    "end",
                    actor_id,
                    role_name,
                    author_name,
                )
                flash("Call ended.", "success")
            else:
                flash("Unable to end call.", "error")

        elif action == "virtual_call_rotate_password":
            call_post_id = _parse_int(request.form.get("call_post_id"))
            new_password = (request.form.get(
                "new_call_password") or "").strip()
            if len(new_password) < 4:
                flash("New call password must be at least 4 characters.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            call_post = _virtual_call_get_post(
                classroom_id, call_post_id) if call_post_id is not None else None
            payload = _virtual_call_payload_decode(
                (call_post or {}).get("content")) if call_post else None
            if not call_post or not payload:
                flash("Call not found.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            actor_id = str(effective_user_id or "")
            host_id = str(payload.get("created_by_id") or "")
            if host_id and actor_id != host_id:
                flash("Only the host can rotate this call password.", "error")
                return redirect(url_for("classroom_detail", classroom_id=classroom_id))

            payload["password_hash"] = _virtual_call_password_hash(
                new_password)
            payload["password_sealed"] = _seal_meeting_password(new_password)
            payload["password_rotated_at"] = datetime.utcnow().isoformat()
            if _virtual_call_update_post_payload(classroom_id, call_post_id, payload):
                session[f"virtual_call_access_{call_post_id}"] = datetime.utcnow(
                ).isoformat()
                flash("Call password updated.", "success")
            else:
                flash("Unable to update call password.", "error")

# =====================================================================Deleting assignment submissions
        elif action == "delete_submission":
            submission_id = request.form.get("submission_id")
            if submission_id:
                submission_id = submission_id.strip()
                if submission_id.isdigit():
                    submission_id = int(submission_id)
            if not submission_id:
                flash("Invalid submission.", "error")
            else:
                # Check ownership and deadline
                try:
                    submission_resp = supabase.table("assignment_submissions").select(
                        "*").eq("id", submission_id).execute()
                    if submission_resp.data:
                        submission = submission_resp.data[0]

                        # Check if user owns this submission
                        submitted_user_id = submission.get(
                            "submitted_by_user_id")
                        is_owner = False
                        if session.get("user_id"):
                            is_owner = str(submitted_user_id) == str(
                                session["user_id"])
                        elif session.get("teacher_id"):
                            teacher_resp = supabase.table("teachers").select(
                                "user_id").eq("id", session["teacher_id"]).execute()
                            if teacher_resp.data:
                                is_owner = str(submitted_user_id) == str(
                                    teacher_resp.data[0]["user_id"])
                        elif session.get("lecturer_id"):
                            lecturer_resp = supabase.table("lecturers").select(
                                "user_id").eq("id", session["lecturer_id"]).execute()
                            if lecturer_resp.data:
                                is_owner = str(submitted_user_id) == str(
                                    lecturer_resp.data[0]["user_id"])

                        if not is_owner:
                            flash(
                                "You can only delete your own submissions.", "error")
                        else:
                            # Check if deadline has passed
                            assignment_resp = supabase.table("classroom_assignments").select(
                                "due_date").eq("id", submission["assignment_id"]).execute()
                            can_delete = True
                            if assignment_resp.data and assignment_resp.data[0].get("due_date"):
                                due_date_str = assignment_resp.data[0]["due_date"]
                                try:
                                    if due_date_str.endswith('Z'):
                                        due_date_str = due_date_str[:-
                                                                    1] + '+00:00'
                                    due_date = datetime.fromisoformat(
                                        due_date_str)
                                    now = datetime.now(
                                        due_date.tzinfo) if due_date.tzinfo else datetime.now()
                                    if now > due_date:
                                        can_delete = False
                                except (ValueError, TypeError):
                                    # If we can't parse the date, allow deletion (fail safe)
                                    pass

                            if not can_delete:
                                flash(
                                    "Cannot delete submission after assignment deadline.", "error")
                            else:
                                supabase.table("assignment_submissions").delete().eq(
                                    "id", submission_id).execute()
                                flash("Submission deleted successfully.", "success")
                    else:
                        flash("Submission not found.", "error")
                except Exception:
                    flash("Unable to delete submission.", "error")

# =====================================================================Joining classroom
        elif action == "join_classroom":
            if is_classroom_member():
                flash("You are already a member of this classroom.", "info")
            else:
                joined = add_classroom_member()
                if joined:
                    flash("You have joined the classroom.", "success")
                else:
                    flash(
                        "Unable to join classroom. Make sure classroom_members table exists.", "error")

# =================================================================removing classroom members
        elif action == "remove_member":
            if not (session.get("teacher_id") or session.get("lecturer_id")):
                flash("Only teachers and lecturers can remove members.", "error")
            else:
                member_id = request.form.get("member_id")
                try:
                    member_id = int(member_id) if member_id else None
                except ValueError:
                    member_id = None
                if not member_id:
                    flash("Invalid member.", "error")
                else:
                    try:
                        supabase.table("classroom_members").delete().eq(
                            "id", member_id).execute()
                        flash("Member removed from classroom.", "success")
                    except Exception:
                        flash("Unable to remove member.", "error")

# ==============================================================deleting classroom posts
        elif action == "delete_post":
            flash("Post deletion is disabled.", "error")

        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    def safe_query(table_name):
        try:
            order_column = "created_at"
            if table_name == "assignment_submissions":
                order_column = "submitted_at"
            query = supabase.table(table_name).select(
                "*").eq("classroom_id", classroom_id)
            try:
                return query.order(order_column, desc=True).execute().data
            except Exception:
                # Some tables/environments may not support the expected sort column.
                return query.execute().data
        except Exception:
            return []

    def static_url(file_path):
        if file_path:
            return url_for("static", filename=file_path)
        return None

# ============================================================Lookup classroom members with full details
    def lookup_members():
        """Fetch all classroom members with their IDs for management."""
        members = []
        seen_user_ids = set()  # Track seen user IDs to avoid duplicates

        # Determine classroom type: lecturer_id -> university, teacher_id -> school
        is_university_classroom = bool(classroom.get("lecturer_id"))

        try:
            member_records = supabase.table("classroom_members").select(
                "*").eq("classroom_id", classroom_id).execute().data
            if member_records:
                for member in member_records:
                    member_id = member.get("id")

                    # Determine the user identifier based on role
                    user_identifier = None
                    if member.get("teacher_id"):
                        # Teachers don't belong in university classrooms
                        if is_university_classroom:
                            continue
                        user_identifier = f"teacher_{member['teacher_id']}"
                        if user_identifier in seen_user_ids:
                            continue  # Skip duplicate
                        seen_user_ids.add(user_identifier)
                        resp = supabase.table("teachers").select(
                            "name").eq("id", member["teacher_id"]).execute()
                        if resp.data:
                            members.append({
                                "id": member_id,
                                "name": resp.data[0]["name"],
                                "role": "Teacher",
                                "can_remove": session.get("teacher_id") or session.get("lecturer_id")
                            })
                    elif member.get("lecturer_id"):
                        # Lecturers don't belong in school classrooms
                        if not is_university_classroom:
                            continue
                        user_identifier = f"lecturer_{member['lecturer_id']}"
                        if user_identifier in seen_user_ids:
                            continue  # Skip duplicate
                        seen_user_ids.add(user_identifier)
                        resp = supabase.table("lecturers").select(
                            "name").eq("id", member["lecturer_id"]).execute()
                        if resp.data:
                            members.append({
                                "id": member_id,
                                "name": resp.data[0]["name"],
                                "role": "Lecturer",
                                "can_remove": session.get("teacher_id") or session.get("lecturer_id")
                            })
                    elif member.get("student_id"):
                        # Students belong in university classrooms
                        if not is_university_classroom:
                            continue
                        user_identifier = f"student_{member['student_id']}"
                        if user_identifier in seen_user_ids:
                            continue  # Skip duplicate
                        seen_user_ids.add(user_identifier)
                        resp = supabase.table("students").select(
                            "name").eq("id", member["student_id"]).execute()
                        if resp.data:
                            members.append({
                                "id": member_id,
                                "name": resp.data[0]["name"],
                                "role": "Student",
                                "can_remove": session.get("teacher_id") or session.get("lecturer_id")
                            })
                    elif member.get("learner_id"):
                        # Learners belong in school classrooms
                        if is_university_classroom:
                            continue
                        user_identifier = f"learner_{member['learner_id']}"
                        if user_identifier in seen_user_ids:
                            continue  # Skip duplicate
                        seen_user_ids.add(user_identifier)
                        resp = supabase.table("learners").select(
                            "name").eq("id", member["learner_id"]).execute()
                        if resp.data:
                            members.append({
                                "id": member_id,
                                "name": resp.data[0]["name"],
                                "role": "Learner",
                                "can_remove": session.get("teacher_id") or session.get("lecturer_id")
                            })
            return members
        except Exception:
            return []

    is_member = is_classroom_member()
    show_join_prompt = not is_member and session.get("role") in [
        "student", "learner"]

    posts = []
    virtual_calls = []
    virtual_call_analytics = {
        "total_calls": 0,
        "live_calls": 0,
        "scheduled_calls": 0,
        "ended_calls": 0,
        "unique_participants": 0,
        "total_join_events": 0,
    }
    materials = []
    assignments = []
    submissions = []
    assignment_title_map = {}
    current_actor_id = str(
        session.get("user_id") or session.get(
            "teacher_id") or session.get("lecturer_id") or ""
    )
    if is_member:
        stream_posts = safe_query("classroom_posts")
        for post in stream_posts:
            call_payload = _virtual_call_payload_decode(post.get("content"))
            if call_payload:
                post_id = post.get("id")
                created_by_id = str(call_payload.get("created_by_id") or "")
                status = _virtual_call_status(call_payload)
                is_host = bool(
                    created_by_id and current_actor_id and created_by_id == current_actor_id)
                has_access = bool(session.get(
                    f"virtual_call_access_{post_id}"))
                if not (is_host or has_access):
                    continue
                virtual_calls.append({
                    "post_id": post_id,
                    "title": call_payload.get("title") or "Classroom Call",
                    "room_name": call_payload.get("room_name"),
                    "meeting_code": (call_payload.get("meeting_code") or "").strip(),
                    "created_by": call_payload.get("created_by") or post.get("author_name") or "Host",
                    "created_at": call_payload.get("created_at") or post.get("created_at"),
                    "scheduled_start": call_payload.get("scheduled_start"),
                    "scheduled_end": call_payload.get("scheduled_end"),
                    "status": status,
                    "is_host": is_host,
                    "creator_password": _reveal_meeting_password(call_payload.get("password_sealed") or "") if is_host else "",
                    "session_summary": (call_payload.get("session_summary") or "").strip(),
                    "session_action_items": call_payload.get("session_action_items") or [],
                    "session_followups": call_payload.get("session_followups") or [],
                    "session_notes_generated_at": call_payload.get("session_notes_generated_at"),
                })
                continue
            post["attachment_url"] = static_url(post.get("attachment_path"))
            posts.append(post)

        attendance_snapshot = _virtual_call_attendance_snapshot(
            classroom_id,
            [row.get("post_id") for row in virtual_calls],
        )
        for row in virtual_calls:
            metrics = attendance_snapshot.get(str(row.get("post_id")), {})
            row["join_events"] = metrics.get("joins", 0)
            row["leave_events"] = metrics.get("leaves", 0)
            row["participant_count"] = metrics.get("unique_participants", 0)
            virtual_call_analytics["total_join_events"] += row["join_events"]
            if row.get("status") == "live":
                virtual_call_analytics["live_calls"] += 1
            elif row.get("status") == "scheduled":
                virtual_call_analytics["scheduled_calls"] += 1
            else:
                virtual_call_analytics["ended_calls"] += 1

        virtual_call_analytics["total_calls"] = len(virtual_calls)
        virtual_call_analytics["unique_participants"] = sum(
            attendance_snapshot.get(str(row.get("post_id")), {}).get(
                "unique_participants", 0)
            for row in virtual_calls
        )

        virtual_calls.sort(
            key=lambda row: str(row.get("created_at") or ""), reverse=True)
        materials = safe_query("classroom_materials")
        assignments = safe_query("classroom_assignments")
        assignment_title_map = {
            str(assignment.get("id")): assignment.get("title") or "Assignment"
            for assignment in assignments
        }
        submissions = safe_query("assignment_submissions")
        for submission in submissions:
            assignment_title = assignment_title_map.get(
                str(submission.get("assignment_id")), "Assignment")
            sender_name = submission.get("submitted_by_name") or "Student"
            submission["submission_label"] = f"{assignment_title} submission"
            submission["teacher_submission_label"] = f"{sender_name} {assignment_title} submission"

    my_submissions = []
    if is_member and session.get("user_id") and session.get("role") in ["student", "learner"]:
        try:
            my_submissions = supabase.table("assignment_submissions").select(
                "*").eq("submitted_by_user_id", session["user_id"]).eq("classroom_id", classroom_id).order("submitted_at", desc=True).execute().data

            # Add delete permission info for each submission
            for submission in my_submissions:
                assignment_title = assignment_title_map.get(
                    str(submission.get("assignment_id")), "Assignment")
                submission["submission_label"] = f"{assignment_title} submission"

                can_delete = True
                try:
                    # Get assignment deadline
                    assignment_resp = supabase.table("classroom_assignments").select(
                        "due_date").eq("id", submission["assignment_id"]).execute()
                    if assignment_resp.data and assignment_resp.data[0].get("due_date"):
                        due_date_str = assignment_resp.data[0]["due_date"]
                        try:
                            # Handle different datetime formats
                            if due_date_str.endswith('Z'):
                                due_date_str = due_date_str[:-1] + '+00:00'
                            due_date = datetime.fromisoformat(due_date_str)
                            if datetime.now(due_date.tzinfo) > due_date:
                                can_delete = False
                        except (ValueError, TypeError):
                            # If we can't parse the date, allow deletion (fail safe)
                            pass
                except Exception:
                    # If we can't check deadline, allow deletion (fail safe)
                    pass

                submission["can_delete"] = can_delete
        except Exception:
            my_submissions = []

    class_members = lookup_members()

    # Clean up any duplicate member entries
    cleanup_duplicate_members()

    dashboard_url = url_for("login")
    if session.get("teacher_id"):
        dashboard_url = url_for("teacher_dashboard",
                                school_id=session.get("school_id"))
    elif session.get("lecturer_id"):
        dashboard_url = url_for("lecturer_dashboard",
                                school_id=session.get("school_id"))
    elif session.get("role") in ["student", "learner"]:
        dashboard_url = url_for("student_dashboard",
                                school_id=session.get("school_id"))

    return render_template(
        "classroom_detail.html",
        classroom=classroom,
        school_name=school_name,
        created_by=created_by,
        posts=posts,
        materials=materials,
        assignments=assignments,
        submissions=submissions,
        my_submissions=my_submissions,
        is_member=is_member,
        show_join_prompt=show_join_prompt,
        class_members=class_members,
        virtual_calls=virtual_calls,
        virtual_call_analytics=virtual_call_analytics,
        dashboard_url=dashboard_url,
        instructor_ai_enabled=INSTRUCTOR_AI_PREMIUM_ENABLED,
    )


@app.route("/classroom/<signed_id:classroom_id>/virtual-call/<signed_id:call_post_id>")
def classroom_virtual_call(classroom_id, call_post_id):
    classroom_resp = supabase.table("classrooms").select(
        "*").eq("id", classroom_id).limit(1).execute()
    classroom = classroom_resp.data[0] if classroom_resp and classroom_resp.data else None
    if not classroom:
        flash("Classroom not found.", "error")
        return redirect(url_for("login"))

    if not _session_is_classroom_member(classroom_id):
        flash("Join the classroom first to access virtual calls.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    try:
        call_resp = supabase.table("classroom_posts").select(
            "id,classroom_id,content,author_name,created_at").eq("id", call_post_id).eq("classroom_id", classroom_id).limit(1).execute()
        call_post = call_resp.data[0] if call_resp and call_resp.data else None
    except Exception:
        call_post = None

    if not call_post:
        flash("Virtual call not found.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    call_payload = _virtual_call_payload_decode(call_post.get("content"))
    if not call_payload:
        flash("This virtual call is malformed.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    if not session.get(f"virtual_call_access_{call_post_id}"):
        flash("Enter call password first to join this meeting.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    actor_id = str(session.get("user_id") or session.get(
        "teacher_id") or session.get("lecturer_id") or "")
    actor_role = session.get("role") or "member"
    actor_name = session.get("user_name") or session.get(
        "username") or actor_role.title()
    _virtual_call_log_attendance(
        classroom_id,
        call_post_id,
        "join",
        actor_id,
        actor_role,
        actor_name,
    )

    host_id = str(call_payload.get("created_by_id") or "")
    is_host = bool(host_id and actor_id and host_id == actor_id)

    return render_template(
        "virtual_classroom_call.html",
        classroom=classroom,
        call_post_id=call_post_id,
        call_title=call_payload.get("title") or "Virtual Classroom Call",
        room_name=call_payload.get("room_name"),
        meeting_code=(call_payload.get("meeting_code") or "").strip(),
        creator_password=_reveal_meeting_password(
            call_payload.get("password_sealed") or "") if is_host else "",
        host_name=call_payload.get("created_by") or call_post.get(
            "author_name") or "Host",
        created_at=call_payload.get(
            "created_at") or call_post.get("created_at"),
        scheduled_start=call_payload.get("scheduled_start"),
        scheduled_end=call_payload.get("scheduled_end"),
        call_status=_virtual_call_status(call_payload),
        is_call_host=is_host,
    )


@app.route("/classroom/<signed_id:classroom_id>/virtual-call/<signed_id:call_post_id>/attendance", methods=["POST"])
def classroom_virtual_call_attendance(classroom_id, call_post_id):
    if not _session_is_classroom_member(classroom_id):
        return jsonify({"error": "Access denied."}), 403

    if not session.get(f"virtual_call_access_{call_post_id}"):
        return jsonify({"error": "Join access missing."}), 403

    call_post = _virtual_call_get_post(classroom_id, call_post_id)
    call_payload = _virtual_call_payload_decode(
        (call_post or {}).get("content")) if call_post else None
    if not call_post or not call_payload:
        return jsonify({"error": "Call not found."}), 404

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    event_type = (payload.get("event") or "heartbeat").strip().lower()
    if event_type not in {"join", "leave", "heartbeat"}:
        event_type = "heartbeat"

    actor_id = str(session.get("user_id") or session.get(
        "teacher_id") or session.get("lecturer_id") or "")
    actor_role = session.get("role") or "member"
    actor_name = session.get("user_name") or session.get(
        "username") or actor_role.title()
    _virtual_call_log_attendance(
        classroom_id,
        call_post_id,
        event_type,
        actor_id,
        actor_role,
        actor_name,
    )
    return jsonify({"ok": True})


@app.route("/classroom/<signed_id:classroom_id>/virtual-call/<signed_id:call_post_id>/host-control", methods=["POST"])
def classroom_virtual_call_host_control(classroom_id, call_post_id):
    if not _session_is_classroom_member(classroom_id):
        flash("Access denied.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    call_post = _virtual_call_get_post(classroom_id, call_post_id)
    call_payload = _virtual_call_payload_decode(
        (call_post or {}).get("content")) if call_post else None
    if not call_post or not call_payload:
        flash("Call not found.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    actor_id = str(session.get("user_id") or session.get(
        "teacher_id") or session.get("lecturer_id") or "")
    host_id = str(call_payload.get("created_by_id") or "")
    if host_id and actor_id != host_id:
        flash("Only the host can control this meeting.", "error")
        return redirect(url_for("classroom_virtual_call", classroom_id=classroom_id, call_post_id=call_post_id))

    action = (request.form.get("action") or "").strip().lower()
    if action == "end_call":
        call_payload["ended_at"] = datetime.utcnow().isoformat()
        if _virtual_call_update_post_payload(classroom_id, call_post_id, call_payload):
            _virtual_call_log_attendance(
                classroom_id,
                call_post_id,
                "end",
                actor_id,
                session.get("role") or "member",
                session.get("user_name") or session.get("username") or "Host",
            )
            flash("Meeting ended.", "success")
        else:
            flash("Could not end meeting.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    if action == "rotate_password":
        new_password = (request.form.get("new_call_password") or "").strip()
        if len(new_password) < 4:
            flash("New password must be at least 4 characters.", "error")
            return redirect(url_for("classroom_virtual_call", classroom_id=classroom_id, call_post_id=call_post_id))
        call_payload["password_hash"] = _virtual_call_password_hash(
            new_password)
        call_payload["password_sealed"] = _seal_meeting_password(new_password)
        call_payload["password_rotated_at"] = datetime.utcnow().isoformat()
        if _virtual_call_update_post_payload(classroom_id, call_post_id, call_payload):
            session[f"virtual_call_access_{call_post_id}"] = datetime.utcnow(
            ).isoformat()
            flash("Meeting password rotated.", "success")
        else:
            flash("Could not rotate meeting password.", "error")
        return redirect(url_for("classroom_virtual_call", classroom_id=classroom_id, call_post_id=call_post_id))

    flash("Unsupported host control action.", "error")
    return redirect(url_for("classroom_virtual_call", classroom_id=classroom_id, call_post_id=call_post_id))


@app.route("/ai/instructor-virtual-call-analytics", methods=["POST"])
def ai_instructor_virtual_call_analytics():
    identity, identity_error = _instructor_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403
    if not INSTRUCTOR_AI_PREMIUM_ENABLED:
        return jsonify({"error": "Virtual call analytics is a premium feature."}), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    classroom_id = _parse_int(payload.get("classroom_id"))
    if classroom_id is None:
        return jsonify({"error": "classroom_id is required."}), 400

    try:
        class_resp = supabase.table("classrooms").select(
            "id,school_id").eq("id", classroom_id).limit(1).execute()
        class_row = class_resp.data[0] if class_resp and class_resp.data else None
    except Exception:
        class_row = None
    if not class_row:
        return jsonify({"error": "Classroom not found."}), 404
    if identity.get("school_id") and class_row.get("school_id") and str(identity.get("school_id")) != str(class_row.get("school_id")):
        return jsonify({"error": "Classroom is outside your school scope."}), 403

    try:
        stream_rows = supabase.table("classroom_posts").select(
            "id,content,created_at,author_name,classroom_id").eq("classroom_id", classroom_id).order("created_at", desc=True).limit(300).execute().data or []
    except Exception:
        stream_rows = []

    calls = []
    for row in stream_rows:
        call_payload = _virtual_call_payload_decode(row.get("content"))
        if not call_payload:
            continue
        calls.append({
            "post_id": row.get("id"),
            "title": call_payload.get("title") or "Classroom Call",
            "status": _virtual_call_status(call_payload),
            "scheduled_start": call_payload.get("scheduled_start"),
            "scheduled_end": call_payload.get("scheduled_end"),
            "created_by": call_payload.get("created_by") or row.get("author_name") or "Host",
        })

    attendance = _virtual_call_attendance_snapshot(
        classroom_id,
        [row.get("post_id") for row in calls],
    )
    total_participants = 0
    total_joins = 0
    for call in calls:
        metrics = attendance.get(str(call.get("post_id")), {})
        call["participant_count"] = metrics.get("unique_participants", 0)
        call["join_events"] = metrics.get("joins", 0)
        total_participants += metrics.get("unique_participants", 0)
        total_joins += metrics.get("joins", 0)

    summary = {
        "total_calls": len(calls),
        "live_calls": len([c for c in calls if c.get("status") == "live"]),
        "scheduled_calls": len([c for c in calls if c.get("status") == "scheduled"]),
        "ended_calls": len([c for c in calls if c.get("status") == "ended"]),
        "participant_sum": total_participants,
        "join_event_sum": total_joins,
    }

    insight = "No call analytics available yet."
    client, config_error = _build_openai_client()
    if not config_error and calls:
        prompt = (
            "Generate concise instructor insights from classroom virtual-call metrics. "
            "Return 4 bullet points in plain text with action recommendations.\n\n"
            f"Summary: {summary}\n"
            f"Calls: {std_json.dumps(calls[:30])}"
        )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system",
                        "content": "You are an education operations analyst."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.2,
            )
            insight = (
                (response.choices[0].message.content if response.choices else "") or "").strip() or insight
        except Exception:
            insight = "Analytics summary is ready, but AI insight generation failed."

    return jsonify({
        "summary": summary,
        "calls": calls,
        "insight": insight,
    })


@app.route("/ai/instructor-virtual-call-summary", methods=["POST"])
def ai_instructor_virtual_call_summary():
    identity, identity_error = _instructor_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403
    if not INSTRUCTOR_AI_PREMIUM_ENABLED:
        return jsonify({"error": "Meeting session notes is a premium feature."}), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}

    classroom_id = _parse_int(payload.get("classroom_id"))
    call_post_id = _parse_int(payload.get("call_post_id"))
    host_notes = (payload.get("host_notes") or "").strip()
    if classroom_id is None or call_post_id is None:
        return jsonify({"error": "classroom_id and call_post_id are required."}), 400

    call_post = _virtual_call_get_post(classroom_id, call_post_id)
    call_payload = _virtual_call_payload_decode(
        (call_post or {}).get("content")) if call_post else None
    if not call_post or not call_payload:
        return jsonify({"error": "Virtual call not found."}), 404

    try:
        class_resp = supabase.table("classrooms").select(
            "id,school_id").eq("id", classroom_id).limit(1).execute()
        class_row = class_resp.data[0] if class_resp and class_resp.data else None
    except Exception:
        class_row = None
    if not class_row:
        return jsonify({"error": "Classroom not found."}), 404
    if identity.get("school_id") and class_row.get("school_id") and str(identity.get("school_id")) != str(class_row.get("school_id")):
        return jsonify({"error": "Classroom is outside your school scope."}), 403

    if _virtual_call_status(call_payload) != "ended":
        return jsonify({"error": "Session notes can only be generated for ended meetings."}), 400

    attendance = _virtual_call_attendance_snapshot(
        classroom_id, [call_post_id])
    metrics = attendance.get(str(call_post_id), {})

    summary_text = ""
    action_items = []
    followups = []

    client, config_error = _build_openai_client()
    if config_error:
        summary_text = (
            "Meeting notes generated in offline mode. "
            f"Participants: {metrics.get('unique_participants', 0)}, joins: {metrics.get('joins', 0)}, leaves: {metrics.get('leaves', 0)}."
        )
        action_items = [
            "Review host notes and assign clear owners for each task.",
            "Share meeting outcomes in classroom stream.",
            "Set next check-in date for unresolved tasks.",
        ]
        followups = [
            "Collect pending deliverables from group members.",
            "Post revised timeline before next meeting.",
        ]
    else:
        prompt = (
            "Generate concise academic meeting notes from this virtual classroom call. "
            "Return strict JSON with keys: summary, action_items (array), follow_ups (array). "
            "Keep practical and short.\n\n"
            f"Meeting title: {call_payload.get('title') or 'Virtual Classroom Call'}\n"
            f"Host: {call_payload.get('created_by') or 'Host'}\n"
            f"Scheduled start: {call_payload.get('scheduled_start') or 'N/A'}\n"
            f"Scheduled end: {call_payload.get('scheduled_end') or 'N/A'}\n"
            f"Attendance metrics: {std_json.dumps(metrics)}\n"
            f"Host notes: {host_notes[:2500]}"
        )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system",
                        "content": "You summarize classroom meetings for educators."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=500,
                temperature=0.2,
            )
            parsed = std_json.loads(
                ((response.choices[0].message.content if response.choices else "") or "{}").strip())
            summary_text = (parsed.get("summary") or "").strip()
            action_items = [str(x).strip() for x in (
                parsed.get("action_items") or []) if str(x).strip()][:8]
            followups = [str(x).strip() for x in (
                parsed.get("follow_ups") or []) if str(x).strip()][:8]
        except Exception:
            summary_text = (
                "AI could not generate full notes right now. "
                f"Participants: {metrics.get('unique_participants', 0)}, joins: {metrics.get('joins', 0)}."
            )
            action_items = [
                "Review host notes and post final decisions.",
                "Assign owners and deadlines for next tasks.",
            ]
            followups = [
                "Schedule the next meeting if open items remain.",
            ]

    if not summary_text:
        summary_text = "Session notes generated, but summary text is currently minimal."

    call_payload["session_summary"] = summary_text[:3000]
    call_payload["session_action_items"] = action_items
    call_payload["session_followups"] = followups
    call_payload["session_notes_generated_at"] = datetime.utcnow().isoformat()
    if host_notes:
        call_payload["session_host_notes"] = host_notes[:4000]
    _virtual_call_update_post_payload(classroom_id, call_post_id, call_payload)

    return jsonify({
        "summary": call_payload.get("session_summary"),
        "action_items": call_payload.get("session_action_items") or [],
        "followups": call_payload.get("session_followups") or [],
        "generated_at": call_payload.get("session_notes_generated_at"),
        "metrics": metrics,
    })

# ===================================================================================================PARENTS DASHBOARD===========


@app.route("/parent/dashboard/<school_ref:school_id>")
def parent_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"parent"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    # Pull classrooms for this school
    classrooms = supabase.table("classrooms").select(
        "*").eq("school_id", school_id).execute().data

    return render_template(
        "parent_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events,
        classrooms=classrooms
    )


# ===================================================================================================STAFF DASHBOARD+++++++++++
@app.route("/staff/dashboard/<school_ref:school_id>")
def staff_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"staff"})
    if gate:
        return gate

    # Pull announcements for this school
    announcements = _load_active_announcements(school_id)

    # Pull events for this school
    events = supabase.table("events").select(
        "*").eq("school_id", school_id).execute().data

    return render_template(
        "staff_dashboard.html",
        school_id=school_id,
        announcements=announcements,
        events=events
    )

# ========================================================================CLASSES

# ---------------------------------------------------------create classrooms


@app.route("/classrooms/create", methods=["GET", "POST"])
def create_classroom():
    if request.method == "POST":
        class_name = (request.form.get("name") or "").strip()
        if not class_name:
            flash("Classroom name is required.", "error")
            return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")) if session.get("teacher_id") else url_for("lecturer_dashboard", school_id=session.get("school_id")))

        requested_code = (request.form.get("code") or request.form.get(
            "class_code") or "").strip().upper()
        generated_code = requested_code or f"CLS-{uuid.uuid4().hex[:6].upper()}"

        base_payload = {
            "name": class_name,
            "school_id": session.get("school_id")
        }

        # Attach role-specific ID
        if session.get("teacher_id"):
            base_payload["teacher_id"] = session["teacher_id"]
        elif session.get("lecturer_id"):
            base_payload["lecturer_id"] = session["lecturer_id"]
        else:
            flash("You must be logged in as a teacher or lecturer.", "error")
            return redirect(url_for("login"))

        # Different deployments use different classroom code column names.
        candidate_payloads = [
            {**base_payload, "code": generated_code, "class_code": generated_code},
            {**base_payload, "class_code": generated_code},
            {**base_payload, "code": generated_code},
            base_payload,
        ]

        created = None
        last_error = None
        for payload in candidate_payloads:
            try:
                created = supabase.table(
                    "classrooms").insert(payload).execute()
                if created:
                    break
            except Exception as e:
                last_error = e
                created = None

        if not created:
            flash(
                f"Unable to create classroom. Please check table constraints. ({str(last_error)[:120] if last_error else 'no insert response'})",
                "error",
            )
            return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")) if session.get("teacher_id") else url_for("lecturer_dashboard", school_id=session.get("school_id")))

        classroom_id = None
        try:
            if getattr(created, "data", None):
                classroom_id = created.data[0].get("id")
        except Exception:
            classroom_id = None

        # Some Supabase client versions may not return inserted row data.
        if not classroom_id:
            try:
                lookup = supabase.table("classrooms").select("id").eq("school_id", session.get("school_id")).eq(
                    "name", class_name)
                if session.get("teacher_id"):
                    lookup = lookup.eq("teacher_id", session["teacher_id"])
                elif session.get("lecturer_id"):
                    lookup = lookup.eq("lecturer_id", session["lecturer_id"])
                lookup_resp = lookup.order("id", desc=True).limit(1).execute()
                if lookup_resp and lookup_resp.data:
                    classroom_id = lookup_resp.data[0].get("id")
            except Exception:
                classroom_id = None

        if classroom_id and session.get("teacher_id"):
            try:
                supabase.table("classroom_members").insert({
                    "classroom_id": classroom_id,
                    "teacher_id": session["teacher_id"],
                    "role": "teacher"
                }).execute()
            except Exception:
                pass
        elif classroom_id and session.get("lecturer_id"):
            try:
                supabase.table("classroom_members").insert({
                    "classroom_id": classroom_id,
                    "lecturer_id": session["lecturer_id"],
                    "role": "lecturer"
                }).execute()
            except Exception:
                pass
        flash("Classroom created successfully!", "success")

        # Redirect to the right dashboard
        if session.get("teacher_id"):
            return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")))
        elif session.get("lecturer_id"):
            return redirect(url_for("lecturer_dashboard", school_id=session.get("school_id")))

    # GET request  show dashboard with classrooms
    if session.get("teacher_id"):
        classrooms = supabase.table("classrooms").select(
            "*").eq("teacher_id", session["teacher_id"]).execute().data
        return render_template(
            "teacher_dashboard.html",
            classrooms=classrooms,
            school_id=session.get("school_id")
        )

    elif session.get("lecturer_id"):
        classrooms = supabase.table("classrooms").select(
            "*").eq("lecturer_id", session["lecturer_id"]).execute().data
        return render_template(
            "lecturer_dashboard.html",
            classrooms=classrooms,
            school_id=session.get("school_id")
        )

    flash("Please log in first.", "error")
    return redirect(url_for("login"))


@app.route("/create_class", methods=["GET", "POST"])
def create_class():
    """Backward-compatible alias for older templates still using create_class endpoint."""
    return create_classroom()


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


@app.route("/classrooms/update/<signed_id:classroom_id>", methods=["GET", "POST"])
def update_classroom(classroom_id):
    if request.method == "POST":
        payload = {
            "name": request.form["name"]
        }

        # Attach role-specific ID
        if session.get("teacher_id"):
            payload["teacher_id"] = session["teacher_id"]
        elif session.get("lecturer_id"):
            payload["lecturer_id"] = session["lecturer_id"]

        supabase.table("classrooms").update(
            payload).eq("id", classroom_id).execute()
        flash("Classroom updated successfully!", "success")

        # Redirect back to the right dashboard
        if session.get("teacher_id"):
            return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")))
        elif session.get("lecturer_id"):
            return redirect(url_for("lecturer_dashboard", school_id=session.get("school_id")))
        return redirect(url_for("login"))

    # GET request -> fetch classroom data for editing
    classroom_resp = supabase.table("classrooms").select(
        "*").eq("id", classroom_id).execute()
    classroom_data = classroom_resp.data[0] if classroom_resp.data else None
    if not classroom_data:
        flash("Classroom not found.", "error")
        if session.get("teacher_id"):
            return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")))
        elif session.get("lecturer_id"):
            return redirect(url_for("lecturer_dashboard", school_id=session.get("school_id")))
        return redirect(url_for("login"))

    # Render the correct dashboard with edit form inline
    if session.get("teacher_id"):
        classrooms = supabase.table("classrooms").select(
            "*").eq("teacher_id", session["teacher_id"]).execute().data
        return render_template("teacher_dashboard.html", classrooms=classrooms, edit_classroom=classroom_data, school_id=session.get("school_id"), instructor_ai_enabled=INSTRUCTOR_AI_PREMIUM_ENABLED)

    elif session.get("lecturer_id"):
        classrooms = supabase.table("classrooms").select(
            "*").eq("lecturer_id", session["lecturer_id"]).execute().data
        return render_template("lecturer_dashboard.html", classrooms=classrooms, edit_classroom=classroom_data, school_id=session.get("school_id"), instructor_ai_enabled=INSTRUCTOR_AI_PREMIUM_ENABLED)

    return redirect(url_for("login"))

   # ------------------------------------------------------------Delete classrooms


@app.route("/classrooms/delete/<signed_id:classroom_id>", methods=["POST"])
def delete_classroom(classroom_id):
    supabase.table("classrooms").delete().eq("id", classroom_id).execute()
    flash("Classroom deleted successfully!", "success")

    # Redirect back to the right dashboard
    if session.get("teacher_id"):
        return redirect(url_for("teacher_dashboard", school_id=session.get("school_id")))
    elif session.get("lecturer_id"):
        return redirect(url_for("lecturer_dashboard", school_id=session.get("school_id")))

    return redirect(url_for("login"))  # fallback


# ====================================================================================JOIN CLASSROOM BY CODE====================

@app.route("/join-classroom", methods=["POST"])
def join_classroom_by_code():
    """Allow students/learners to join a classroom by entering its code."""
    if not session.get("user_id") and not session.get("student_id") and not session.get("learner_id"):
        flash("Please log in to join a classroom.", "error")
        return redirect(url_for("login"))

    code = (request.form.get("class_code") or "").strip().upper()
    if not code:
        flash("Please enter a classroom code.", "error")
        return _redirect_to_user_dashboard()

    classroom = _find_classroom_by_code(
        code, school_id=session.get("school_id"))
    if not classroom:
        classroom = _find_classroom_by_code(code)

    if not classroom:
        flash("Classroom not found. Please check the code and try again.", "error")
        return _redirect_to_user_dashboard()

    classroom_id = classroom["id"]
    school_id = classroom.get("school_id")

    # Determine the member payload for this user
    member_payload = {"classroom_id": classroom_id, "role": "member"}
    if session.get("student_id"):
        member_payload["student_id"] = session["student_id"]
        member_col = "student_id"
        member_val = session["student_id"]
        member_role = "student"
    elif session.get("learner_id"):
        member_payload["learner_id"] = session["learner_id"]
        member_col = "learner_id"
        member_val = session["learner_id"]
        member_role = "learner"
    elif session.get("user_id"):
        # Resolve role from DB
        student_resp = supabase.table("students").select(
            "id").eq("user_id", session["user_id"]).execute()
        if student_resp and student_resp.data:
            member_payload["student_id"] = student_resp.data[0]["id"]
            member_col = "student_id"
            member_val = student_resp.data[0]["id"]
            member_role = "student"
        else:
            learner_resp = supabase.table("learners").select(
                "id").eq("user_id", session["user_id"]).execute()
            if learner_resp and learner_resp.data:
                member_payload["learner_id"] = learner_resp.data[0]["id"]
                member_col = "learner_id"
                member_val = learner_resp.data[0]["id"]
                member_role = "learner"
            else:
                flash("Only students and learners can join classrooms by code.", "error")
                return _redirect_to_user_dashboard()
    else:
        flash("Only students and learners can join classrooms by code.", "error")
        return _redirect_to_user_dashboard()

    # Check if already a member
    existing = _find_existing_classroom_membership(
        classroom_id,
        member_col,
        member_val,
        user_id=session.get("user_id"),
    )
    if existing:
        flash(
            f"You are already a member of \"{classroom['name']}\".", "info")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    # Insert membership
    joined, error = _insert_classroom_membership(
        classroom_id,
        member_col,
        member_val,
        member_role,
        user_id=session.get("user_id"),
    )
    if joined:
        flash(
            f"You have joined \"{classroom['name']}\" successfully!", "success")
    else:
        flash(
            f"Could not join classroom: {str(error)[:120] if error else 'unknown error'}", "error")

    return redirect(url_for("classroom_detail", classroom_id=classroom_id))


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

@app.route("/school/<signed_id:school_id>/search-enrollees")
def search_enrollees(school_id):
    """JSON endpoint: search students or learners by name for teacher/lecturer classroom assignment."""
    if not session.get("teacher_id") and not session.get("lecturer_id") and session.get("role") != "school_admin":
        return jsonify([]), 403

    q = (request.args.get("q") or "").strip()
    is_university = request.args.get("university", "0") == "1"
    if len(q) < 2:
        return jsonify([])

    results = []
    try:
        if is_university:
            resp = supabase.table("students").select("id, name").eq(
                "school_id", school_id).ilike("name", f"%{q}%").limit(20).execute()
            for row in (resp.data or []):
                results.append(
                    {"id": row["id"], "name": row["name"], "type": "student"})
        else:
            resp = supabase.table("learners").select("id, name").eq(
                "school_id", school_id).ilike("name", f"%{q}%").limit(20).execute()
            for row in (resp.data or []):
                results.append(
                    {"id": row["id"], "name": row["name"], "type": "learner"})
    except Exception:
        pass
    return jsonify(results)


# ====================================================================================ADD STUDENT TO CLASSROOM (teacher/lecturer)==

@app.route("/classroom/<signed_id:classroom_id>/add-student", methods=["POST"])
def add_student_to_classroom(classroom_id):
    """Teacher/lecturer manually adds a student or learner to a classroom."""
    if not session.get("teacher_id") and not session.get("lecturer_id"):
        flash("Only teachers and lecturers can add students to classrooms.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    target_id_raw = request.form.get("target_id", "").strip()
    target_type = (request.form.get("target_type") or "").strip().lower()

    if not target_id_raw or not target_id_raw.isdigit():
        flash("Invalid student selection.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    target_id = int(target_id_raw)
    if target_type not in ("student", "learner"):
        flash("Invalid member type.", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    member_col = f"{target_type}_id"

    # Verify the classroom belongs to this teacher/lecturer
    try:
        cr = supabase.table("classrooms").select(
            "id, school_id, teacher_id, lecturer_id").eq("id", classroom_id).limit(1).execute()
        if not cr.data:
            flash("Classroom not found.", "error")
            return redirect(url_for("classroom_detail", classroom_id=classroom_id))
        classroom = cr.data[0]
        if session.get("teacher_id") and classroom.get("teacher_id") != session["teacher_id"]:
            flash("You can only modify your own classrooms.", "error")
            return redirect(url_for("classroom_detail", classroom_id=classroom_id))
        if session.get("lecturer_id") and classroom.get("lecturer_id") != session["lecturer_id"]:
            flash("You can only modify your own classrooms.", "error")
            return redirect(url_for("classroom_detail", classroom_id=classroom_id))
    except Exception as e:
        flash(f"Could not verify classroom: {str(e)[:80]}", "error")
        return redirect(url_for("classroom_detail", classroom_id=classroom_id))

    # Check already a member
    try:
        existing = supabase.table("classroom_members").select("id").eq(
            "classroom_id", classroom_id).eq(member_col, target_id).limit(1).execute()
        if existing and existing.data:
            flash("This student is already a member of the classroom.", "info")
            return redirect(url_for("classroom_detail", classroom_id=classroom_id))
    except Exception:
        pass

    # Look up name for confirmation message
    name = str(target_id)
    try:
        table = "students" if target_type == "student" else "learners"
        nr = supabase.table(table).select("name").eq(
            "id", target_id).limit(1).execute()
        if nr.data:
            name = nr.data[0]["name"]
    except Exception:
        pass

    # Insert
    try:
        supabase.table("classroom_members").insert({
            "classroom_id": classroom_id,
            member_col: target_id,
            "role": target_type
        }).execute()
        flash(f"{name} has been added to the classroom.", "success")
    except Exception as e:
        flash(f"Could not add student: {str(e)[:120]}", "error")

    return redirect(url_for("classroom_detail", classroom_id=classroom_id))


# ====================================================================================PORTAL - shared helpers====================
PORTAL_ASSESSMENT_TYPES = ["test", "project", "exam"]


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

@app.route("/portal/<signed_id:school_id>")
def portal_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    return render_template("portal_dashboard.html", school_id=school_id, actor_type=actor_type, cycle_meta=cycle_meta)


# ====================================================================================PORTAL ASSIGNMENTS - classroom list====================

@app.route("/portal/<signed_id:school_id>/assignments")
def portal_assignments(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    actor_id = session.get("teacher_id") or session.get("lecturer_id")
    try:
        id_col = "teacher_id" if actor_type == "teacher" else "lecturer_id"
        classrooms = supabase.table("classrooms").select(
            "*").eq(id_col, actor_id).eq("school_id", school_id).execute().data or []
    except Exception:
        classrooms = []
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    return render_template("portal_assignments.html", school_id=school_id, classrooms=classrooms, actor_type=actor_type, cycle_meta=cycle_meta)


# ====================================================================================PORTAL ASSIGNMENTS - students in classroom====================

@app.route("/portal/<signed_id:school_id>/assignments/<signed_id:classroom_id>")
def portal_classroom_students(school_id, classroom_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    try:
        classroom = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).execute().data
        classroom = classroom[0] if classroom else None
    except Exception:
        classroom = None
    if not classroom:
        flash("Classroom not found.", "error")
        return redirect(url_for("portal_assignments", school_id=school_id))
    if _parse_int(classroom.get("school_id")) != int(school_id):
        flash("Access denied for this classroom.", "error")
        return redirect(url_for("portal_assignments", school_id=school_id))

    students = []
    seen = set()
    try:
        member_records = supabase.table("classroom_members").select(
            "*").eq("classroom_id", classroom_id).execute().data or []
        for member in member_records:
            if member.get("student_id") and ("student", member["student_id"]) not in seen:
                seen.add(("student", member["student_id"]))
                resp = supabase.table("students").select(
                    "id,name").eq("id", member["student_id"]).execute()
                if resp.data:
                    students.append(
                        {"id": resp.data[0]["id"], "name": resp.data[0]["name"], "type": "student"})
            elif member.get("learner_id") and ("learner", member["learner_id"]) not in seen:
                seen.add(("learner", member["learner_id"]))
                resp = supabase.table("learners").select(
                    "id,name").eq("id", member["learner_id"]).execute()
                if resp.data:
                    students.append(
                        {"id": resp.data[0]["id"], "name": resp.data[0]["name"], "type": "learner"})
    except Exception:
        students = []

    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)

    return render_template("portal_classroom_students.html",
                           school_id=school_id, classroom=classroom, students=students,
                           subjects=[], actor_type=actor_type, cycle_meta=cycle_meta)


@app.route("/portal/student_subject_options")
def portal_student_subject_options():
    if not session.get("teacher_id") and not session.get("lecturer_id"):
        return jsonify({"ok": False, "items": []}), 403
    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    try:
        student_id = int(request.args.get("student_id", "0"))
    except (TypeError, ValueError):
        student_id = 0
    student_type = (request.args.get("student_type")
                    or "student").strip().lower()
    if student_id <= 0 or student_type not in {"student", "learner"}:
        return jsonify({"ok": False, "items": []}), 400
    options = resolve_student_subjects(student_id, student_type, actor_type)
    return jsonify({"ok": True, "items": options})


# ====================================================================================PORTAL ASSIGNMENTS - student performance table====================

@app.route("/portal/<signed_id:school_id>/assignments/<signed_id:classroom_id>/student/<signed_id:student_id>/<student_type>")
def portal_student_performance(school_id, classroom_id, student_id, student_type):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    is_tertiary = cycle_meta["is_tertiary"]

    try:
        classroom = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).execute().data
        classroom = classroom[0] if classroom else None
    except Exception:
        classroom = None
    if not classroom or _parse_int(classroom.get("school_id")) != int(school_id):
        flash("Access denied for this classroom.", "error")
        return redirect(url_for("portal_assignments", school_id=school_id))

    student_name = "Student"
    student_info = {}
    try:
        db_table = "students" if student_type == "student" else "learners"
        resp = supabase.table(db_table).select(
            "*").eq("id", student_id).execute()
        student_info = resp.data[0] if resp.data else {}
        student_name = student_info.get("name", "Student")
    except Exception:
        pass

    all_records = []
    try:
        all_records = supabase.table("performance_records").select("*").eq(
            "classroom_id", classroom_id).eq("student_id", student_id).eq(
            "student_type", student_type).order("created_at", desc=False).execute().data or []
    except Exception:
        all_records = []

    # Keep only the core grading categories used by schools.
    filtered_records = [
        r for r in all_records
        if (r.get("assignment_type") or "").strip().lower() in PORTAL_ASSESSMENT_TYPES
    ]

    cycles_seen = []
    cycle_map = {}
    for row in filtered_records:
        label = (row.get("cycle_label") or row.get("term_label")
                 or "Unspecified").strip() or "Unspecified"
        year = str(row.get("academic_year") or "Unknown")
        key = f"{year}::{label}"
        cycle_map[key] = {"label": label, "year": year}
    cycles_seen = sorted(cycle_map.keys(), reverse=True)

    selected_cycle = request.args.get("cycle", "").strip()
    if not selected_cycle:
        selected_cycle = f"{cycle_meta['academic_year']}::{cycle_meta['cycle_label']}"
    if selected_cycle not in cycle_map and cycles_seen:
        selected_cycle = cycles_seen[0]

    records = []
    if selected_cycle:
        for row in filtered_records:
            label = (row.get("cycle_label") or row.get("term_label")
                     or "Unspecified").strip() or "Unspecified"
            year = str(row.get("academic_year") or "Unknown")
            if f"{year}::{label}" == selected_cycle:
                records.append(row)
    else:
        records = filtered_records

    from collections import defaultdict
    type_order = PORTAL_ASSESSMENT_TYPES
    grouped = defaultdict(list)
    for r in records:
        grouped[r.get("assignment_type", "classwork")].append(r)

    type_averages = {}
    for atype, recs in grouped.items():
        pcts = [r.get("percentage") or 0 for r in recs]
        type_averages[atype] = round(sum(pcts) / len(pcts), 1) if pcts else 0.0

    all_pcts = [r.get("percentage") or 0 for r in records]
    overall_pct = round(sum(all_pcts) / len(all_pcts), 1) if all_pcts else 0.0
    overall_symbol = calc_symbol(overall_pct, is_tertiary)
    gpa = symbol_to_gpa(overall_symbol)

    all_symbols = [calc_symbol(
        _to_float(r.get("percentage"), 0.0), is_tertiary) for r in filtered_records]
    cgpa = round(sum(symbol_to_gpa(s) for s in all_symbols) /
                 len(all_symbols), 2) if all_symbols else 0.0

    subject_options = resolve_student_subjects(
        student_id, student_type, actor_type)

    yearly_trend = []
    for row in filtered_records:
        date_hint = _safe_iso_date(
            row.get("created_at")) or _safe_iso_date(row.get("record_date"))
        yearly_trend.append({
            "date": date_hint,
            "type": (row.get("assignment_type") or "test").title(),
            "percentage": round(_to_float(row.get("percentage"), 0.0), 2),
        })

    return render_template("portal_student_performance.html",
                           school_id=school_id, classroom=classroom, classroom_id=classroom_id,
                           student_id=student_id, student_type=student_type,
                           student_name=student_name, student_info=student_info,
                           records=records, grouped=dict(grouped), type_order=type_order,
                           type_averages=type_averages, overall_pct=overall_pct,
                           overall_symbol=overall_symbol, gpa=gpa, cgpa=cgpa,
                           actor_type=actor_type, is_tertiary=is_tertiary,
                           subjects_list=[opt["name"]
                                          for opt in subject_options],
                           subject_options=subject_options,
                           cycle_meta=cycle_meta,
                           selected_cycle=selected_cycle,
                           cycle_options=[{"key": key, "label": cycle_map[key]["label"],
                                           "year": cycle_map[key]["year"]} for key in cycles_seen],
                           yearly_trend=yearly_trend)


# ====================================================================================PORTAL - record performance (POST)====================

@app.route("/portal/record_performance", methods=["POST"])
def record_performance():
    if not session.get("teacher_id") and not session.get("lecturer_id"):
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    actor_id = session.get("teacher_id") or session.get("lecturer_id")

    classroom_id = int(request.form.get("classroom_id", 0))
    student_id = int(request.form.get("student_id", 0))
    student_type = request.form.get("student_type", "student")
    school_id = int(request.form.get("school_id", 0))
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    subject_name = request.form.get("subject_name", "").strip()
    assignment_name = request.form.get("assignment_name", "").strip()
    assignment_type = (request.form.get(
        "assignment_type", "test") or "test").strip().lower()
    marks_scored = request.form.get("marks_scored", "").strip()
    total_marks = request.form.get("total_marks", "100").strip()
    teacher_comment = request.form.get("teacher_comment", "").strip()
    subject_ref_id = request.form.get("subject_ref_id")
    subject_ref_type = request.form.get("subject_ref_type")

    redirect_url = url_for("portal_student_performance",
                           school_id=school_id, classroom_id=classroom_id,
                           student_id=student_id, student_type=student_type)

    cycle = get_cycle_meta(get_school_record(school_id), actor_type)
    if not cycle["marks_open"]:
        flash("Marks portal is currently closed by school admin.", "error")
        return redirect(redirect_url)

    if not subject_name or not assignment_name or not marks_scored:
        flash("Subject, assignment name, and marks are required.", "error")
        return redirect(redirect_url)

    if assignment_type not in PORTAL_ASSESSMENT_TYPES:
        flash("Only test, project, and exam records are allowed in this portal.", "error")
        return redirect(redirect_url)

    try:
        scored = float(marks_scored)
        total = float(total_marks) if total_marks else 100.0
        percentage = round((scored / total) * 100, 2) if total > 0 else 0.0
    except ValueError:
        flash("Marks must be numeric values.", "error")
        return redirect(redirect_url)

    payload = {
        "student_id": student_id,
        "student_type": student_type,
        "classroom_id": classroom_id,
        "subject_name": subject_name,
        "subject_ref_id": int(subject_ref_id) if str(subject_ref_id).isdigit() else None,
        "subject_ref_type": subject_ref_type or None,
        "assignment_name": assignment_name,
        "assignment_type": assignment_type,
        "marks_scored": scored,
        "total_marks": total,
        "percentage": percentage,
        "teacher_comment": teacher_comment or None,
        "cycle_label": cycle["cycle_label"],
        "academic_year": cycle["academic_year"],
        "recorded_by_id": actor_id,
        "recorded_by_type": actor_type,
        "created_at": datetime.utcnow().isoformat()
    }
    try:
        supabase.table("performance_records").insert(payload).execute()
        flash("Performance record saved successfully.", "success")
    except Exception as e:
        # Backward compatibility for legacy table definitions.
        fallback_payload = {
            key: value for key, value in payload.items()
            if key not in {"subject_ref_id", "subject_ref_type", "cycle_label", "academic_year"}
        }
        try:
            supabase.table("performance_records").insert(
                fallback_payload).execute()
            flash("Performance record saved (legacy schema mode).", "success")
        except Exception:
            flash(
                f"Could not save. Ensure 'performance_records' table exists in Supabase. ({str(e)[:100]})", "error")
    return redirect(redirect_url)


# ====================================================================================PORTAL - delete performance record====================

@app.route("/portal/delete_performance/<signed_id:record_id>", methods=["POST"])
def delete_performance(record_id):
    if not session.get("teacher_id") and not session.get("lecturer_id"):
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    school_id = int(request.form.get("school_id", 0))
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    classroom_id = int(request.form.get("classroom_id", 0))
    student_id = int(request.form.get("student_id", 0))
    student_type = request.form.get("student_type", "student")
    try:
        supabase.table("performance_records").delete().eq(
            "id", record_id).execute()
        flash("Record deleted.", "success")
    except Exception as e:
        flash(f"Could not delete record: {str(e)[:80]}", "error")
    return redirect(url_for("portal_student_performance",
                            school_id=school_id, classroom_id=classroom_id,
                            student_id=student_id, student_type=student_type))


# ====================================================================================PORTAL TERM RESULTS - classroom list====================

@app.route("/portal/<signed_id:school_id>/term_results")
def portal_term_results(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    actor_id = session.get("teacher_id") or session.get("lecturer_id")
    try:
        id_col = "teacher_id" if actor_type == "teacher" else "lecturer_id"
        classrooms = supabase.table("classrooms").select(
            "*").eq(id_col, actor_id).eq("school_id", school_id).execute().data or []
    except Exception:
        classrooms = []
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    return render_template("portal_term_results.html", school_id=school_id, classrooms=classrooms, actor_type=actor_type, cycle_meta=cycle_meta)


# ====================================================================================PORTAL TERM RESULTS - students in classroom====================

@app.route("/portal/<signed_id:school_id>/term_results/<signed_id:classroom_id>")
def portal_term_classroom(school_id, classroom_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    try:
        classroom = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).execute().data
        classroom = classroom[0] if classroom else None
    except Exception:
        classroom = None
    if not classroom or _parse_int(classroom.get("school_id")) != int(school_id):
        flash("Access denied for this classroom.", "error")
        return redirect(url_for("portal_term_results", school_id=school_id))

    students = []
    seen = set()
    try:
        member_records = supabase.table("classroom_members").select(
            "*").eq("classroom_id", classroom_id).execute().data or []
        for member in member_records:
            if member.get("student_id") and ("student", member["student_id"]) not in seen:
                seen.add(("student", member["student_id"]))
                resp = supabase.table("students").select(
                    "id,name").eq("id", member["student_id"]).execute()
                if resp.data:
                    students.append(
                        {"id": resp.data[0]["id"], "name": resp.data[0]["name"], "type": "student"})
            elif member.get("learner_id") and ("learner", member["learner_id"]) not in seen:
                seen.add(("learner", member["learner_id"]))
                resp = supabase.table("learners").select(
                    "id,name").eq("id", member["learner_id"]).execute()
                if resp.data:
                    students.append(
                        {"id": resp.data[0]["id"], "name": resp.data[0]["name"], "type": "learner"})
    except Exception:
        students = []
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    return render_template("portal_term_classroom.html",
                           school_id=school_id, classroom=classroom, students=students, actor_type=actor_type, cycle_meta=cycle_meta)


# ====================================================================================PORTAL TERM RESULTS - student term report====================

@app.route("/portal/<signed_id:school_id>/term_results/<signed_id:classroom_id>/student/<signed_id:student_id>/<student_type>", methods=["GET", "POST"])
def portal_term_student(school_id, classroom_id, student_id, student_type):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"teacher", "lecturer"})
    if gate:
        return gate

    actor_type = "teacher" if session.get("teacher_id") else "lecturer"
    actor_id = session.get("teacher_id") or session.get("lecturer_id")
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, actor_type)
    is_tertiary = cycle_meta["is_tertiary"]
    redirect_url = url_for("portal_term_student",
                           school_id=school_id, classroom_id=classroom_id,
                           student_id=student_id, student_type=student_type)

    try:
        classroom = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).execute().data
        classroom = classroom[0] if classroom else None
    except Exception:
        classroom = None
    if not classroom or _parse_int(classroom.get("school_id")) != int(school_id):
        flash("Access denied for this classroom.", "error")
        return redirect(url_for("portal_term_results", school_id=school_id))

    student_name = "Student"
    student_info = {}
    try:
        db_table = "students" if student_type == "student" else "learners"
        resp = supabase.table(db_table).select(
            "*").eq("id", student_id).execute()
        student_info = resp.data[0] if resp.data else {}
        student_name = student_info.get("name", "Student")
    except Exception:
        pass

    if request.method == "POST":
        action = request.form.get("action")
        if action == "record_term_result":
            if not cycle_meta["reports_open"]:
                flash("Reports section is currently closed by school admin.", "error")
                return redirect(redirect_url)
            subject_name = request.form.get("subject_name", "").strip()
            overall_mark = request.form.get("overall_mark", "").strip()
            total_possible = request.form.get("total_possible", "100").strip()
            teacher_comment = request.form.get("teacher_comment", "").strip()
            term_label = request.form.get("term_label", "").strip()
            academic_year = request.form.get("academic_year", "").strip()
            subject_ref_id = request.form.get("subject_ref_id")
            subject_ref_type = request.form.get("subject_ref_type")
            if not subject_name or not overall_mark:
                flash("Subject name and overall mark are required.", "error")
            else:
                try:
                    mark = float(overall_mark)
                    total = float(total_possible) if total_possible else 100.0
                    pct = round((mark / total) * 100, 2) if total > 0 else 0.0
                    symbol = calc_symbol(pct, is_tertiary)
                    payload = {
                        "student_id": student_id,
                        "student_type": student_type,
                        "classroom_id": classroom_id,
                        "subject_name": subject_name,
                        "subject_ref_id": int(subject_ref_id) if str(subject_ref_id).isdigit() else None,
                        "subject_ref_type": subject_ref_type or None,
                        "overall_mark": mark,
                        "total_possible": total,
                        "percentage": pct,
                        "symbol": symbol,
                        "teacher_comment": teacher_comment or None,
                        "term_label": term_label or cycle_meta["cycle_label"],
                        "academic_year": academic_year or cycle_meta["academic_year"],
                        "recorded_by_id": actor_id,
                        "recorded_by_type": actor_type,
                        "created_at": datetime.utcnow().isoformat()
                    }
                    try:
                        supabase.table("term_results").insert(
                            payload).execute()
                        flash("Term result recorded.", "success")
                    except Exception:
                        fallback_payload = {
                            key: value for key, value in payload.items()
                            if key not in {"subject_ref_id", "subject_ref_type"}
                        }
                        supabase.table("term_results").insert(
                            fallback_payload).execute()
                        flash("Term result recorded (legacy schema mode).", "success")
                except Exception as e:
                    flash(
                        f"Could not save. Ensure 'term_results' table exists in Supabase. ({str(e)[:100]})", "error")
        elif action == "publish_term_report":
            if not cycle_meta["reports_open"]:
                flash("Reports section is currently closed by school admin.", "error")
                return redirect(redirect_url)
            report_comment = request.form.get("report_comment", "").strip()
            report_overall_pct = _to_float(
                request.form.get("overall_percentage"), 0.0)
            report_cycle_label = request.form.get(
                "term_label", "").strip() or cycle_meta["cycle_label"]
            report_year = request.form.get(
                "academic_year", "").strip() or cycle_meta["academic_year"]

            term_rows = []
            try:
                term_rows = supabase.table("term_results").select("*").eq(
                    "classroom_id", classroom_id).eq("student_id", student_id).eq(
                    "student_type", student_type).eq("term_label", report_cycle_label).eq(
                    "academic_year", report_year).order("created_at", desc=False).execute().data or []
            except Exception:
                term_rows = []

            if not term_rows:
                flash(
                    "No term results found for this cycle. Record at least one result first.", "error")
                return redirect(redirect_url)

            if report_overall_pct <= 0:
                term_avg = [_to_float(r.get("percentage"), 0.0)
                            for r in term_rows]
                report_overall_pct = round(
                    sum(term_avg) / len(term_avg), 2) if term_avg else 0.0

            report_payload = {
                "classroom_id": classroom_id,
                "student_id": student_id,
                "student_type": student_type,
                "overall_percentage": report_overall_pct,
                "teacher_comment": report_comment or None,
                "term_label": report_cycle_label,
                "academic_year": report_year,
                "school_type": school.get("school_type") or None,
                "template_variant": "tertiary" if is_tertiary else "basic",
                "report_rows": render_report_payload(term_rows),
                "created_by_id": actor_id,
                "created_by_type": actor_type,
                "created_at": datetime.utcnow().isoformat()
            }
            try:
                supabase.table("term_report_documents").insert(
                    report_payload).execute()
                flash("Term/Semester report saved to history.", "success")
            except Exception as e:
                flash(
                    f"Could not publish report. Ensure 'term_report_documents' table exists. ({str(e)[:100]})",
                    "error",
                )
        elif action == "delete_term_result":
            result_id = request.form.get("result_id")
            try:
                supabase.table("term_results").delete().eq(
                    "id", result_id).execute()
                flash("Result deleted.", "success")
            except Exception as e:
                flash(f"Could not delete: {str(e)[:80]}", "error")
        return redirect(redirect_url)

    term_results = []
    try:
        term_results = supabase.table("term_results").select("*").eq(
            "classroom_id", classroom_id).eq("student_id", student_id).eq(
            "student_type", student_type).order("created_at", desc=False).execute().data or []
    except Exception:
        term_results = []

    gpa = 0.0
    if term_results:
        gpa_points = [symbol_to_gpa(r.get("symbol", "F"))
                      for r in term_results]
        gpa = round(sum(gpa_points) / len(gpa_points), 2)

    report_docs = []
    try:
        report_docs = supabase.table("term_report_documents").select("*").eq(
            "classroom_id", classroom_id).eq("student_id", student_id).eq(
            "student_type", student_type).order("created_at", desc=True).execute().data or []
    except Exception:
        report_docs = []

    subject_options = resolve_student_subjects(
        student_id, student_type, actor_type)
    subjects_list = [item["name"] for item in subject_options]

    cycle_options = {}
    for row in term_results:
        label = row.get("term_label") or "Unspecified"
        year = str(row.get("academic_year") or "Unknown")
        key = f"{year}::{label}"
        cycle_options[key] = {"label": label, "year": year}

    selected_cycle = request.args.get("cycle", "").strip()
    if not selected_cycle:
        selected_cycle = f"{cycle_meta['academic_year']}::{cycle_meta['cycle_label']}"
    if selected_cycle in cycle_options:
        term_results = [
            row for row in term_results
            if f"{str(row.get('academic_year') or 'Unknown')}::{row.get('term_label') or 'Unspecified'}" == selected_cycle
        ]
        if term_results:
            gpa_points = [symbol_to_gpa(r.get("symbol", "F"))
                          for r in term_results]
            gpa = round(sum(gpa_points) / len(gpa_points), 2)
        else:
            gpa = 0.0

    return render_template("portal_term_student.html",
                           school_id=school_id, classroom=classroom, classroom_id=classroom_id,
                           student_id=student_id, student_type=student_type,
                           student_name=student_name, student_info=student_info,
                           term_results=term_results, gpa=gpa,
                           actor_type=actor_type, is_tertiary=is_tertiary,
                           subjects_list=subjects_list,
                           subject_options=subject_options,
                           cycle_meta=cycle_meta,
                           cycle_options=[{"key": key, "label": val["label"], "year": val["year"]}
                                          for key, val in sorted(cycle_options.items(), reverse=True)],
                           selected_cycle=selected_cycle,
                           report_docs=report_docs)


@app.route("/portal/report/<signed_id:report_id>")
def portal_report_view(report_id):
    if not session.get("teacher_id") and not session.get("lecturer_id") and session.get("role") not in ["student", "learner"]:
        flash("Access denied.", "error")
        return redirect(url_for("login"))
    report_doc = None
    try:
        resp = supabase.table("term_report_documents").select(
            "*").eq("id", report_id).execute()
        report_doc = resp.data[0] if resp.data else None
    except Exception:
        report_doc = None
    if not report_doc:
        flash("Report not found.", "error")
        return redirect(url_for("login"))

    classroom_school_id = None
    try:
        classroom_rows = (
            supabase.table("classrooms")
            .select("school_id")
            .eq("id", report_doc.get("classroom_id"))
            .limit(1)
            .execute()
            .data
            or []
        )
        if classroom_rows:
            classroom_school_id = _parse_int(
                classroom_rows[0].get("school_id"))
    except Exception:
        classroom_school_id = None

    session_school_id = _parse_int(session.get("school_id"))
    if classroom_school_id is not None and session_school_id is not None and classroom_school_id != session_school_id:
        flash("Access denied for this school context.", "error")
        return redirect(_current_school_dashboard_url())

    # Learners and students can only read own reports.
    if session.get("role") in ["student", "learner"]:
        own_id = session.get("student_id") if session.get(
            "role") == "student" else session.get("learner_id")
        own_type = session.get("role")
        if report_doc.get("student_id") != own_id or report_doc.get("student_type") != own_type:
            flash("Access denied.", "error")
            return redirect(url_for("login"))

    return render_template("portal_report_view.html", report_doc=report_doc)


@app.route("/student-portal/<signed_id:school_id>")
def student_portal_dashboard(school_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"student", "learner"})
    if gate:
        return gate

    student_type = session.get("role")
    student_id = session.get(
        "student_id") if student_type == "student" else session.get("learner_id")
    if not student_id:
        flash("Student profile not found in session.", "error")
        return redirect(url_for("login"))

    # Find classrooms where this learner/student is a member.
    class_ids = []
    try:
        member_col = "student_id" if student_type == "student" else "learner_id"
        memberships = supabase.table("classroom_members").select(
            "classroom_id").eq(member_col, student_id).execute().data or []
        class_ids = [m.get("classroom_id")
                     for m in memberships if m.get("classroom_id") is not None]
    except Exception:
        class_ids = []

    classrooms = _select_classrooms_by_ids(class_ids)

    report_docs = []
    try:
        report_docs = supabase.table("term_report_documents").select("*").eq("student_id", student_id).eq(
            "student_type", student_type).order("created_at", desc=True).execute().data or []
    except Exception:
        report_docs = []

    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, "lecturer" if school.get(
        "school_type") == "tertiary" else "teacher")
    active_tab = (request.args.get("tab") or "grades").strip().lower()
    if active_tab not in {"grades", "results"}:
        active_tab = "grades"
    marks_enabled = bool(cycle_meta.get("marks_open", True))
    reports_enabled = bool(cycle_meta.get("reports_open", True))

    return render_template(
        "portal_student_dashboard.html",
        school_id=school_id,
        classrooms=classrooms,
        report_docs=report_docs,
        cycle_meta=cycle_meta,
        active_tab=active_tab,
        marks_enabled=marks_enabled,
        reports_enabled=reports_enabled,
    )


@app.route("/student-portal/<signed_id:school_id>/classroom/<signed_id:classroom_id>")
def student_portal_classroom(school_id, classroom_id):
    gate = _require_authenticated_school_context(
        school_id, allowed_roles={"student", "learner"})
    if gate:
        return gate

    student_type = session.get("role")
    student_id = session.get(
        "student_id") if student_type == "student" else session.get("learner_id")
    if not student_id:
        flash("Student profile not found in session.", "error")
        return redirect(url_for("login"))

    classroom = None
    try:
        resp = supabase.table("classrooms").select(
            "*").eq("id", classroom_id).execute()
        classroom = resp.data[0] if resp.data else None
    except Exception:
        classroom = None
    if not classroom:
        flash("Classroom not found.", "error")
        return redirect(url_for("student_portal_dashboard", school_id=school_id))
    if _parse_int(classroom.get("school_id")) != int(school_id):
        flash("Access denied for this classroom.", "error")
        return redirect(url_for("student_portal_dashboard", school_id=school_id))

    perf_rows = []
    school = get_school_record(school_id)
    cycle_meta = get_cycle_meta(school, "lecturer" if school.get(
        "school_type") == "tertiary" else "teacher")
    marks_enabled = bool(cycle_meta.get("marks_open", True))
    if marks_enabled:
        try:
            perf_rows = supabase.table("performance_records").select("*").eq("classroom_id", classroom_id).eq(
                "student_id", student_id).eq("student_type", student_type).order("created_at", desc=False).execute().data or []
        except Exception:
            perf_rows = []

    perf_rows = [
        row for row in perf_rows
        if (row.get("assignment_type") or "").strip().lower() in PORTAL_ASSESSMENT_TYPES
    ]

    # Build grouped display by cycle and subject.
    matrix = {}
    cycle_order = []
    for row in perf_rows:
        cycle_label = (row.get("cycle_label") or row.get(
            "term_label") or "Unspecified").strip() or "Unspecified"
        cycle_year = str(row.get("academic_year") or "Unknown")
        cycle_key = f"{cycle_year}::{cycle_label}"
        if cycle_key not in matrix:
            matrix[cycle_key] = {}
            cycle_order.append(cycle_key)
        subject = row.get("subject_name") or "Subject"
        if subject not in matrix[cycle_key]:
            matrix[cycle_key][subject] = {
                "test": None, "project": None, "exam": None}
        a_type = (row.get("assignment_type") or "test").strip().lower()
        matrix[cycle_key][subject][a_type] = _to_float(
            row.get("percentage"), 0.0)

    chart_points = [
        {
            "date": _safe_iso_date(row.get("created_at")),
            "type": (row.get("assignment_type") or "test").title(),
            "percentage": round(_to_float(row.get("percentage"), 0.0), 2),
        }
        for row in perf_rows
    ]

    return render_template(
        "portal_student_classroom.html",
        school_id=school_id,
        classroom=classroom,
        matrix=matrix,
        cycle_order=cycle_order,
        chart_points=chart_points,
        marks_enabled=marks_enabled,
    )


# =============================================================================
# ONLINE APPLICATION SYSTEM
# =============================================================================

EMRC_PROGRAMMES = [
    "Bachelor of Health Science in Emergency Medical Care and Rescue",
    "Diploma in Emergency Medical Care and Rescue",
    "Diploma in Occupational Safety and Health",
    "Certificate in Emergency Medical Care and Rescue",
    "Diploma in Rescue Technology",
    "Diploma in Disaster Management",
    "Diploma in Beauty Therapy and Aesthetics",
    "Diploma in Public Health",
    "BSc in Occupational Health and Safety",
    "BSc in Disasters Risk Reduction & Management",
    "BSc in Public Health Management",
]

EMRC_ACADEMIC_YEARS = ["2026/2027", "2027/2028", "2028/2029"]
EMRC_SECTIONS = ["Full Time", "Part Time", "Distance Learning"]

EMRC_PAYMENT_DETAILS = {
    "bank": "First National Bank (FNB)",
    "account_name": "Emergency Medical Rescue College",
    "account_type": "Business Account",
    "branch_code": "281764",
    "account_number": "63015617509",
    "swift_code": "FIRNSZMX",
    "fee": "E 300.00",
    "reference_format": "National ID/Passport Number + Surname + Initials",
}

APP_STEP_LABELS = [
    "Programme",
    "Personal Info",
    "Guardian / Payer",
    "Academic Background",
    "Documents",
    "Payment",
    "Review & Submit",
]


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


@app.route("/school/<signed_id:school_id>/apply")
def apply_instructions(school_id):
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    return render_template(
        "apply_instructions.html",
        school=school,
        menu_items=menu_items,
        payment_details=EMRC_PAYMENT_DETAILS,
    )


@app.route("/school/<signed_id:school_id>/apply/step/1", methods=["GET", "POST"])
def apply_step1(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    draft = _get_draft_application(ref) if ref else None

    if request.method == "POST":
        academic_year = (request.form.get("academic_year") or "").strip()
        qualification = (request.form.get("qualification") or "").strip()
        section = (request.form.get("section") or "").strip()
        errors = []
        if not academic_year:
            errors.append("Please select an academic year.")
        if not qualification:
            errors.append("Please select a qualification / programme.")
        if not section:
            errors.append("Please select a study mode.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "apply_step1.html",
                school=school,
                menu_items=menu_items,
                draft=draft,
                programmes=EMRC_PROGRAMMES,
                academic_years=EMRC_ACADEMIC_YEARS,
                sections=EMRC_SECTIONS,
                step_labels=APP_STEP_LABELS,
                step=1,
            )
        if not ref or not draft:
            ref = _generate_app_ref()
            supabase.table("online_applications").insert({
                "ref": ref,
                "school_id": school_id,
                "status": "draft",
                "academic_year": academic_year,
                "qualification": qualification,
                "section": section,
            }).execute()
            _set_apply_ref(school_id, ref)
        else:
            supabase.table("online_applications").update({
                "academic_year": academic_year,
                "qualification": qualification,
                "section": section,
            }).eq("ref", ref).execute()
        return redirect(url_for("apply_step2", school_id=school_id))

    return render_template(
        "apply_step1.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        programmes=EMRC_PROGRAMMES,
        academic_years=EMRC_ACADEMIC_YEARS,
        sections=EMRC_SECTIONS,
        step_labels=APP_STEP_LABELS,
        step=1,
    )


@app.route("/school/<signed_id:school_id>/apply/step/2", methods=["GET", "POST"])
def apply_step2(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        flash("Please start your application from step 1.", "error")
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        flash("Application session not found. Please start again.", "error")
        return redirect(url_for("apply_step1", school_id=school_id))

    if request.method == "POST":
        f = request.form
        errors = []
        surname = (f.get("surname") or "").strip()
        first_names = (f.get("first_names") or "").strip()
        dob = (f.get("dob") or "").strip()
        national_id = (f.get("national_id") or "").strip()
        disability = (f.get("disability") or "").strip()
        email = (f.get("email") or "").strip()
        phone = (f.get("phone") or "").strip()
        if not surname:
            errors.append("Surname is required.")
        if not first_names:
            errors.append("First name(s) are required.")
        if not dob:
            errors.append("Date of birth is required.")
        if not national_id:
            errors.append("National ID / Passport number is required.")
        if not disability:
            errors.append("Please indicate disability status.")
        if not email:
            errors.append("Email address is required.")
        if not phone:
            errors.append("Phone number is required.")
        if errors:
            for e in errors:
                flash(e, "error")
            merged = {**draft, **{k: f.get(k, "") for k in f}}
            return render_template(
                "apply_step2.html",
                school=school,
                menu_items=menu_items,
                draft=merged,
                step_labels=APP_STEP_LABELS,
                step=2,
            )
        supabase.table("online_applications").update({
            "title": (f.get("title") or "").strip() or None,
            "surname": surname,
            "first_names": first_names,
            "dob": dob,
            "gender": (f.get("gender") or "").strip() or None,
            "nationality": (f.get("nationality") or "").strip() or None,
            "national_id": national_id,
            "disability": disability,
            "disability_description": (f.get("disability_description") or "").strip() or None,
            "marital_status": (f.get("marital_status") or "").strip() or None,
            "region": (f.get("region") or "").strip() or None,
            "email": email,
            "phone": phone,
        }).eq("ref", ref).execute()
        return redirect(url_for("apply_step3", school_id=school_id))

    return render_template(
        "apply_step2.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        step_labels=APP_STEP_LABELS,
        step=2,
    )


@app.route("/school/<signed_id:school_id>/apply/step/3", methods=["GET", "POST"])
def apply_step3(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        return redirect(url_for("apply_step1", school_id=school_id))

    if request.method == "POST":
        f = request.form
        errors = []
        payer_surname = (f.get("payer_surname") or "").strip()
        payer_relationship = (f.get("payer_relationship") or "").strip()
        payer_tel = (f.get("payer_tel") or "").strip()
        payer_mobile = (f.get("payer_mobile") or "").strip()
        payer_email = (f.get("payer_email") or "").strip()
        payer_address = (f.get("payer_address") or "").strip()
        if not payer_surname:
            errors.append("Payer / Guardian surname is required.")
        if not payer_relationship:
            errors.append("Relationship to applicant is required.")
        if not payer_tel:
            errors.append("Telephone number is required.")
        if not payer_mobile:
            errors.append("Mobile number is required.")
        if not payer_email:
            errors.append("Payer / Guardian email is required.")
        if not payer_address:
            errors.append("Residential address is required.")
        if errors:
            for e in errors:
                flash(e, "error")
            merged = {**draft, **{k: f.get(k, "") for k in f}}
            return render_template(
                "apply_step3.html",
                school=school,
                menu_items=menu_items,
                draft=merged,
                step_labels=APP_STEP_LABELS,
                step=3,
            )
        supabase.table("online_applications").update({
            "payer_title": (f.get("payer_title") or "").strip() or None,
            "payer_surname": payer_surname,
            "payer_relationship": payer_relationship,
            "payer_tel": payer_tel,
            "payer_mobile": payer_mobile,
            "payer_email": payer_email,
            "payer_address": payer_address,
        }).eq("ref", ref).execute()
        return redirect(url_for("apply_step4", school_id=school_id))

    return render_template(
        "apply_step3.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        step_labels=APP_STEP_LABELS,
        step=3,
    )


@app.route("/school/<signed_id:school_id>/apply/step/4", methods=["GET", "POST"])
def apply_step4(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        return redirect(url_for("apply_step1", school_id=school_id))

    if request.method == "POST":
        f = request.form
        supabase.table("online_applications").update({
            "highest_qualification": (f.get("highest_qualification") or "").strip() or None,
            "institution_attended": (f.get("institution_attended") or "").strip() or None,
            "year_completed": (f.get("year_completed") or "").strip() or None,
            "subjects_passed": (f.get("subjects_passed") or "").strip() or None,
            "has_rpl": f.get("has_rpl") == "yes",
            "rpl_details": (f.get("rpl_details") or "").strip() or None,
        }).eq("ref", ref).execute()
        return redirect(url_for("apply_step5", school_id=school_id))

    return render_template(
        "apply_step4.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        step_labels=APP_STEP_LABELS,
        step=4,
    )


@app.route("/school/<signed_id:school_id>/apply/step/5", methods=["GET", "POST"])
def apply_step5(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        return redirect(url_for("apply_step1", school_id=school_id))

    existing_docs = (
        supabase.table("online_application_docs")
        .select("*")
        .eq("application_ref", ref)
        .execute()
        .data or []
    )
    existing_by_type = {d["doc_type"]: d for d in existing_docs}

    if request.method == "POST":
        upload_dir = os.path.join(APPLY_UPLOAD_FOLDER, ref)
        os.makedirs(upload_dir, exist_ok=True)
        doc_types = ["national_id_doc", "form5_results",
                     "payment_slip", "certificates"]
        for doc_type in doc_types:
            file = request.files.get(doc_type)
            if file and file.filename and file.filename != "":
                filename = secure_filename(file.filename)
                if not allowed_file(filename):
                    flash(
                        f"Invalid file type for '{doc_type.replace('_', ' ')}'. "
                        "Allowed: PDF, JPG, PNG, DOC.", "error"
                    )
                    continue
                stored_name = f"{uuid.uuid4().hex}_{filename}"
                file.save(os.path.join(upload_dir, stored_name))
                file_url = f"uploads/applications/{ref}/{stored_name}"
                if doc_type in existing_by_type:
                    supabase.table("online_application_docs").update({
                        "file_url": file_url,
                        "original_name": filename,
                    }).eq("id", existing_by_type[doc_type]["id"]).execute()
                else:
                    supabase.table("online_application_docs").insert({
                        "application_ref": ref,
                        "doc_type": doc_type,
                        "file_url": file_url,
                        "original_name": filename,
                    }).execute()
        return redirect(url_for("apply_step6", school_id=school_id))

    return render_template(
        "apply_step5.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        existing_docs=existing_by_type,
        step_labels=APP_STEP_LABELS,
        step=5,
    )


@app.route("/school/<signed_id:school_id>/apply/step/6", methods=["GET", "POST"])
def apply_step6(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        return redirect(url_for("apply_step1", school_id=school_id))

    if request.method == "POST":
        f = request.form
        errors = []
        payment_reference = (f.get("payment_reference") or "").strip()
        payment_date = (f.get("payment_date") or "").strip()
        if not payment_reference:
            errors.append("Please enter the reference you used at the bank.")
        if not payment_date:
            errors.append("Please enter the date of your deposit.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "apply_step6.html",
                school=school,
                menu_items=menu_items,
                draft=draft,
                payment_details=EMRC_PAYMENT_DETAILS,
                step_labels=APP_STEP_LABELS,
                step=6,
            )
        supabase.table("online_applications").update({
            "payment_reference": payment_reference,
            "payment_date": payment_date,
            "payment_amount": 300.00,
            "payment_bank": EMRC_PAYMENT_DETAILS["bank"],
        }).eq("ref", ref).execute()
        return redirect(url_for("apply_step7", school_id=school_id))

    return render_template(
        "apply_step6.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        payment_details=EMRC_PAYMENT_DETAILS,
        step_labels=APP_STEP_LABELS,
        step=6,
    )


@app.route("/school/<signed_id:school_id>/apply/step/7")
def apply_step7(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        return redirect(url_for("apply_step1", school_id=school_id))
    docs = (
        supabase.table("online_application_docs")
        .select("*")
        .eq("application_ref", ref)
        .execute()
        .data or []
    )
    return render_template(
        "apply_step7.html",
        school=school,
        menu_items=menu_items,
        draft=draft,
        docs=docs,
        step_labels=APP_STEP_LABELS,
        step=7,
    )


@app.route("/school/<signed_id:school_id>/apply/submit", methods=["POST"])
def apply_submit(school_id):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    ref = _get_apply_ref(school_id)
    if not ref:
        flash("Your session has expired. Please start a new application.", "error")
        return redirect(url_for("apply_step1", school_id=school_id))
    draft = _get_draft_application(ref)
    if not draft:
        flash("Application not found. Please start again.", "error")
        return redirect(url_for("apply_step1", school_id=school_id))
    if not request.form.get("declaration_accepted"):
        flash("You must accept the declaration before submitting.", "error")
        return redirect(url_for("apply_step7", school_id=school_id))
    from datetime import datetime
    supabase.table("online_applications").update({
        "status": "submitted",
        "declaration_accepted": True,
        "submitted_at": datetime.utcnow().isoformat(),
    }).eq("ref", ref).execute()

    school_name = (school or {}).get("name") or "School"
    applicant_name = " ".join(filter(None, [
        draft.get("title"),
        draft.get("surname"),
        draft.get("first_names"),
    ])).strip() or "Applicant"

    _notify_school_admins(
        school_id=school_id,
        title="New Application Submitted",
        message=(
            f"A new online application ({ref}) was submitted for {school_name}. "
            f"Applicant: {applicant_name}."
        ),
        notification_type="application",
        priority="high",
        send_email=True,
        send_sms=True,
        meta={"event": "application_submitted",
              "application_ref": ref, "school_id": school_id},
    )

    _notify_global_admins(
        title="Application Submitted",
        message=f"{school_name} received a new application: {ref}.",
        notification_type="application",
        priority="high",
        send_email=True,
        send_sms=True,
        meta={"event": "application_submitted",
              "application_ref": ref, "school_id": school_id},
    )

    _clear_apply_ref(school_id)
    return redirect(url_for("apply_confirmation", school_id=school_id, ref=ref))


@app.route("/school/<signed_id:school_id>/apply/confirmation/<ref>")
def apply_confirmation(school_id, ref):
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("schools_directory"))
    if not _school_application_enabled(school):
        return _apply_unavailable_redirect(school_id)
    menu_items = _apply_school_menu(school_id)
    application = _get_draft_application(ref)
    return render_template(
        "apply_confirmation.html",
        school=school,
        menu_items=menu_items,
        application=application,
        ref=ref,
    )


APPLICATION_SCREENING_REQUIRED_FIELDS = [
    ("academic_year", "Academic year"),
    ("qualification", "Qualification / programme"),
    ("section", "Study mode"),
    ("surname", "Applicant surname"),
    ("first_names", "Applicant first names"),
    ("dob", "Date of birth"),
    ("national_id", "National ID / Passport"),
    ("email", "Applicant email"),
    ("phone", "Applicant phone"),
    ("payer_surname", "Guardian / payer surname"),
    ("payer_relationship", "Guardian relationship"),
    ("payer_mobile", "Guardian mobile"),
    ("payer_email", "Guardian email"),
    ("payer_address", "Guardian address"),
    ("highest_qualification", "Highest qualification"),
    ("institution_attended", "Institution attended"),
    ("year_completed", "Year completed"),
    ("payment_reference", "Payment reference"),
    ("payment_date", "Payment date"),
]

APPLICATION_SCREENING_DOC_LABELS = {
    "national_id_doc": "National ID document",
    "form5_results": "Academic results",
    "payment_slip": "Payment slip",
    "certificates": "Certificates",
}

APPLICATION_SCREENING_RECOMMENDATION_LABELS = {
    "recommended": "Recommended",
    "review": "Manual Review",
    "needs_info": "Needs Information",
}


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

@app.route("/admin/school/<signed_id:school_id>/applications")
def admin_applications(school_id):
    gate = _require_admin_or_school_admin_for_school(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("admin_dashboard"))
    status_filter = request.args.get("status") or "all"
    builder = (
        supabase.table("online_applications")
        .select("*")
        .eq("school_id", school_id)
    )
    if status_filter and status_filter != "all":
        builder = builder.eq("status", status_filter)
    applications = builder.order("created_at", desc=True).execute().data or []
    screenings_by_ref = _get_latest_application_screenings_for_school(
        school_id)
    return render_template(
        "admin_applications.html",
        school=school,
        applications=applications,
        screenings_by_ref=screenings_by_ref,
        screening_labels=APPLICATION_SCREENING_RECOMMENDATION_LABELS,
        status_filter=status_filter,
    )


@app.route("/admin/school/<signed_id:school_id>/applications/<ref>", methods=["GET", "POST"])
def admin_application_detail(school_id, ref):
    gate = _require_admin_or_school_admin_for_school(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    if not school:
        return redirect(url_for("admin_dashboard"))
    application = _get_draft_application(ref)
    if not application or application.get("school_id") != school_id:
        flash("Application not found.", "error")
        return redirect(url_for("admin_applications", school_id=school_id))
    docs = (
        supabase.table("online_application_docs")
        .select("*")
        .eq("application_ref", ref)
        .execute()
        .data or []
    )
    latest_screening = _get_latest_application_screening(ref)
    if request.method == "POST":
        action = (request.form.get("action") or "update_status").strip()
        if action == "run_ai_screening":
            latest_screening = _generate_application_screening(
                school, application, docs)
            save_error = _save_application_screening(
                latest_screening,
                created_by=session.get(
                    "username") or session.get("role") or "admin",
            )
            if application.get("status") == "submitted":
                try:
                    reviewed_at = datetime.utcnow().isoformat()
                    supabase.table("online_applications").update({
                        "status": "under_review",
                        "reviewed_by": session.get("username") or "admin",
                        "reviewed_at": reviewed_at,
                    }).eq("ref", ref).execute()
                    application["status"] = "under_review"
                    application["reviewed_by"] = session.get(
                        "username") or "admin"
                    application["reviewed_at"] = reviewed_at
                except Exception:
                    pass
            if save_error:
                if _is_missing_application_screenings_table(save_error):
                    flash("Screening was generated, but persistence is not ready yet. Run schema_application_screenings.sql in Supabase to save screenings.", "info")
                else:
                    flash(
                        f"Screening was generated but could not be saved. ({str(save_error)[:100]})", "error")
                return render_template(
                    "admin_application_detail.html",
                    school=school,
                    application=application,
                    docs=docs,
                    latest_screening=latest_screening,
                    screening_labels=APPLICATION_SCREENING_RECOMMENDATION_LABELS,
                )
            flash("Application screening completed.", "success")
            return redirect(url_for("admin_application_detail", school_id=school_id, ref=ref))

        new_status = (request.form.get("status") or "").strip()
        admin_notes = (request.form.get("admin_notes") or "").strip()
        valid_statuses = ["submitted", "under_review",
                          "missing_docs", "accepted", "rejected"]
        if new_status in valid_statuses:
            supabase.table("online_applications").update({
                "status": new_status,
                "admin_notes": admin_notes or None,
                "reviewed_by": session.get("username") or "admin",
                "reviewed_at": datetime.utcnow().isoformat(),
            }).eq("ref", ref).execute()

            outcome_message = (
                f"Application {ref} status is now '{new_status.replace('_', ' ').title()}'."
            )

            _notify_school_admins(
                school_id=school_id,
                title="Application Status Updated",
                message=outcome_message,
                notification_type="application",
                priority="high" if new_status in {
                    "missing_docs", "accepted", "rejected"} else "normal",
                send_email=True,
                send_sms=new_status in {
                    "missing_docs", "accepted", "rejected"},
                meta={"event": "application_status_changed",
                      "application_ref": ref, "status": new_status},
            )

            _notify_global_admins(
                title="Application Workflow Update",
                message=f"{school.get('name') or 'School'}: {outcome_message}",
                notification_type="application",
                priority="high" if new_status in {
                    "missing_docs", "accepted", "rejected"} else "normal",
                send_email=True,
                send_sms=new_status in {
                    "missing_docs", "accepted", "rejected"},
                meta={"event": "application_status_changed",
                      "application_ref": ref, "status": new_status},
            )

            flash(f"Application {ref} updated to '{new_status}'.", "success")
            return redirect(url_for("admin_application_detail", school_id=school_id, ref=ref))
    return render_template(
        "admin_application_detail.html",
        school=school,
        application=application,
        docs=docs,
        latest_screening=latest_screening,
        screening_labels=APPLICATION_SCREENING_RECOMMENDATION_LABELS,
    )


# --- AI Helpers ---

@app.route("/ai/generate-report-comment", methods=["POST"])
def ai_generate_report_comment():
    """Generate a report comment draft using OpenAI GPT-4o-mini."""
    if not session.get("teacher_id") and not session.get("lecturer_id"):
        return jsonify({"error": "Access denied."}), 403

    client, config_error = _build_openai_client()
    if config_error:
        return jsonify({"error": config_error}), 503

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body."}), 400

    student_name = str(data.get("student_name", "the student"))[:80]
    subjects = data.get("subjects", [])
    gpa = data.get("gpa")
    is_tertiary = bool(data.get("is_tertiary", False))
    mode = data.get("mode", "overall")

    cycle_word = "semester" if is_tertiary else "term"
    role_word = "lecturer" if is_tertiary else "teacher"

    if mode not in {"overall", "subject"}:
        return jsonify({"error": "Unsupported AI comment mode."}), 400

    if mode == "subject":
        if not subjects:
            return jsonify({"error": "No subject data provided."}), 400
        s = subjects[0]
        subject_name = str(s.get("name") or "").strip()
        if not subject_name:
            return jsonify({"error": "Subject name is required for subject comment generation."}), 400
        pct_str = f"{s.get('pct')}%" if s.get(
            "pct") is not None else "an unrecorded mark"
        scored_str = f"{s.get('scored')}/{s.get('total')}" if s.get("scored") else ""
        prompt = (
            f"You are a {role_word} writing a brief subject comment for a school report card. "
            f"Student: {student_name}. Subject: {subject_name}. "
            f"Score: {scored_str} ({pct_str}). "
            f"Write a single professional, constructive, and encouraging sentence (max 30 words) "
            f"as the {cycle_word} comment for this subject. No quotes or bullet points."
        )
    else:
        if not subjects:
            return jsonify({"error": "No subjects provided for overall comment."}), 400
        subject_lines = "\n".join(
            f"- {s.get('name', '?')}: {s.get('pct', '?')}% ({s.get('symbol', '?')})"
            for s in subjects
        )
        gpa_text = f" Overall GPA: {gpa}." if gpa is not None else ""
        prompt = (
            f"You are a {role_word} writing an overall {cycle_word} report comment for a formal school report card.\n"
            f"Student: {student_name}.{gpa_text}\n"
            f"Subject results:\n{subject_lines}\n\n"
            f"Write 2-3 professional, encouraging, and honest sentences as the overall comment. "
            f"Mention strong subjects and areas needing improvement where relevant. "
            f"Suitable for a formal school report card. Plain sentences only - no bullet points, headings, or quotes."
        )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.72,
        )
        comment = (
            (response.choices[0].message.content if response.choices else "") or "").strip()
        if not comment:
            return jsonify({"error": "AI returned an empty response. Please try again."}), 502
        return jsonify({"comment": comment})
    except _OpenAIAuthenticationError:
        app.logger.exception(
            "OpenAI authentication failed while generating report comment.")
        return jsonify({"error": "OpenAI rejected the API key. Check OPENAI_API_KEY in your .env file."}), 502
    except _OpenAIRateLimitError:
        app.logger.exception(
            "OpenAI rate limit hit while generating report comment.")
        return jsonify({"error": "OpenAI rate limit reached. Please wait a moment and try again."}), 429
    except _OpenAIConnectionError:
        app.logger.exception(
            "OpenAI connection error while generating report comment.")
        return jsonify({"error": "Could not reach OpenAI. Check your internet connection and try again."}), 502
    except Exception as exc:
        if _httpx_available and isinstance(exc, _httpx.ReadError):
            app.logger.exception(
                "HTTPX read error while generating report comment.")
            return jsonify({"error": "Temporary network read error while contacting OpenAI. Please retry."}), 502
        app.logger.exception("Unexpected AI generation error.")
        return jsonify({"error": f"AI generation failed: {str(exc)[:120]}"}), 500


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


@app.route("/ai/instructor-dashboard-bot", methods=["POST"])
def ai_instructor_dashboard_bot():
    identity, identity_error = _instructor_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = request.form.to_dict(flat=True)

    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Please enter your AI question."}), 400

    selected_classroom_id = _parse_int(payload.get("classroom_id"))
    requires_premium = _instructor_dashboard_requires_premium(message)
    if requires_premium and not INSTRUCTOR_AI_PREMIUM_ENABLED:
        return jsonify({
            "error": "This instructor analytics request is a premium feature. Enable premium to use submission/AI/plagiarism dashboard intelligence."
        }), 403

    snapshot = _instructor_dashboard_context(
        identity,
        classroom_id=selected_classroom_id,
        include_analytics=INSTRUCTOR_AI_PREMIUM_ENABLED,
    )

    context_text = (
        "INSTRUCTOR SUMMARY:\n"
        f"- Your role: {identity.get('role')}\n"
        f"- School classrooms total: {snapshot['counts'].get('school_classrooms', 0)}\n"
        f"- Your classrooms total: {snapshot['counts'].get('owned_classrooms', 0)}\n"
        f"- Selected classrooms: {snapshot['counts'].get('selected_classrooms', 0)}\n\n"
        "YOUR CLASSROOMS:\n" +
        "\n".join(snapshot.get("classroom_lines") or [
                  "- No classroom rows found."]) + "\n\n"
        "LATEST ASSIGNMENTS:\n" + "\n".join(snapshot.get("latest_assignment_lines") or [
                                            "- No assignment rows found."]) + "\n\n"
        "PREMIUM ANALYTICS (submission coverage):\n" + "\n".join(snapshot.get(
            "analytics_lines") or ["- Premium analytics disabled or no data."])
    )[:15000]

    client, config_error = _build_openai_client()
    if config_error:
        return jsonify({
            "mode": "offline_fallback",
            "reply": (
                "AI service is unavailable right now, but here is your latest local snapshot.\n\n"
                + context_text
            ),
            "used_context": snapshot.get("counts", {}),
            "premium_enabled": INSTRUCTOR_AI_PREMIUM_ENABLED,
        })

    prompt = (
        "You are an educator dashboard copilot for teachers and lecturers. "
        "Answer with practical, clear guidance. Use provided school/classroom context when available. "
        "If the user asks general world questions, answer normally like a global assistant. "
        "If data is missing, say what is missing and suggest next step.\n\n"
        f"INSTRUCTOR QUESTION:\n{message[:2200]}\n\n"
        f"CONTEXT:\n{context_text}"
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a wise, practical AI copilot for school dashboards."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700,
            temperature=0.32,
        )
        reply = (
            (response.choices[0].message.content if response.choices else "") or "").strip()
        if not reply:
            return jsonify({"error": "AI returned an empty response."}), 502
        return jsonify({
            "mode": "ai",
            "reply": reply,
            "used_context": snapshot.get("counts", {}),
            "premium_enabled": INSTRUCTOR_AI_PREMIUM_ENABLED,
        })
    except Exception as exc:
        return jsonify({"error": f"Instructor dashboard AI failed: {str(exc)[:120]}"}), 502


@app.route("/ai/instructor-bulk-marking-table", methods=["POST"])
def ai_instructor_bulk_marking_table():
    identity, identity_error = _instructor_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403
    if not INSTRUCTOR_AI_PREMIUM_ENABLED:
        return jsonify({
            "error": "Bulk AI marking table is a premium feature and is currently disabled."
        }), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = request.form.to_dict(flat=True)

    classroom_id = _parse_int(payload.get("classroom_id"))
    if classroom_id is None:
        return jsonify({"error": "classroom_id is required."}), 400
    assignment_id = _parse_int(payload.get("assignment_id"))

    bundle = _instructor_ai_get_classroom_bundle(classroom_id)
    if not bundle:
        return jsonify({"error": "Classroom not found."}), 404
    classroom = bundle.get("classroom") or {}
    if identity.get("school_id") and classroom.get("school_id") and str(identity.get("school_id")) != str(classroom.get("school_id")):
        return jsonify({"error": "Classroom is outside your school scope."}), 403

    assignments = bundle.get("assignments") or []
    submissions = bundle.get("submissions") or []
    if assignment_id is not None:
        submissions = [s for s in submissions if str(
            s.get("assignment_id")) == str(assignment_id)]

    if not submissions:
        return jsonify({
            "rows": [],
            "counts": {"assignments": len(assignments), "submissions": 0},
            "table_html": "",
            "note": "No submissions available for bulk AI table yet.",
        })

    assignment_map = {
        str(a.get("id")): a for a in assignments if a.get("id") is not None}
    pair_candidates = _instructor_ai_similarity_report(submissions)
    max_similarity = {}
    for pair in pair_candidates:
        pct = _to_float(pair.get("similarity_pct"), 0.0)
        a_id = str(pair.get("submission_a_id"))
        b_id = str(pair.get("submission_b_id"))
        max_similarity[a_id] = max(max_similarity.get(a_id, 0.0), pct)
        max_similarity[b_id] = max(max_similarity.get(b_id, 0.0), pct)

    rows = []
    ai_input = []
    for submission in submissions[:60]:
        sub_id = submission.get("id")
        assignment = assignment_map.get(
            str(submission.get("assignment_id"))) or {}
        submission_text = ((submission.get("submission_text") or "") + "\n" +
                           (submission.get("file_text") or "")).strip()
        ai_pct, ai_cues = _instructor_ai_ai_content_fallback(submission_text)
        similarity_pct = round(max_similarity.get(str(sub_id), 0.0), 1)
        heuristic_score = int(max(30, min(
            95, round(78 - (ai_pct * 0.12) - (similarity_pct * 0.16)))))

        row = {
            "submission_id": sub_id,
            "assignment_id": submission.get("assignment_id"),
            "assignment_title": assignment.get("title") or "Assignment",
            "submitter": submission.get("submitted_by_name") or "Student",
            "score": heuristic_score,
            "out_of": 100,
            "ai_content_pct": round(ai_pct, 1),
            "plagiarism_similarity_pct": similarity_pct,
            "plagiarism_risk": "high" if similarity_pct >= 75 else "medium" if similarity_pct >= 55 else "low",
            "score_summary": "Heuristic draft generated; AI refinement pending.",
            "submitted_at": submission.get("submitted_at"),
            "signals": ai_cues[:3],
        }
        rows.append(row)
        ai_input.append({
            "submission_id": sub_id,
            "assignment": row["assignment_title"],
            "student": row["submitter"],
            "assignment_description": (assignment.get("description") or "")[:700],
            "submission_excerpt": submission_text[:1200],
        })

    client, config_error = _build_openai_client()
    if not config_error and ai_input:
        prompt = (
            "You are an assessment copilot. For each submission, provide a conservative draft mark and a one-line rationale. "
            "Return strict JSON: {rows:[{submission_id:number, score:number, out_of:number, score_summary:string}]}. "
            "Use out_of=100 for all unless impossible. No extra keys.\n\n"
            f"Submissions:\n{std_json.dumps(ai_input)[:21000]}"
        )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You help lecturers/teachers triage bulk marking drafts."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
                temperature=0.2,
            )
            parsed = std_json.loads(
                ((response.choices[0].message.content if response.choices else "") or "{}").strip())
            ai_rows = parsed.get("rows") or []
            ai_map = {str(item.get("submission_id")): item for item in ai_rows}
            for row in rows:
                update = ai_map.get(str(row.get("submission_id")))
                if not update:
                    continue
                maybe_score = _parse_int(update.get("score"))
                maybe_out_of = _parse_int(update.get("out_of")) or 100
                if maybe_score is not None:
                    row["score"] = max(0, min(maybe_out_of, maybe_score))
                row["out_of"] = max(1, maybe_out_of)
                summary = (update.get("score_summary") or "").strip()
                if summary:
                    row["score_summary"] = summary[:280]
        except Exception:
            pass

    rows.sort(key=lambda r: (
        -_to_float(r.get("plagiarism_similarity_pct"), 0.0),
        -_to_float(r.get("ai_content_pct"), 0.0),
        str(r.get("submitter") or ""),
    ))

    table_headers = [
        "Submitter",
        "Assignment",
        "Score",
        "AI Content %",
        "Plagiarism %",
        "Risk",
        "AI Summary",
    ]
    table_rows = []
    for row in rows[:80]:
        table_rows.append([
            row.get("submitter") or "Student",
            row.get("assignment_title") or "Assignment",
            f"{row.get('score')}/{row.get('out_of')}",
            f"{row.get('ai_content_pct')}%",
            f"{row.get('plagiarism_similarity_pct')}%",
            row.get("plagiarism_risk") or "low",
            row.get("score_summary") or "",
        ])

    return jsonify({
        "rows": rows,
        "columns": table_headers,
        "table_rows": table_rows,
        "counts": {
            "assignments": len(assignments),
            "submissions": len(submissions),
            "rows": len(rows),
        },
        "note": "AI bulk table is draft guidance only. Final marking decisions must be lecturer/teacher approved.",
    })


@app.route("/ai/instructor-assistant", methods=["POST"])
def ai_instructor_assistant():
    identity, identity_error = _instructor_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403
    if not INSTRUCTOR_AI_PREMIUM_ENABLED:
        return jsonify({
            "error": "Instructor AI is currently disabled. Enable premium plan features to activate this module."
        }), 403

    payload = request.form.to_dict(flat=True)
    task = (payload.get("task") or "generate_assessment").strip().lower()
    if task not in {"generate_assessment", "mark_submission", "detect_ai_content", "detect_similarity"}:
        return jsonify({"error": "Unsupported instructor AI task."}), 400

    classroom_id = _parse_int(payload.get("classroom_id"))
    if classroom_id is None:
        return jsonify({"error": "classroom_id is required."}), 400

    bundle = _instructor_ai_get_classroom_bundle(classroom_id)
    if not bundle:
        return jsonify({"error": "Classroom not found."}), 404
    classroom = bundle.get("classroom") or {}
    if identity.get("school_id") and classroom.get("school_id") and str(identity.get("school_id")) != str(classroom.get("school_id")):
        return jsonify({"error": "Classroom is outside your school scope."}), 403

    uploaded_assets = _instructor_ai_parse_uploaded_files(
        request.files.getlist("notes_files"), max_chars=9000)
    rubric_assets = _instructor_ai_parse_uploaded_files(
        [request.files.get("rubric_file")], max_chars=7000)
    guide_assets = _instructor_ai_parse_uploaded_files(
        [request.files.get("marking_guide_file")], max_chars=7000)
    context_text = _instructor_ai_prompt_context(bundle, uploaded_assets)

    if task == "detect_similarity":
        assignment_id = _parse_int(payload.get("assignment_id"))
        targets = bundle.get("submissions") or []
        if assignment_id is not None:
            targets = [s for s in targets if str(
                s.get("assignment_id")) == str(assignment_id)]
        pairs = _instructor_ai_similarity_report(targets)
        return jsonify({
            "task": task,
            "pair_count": len(pairs),
            "pairs": pairs,
            "note": "Similarity is an indicator only. Use teacher judgment before action.",
        })

    message = (payload.get("message") or "").strip()
    client, config_error = _build_openai_client()

    if task == "detect_ai_content":
        submission_id = _parse_int(payload.get("submission_id"))
        target = None
        for sub in bundle.get("submissions") or []:
            if submission_id is not None and str(sub.get("id")) == str(submission_id):
                target = sub
                break
        if not target:
            return jsonify({"error": "Pick a valid submission to analyze."}), 400

        submission_text = ((target.get("submission_text") or "") + "\n" +
                           (target.get("file_text") or "")).strip()
        fallback_pct, fallback_cues = _instructor_ai_ai_content_fallback(
            submission_text)

        ai_pct = fallback_pct
        ai_notes = list(fallback_cues)
        if not config_error and submission_text:
            prompt = (
                "Estimate likelihood that this student submission was AI-generated. "
                "Return JSON: {ai_content_pct:number, rationale:[...], confidence:'low|medium|high'}. "
                "Use cautious language and do not claim certainty.\n\n"
                f"Submission text:\n{submission_text[:12000]}"
            )
            try:
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[{"role": "system", "content": "You are an academic integrity assistant."}, {
                        "role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=260,
                    temperature=0.15,
                )
                parsed = std_json.loads(
                    ((response.choices[0].message.content if response.choices else "") or "{}").strip())
                ai_pct = max(0.0, min(100.0, float(
                    parsed.get("ai_content_pct", fallback_pct))))
                ai_notes = [str(x) for x in (parsed.get(
                    "rationale") or [])][:5] or ai_notes
                confidence = str(parsed.get("confidence") or "medium")
            except Exception:
                confidence = "low"
        else:
            confidence = "low"

        return jsonify({
            "task": task,
            "submission_id": target.get("id"),
            "student": target.get("submitted_by_name") or "Student",
            "ai_content_pct": round(ai_pct, 1),
            "confidence": confidence,
            "signals": ai_notes,
            "warning": "AI-content estimation is advisory and must be verified by teacher review.",
        })

    if task == "mark_submission":
        assignment_id = _parse_int(payload.get("assignment_id"))
        submission_id = _parse_int(payload.get("submission_id"))
        answer_key_text = (payload.get("answer_key") or "").strip()
        if not assignment_id or not submission_id:
            return jsonify({"error": "assignment_id and submission_id are required for marking."}), 400

        assignment = next((a for a in bundle.get("assignments") or [] if str(
            a.get("id")) == str(assignment_id)), None)
        submission = next((s for s in bundle.get("submissions") or [] if str(
            s.get("id")) == str(submission_id)), None)
        if not assignment or not submission:
            return jsonify({"error": "Assignment or submission not found for this classroom."}), 404

        submission_text = ((submission.get("submission_text") or "") + "\n" +
                           (submission.get("file_text") or "")).strip()
        rubric_text = "\n".join(
            [asset.get("text") or "" for asset in rubric_assets[:2]])
        guide_text = "\n".join(
            [asset.get("text") or "" for asset in guide_assets[:2]])

        if config_error:
            pct, cues = _instructor_ai_ai_content_fallback(submission_text)
            return jsonify({
                "task": task,
                "mode": "offline_fallback",
                "student": submission.get("submitted_by_name") or "Student",
                "draft_score": 60,
                "out_of": 100,
                "strengths": ["Submission captured and available for manual teacher review."],
                "gaps": ["AI marking unavailable right now.", "Use rubric and guide manually."],
                "feedback": "Use this as a draft assistant output only; final marks should be teacher-approved.",
                "ai_content_pct": pct,
                "integrity_flags": cues,
            })

        prompt = (
            "You are an assessment assistant for teachers/lecturers. Mark this submission using rubric and guide if provided. "
            "Return strict JSON with keys: score, out_of, strengths[], gaps[], feedback, rubric_alignment[], confidence, teacher_review_required. "
            "Be conservative and transparent about uncertainty.\n\n"
            f"Classroom: {classroom.get('name') or 'Class'}\n"
            f"Assignment title: {assignment.get('title') or 'Assignment'}\n"
            f"Assignment description: {(assignment.get('description') or '')[:1500]}\n"
            f"Answer key/keywords: {answer_key_text[:2000]}\n\n"
            f"Rubric text: {rubric_text[:5000]}\n\n"
            f"Marking guide text: {guide_text[:5000]}\n\n"
            f"Student submission by {submission.get('submitted_by_name') or 'Student'}:\n{submission_text[:10000]}"
        )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You help teachers mark work but always require teacher verification."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=650,
                temperature=0.2,
            )
            parsed = std_json.loads(
                ((response.choices[0].message.content if response.choices else "") or "{}").strip())
        except Exception as exc:
            return jsonify({"error": f"AI marking failed: {str(exc)[:120]}"}), 502

        ai_pct, cues = _instructor_ai_ai_content_fallback(submission_text)
        similarity_pairs = _instructor_ai_similarity_report(
            [s for s in (bundle.get("submissions") or []) if str(s.get("assignment_id")) == str(assignment_id)])
        related_pairs = [p for p in similarity_pairs if str(
            submission_id) in {str(p.get("submission_a_id")), str(p.get("submission_b_id"))}][:5]

        return jsonify({
            "task": task,
            "mode": "ai",
            "student": submission.get("submitted_by_name") or "Student",
            "assignment": assignment.get("title") or "Assignment",
            "score": parsed.get("score"),
            "out_of": parsed.get("out_of") or 100,
            "strengths": parsed.get("strengths") or [],
            "gaps": parsed.get("gaps") or [],
            "feedback": parsed.get("feedback") or "",
            "rubric_alignment": parsed.get("rubric_alignment") or [],
            "confidence": parsed.get("confidence") or "medium",
            "teacher_review_required": True,
            "ai_content_pct": ai_pct,
            "integrity_flags": cues,
            "similarity_matches": related_pairs,
        })

    # generate_assessment
    assessment_type = (payload.get("assessment_type")
                       or "quiz").strip().lower()
    if assessment_type not in {"quiz", "test", "exam_practice", "worksheet"}:
        assessment_type = "quiz"
    question_count = _parse_int(payload.get("question_count")) or 8
    question_count = max(3, min(25, question_count))

    if config_error:
        fallback = {
            "title": f"{assessment_type.title()} Draft",
            "questions": [
                {"question": "Define the core concept from the latest lecture.",
                    "answer_key": "Teacher-defined", "marks": 5},
                {"question": "Explain one practical application of the topic.",
                    "answer_key": "Teacher-defined", "marks": 5},
                {"question": "Compare two related concepts discussed in class.",
                    "answer_key": "Teacher-defined", "marks": 5},
            ],
            "note": "Offline fallback draft. Review and customize before publishing.",
        }
        return jsonify({"task": task, "mode": "offline_fallback", "assessment": fallback})

    prompt = (
        f"Create a {assessment_type} for classroom teaching. "
        f"Generate exactly {question_count} high-quality questions from class notes, uploaded files, and teacher instructions. "
        "Mix levels (easy/medium/hard), include answer keys and mark allocation. "
        "Return strict JSON with keys: title, instructions, questions[{question,answer_key,marks,difficulty,source_hint}], total_marks, teacher_tips.\n\n"
        f"Teacher request: {message[:1200]}\n\n"
        f"Grounding context:\n{context_text}"
    )

    messages = [
        {"role": "system", "content": "You are an expert instructional designer for school and university assessments."},
        {"role": "user", "content": prompt},
    ]
    image_assets = [a for a in uploaded_assets if a.get("image_data_url")][:2]
    for asset in image_assets:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text",
                    "text": f"Use this image note/media as part of source material: {asset.get('name')}"},
                {"type": "image_url", "image_url": {
                    "url": asset.get("image_data_url")}},
            ],
        })

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=1200,
            temperature=0.35,
        )
        parsed = std_json.loads(
            ((response.choices[0].message.content if response.choices else "") or "{}").strip())
    except Exception as exc:
        return jsonify({"error": f"Assessment generation failed: {str(exc)[:120]}"}), 502

    return jsonify({
        "task": task,
        "mode": "ai",
        "assessment": parsed,
        "source_assets": [{"name": a.get("name"), "type": a.get("mimetype") or a.get("ext")} for a in uploaded_assets],
    })


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


@app.route("/ai/student-study-bot", methods=["POST"])
def ai_student_study_bot():
    identity, identity_error = _student_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403

    payload = {}
    image_file = None
    if request.content_type and "multipart/form-data" in request.content_type.lower():
        payload = request.form.to_dict(flat=True)
        image_file = request.files.get("image")
    else:
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            return jsonify({"error": "Invalid request body."}), 400

    task = (payload.get("task") or "chat").strip().lower()
    message = (payload.get("message") or "").strip()
    if task not in {"chat", "quiz", "plan", "review"}:
        return jsonify({"error": "Unsupported task type."}), 400
    if task in {"chat", "plan", "review"} and not message:
        return jsonify({"error": "Please enter a question or topic."}), 400

    preferred_classroom_id = payload.get("classroom_id")
    if preferred_classroom_id in {"", None, "all"}:
        preferred_classroom_id = None
    else:
        preferred_classroom_id = _parse_int(preferred_classroom_id)

    question_count = _parse_int(payload.get("question_count")) or 5
    if question_count < 3:
        question_count = 3
    if question_count > 12:
        question_count = 12

    lock_classroom = _to_bool(payload.get("lock_classroom"), default=False)
    if lock_classroom and preferred_classroom_id is None:
        return jsonify({"error": "Select a classroom when classroom lock is enabled."}), 400

    image_name = None
    image_data_url = None
    if image_file and image_file.filename:
        if not (image_file.mimetype or "").lower().startswith("image/"):
            return jsonify({"error": "Only image uploads are supported in Study AI chat."}), 400
        consumed_count, media_ready = _student_ai_count_media_today(identity)
        if media_ready and STUDY_AI_MEDIA_DAILY_LIMIT > 0 and consumed_count >= STUDY_AI_MEDIA_DAILY_LIMIT:
            return jsonify({
                "error": f"Daily image limit reached ({STUDY_AI_MEDIA_DAILY_LIMIT}/day). Paid plans can raise this later."
            }), 429
        blob = image_file.read()
        if not blob:
            return jsonify({"error": "Uploaded image is empty."}), 400
        if len(blob) > 6 * 1024 * 1024:
            return jsonify({"error": "Image too large. Max size is 6MB."}), 400
        encoded = base64.b64encode(blob).decode("ascii")
        image_name = secure_filename(image_file.filename)
        image_data_url = f"data:{image_file.mimetype};base64,{encoded}"

    context_bundle = _student_ai_fetch_context(
        identity,
        preferred_classroom_id=preferred_classroom_id,
        strict_preferred=lock_classroom,
    )
    if lock_classroom and not context_bundle.get("classrooms"):
        return jsonify({"error": "Selected classroom is not available in your membership list."}), 400

    snapshot = _student_ai_context_snapshot(context_bundle)

    school_classrooms_total = 0
    if identity.get("school_id"):
        try:
            school_rows = supabase.table("classrooms").select("id").eq(
                "school_id", identity.get("school_id")).limit(2000).execute().data or []
            school_classrooms_total = len(school_rows)
        except Exception:
            school_classrooms_total = 0

    context_text = (
        f"SCHOOL OVERVIEW:\nTotal classrooms in school: {school_classrooms_total}\n\n"
        "CLASSROOM POSTS:\n" + "\n".join(snapshot["posts"]) + "\n\n"
        "MATERIALS:\n" + "\n".join(snapshot["materials"]) + "\n\n"
        "ASSIGNMENTS:\n" + "\n".join(snapshot["assignments"]) + "\n\n"
        "MY SUBMISSIONS:\n" + "\n".join(snapshot["submissions"]) + "\n\n"
        "WEAKNESSES:\n" + "\n".join(snapshot["weaknesses"])
    )[:16000]

    if task == "quiz":
        user_prompt = message or "Generate a revision quiz from the latest classroom notes and teacher instructions."
        instruction = (
            f"You are StudyMate AI helping {identity.get('name')} prepare for tests. "
            "Use classroom context first. If teacher posts mention specific lecture numbers or test focus, prioritize those sources. "
            "Video files may exist but cannot be read directly; use titles/descriptions only. "
            f"Create exactly {question_count} revision questions with answer keys."
        )
        output_instruction = (
            "Return valid JSON only with this shape: "
            "{\"quiz_title\":\"...\",\"questions\":[{\"question\":\"...\",\"answer\":\"...\",\"explanation\":\"...\",\"difficulty\":\"easy|medium|hard\",\"source_hint\":\"...\"}],\"study_tips\":[\"...\"]}."
        )
    elif task == "plan":
        user_prompt = message
        instruction = (
            f"You are StudyMate AI helping {identity.get('name')} build a practical revision plan. "
            "Ground advice in classroom posts, materials, assignments, and weaknesses. "
            "Return concise steps, with day-by-day actions and practice targets."
        )
        output_instruction = "Respond in short sections: Focus, 7-day Plan, Practice Targets, and Questions to Ask Teacher."
    elif task == "review":
        user_prompt = message
        instruction = (
            f"You are StudyMate AI helping {identity.get('name')} improve weak areas using previous performance records. "
            "Identify likely weak subjects/topics, explain why, and propose targeted drills from available class materials."
        )
        output_instruction = "Respond with: Weakness Analysis, What to Review First, Drill Questions, and Confidence Check."
    else:
        user_prompt = message
        instruction = (
            f"You are StudyMate AI for {identity.get('name')}. "
            "Primary mode: grounded classroom tutor using posts, notes/materials metadata, assignments, and performance trends. "
            "If the student asks broader world/general knowledge, answer normally like a global AI tutor. "
            "Always be clear, supportive, and practical."
        )
        output_instruction = "Keep response structured and actionable. Mention classroom source hints when relevant."

    client, config_error = _build_openai_client()
    if config_error:
        fallback = _student_ai_fallback_answer(task, user_prompt, snapshot)
        fallback["mode"] = "offline_fallback"
        _student_ai_save_chat_history(
            identity,
            task,
            user_prompt,
            fallback.get("reply") or std_json.dumps(
                fallback.get("quiz") or {}),
            fallback["mode"],
            snapshot.get("counts", {}),
            classroom_id=preferred_classroom_id,
            has_image=bool(image_data_url),
            image_name=image_name,
        )
        return jsonify(fallback)

    prompt = (
        f"TASK: {task}\n"
        f"STUDENT ASK: {user_prompt}\n\n"
        f"INSTRUCTIONS:\n{instruction}\n{output_instruction}\n\n"
        "GROUNDING CONTEXT (latest classroom information):\n"
        f"{context_text}"
    )

    try:
        request_payload = {
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system",
                    "content": "You are a smart, safe school study assistant."},
            ],
            "temperature": 0.35,
            "max_tokens": 900,
        }
        if image_data_url:
            request_payload["messages"].append({"role": "user", "content": (
                "Use this classroom context first before answering.\n\n"
                + prompt
            )})
            request_payload["messages"].append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Student message: {user_prompt}\nAlso analyze the uploaded image if relevant."},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            })
        else:
            request_payload["messages"].append(
                {"role": "user", "content": prompt})

        if task == "quiz":
            request_payload["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**request_payload)
        content = (
            (response.choices[0].message.content if response.choices else "") or "").strip()
        if not content:
            return jsonify({"error": "AI returned an empty response."}), 502

        if task == "quiz":
            try:
                parsed = std_json.loads(content)
            except Exception:
                parsed = {
                    "quiz_title": "Classroom Revision Quiz",
                    "questions": [],
                    "study_tips": ["AI returned non-JSON content. Please retry."]
                }
            _student_ai_save_chat_history(
                identity,
                task,
                user_prompt,
                std_json.dumps(parsed),
                "ai",
                snapshot.get("counts", {}),
                classroom_id=preferred_classroom_id,
                has_image=bool(image_data_url),
                image_name=image_name,
            )
            return jsonify({
                "mode": "ai",
                "task": task,
                "quiz": parsed,
                "used_context": snapshot.get("counts", {}),
            })

        _student_ai_save_chat_history(
            identity,
            task,
            user_prompt,
            content,
            "ai",
            snapshot.get("counts", {}),
            classroom_id=preferred_classroom_id,
            has_image=bool(image_data_url),
            image_name=image_name,
        )
        return jsonify({
            "mode": "ai",
            "task": task,
            "reply": content,
            "used_context": snapshot.get("counts", {}),
        })
    except _OpenAIAuthenticationError:
        app.logger.exception("OpenAI auth error in student study bot.")
        return jsonify({"error": "OpenAI authentication failed. Please check API configuration."}), 502
    except _OpenAIRateLimitError:
        app.logger.exception("OpenAI rate limit in student study bot.")
        fallback = _student_ai_fallback_answer(task, user_prompt, snapshot)
        fallback["mode"] = "offline_fallback"
        _student_ai_save_chat_history(
            identity,
            task,
            user_prompt,
            fallback.get("reply") or std_json.dumps(
                fallback.get("quiz") or {}),
            fallback["mode"],
            snapshot.get("counts", {}),
            classroom_id=preferred_classroom_id,
            has_image=bool(image_data_url),
            image_name=image_name,
        )
        return jsonify(fallback)
    except _OpenAIConnectionError:
        app.logger.exception("OpenAI connection error in student study bot.")
        return jsonify({"error": "Could not reach OpenAI. Check internet connection and retry."}), 502
    except Exception as exc:
        if _httpx_available and isinstance(exc, _httpx.ReadError):
            app.logger.exception("HTTPX read error in student study bot.")
            return jsonify({"error": "Temporary network read error while contacting AI. Please retry."}), 502
        app.logger.exception("Unexpected student study bot error.")
        return jsonify({"error": f"Study bot failed: {str(exc)[:120]}"}), 500


@app.route("/ai/student-study-history", methods=["GET"])
def ai_student_study_history():
    identity, identity_error = _student_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403

    classroom_id = request.args.get("classroom_id")
    if classroom_id in {None, "", "all"}:
        classroom_id = None
    else:
        classroom_id = _parse_int(classroom_id)

    rows, table_ready = _student_ai_get_history(
        identity, classroom_id=classroom_id, limit=12)
    return jsonify({"history": rows, "table_ready": table_ready})


@app.route("/ai/student-weekly-quiz", methods=["POST"])
def ai_student_weekly_quiz():
    identity, identity_error = _student_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body."}), 400

    classroom_id = payload.get("classroom_id")
    if classroom_id in {None, "", "all"}:
        classroom_id = None
    else:
        classroom_id = _parse_int(classroom_id)

    week_key = _student_ai_week_key()
    existing, quiz_table_ready = _student_ai_get_weekly_quiz(
        identity, week_key=week_key, classroom_id=classroom_id)
    if existing:
        return jsonify({
            "week_key": week_key,
            "quiz_id": existing.get("id"),
            "quiz": _student_ai_parse_quiz_payload(existing.get("quiz_payload")),
            "source": "existing",
            "table_ready": quiz_table_ready,
        })

    context_bundle = _student_ai_fetch_context(
        identity,
        preferred_classroom_id=classroom_id,
        strict_preferred=classroom_id is not None,
    )
    if classroom_id is not None and not context_bundle.get("classrooms"):
        return jsonify({"error": "Selected classroom is not available in your membership list."}), 400
    snapshot = _student_ai_context_snapshot(context_bundle)

    client, config_error = _build_openai_client()
    if config_error:
        quiz_payload = {
            "quiz_title": "Weekly Study Check",
            "questions": [
                {"question": "What are the top 3 topics your teacher emphasized this week?", "answer": "Use class posts and lecture notes to list them.",
                    "explanation": "Teacher emphasis predicts likely test focus.", "difficulty": "easy", "source_hint": "Classroom posts"},
                {"question": "Write one short answer for each weak subject area.", "answer": "Student-specific answer",
                    "explanation": "Practice in weak zones improves scores fastest.", "difficulty": "medium", "source_hint": "Performance records"},
                {"question": "Pick one assignment and explain its core concept in your own words.", "answer": "Student-specific answer",
                    "explanation": "Explaining concepts builds durable understanding.", "difficulty": "medium", "source_hint": "Classroom assignments"},
            ],
            "study_tips": [
                "Revise from teacher-highlighted lectures first.",
                "Spend extra 20 minutes daily on weakest subject.",
            ],
        }
    else:
        prompt = (
            "Create a weekly revision quiz for this student using class context. "
            "Prioritize teacher instructions and weak areas. Return JSON only with keys quiz_title, questions, study_tips. "
            "Each question must include question, answer, explanation, difficulty, source_hint.\n\n"
            f"CONTEXT:\n{('CLASSROOM POSTS:\n' + '\n'.join(snapshot.get('posts', [])) + '\n\n'
                          'MATERIALS:\n' +
                          '\n'.join(snapshot.get('materials', [])) + '\n\n'
                          'ASSIGNMENTS:\n' +
                          '\n'.join(snapshot.get(
                              'assignments', [])) + '\n\n'
                          'WEAKNESSES:\n' + '\n'.join(snapshot.get('weaknesses', [])))[:14000]}"
        )
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system",
                        "content": "You generate safe, curriculum-focused quizzes."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=900,
                temperature=0.25,
            )
            content = (
                (response.choices[0].message.content if response.choices else "") or "").strip()
            quiz_payload = std_json.loads(content) if content else {}
        except Exception:
            quiz_payload = {
                "quiz_title": "Weekly Study Check",
                "questions": [],
                "study_tips": ["Unable to generate AI quiz now. Please try again."],
            }

    saved_row, saved = _student_ai_save_weekly_quiz(
        identity, week_key=week_key, quiz_payload=quiz_payload, classroom_id=classroom_id)
    return jsonify({
        "week_key": week_key,
        "quiz_id": (saved_row or {}).get("id"),
        "quiz": quiz_payload,
        "source": "generated",
        "table_ready": saved,
    })


@app.route("/ai/student-weekly-quiz-attempt", methods=["POST"])
def ai_student_weekly_quiz_attempt():
    identity, identity_error = _student_ai_identity()
    if identity_error:
        return jsonify({"error": identity_error}), 403

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body."}), 400

    weekly_quiz_id = _parse_int(payload.get("weekly_quiz_id"))
    score = _parse_int(payload.get("score"))
    total_questions = _parse_int(payload.get("total_questions"))
    classroom_id = _parse_int(payload.get("classroom_id")) if payload.get(
        "classroom_id") not in {None, "", "all"} else None

    if weekly_quiz_id is None:
        return jsonify({"error": "weekly_quiz_id is required."}), 400
    if score is None or total_questions is None or total_questions <= 0:
        return jsonify({"error": "Valid score and total_questions are required."}), 400
    if score < 0:
        score = 0
    if score > total_questions:
        score = total_questions

    saved = _student_ai_save_quiz_attempt(
        identity,
        weekly_quiz_id=weekly_quiz_id,
        classroom_id=classroom_id,
        score=score,
        total_questions=total_questions,
        answers_payload=payload.get("answers"),
        feedback=payload.get("feedback"),
    )
    percent = round((score / total_questions) * 100, 1)
    return jsonify({"saved": saved, "score": score, "total_questions": total_questions, "percentage": percent})


# --- Notifications API ---

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000, debug=True)
