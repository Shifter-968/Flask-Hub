from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)


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
    schools = _safe_select_table(
        "schools", "id,name,school_type", order_by="name")
    if not schools:
        flash("No schools are available for registration yet.", "error")
        return redirect(url_for("login"))
    return render_template("register_school_admin_init.html", schools=schools)


@app.route("/school_admin/register/create", methods=["POST"])
def register_school_admin_handler():
    school_id = _parse_int(request.form.get("school_id"))
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    name = (request.form.get("name") or "").strip()
    phone_number = (request.form.get("phone_number") or "").strip()

    if school_id is None:
        flash("Please select a school.", "error")
        return redirect(url_for("register_school_admin_init"))

    school = _get_school_record(school_id)
    if not school:
        flash("Selected school was not found.", "error")
        return redirect(url_for("register_school_admin_init"))

    if not username or not email or not name:
        flash("Username, email, and full name are required.", "error")
        return redirect(url_for("register_school_admin_init"))

    password_error = _validate_password_strength(password)
    if password_error:
        flash(password_error, "error")
        return redirect(url_for("register_school_admin_init"))

    conflicts = _find_user_identity_conflicts(email=email, username=username)
    if conflicts.get("email"):
        flash(_availability_message("email", conflicts["email"]), "error")
        return redirect(url_for("register_school_admin_init"))
    if conflicts.get("username"):
        flash(_availability_message(
            "username", conflicts["username"]), "error")
        return redirect(url_for("register_school_admin_init"))

    try:
        user_resp = supabase.table("users").insert({
            "username": username,
            "email": email,
            "password": generate_password_hash(password),
            "role": "school_admin",
        }).execute()
    except Exception as error:
        if _is_duplicate_user_identity_error(error):
            flash("That email or username is already in use.", "error")
        else:
            flash(
                f"Could not create user account: {str(error)[:120]}", "error")
        return redirect(url_for("register_school_admin_init"))

    if not getattr(user_resp, "data", None):
        flash("Could not create user account.", "error")
        return redirect(url_for("register_school_admin_init"))

    user_id = user_resp.data[0].get("id")

    try:
        _upsert_profile_for_role(
            role="school_admin",
            user_id=user_id,
            school_id=school_id,
            form_data={"name": name, "phone_number": phone_number},
            mode="create",
        )
    except Exception as error:
        try:
            supabase.table("users").delete().eq("id", int(user_id)).execute()
        except Exception:
            pass

        if _is_missing_school_admins_table(error):
            flash(
                "Database table 'school_admins' is missing. Run schema_school_admin.sql in Supabase SQL Editor, then try again.",
                "error",
            )
        else:
            flash(
                f"Could not create school admin profile: {str(error)[:120]}", "error")
        return redirect(url_for("register_school_admin_init"))

    flash("School Admin account created successfully. Please log in.", "success")
    return redirect(url_for("login", school_ref=_encode_school_ref(school_id)))


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
