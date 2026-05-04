from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)


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
    if status_filter == "unscreened":
        # Load all and post-filter after fetching screenings
        all_apps = (
            supabase.table("online_applications")
            .select("*")
            .eq("school_id", school_id)
            .order("created_at", desc=True)
            .execute()
            .data or []
        )
        screenings_by_ref = _get_latest_application_screenings_for_school(
            school_id)
        applications = [
            a for a in all_apps if not screenings_by_ref.get(a.get("ref"))]
    else:
        if status_filter and status_filter != "all":
            builder = builder.eq("status", status_filter)
        applications = builder.order(
            "created_at", desc=True).execute().data or []
        screenings_by_ref = _get_latest_application_screenings_for_school(
            school_id)

    # Build screening summary stats
    screening_stats = {"recommended": 0, "review": 0,
                       "needs_info": 0, "unscreened": 0}
    all_refs = {a.get("ref") for a in (
        supabase.table("online_applications")
        .select("ref")
        .eq("school_id", school_id)
        .execute()
        .data or []
    ) if a.get("ref")}
    for ref_key in all_refs:
        s = screenings_by_ref.get(ref_key)
        if s:
            rec = s.get("recommendation") or "review"
            if rec in screening_stats:
                screening_stats[rec] += 1
            else:
                screening_stats["review"] += 1
        else:
            screening_stats["unscreened"] += 1

    return render_template(
        "admin_applications.html",
        school=school,
        applications=applications,
        screenings_by_ref=screenings_by_ref,
        screening_labels=APPLICATION_SCREENING_RECOMMENDATION_LABELS,
        status_filter=status_filter,
        screening_stats=screening_stats,
    )


@app.route("/admin/school/<signed_id:school_id>/applications/bulk-screen", methods=["POST"])
def admin_applications_bulk_screen(school_id):
    gate = _require_admin_or_school_admin_for_school(school_id)
    if gate:
        return gate
    school = _get_school_record(school_id)
    if not school:
        flash("School not found.", "error")
        return redirect(url_for("admin_dashboard"))

    # Only screen submitted / under_review apps that haven't been screened yet
    target_statuses = {"submitted", "under_review"}
    try:
        all_apps = (
            supabase.table("online_applications")
            .select("*")
            .eq("school_id", school_id)
            .execute()
            .data or []
        )
    except Exception as e:
        flash(f"Could not load applications: {str(e)[:120]}", "error")
        return redirect(url_for("admin_applications", school_id=school_id))

    screenings_by_ref = _get_latest_application_screenings_for_school(
        school_id)
    candidates = [
        a for a in all_apps
        if (a.get("status") or "") in target_statuses
        and not screenings_by_ref.get(a.get("ref"))
    ]

    if not candidates:
        flash("No unscreened submitted applications found.", "info")
        return redirect(url_for("admin_applications", school_id=school_id))

    screened = 0
    failed = 0
    for application in candidates:
        ref = application.get("ref")
        try:
            docs = (
                supabase.table("online_application_docs")
                .select("*")
                .eq("application_ref", ref)
                .execute()
                .data or []
            )
            screening = _generate_application_screening(
                school, application, docs)
            save_error = _save_application_screening(
                screening,
                created_by=session.get(
                    "username") or session.get("role") or "admin",
            )
            if save_error and not _is_missing_application_screenings_table(save_error):
                app.logger.warning(
                    "Bulk screening save failed for %s: %s", ref, save_error)
                failed += 1
            else:
                # Advance status from submitted → under_review automatically
                if application.get("status") == "submitted":
                    try:
                        supabase.table("online_applications").update({
                            "status": "under_review",
                            "reviewed_by": session.get("username") or "admin",
                            "reviewed_at": datetime.utcnow().isoformat(),
                        }).eq("ref", ref).execute()
                    except Exception:
                        pass
                screened += 1
        except Exception as exc:
            app.logger.warning("Bulk screening error for %s: %s", ref, exc)
            failed += 1

    msg_parts = [f"Bulk screening complete. Screened: {screened}"]
    if failed:
        msg_parts.append(f"Failed: {failed}")
    flash(". ".join(msg_parts) + ".", "success" if not failed else "info")
    return redirect(url_for("admin_applications", school_id=school_id))


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
