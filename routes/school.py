from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

@app.route("/school/<signed_id:school_id>")
def school_index(school_id):
    return redirect(url_for("school_page", school_id=school_id, page_slug="home"))


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


