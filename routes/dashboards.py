from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
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

    finance_accounts = []
    finance_transactions = []
    finance_transactions_by_account = {}
    finance_available = True
    parent_user_id = _parse_int(session.get("user_id"))

    if parent_user_id is not None:
        try:
            finance_accounts = (
                supabase.table("student_finance_accounts")
                .select("*")
                .eq("school_id", school_id)
                .eq("parent_user_id", parent_user_id)
                .order("id", desc=True)
                .execute()
                .data
                or []
            )
            account_ids = [
                row.get("id") for row in finance_accounts if row.get("id") is not None]
            if account_ids:
                finance_transactions = (
                    supabase.table("student_finance_transactions")
                    .select("*")
                    .in_("account_id", account_ids)
                    .order("transacted_at", desc=True)
                    .limit(80)
                    .execute()
                    .data
                    or []
                )
                # Group transactions by account_id for per-child ledger view
                for txn in finance_transactions:
                    aid = txn.get("account_id")
                    finance_transactions_by_account.setdefault(
                        aid, []).append(txn)
        except Exception as e:
            if _finance_table_missing_error(e):
                finance_available = False
            else:
                flash(f"Finance panel unavailable: {str(e)[:120]}", "error")

    school = _get_school_record(school_id)

    return render_template(
        "parent_dashboard.html",
        school_id=school_id,
        school=school,
        announcements=announcements,
        events=events,
        classrooms=classrooms,
        finance_available=finance_available,
        finance_accounts=finance_accounts,
        finance_transactions=finance_transactions,
        finance_transactions_by_account=finance_transactions_by_account,
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
