from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

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


