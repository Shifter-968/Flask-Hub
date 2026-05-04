from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

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
