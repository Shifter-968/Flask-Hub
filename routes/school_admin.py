import csv
import io
from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
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


@app.route("/school/<signed_id:school_id>/admin/finance", methods=["GET", "POST"])
def admin_manage_finance(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "create_account":
            student_name = (request.form.get("student_name") or "").strip()
            student_role = (_normalize_role(
                request.form.get("student_role")) or "learner").strip()
            opening_balance = _parse_money(request.form.get("opening_balance"))
            if opening_balance is None:
                opening_balance = 0.0

            if not student_name:
                flash("Student or learner name is required.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            account_payload = {
                "school_id": school_id,
                "student_user_id": _parse_int(request.form.get("student_user_id")),
                "parent_user_id": _parse_int(request.form.get("parent_user_id")),
                "student_name": student_name,
                "student_role": "student" if student_role == "student" else "learner",
                "reference_code": f"ACC-{school_id}-{uuid.uuid4().hex[:8].upper()}",
                "opening_balance": opening_balance,
                "current_balance": opening_balance,
                "status": "active",
            }

            try:
                supabase.table("student_finance_accounts").insert(
                    account_payload).execute()
                flash(
                    f"Finance account created for {student_name}.", "success")
            except Exception as e:
                if _finance_table_missing_error(e):
                    flash(
                        "Finance tables are missing. Run schema_finance_ops.sql in Supabase first.", "error")
                else:
                    flash(
                        f"Could not create finance account: {str(e)[:140]}", "error")

            return redirect(url_for("admin_manage_finance", school_id=school_id))

        if action in {"post_charge", "post_payment", "post_adjustment"}:
            account_id = _parse_int(request.form.get("account_id"))
            amount = _parse_money(request.form.get("amount"))
            method = (request.form.get("method")
                      or "manual").strip() or "manual"
            reference = (request.form.get("reference") or "").strip() or None
            notes = (request.form.get("notes") or "").strip() or None
            txn_type = action.replace("post_", "")

            if account_id is None:
                flash("Select a finance account before posting a transaction.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))
            if amount is None or amount <= 0:
                flash("Enter a valid amount greater than 0.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            account = _finance_get_account_row(school_id, account_id)
            if not account:
                flash("Finance account not found for this school.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            current_balance = _parse_money(
                account.get("current_balance")) or 0.0
            delta = _finance_balance_delta(txn_type, amount)
            tentative_balance = round(current_balance + delta, 2)

            try:
                supabase.table("student_finance_transactions").insert({
                    "school_id": school_id,
                    "account_id": account_id,
                    "txn_type": txn_type,
                    "amount": amount,
                    "method": method,
                    "reference": reference,
                    "notes": notes,
                    "created_by_user_id": _parse_int(session.get("user_id")),
                    "created_by_role": session.get("role") or "school_admin",
                }).execute()

                supabase.table("student_finance_accounts").update({
                    "current_balance": tentative_balance,
                }).eq("id", account_id).eq("school_id", school_id).execute()

                recompute_result = _finance_recompute_account_balance(
                    school_id=school_id,
                    account_id=account_id,
                )
                effective_balance = tentative_balance
                consistency_note = ""
                if recompute_result.get("ok"):
                    effective_balance = recompute_result.get(
                        "balance", tentative_balance)
                    if abs(effective_balance - tentative_balance) > 0.009:
                        consistency_note = " Balance was auto-reconciled from full ledger."

                if txn_type in {"charge", "payment"} and account.get("parent_user_id"):
                    title = "Fee account updated"
                    if txn_type == "charge":
                        message = f"A new charge of E {amount:.2f} was added for {account.get('student_name')}. New balance: E {effective_balance:.2f}."
                    else:
                        message = f"A payment of E {amount:.2f} was received for {account.get('student_name')}. New balance: E {effective_balance:.2f}."
                    notify_user(
                        user_id=account.get("parent_user_id"),
                        title=title,
                        message=message,
                        notification_type="finance",
                        priority="normal",
                        send_email=True,
                        send_sms=False,
                        meta={
                            "event": "finance_update",
                            "school_id": school_id,
                            "account_id": account_id,
                            "txn_type": txn_type,
                        },
                    )

                flash(
                    f"{txn_type.title()} transaction recorded.{consistency_note}", "success")
            except Exception as e:
                if _finance_table_missing_error(e):
                    flash(
                        "Finance tables are missing. Run schema_finance_ops.sql in Supabase first.", "error")
                else:
                    flash(
                        f"Could not post transaction: {str(e)[:140]}", "error")

            return redirect(url_for("admin_manage_finance", school_id=school_id))

        if action == "send_reminder":
            account_id = _parse_int(request.form.get("account_id"))
            account = _finance_get_account_row(
                school_id, account_id) if account_id is not None else None
            if not account:
                flash("Finance account not found.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            parent_user_id = _parse_int(account.get("parent_user_id"))
            if parent_user_id is None:
                flash("This account has no linked parent user ID.", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            balance = _parse_money(account.get("current_balance")) or 0.0
            if balance <= 0:
                flash(
                    "Account has no outstanding balance, so no reminder was sent.", "info")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            reminder_text = (
                f"Friendly reminder: {account.get('student_name')} has an outstanding balance of "
                f"E {balance:.2f}. Please check your parent dashboard for full ledger details."
            )
            result = notify_user(
                user_id=parent_user_id,
                title="Outstanding balance reminder",
                message=reminder_text,
                notification_type="finance",
                priority="high",
                send_email=True,
                send_sms=True,
                meta={
                    "event": "fee_reminder",
                    "school_id": school_id,
                    "account_id": account_id,
                    "balance": balance,
                },
            )
            try:
                supabase.table("fee_reminder_runs").insert({
                    "school_id": school_id,
                    "account_id": account_id,
                    "channel": "email_sms",
                    "status": "sent" if result.get("ok") else "failed",
                    "message": reminder_text,
                }).execute()
            except Exception:
                pass

            if result.get("ok"):
                flash("Reminder sent to linked parent account.", "success")
            else:
                flash(
                    "Reminder could not be delivered. Check parent contact details.", "error")
            return redirect(url_for("admin_manage_finance", school_id=school_id))

        if action == "send_bulk_reminders":
            min_balance = _parse_money(request.form.get("min_balance"))
            if min_balance is None:
                min_balance = 0.01
            sent_count = 0
            failed_count = 0
            skipped_count = 0

            try:
                target_accounts = (
                    supabase.table("student_finance_accounts")
                    .select("id,student_name,parent_user_id,current_balance")
                    .eq("school_id", school_id)
                    .execute()
                    .data
                    or []
                )
            except Exception as e:
                if _finance_table_missing_error(e):
                    flash(
                        "Finance tables are missing. Run schema_finance_ops.sql in Supabase first.", "error")
                else:
                    flash(
                        f"Could not load accounts for reminders: {str(e)[:140]}", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            for account in target_accounts:
                balance = _parse_money(account.get("current_balance")) or 0.0
                parent_user_id = _parse_int(account.get("parent_user_id"))
                if balance < min_balance or parent_user_id is None:
                    skipped_count += 1
                    continue

                reminder_text = (
                    f"Friendly reminder: {account.get('student_name')} has an outstanding balance of "
                    f"E {balance:.2f}. Please check your parent dashboard for full ledger details."
                )
                result = notify_user(
                    user_id=parent_user_id,
                    title="Outstanding balance reminder",
                    message=reminder_text,
                    notification_type="finance",
                    priority="high",
                    send_email=True,
                    send_sms=True,
                    meta={
                        "event": "fee_reminder",
                        "school_id": school_id,
                        "account_id": account.get("id"),
                        "balance": balance,
                    },
                )
                try:
                    supabase.table("fee_reminder_runs").insert({
                        "school_id": school_id,
                        "account_id": account.get("id"),
                        "channel": "email_sms",
                        "status": "sent" if result.get("ok") else "failed",
                        "message": reminder_text,
                    }).execute()
                except Exception:
                    pass

                if result.get("ok"):
                    sent_count += 1
                else:
                    failed_count += 1

            flash(
                f"Bulk reminders complete. Sent: {sent_count}, Failed: {failed_count}, Skipped: {skipped_count}.",
                "success" if failed_count == 0 else "info",
            )
            return redirect(url_for("admin_manage_finance", school_id=school_id))

        if action == "reconcile_balances":
            fixed_count = 0
            unchanged_count = 0
            failed_count = 0
            try:
                account_rows = (
                    supabase.table("student_finance_accounts")
                    .select("id,current_balance")
                    .eq("school_id", school_id)
                    .execute()
                    .data
                    or []
                )
            except Exception as e:
                if _finance_table_missing_error(e):
                    flash(
                        "Finance tables are missing. Run schema_finance_ops.sql in Supabase first.", "error")
                else:
                    flash(
                        f"Could not load accounts for reconciliation: {str(e)[:140]}", "error")
                return redirect(url_for("admin_manage_finance", school_id=school_id))

            for row in account_rows:
                before = _parse_money(row.get("current_balance")) or 0.0
                recompute_result = _finance_recompute_account_balance(
                    school_id=school_id,
                    account_id=row.get("id"),
                )
                if not recompute_result.get("ok"):
                    failed_count += 1
                    continue

                after = _parse_money(recompute_result.get("balance")) or 0.0
                if abs(after - before) > 0.009:
                    fixed_count += 1
                else:
                    unchanged_count += 1

            flash(
                f"Reconciliation complete. Fixed: {fixed_count}, Already correct: {unchanged_count}, Failed: {failed_count}.",
                "success" if failed_count == 0 else "info",
            )
            return redirect(url_for("admin_manage_finance", school_id=school_id))

    accounts = []
    transactions = []
    reminder_runs = []
    finance_available = True
    try:
        accounts = (
            supabase.table("student_finance_accounts")
            .select("*")
            .eq("school_id", school_id)
            .order("id", desc=True)
            .execute()
            .data
            or []
        )
        transactions = (
            supabase.table("student_finance_transactions")
            .select("*")
            .eq("school_id", school_id)
            .order("transacted_at", desc=True)
            .limit(100)
            .execute()
            .data
            or []
        )
        reminder_runs = (
            supabase.table("fee_reminder_runs")
            .select("*")
            .eq("school_id", school_id)
            .order("created_at", desc=True)
            .limit(40)
            .execute()
            .data
            or []
        )
    except Exception as e:
        if _finance_table_missing_error(e):
            finance_available = False
        else:
            flash(f"Could not load finance data: {str(e)[:140]}", "error")

    return render_template(
        "admin_manage_finance.html",
        school=school,
        school_id=school_id,
        finance_available=finance_available,
        accounts=accounts,
        transactions=transactions,
        reminder_runs=reminder_runs,
    )


@app.route("/school/<signed_id:school_id>/admin/finance/export-csv")
def finance_export_csv(school_id):
    gate = _require_school_admin(school_id)
    if gate:
        return gate

    school = _get_school_record(school_id)
    school_name = (school.get("name") or str(
        school_id)) if school else str(school_id)

    try:
        accounts = (
            supabase.table("student_finance_accounts")
            .select("*")
            .eq("school_id", school_id)
            .order("id", desc=False)
            .execute()
            .data
            or []
        )
        transactions = (
            supabase.table("student_finance_transactions")
            .select("*")
            .eq("school_id", school_id)
            .order("transacted_at", desc=False)
            .execute()
            .data
            or []
        )
    except Exception as e:
        if _finance_table_missing_error(e):
            flash(
                "Finance tables are missing. Run schema_finance_ops.sql in Supabase first.", "error")
        else:
            flash(
                f"Could not load finance data for export: {str(e)[:140]}", "error")
        return redirect(url_for("admin_manage_finance", school_id=school_id))

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Finance Export — {school_name}"])
    writer.writerow([])

    # --- Accounts sheet section ---
    writer.writerow(["ACCOUNTS"])
    writer.writerow([
        "ID", "Student Name", "Role", "Reference Code",
        "Opening Balance", "Current Balance", "Status",
        "Student User ID", "Parent User ID", "Created At",
    ])
    for acc in accounts:
        writer.writerow([
            acc.get("id"),
            acc.get("student_name"),
            acc.get("student_role"),
            acc.get("reference_code"),
            acc.get("opening_balance"),
            acc.get("current_balance"),
            acc.get("status"),
            acc.get("student_user_id"),
            acc.get("parent_user_id"),
            (acc.get("created_at") or "")[:19],
        ])

    writer.writerow([])

    # --- Transactions sheet section ---
    writer.writerow(["TRANSACTIONS"])
    writer.writerow([
        "ID", "Account ID", "Type", "Amount", "Method",
        "Reference", "Notes", "Created By (User ID)", "Created By (Role)",
        "Transacted At",
    ])
    for txn in transactions:
        writer.writerow([
            txn.get("id"),
            txn.get("account_id"),
            txn.get("txn_type"),
            txn.get("amount"),
            txn.get("method"),
            txn.get("reference"),
            txn.get("notes"),
            txn.get("created_by_user_id"),
            txn.get("created_by_role"),
            (txn.get("transacted_at") or "")[:19],
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility
    filename = f"finance_{school_id}_{_today_date_str()}.csv"
    return app.response_class(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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
