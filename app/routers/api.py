"""JSON API routes for quiz generation and Canvas course data."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.genai import errors as genai_errors

from app import config
from app.auth import build_session_info
from app.canvas import download_canvas_file
from app.canvas_courses import list_teacher_courses, publish_canvas_quiz
from app.config import CACHE_DIR
from app.dependencies import (
    CanvasClientDep,
    CourseIdDep,
    RequireLtiLaunchDep,
    RequireTeacherDep,
    validate_course_access,
)
from app.deployment import deploy_quiz_to_canvas, find_module_by_id_or_name
from app.extraction import extract_file_text, is_supported_material
from app.generation import format_llm_error, generate_weekly_quiz
from app.llm.catalog import list_models_for_api, resolve_model
from app.llm.fallback import AllModelsFailedError
from app.rate_limiter import rate_limit_generate
from app.quizzes_service import (
    build_quizzes_overview,
    get_quiz_stats,
    process_agentic_feedback,
)
from pydantic import BaseModel

from app.schemas import (
    DeployQuizRequest,
    GenerateQuizRequest,
    ModelsResponse,
    ProcessAgenticFeedbackRequest,
    SwitchCourseRequest,
)
from app.storage import (
    get_cached_modules,
    get_quiz_draft,
    list_quizzes,
    save_course_modules,
    save_quiz_draft,
    update_quiz_draft,
)

logger = logging.getLogger("easylearn")
router = APIRouter(prefix="/api", tags=["api"])


@router.get("/session")
def get_session(request: Request) -> dict:
    """Return current auth/session snapshot (no course_id or Canvas API required)."""
    return build_session_info(request)


def _filter_modules_with_supported_materials(modules_data: list) -> list:
    """Drop modules with no PDF/PPTX attachments."""
    filtered = []
    for module in modules_data:
        items = [
            item
            for item in module.get("items", [])
            if is_supported_material(str(item.get("title", "")))
        ]
        if items:
            filtered.append({**module, "items": items})
    return filtered


@router.get("/course-info")
def get_course_info(
    request: Request,
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Retrieve details for the current active course."""
    try:
        course = canvas.get_course(course_id)
        course_code = getattr(course, "course_code", "") or getattr(course, "sis_course_id", "")
        return {
            "id": course.id,
            "name": course.name,
            "course_code": course_code,
            "user_name": request.session.get("user_name", "Instructor"),
            "course_id": course_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s: failed to fetch course info: %s", course_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch course info.") from exc


@router.get("/courses")
def get_courses(
    request: Request,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> list:
    """List courses where the current user is a teacher."""
    try:
        active_id = request.session.get("canvas_course_id")
        include_id = int(active_id) if active_id else None
        return list_teacher_courses(canvas, include_course_id=include_id)
    except Exception as exc:
        logger.warning("failed to list courses: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list courses.") from exc


@router.post("/courses/switch")
def switch_course(
    request: Request,
    body: SwitchCourseRequest,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Switch the active course workspace."""
    validate_course_access(request, body.course_id, canvas)
    request.session["canvas_course_id"] = str(body.course_id)

    course = canvas.get_course(body.course_id)
    course_code = getattr(course, "course_code", "") or getattr(course, "sis_course_id", "")
    return {
        "id": course.id,
        "name": course.name,
        "course_code": course_code,
    }


@router.get("/models", response_model=ModelsResponse)
def api_models(_: RequireLtiLaunchDep, __: RequireTeacherDep) -> ModelsResponse:
    """Return curated AI models plus the auto-selected default for this server."""
    return ModelsResponse.model_validate(list_models_for_api())


def _format_file_size(size_bytes: int | float | None) -> str:
    n = int(size_bytes or 0)
    if n > 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n > 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _module_file_items(module, file_map: dict[int, str]) -> list[dict]:
    """Build Attachment/File item rows for a Canvas module object."""
    raw_items = getattr(module, "items", None)
    if raw_items is None:
        raw_items = list(module.get_module_items())
    items_data: list[dict] = []
    for item in raw_items:
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type not in ("Attachment", "File"):
            continue
        if isinstance(item, dict):
            file_id = item.get("content_id")
            title = item.get("title") or ""
            item_id = item.get("id")
        else:
            file_id = getattr(item, "content_id", None)
            title = getattr(item, "title", "") or ""
            item_id = getattr(item, "id", None)
        size_str = file_map.get(file_id, "Unknown size") if file_id else "Unknown size"
        items_data.append(
            {
                "id": file_id or item_id,
                "title": title,
                "size": size_str,
            }
        )
    return items_data


@router.get("/modules")
def get_modules(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    refresh: bool = Query(False, description="Bypass disk cache and refetch from Canvas"),
) -> list:
    """Retrieve modules and file attachments for the active course."""
    if not refresh:
        cached_data = get_cached_modules(course_id)
        if cached_data is not None:
            logger.info("Serving modules for course %s from disk cache.", course_id)
            return _filter_modules_with_supported_materials(cached_data)

    try:
        logger.info(
            "Fetching modules from Canvas for course %s (%s).",
            course_id,
            "forced refresh" if refresh else "cache miss",
        )
        course = canvas.get_course(course_id)
        file_map: dict[int, str] = {}
        try:
            for file_obj in course.get_files():
                file_map[file_obj.id] = _format_file_size(getattr(file_obj, "size", 0))
        except Exception as exc:
            logger.warning("Error fetching course files list: %s", exc)

        modules_data = []
        for module in course.get_modules(include=["items"]):
            # Canvas may omit inline items when a module is large — fall back per module.
            if getattr(module, "items", None) is None:
                logger.debug(
                    "Module %s missing inline items; fetching module items separately.",
                    getattr(module, "id", "?"),
                )
            items_data = _module_file_items(module, file_map)
            modules_data.append({"id": module.id, "name": module.name, "items": items_data})

        save_course_modules(course_id, modules_data)
        return _filter_modules_with_supported_materials(modules_data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s: failed to fetch modules: %s", course_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch course modules.") from exc


@router.post("/generate-quiz")
def api_generate_quiz(
    request: Request,
    body: GenerateQuizRequest,
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    ___: None = Depends(rate_limit_generate),
):
    """Download files, extract text, and generate a quiz via the selected AI model."""
    model_entry = None
    try:
        course = canvas.get_course(course_id)
        extracted_texts: list[str] = []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        for file_id in body.file_ids:
            try:
                file_obj = course.get_file(file_id)
                dest_path = CACHE_DIR / f"{file_obj.id}_{file_obj.filename}"
                if not dest_path.is_file():
                    logger.info("Downloading file: %s", file_obj.filename)
                    download_canvas_file(
                        canvas,
                        file_obj,
                        dest_path,
                        token=request.session.get("canvas_user_token"),
                    )

                text = extract_file_text(dest_path).strip()
                if text:
                    extracted_texts.append(f"## {file_obj.filename}\n\n{text}")
            except Exception as exc:
                logger.error("Failed to process file %s: %s", file_id, exc)

        if not extracted_texts:
            raise HTTPException(
                status_code=400,
                detail="No extractable text found in the selected files",
            )

        combined_text = "\n\n---\n\n".join(extracted_texts)
        if len(combined_text) > 100_000:
            combined_text = combined_text[:100_000] + "\n\n[truncated]"

        num_mc = body.question_types.get("multiple_choice", 0)
        num_tf = body.question_types.get("true_false", 0)
        num_matching = body.question_types.get("matching", 0)
        if num_mc + num_tf + num_matching == 0:
            raise HTTPException(status_code=400, detail="Must specify at least one question to generate")

        if body.model_id:
            try:
                model_entry = resolve_model(body.model_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        include_answer_feedback = body.include_answer_feedback and not body.include_agentic_feedback

        # Map UI type keys to Canvas question_type strings for per-type point enforcement.
        type_key_map = {
            "multiple_choice": "multiple_choice_question",
            "true_false": "true_false_question",
            "matching": "matching_question",
        }
        points_by_type = {
            canvas_type: int(body.points_per_type[ui_key])
            for ui_key, canvas_type in type_key_map.items()
            if body.points_per_type.get(ui_key)
        }

        quiz, model_entry = generate_weekly_quiz(
            week_name=body.quiz_title,
            material_text=combined_text,
            num_mc=num_mc,
            num_tf=num_tf,
            num_matching=num_matching,
            points_per_q=body.points_per_q,
            points_by_type=points_by_type,
            mc_options=body.mc_options,
            matching_pairs=body.matching_pairs,
            include_answer_feedback=include_answer_feedback,
            custom_instructions=body.custom_instructions,
            model_id=body.model_id,
        )
        if body.quiz_title:
            quiz.quiz_title = body.quiz_title

        quiz_id = secrets.token_hex(8)
        quiz.id = quiz_id
        quiz_dict = quiz.model_dump()
        quiz_dict["includes_answer_feedback"] = include_answer_feedback
        quiz_dict["includes_agentic_feedback"] = body.include_agentic_feedback
        quiz_dict["module_id"] = body.module_id
        quiz_dict["model_id"] = model_entry.id
        quiz_dict["model_label"] = model_entry.label
        save_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            quiz_data=quiz_dict,
            created_by=request.session.get("user_name", "Instructor"),
        )

        return quiz_dict
    except HTTPException:
        raise
    except Exception as exc:
        if model_entry is None and body.model_id:
            try:
                model_entry = resolve_model(body.model_id)
            except ValueError:
                pass
        status, detail = format_llm_error(exc, model_entry)
        if isinstance(exc, AllModelsFailedError):
            logger.warning("All available models failed: %s", exc.errors)
        elif status >= 500 and not isinstance(exc, genai_errors.APIError):
            logger.exception("Error in /api/generate-quiz")
        else:
            logger.warning("LLM error in /api/generate-quiz: %s", detail)
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/deploy-quiz")
def api_deploy_quiz(
    request: Request,
    body: DeployQuizRequest,
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Deploy a generated quiz to Canvas."""
    try:
        course = canvas.get_course(course_id)
        include_agentic_feedback = (
            body.include_agentic_feedback
            if body.include_agentic_feedback is not None
            else bool(getattr(body.quiz, "includes_agentic_feedback", False))
        )
        if body.quiz.id:
            draft = get_quiz_draft(course_id, body.quiz.id)
            if draft:
                if body.include_agentic_feedback is None:
                    include_agentic_feedback = draft.get(
                        "includes_agentic_feedback", include_agentic_feedback
                    )

        module = find_module_by_id_or_name(course, body.module_id)
        deployed_quiz, agentic_meta = deploy_quiz_to_canvas(
            course,
            body.module_id,
            body.quiz,
            include_agentic_feedback=include_agentic_feedback,
        )

        quiz_url = config.canvas_quiz_url(course_id, deployed_quiz.id)

        if body.quiz.id:
            quiz_dict = body.quiz.model_dump()
            quiz_dict["deployed"] = True
            quiz_dict["published"] = False
            quiz_dict["canvas_quiz_id"] = deployed_quiz.id
            quiz_dict["quiz_id"] = deployed_quiz.id
            quiz_dict["module_id"] = module.id
            quiz_dict["module_name"] = module.name
            quiz_dict["includes_agentic_feedback"] = include_agentic_feedback
            quiz_dict["agentic_feedback"] = agentic_meta
            save_quiz_draft(
                course_id=course_id,
                quiz_id=body.quiz.id,
                quiz_data=quiz_dict,
                created_by=request.session.get("user_name", "Instructor"),
            )

        return {
            "status": "success",
            "quiz_id": deployed_quiz.id,
            "quiz_url": quiz_url,
            "includes_agentic_feedback": include_agentic_feedback,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s: quiz deployment failed: %s", course_id, exc)
        raise HTTPException(status_code=500, detail="Quiz deployment failed.") from exc


@router.get("/quizzes")
def get_quizzes(
    course_id: CourseIdDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> list:
    """List saved quiz drafts for the active course."""
    try:
        return list_quizzes(course_id)
    except Exception as exc:
        logger.warning("course %s: failed to list quiz drafts: %s", course_id, exc)
        raise HTTPException(status_code=500, detail="Failed to list quiz drafts.") from exc


@router.get("/quizzes/overview")
def get_quizzes_overview(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    status: str | None = Query(default=None, pattern="^(draft|deployed|published)$"),
) -> list:
    """List quizzes with Canvas publish status synced."""
    try:
        course = canvas.get_course(course_id)
        return build_quizzes_overview(course, canvas, course_id, status_filter=status)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s: failed to load quiz overview: %s", course_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load quiz overview.") from exc


@router.get("/quizzes/{quiz_id}")
def get_quiz_by_id(
    course_id: CourseIdDep,
    quiz_id: str,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Retrieve a specific saved quiz draft."""
    try:
        quiz = get_quiz_draft(course_id, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz draft not found.")
        canvas_quiz_id = quiz.get("canvas_quiz_id") or quiz.get("quiz_id")
        if canvas_quiz_id:
            quiz["quiz_url"] = config.canvas_quiz_url(course_id, canvas_quiz_id)
        else:
            quiz.pop("quiz_url", None)
        return quiz
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: failed to load draft: %s", course_id, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load quiz draft.") from exc


@router.get("/quizzes/{quiz_id}/stats")
def get_quiz_stats_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Return Canvas quiz statistics for a deployed quiz."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    try:
        course = canvas.get_course(course_id)
        return get_quiz_stats(course, canvas, course_id, int(canvas_quiz_id))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: failed to fetch stats: %s", course_id, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch quiz statistics.") from exc


@router.post("/quizzes/{quiz_id}/agentic-feedback/process")
def process_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    request: Request,
    body: ProcessAgenticFeedbackRequest,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Generate personalized feedback comments for completed quiz submissions."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    try:
        course = canvas.get_course(course_id)
        result = process_agentic_feedback(
            course,
            course_id,
            draft,
            force=body.force,
            draft_quiz_id=quiz_id,
        )
        # Final persist (checkpoints may have already written progress)
        update_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            patch={
                "agentic_feedback_processed": result.pop("agentic_feedback_processed"),
                "agentic_feedback_last_run": result.pop("agentic_feedback_last_run"),
            },
            created_by=request.session.get("user_name", "Instructor"),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: agentic feedback processing failed: %s", course_id, quiz_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to process agentic feedback."
        ) from exc


@router.post("/quizzes/{quiz_id}/undeploy")
def undeploy_quiz_endpoint(
    course_id: CourseIdDep,
    quiz_id: str,
    request: Request,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Reset a deployed quiz back to draft state in EasyLearn."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    update_quiz_draft(
        course_id=course_id,
        quiz_id=quiz_id,
        patch={
            "deployed": False,
            "published": False,
            "canvas_quiz_id": None,
            "quiz_url": None,
        },
        created_by=request.session.get("user_name", "Instructor"),
    )
    return {"status": "success", "deployed": False}


@router.post("/quizzes/{quiz_id}/agentic-feedback/preview")
def preview_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Generate student submission feedback preview for instructor review."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    try:
        course = canvas.get_course(course_id)
        submissions = fetch_quiz_submissions_with_answers(course, int(canvas_quiz_id))
        content_questions = draft.get("questions") or []
        mapping = (draft.get("agentic_feedback") or {}).get("questions") or []

        parsed_subs = []
        for sub in submissions:
            sub_id = sub.get("id")
            user_id = sub.get("user_id")
            sub_data = sub.get("submission_data") or []
            
            payload = {}
            if sub_data and mapping:
                try:
                    payload = build_submission_question_payload(
                        sub_data, mapping, content_questions, model_id=draft.get("model_id")
                    )
                except Exception as p_exc:
                    logger.warning("Error building payload for sub %s: %s", sub_id, p_exc)

            q_list = []
            for q_idx, q_item in enumerate(content_questions):
                entry = payload.get(q_idx, {})
                q_list.append({
                    "q_index": q_idx,
                    "question_id": q_item.get("id", q_idx),
                    "question_text": q_item.get("question_text", f"Question {q_idx + 1}"),
                    "student_answer": entry.get("student_answer", "Answer recorded"),
                    "confidence": entry.get("confidence", "Normal"),
                    "explanation": entry.get("explanation", ""),
                    "score": entry.get("score", 1),
                    "ai_feedback": entry.get("comment", "Great work on this topic!")
                })

            parsed_subs.append({
                "submission_id": sub_id,
                "user_id": user_id,
                "user_name": f"Student #{user_id}",
                "score": sub.get("score"),
                "questions": q_list
            })

        return {
            "quiz_id": quiz_id,
            "quiz_title": draft.get("quiz_title", "Quiz Feedback Review"),
            "canvas_quiz_id": int(canvas_quiz_id),
            "questions": content_questions,
            "submissions": parsed_subs
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: feedback preview failed: %s", course_id, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load feedback preview.") from exc


class ApproveFeedbackRequest(BaseModel):
    submissions: list[dict] = []


@router.post("/quizzes/{quiz_id}/agentic-feedback/approve")
def approve_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    body: ApproveFeedbackRequest,
    request: Request,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Push professor-approved feedback comments to Canvas student submissions."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    try:
        course = canvas.get_course(course_id)
        approved_subs = body.submissions or []
        count = 0

        for item in approved_subs:
            sub_id = item.get("submission_id")
            comments = item.get("comments") or {}
            if sub_id and comments:
                payload = {
                    int(k) if str(k).isdigit() else k: {"comment": str(v)}
                    for k, v in comments.items()
                }
                update_quiz_submission_comments(
                    course,
                    int(canvas_quiz_id),
                    int(sub_id),
                    attempt=1,
                    question_payload=payload
                )
                count += 1

        update_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            patch={
                "agentic_feedback_last_run": time.time(),
            },
            created_by=request.session.get("user_name", "Instructor"),
        )
        return {"status": "success", "pushed_submissions": count}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: approve feedback failed: %s", course_id, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Failed to push approved feedback.") from exc


@router.post("/quizzes/{quiz_id}/publish")
def publish_quiz_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    request: Request,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Publish a deployed quiz in Canvas."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    try:
        course = canvas.get_course(course_id)
        publish_canvas_quiz(course, int(canvas_quiz_id))

        update_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            patch={"published": True},
            created_by=request.session.get("user_name", "Instructor"),
        )
        return {"status": "success", "published": True, "canvas_quiz_id": int(canvas_quiz_id)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("course %s quiz %s: publish failed: %s", course_id, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Failed to publish quiz.") from exc

