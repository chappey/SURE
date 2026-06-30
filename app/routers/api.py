"""JSON API routes for quiz generation and Canvas course data."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Query, Request
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
from app.quizzes_service import (
    build_quizzes_overview,
    get_quiz_feedback_summary,
    get_quiz_stats,
)
from app.schemas import DeployQuizRequest, GenerateQuizRequest, ModelInfo, SwitchCourseRequest
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
        logger.exception("Error in /api/course-info")
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
        logger.exception("Error in GET /api/courses")
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


@router.get("/models", response_model=list[ModelInfo])
def api_models(_: RequireLtiLaunchDep, __: RequireTeacherDep) -> list[ModelInfo]:
    """Return curated AI models available for quiz generation."""
    return [ModelInfo.model_validate(entry) for entry in list_models_for_api()]


@router.get("/modules")
def get_modules(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> list:
    """Retrieve modules and file attachments for the active course."""
    cached_data = get_cached_modules(course_id)
    if cached_data is not None:
        logger.info("Serving modules for course %s from disk cache.", course_id)
        return _filter_modules_with_supported_materials(cached_data)

    try:
        course = canvas.get_course(course_id)
        file_map: dict[int, str] = {}
        try:
            for file_obj in course.get_files():
                size_bytes = getattr(file_obj, "size", 0)
                if size_bytes > 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                elif size_bytes > 1024:
                    size_str = f"{size_bytes / 1024:.0f} KB"
                else:
                    size_str = f"{size_bytes} B"
                file_map[file_obj.id] = size_str
        except Exception as exc:
            logger.warning("Error fetching course files list: %s", exc)

        modules_data = []
        for module in course.get_modules():
            items_data = []
            for item in module.get_module_items():
                if item.type in ("Attachment", "File"):
                    file_id = getattr(item, "content_id", None)
                    size_str = file_map.get(file_id, "Unknown size") if file_id else "Unknown size"
                    items_data.append(
                        {
                            "id": file_id or item.id,
                            "title": item.title,
                            "size": size_str,
                        }
                    )
            modules_data.append({"id": module.id, "name": module.name, "items": items_data})

        save_course_modules(course_id, modules_data)
        return _filter_modules_with_supported_materials(modules_data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in /api/modules")
        raise HTTPException(status_code=500, detail="Failed to fetch course modules.") from exc


@router.post("/generate-quiz")
def api_generate_quiz(
    request: Request,
    body: GenerateQuizRequest,
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
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

        try:
            model_entry = resolve_model(body.model_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        quiz, model_entry = generate_weekly_quiz(
            week_name=body.quiz_title,
            material_text=combined_text,
            num_mc=num_mc,
            num_tf=num_tf,
            num_matching=num_matching,
            points_per_q=body.points_per_q,
            model_id=model_entry.id,
        )
        if body.quiz_title:
            quiz.quiz_title = body.quiz_title

        quiz_id = secrets.token_hex(8)
        quiz.id = quiz_id
        quiz_dict = quiz.model_dump()
        quiz_dict["includes_feedback"] = body.include_feedback
        quiz_dict["module_id"] = body.module_id
        quiz_dict["model_id"] = model_entry.id
        quiz_dict["model_label"] = model_entry.label
        save_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            quiz_data=quiz_dict,
            created_by=request.session.get("user_name", "Instructor"),
        )

        return quiz
    except HTTPException:
        raise
    except Exception as exc:
        if model_entry is None and body.model_id:
            try:
                model_entry = resolve_model(body.model_id)
            except ValueError:
                pass
        status, detail = format_llm_error(exc, model_entry)
        if status >= 500 and not isinstance(exc, genai_errors.APIError):
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
        include_feedback = (
            body.include_feedback
            if body.include_feedback is not None
            else bool(getattr(body.quiz, "includes_feedback", False))
        )
        if body.quiz.id:
            draft = get_quiz_draft(course_id, body.quiz.id)
            if draft and body.include_feedback is None:
                include_feedback = draft.get("includes_feedback", include_feedback)

        module = find_module_by_id_or_name(course, body.module_id)
        deployed_quiz = deploy_quiz_to_canvas(
            course,
            body.module_id,
            body.quiz,
            include_feedback=include_feedback,
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
            quiz_dict["includes_feedback"] = include_feedback
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
            "includes_feedback": include_feedback,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in /api/deploy-quiz")
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
        logger.exception("Error in GET /api/quizzes")
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
        logger.exception("Error in GET /api/quizzes/overview")
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
        logger.exception("Error in GET /api/quizzes/%s", quiz_id)
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
        logger.exception("Error in GET /api/quizzes/%s/stats", quiz_id)
        raise HTTPException(status_code=500, detail="Failed to fetch quiz statistics.") from exc


@router.get("/quizzes/{quiz_id}/feedback")
def get_quiz_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: str,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Aggregate student feedback Likert responses from Canvas."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    try:
        course = canvas.get_course(course_id)
        return get_quiz_feedback_summary(course, int(canvas_quiz_id))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error in GET /api/quizzes/%s/feedback", quiz_id)
        raise HTTPException(status_code=500, detail="Failed to fetch quiz feedback.") from exc


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
        logger.exception("Error in POST /api/quizzes/%s/publish", quiz_id)
        raise HTTPException(status_code=500, detail="Failed to publish quiz.") from exc
