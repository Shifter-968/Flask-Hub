from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
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


