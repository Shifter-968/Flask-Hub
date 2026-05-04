from extensions import app, supabase
from core.helpers import *
from core.notifications import (
    notify_user, _notify_school_admins, _notify_global_admins,
    _notify_school_users,
)

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

