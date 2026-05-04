from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

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


