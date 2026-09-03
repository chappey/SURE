"""JSON API routes for quiz generation and Canvas course data."""

from __future__ import annotations

import logging
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from google.genai import errors as genai_errors

from app import config
from app.auth import build_session_info
from app.canvas import download_canvas_file
from app.canvas_courses import (
    list_teacher_courses,
    publish_canvas_quiz,
    update_quiz_submission_comments,
)
from app.config import CACHE_DIR
from app.dependencies import (
    CanvasClientDep,
    CourseIdDep,
    QuizIdPath,
    RequireLtiLaunchDep,
    RequireTeacherDep,
    validate_course_access,
)
from app.deployment import deploy_quiz_to_canvas, find_module_by_id_or_name
from app.agentic_feedback import confidence_is_high, html_to_plain_text
from app.feedback_workspace import (
    build_or_merge_feedback_workspace,
    filter_content_question_stats,
    get_saved_workspace_payload,
    save_feedback_workspace,
)
from app.extraction import extract_file_text, is_supported_material
from app.generation import format_llm_error, generate_weekly_quiz
from app.llm import jobs as generate_jobs
from app.llm.catalog import list_models_for_api, resolve_model
from app.llm.fallback import AllModelsFailedError
from app.ops import context as ops_context
from app.rate_limiter import rate_limit_feedback_llm, rate_limit_generate, require_llm_budget
from app.quizzes_service import (
    build_quizzes_overview,
    delete_entire_quiz_draft,
    delete_question_from_draft,
    get_quiz_stats,
    process_agentic_feedback,
    save_full_quiz_draft,
    update_question_in_draft,
)
from pydantic import BaseModel

from app.schemas import (
    DeployQuizRequest,
    DraftQuestion,
    DraftQuiz,
    GenerateQuizRequest,
    ModelsResponse,
    ProcessAgenticFeedbackRequest,
    SwitchCourseRequest,
)
from app.storage import (
    add_user_memory,
    delete_user_memory,
    get_active_memories_for_generation,
    get_cached_modules,
    get_quiz_draft,
    get_user_profile,
    list_quizzes,
    save_course_modules,
    save_quiz_draft,
    save_user_profile,
    toggle_user_memory,
    update_quiz_draft,
)

class UpdateProfileRequest(BaseModel):
    memory_enabled: bool

class AddMemoryRequest(BaseModel):
    text: str
    course_id: int | str | None = None

class ToggleMemoryRequest(BaseModel):
    enabled: bool
    course_id: int | str | None = None

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
    course = canvas.get_course(course_id)
    course_code = getattr(course, "course_code", "") or getattr(course, "sis_course_id", "")
    return {
        "id": course.id,
        "name": course.name,
        "course_code": course_code,
        "user_name": request.session.get("user_name", "Instructor"),
        "course_id": course_id,
    }


@router.get("/courses")
def get_courses(
    request: Request,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> list:
    """List courses where the current user is a teacher."""
    active_id = request.session.get("canvas_course_id")
    include_id = int(active_id) if active_id else None
    return list_teacher_courses(canvas, include_course_id=include_id)


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

    logger.info(
        "Fetching modules from Canvas for course %s (%s).",
        course_id,
        "forced refresh" if refresh else "cache miss",
    )
    try:
        course = canvas.get_course(course_id)
    except Exception as exc:
        from canvasapi.exceptions import Forbidden, ResourceDoesNotExist

        if isinstance(exc, Forbidden):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Your Canvas account cannot access course {course_id}. "
                    "Confirm you are enrolled as a teacher, then re-launch EasyLearn "
                    "from that course and Authorize again."
                ),
            ) from exc
        if isinstance(exc, ResourceDoesNotExist):
            raise HTTPException(
                status_code=404,
                detail=f"Course {course_id} was not found in Canvas.",
            ) from exc
        raise
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


@router.post("/generate-quiz")
def api_generate_quiz(
    request: Request,
    body: GenerateQuizRequest,
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    ___: None = Depends(rate_limit_generate),
    ____: None = Depends(require_llm_budget),
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

        quiz_id = secrets.token_hex(8)
        job_id = secrets.token_hex(8)
        generate_jobs.create(job_id)
        ident = ops_context.snapshot()
        created_by = request.session.get("user_name", "Instructor")
        user_key = (
            request.session.get("canvas_user_id")
            or request.session.get("user_email")
            or "default_user"
        )
        active_memories = get_active_memories_for_generation(user_key, course_id)

        course_name = request.session.get("course_name")

        def _run() -> None:
            generate_jobs.set_running(job_id)
            ops_context.bind_snapshot(ident)
            try:
                quiz, entry = generate_weekly_quiz(
                    week_name=body.quiz_title,
                    material_text=combined_text,
                    num_mc=num_mc,
                    num_tf=num_tf,
                    num_matching=num_matching,
                    difficulty_counts=body.difficulty_counts,
                    points_per_q=body.points_per_q,
                    points_by_type=points_by_type,
                    mc_options=body.mc_options,
                    matching_pairs=body.matching_pairs,
                    include_answer_feedback=include_answer_feedback,
                    custom_instructions=body.custom_instructions,
                    model_id=body.model_id,
                    professor_memories=active_memories,
                    course_name=course_name,
                )
                if body.quiz_title:
                    quiz.quiz_title = body.quiz_title
                quiz.id = quiz_id
                quiz_dict = quiz.model_dump()
                quiz_dict["includes_answer_feedback"] = include_answer_feedback
                quiz_dict["includes_agentic_feedback"] = body.include_agentic_feedback
                quiz_dict["module_id"] = body.module_id
                quiz_dict["file_ids"] = list(body.file_ids)
                quiz_dict["source_text"] = combined_text
                quiz_dict["model_id"] = entry.id
                quiz_dict["model_label"] = entry.label
                save_quiz_draft(
                    course_id=course_id,
                    quiz_id=quiz_id,
                    quiz_data=quiz_dict,
                    created_by=created_by,
                )
                generate_jobs.set_ready(job_id, quiz_dict)
            except Exception as exc:
                status, detail = format_llm_error(exc, model_entry)
                if isinstance(exc, AllModelsFailedError):
                    logger.warning("All available models failed: %s", exc.errors)
                elif status >= 500 and not isinstance(exc, genai_errors.APIError):
                    logger.exception("Error in background /api/generate-quiz")
                else:
                    logger.warning("LLM error in background /api/generate-quiz: %s", detail)
                generate_jobs.set_error(job_id, detail)

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id, "status": "pending"}
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


@router.get("/generate-jobs/{job_id}")
def get_generate_job(
    job_id: str,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Poll a background quiz-generation job."""
    job = generate_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return job


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


@router.get("/quizzes")
def get_quizzes(
    course_id: CourseIdDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> list:
    """List saved quiz drafts for the active course."""
    return list_quizzes(course_id)


@router.get("/quizzes/overview")
def get_quizzes_overview(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    status: str | None = Query(default=None, pattern="^(draft|deployed|published)$"),
) -> list:
    """List quizzes with Canvas publish status synced."""
    course = canvas.get_course(course_id)
    return build_quizzes_overview(course, canvas, course_id, status_filter=status)


@router.get("/quizzes/{quiz_id}")
def get_quiz_by_id(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Retrieve a specific saved quiz draft."""
    quiz = get_quiz_draft(course_id, quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    canvas_quiz_id = quiz.get("canvas_quiz_id") or quiz.get("quiz_id")
    if canvas_quiz_id:
        quiz["quiz_url"] = config.canvas_quiz_url(course_id, canvas_quiz_id)
    else:
        quiz.pop("quiz_url", None)
    return quiz


@router.delete("/quizzes/{quiz_id}/questions/{question_index}")
def delete_quiz_question_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    question_index: int,
    request: Request,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Delete a specific question from a quiz draft."""
    try:
        course = canvas.get_course(course_id)
        user_name = request.session.get("user_name", "Instructor")
        res = delete_question_from_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            question_index=question_index,
            user_name=user_name,
            course=course,
        )
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error deleting question %s from quiz %s: %s", question_index, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Could not delete question.")


@router.put("/quizzes/{quiz_id}/questions/{question_index}")
def update_quiz_question_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    question_index: int,
    body: DraftQuestion,
    request: Request,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Update a specific question in a quiz draft."""
    try:
        user_name = request.session.get("user_name", "Instructor")
        res = update_question_in_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            question_index=question_index,
            question_data=body.model_dump(),
            user_name=user_name,
        )
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error updating question %s in quiz %s: %s", question_index, quiz_id, exc)
        raise HTTPException(status_code=500, detail="Could not update question.")


@router.put("/quizzes/{quiz_id}")
def save_quiz_draft_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    body: DraftQuiz,
    request: Request,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Save full quiz draft (title and questions)."""
    try:
        course = canvas.get_course(course_id)
        user_name = request.session.get("user_name", "Instructor")
        res = save_full_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            quiz_title=body.quiz_title,
            questions=[q.model_dump() for q in body.questions],
            user_name=user_name,
            course=course,
        )
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error saving quiz draft %s: %s", quiz_id, exc)
        raise HTTPException(status_code=500, detail="Could not save quiz draft.")


@router.delete("/quizzes/{quiz_id}")
def delete_quiz_draft_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    request: Request,
    canvas: CanvasClientDep,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Delete an entire quiz draft from disk."""
    try:
        course = canvas.get_course(course_id)
        user_name = request.session.get("user_name", "Instructor")
        res = delete_entire_quiz_draft(
            course_id=course_id,
            quiz_id=quiz_id,
            user_name=user_name,
            course=course,
        )
        return {"status": "success", **res}
    except KeyError:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Error deleting quiz draft %s: %s", quiz_id, exc)
        raise HTTPException(status_code=500, detail="Could not delete quiz draft.")


@router.get("/quizzes/{quiz_id}/stats")
def get_quiz_stats_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: QuizIdPath,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Return Canvas quiz statistics for a deployed quiz (content questions only)."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    canvas_quiz_id = draft.get("canvas_quiz_id") or draft.get("quiz_id")
    if not canvas_quiz_id:
        raise HTTPException(status_code=400, detail="Quiz has not been deployed to Canvas.")

    course = canvas.get_course(course_id)
    stats = get_quiz_stats(course, canvas, course_id, int(canvas_quiz_id))
    if stats.get("available") and stats.get("questions"):
        content_qs = filter_content_question_stats(stats["questions"], draft)
        content_ids = {
            int(r["content_canvas_id"]): i
            for i, r in enumerate((draft.get("agentic_feedback") or {}).get("questions") or [])
            if r.get("content_canvas_id") is not None
        }
        draft_qs = draft.get("questions") or []
        for q in content_qs:
            try:
                qid = int(q.get("id"))
            except (TypeError, ValueError):
                qid = None
            idx = content_ids.get(qid) if qid is not None else None
            if idx is not None and idx < len(draft_qs):
                q["question_text"] = html_to_plain_text(draft_qs[idx].get("question_text") or "")
                q["question_name"] = draft_qs[idx].get("question_name") or q.get("question_name") or ""
            else:
                q["question_text"] = html_to_plain_text(q.get("question_text") or "")
        stats["questions"] = content_qs
    stats["has_feedback_workspace"] = bool(
        (draft.get("feedback_workspace") or {}).get("submissions")
    )
    processed = draft.get("agentic_feedback_processed") or {}
    stats["feedback_done"] = len(processed) if isinstance(processed, dict) else 0

    # Extract misconception metrics from feedback workspace if present
    misconception_matrix = {
        "high_confidence_wrong": 0,
        "high_confidence_correct": 0,
        "low_confidence_wrong": 0,
        "low_confidence_correct": 0,
        "total_responses": 0,
    }
    workspace = draft.get("feedback_workspace") or {}
    for sub in workspace.get("submissions") or []:
        for q_item in sub.get("questions") or []:
            conf = q_item.get("confidence")
            is_corr = bool(q_item.get("is_correct"))
            if not conf:
                continue
            misconception_matrix["total_responses"] += 1
            # Labels are the meta-question options ("Very confident", ...) —
            # confidence_is_high normalizes case and legacy short forms.
            is_high = confidence_is_high(str(conf))
            if is_high and not is_corr:
                misconception_matrix["high_confidence_wrong"] += 1
            elif is_high and is_corr:
                misconception_matrix["high_confidence_correct"] += 1
            elif not is_high and not is_corr:
                misconception_matrix["low_confidence_wrong"] += 1
            else:
                misconception_matrix["low_confidence_correct"] += 1

    stats["misconception_matrix"] = misconception_matrix
    return stats



@router.post("/quizzes/{quiz_id}/agentic-feedback/process")
def process_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: QuizIdPath,
    request: Request,
    body: ProcessAgenticFeedbackRequest,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    ___: None = Depends(rate_limit_feedback_llm),
    ____: None = Depends(require_llm_budget),
) -> dict:
    """Generate personalized feedback comments for completed quiz submissions."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    course = canvas.get_course(course_id)
    try:
        result = process_agentic_feedback(
            course,
            course_id,
            draft,
            force=body.force,
            draft_quiz_id=quiz_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.post("/quizzes/{quiz_id}/undeploy")
def undeploy_quiz_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
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


class PreviewFeedbackRequest(BaseModel):
    force: bool = False


class SaveWorkspaceRequest(BaseModel):
    submissions: list[dict] = []


@router.get("/quizzes/{quiz_id}/agentic-feedback/workspace")
def get_feedback_workspace_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Return the saved Feedback Review workspace without calling the LLM."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    payload = get_saved_workspace_payload(quiz_id, draft)
    if not payload:
        return {
            "quiz_id": quiz_id,
            "quiz_title": draft.get("quiz_title", "Quiz Feedback Review"),
            "submissions": [],
            "questions": draft.get("questions") or [],
            "source_available": bool((draft.get("source_text") or "").strip()),
            "empty": True,
        }
    return payload


@router.post("/quizzes/{quiz_id}/agentic-feedback/preview")
def preview_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: QuizIdPath,
    request: Request,
    body: PreviewFeedbackRequest,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
    ___: None = Depends(rate_limit_feedback_llm),
    ____: None = Depends(require_llm_budget),
) -> dict:
    """Build or merge Feedback Review workspace (LLM only for new/forced rows)."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")

    course = canvas.get_course(course_id)
    try:
        return build_or_merge_feedback_workspace(
            course,
            course_id,
            quiz_id,
            draft,
            force=bool(body.force),
            created_by=request.session.get("user_name", "Instructor"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/quizzes/{quiz_id}/agentic-feedback/workspace")
def save_feedback_workspace_endpoint(
    course_id: CourseIdDep,
    quiz_id: QuizIdPath,
    body: SaveWorkspaceRequest,
    request: Request,
    _: RequireLtiLaunchDep,
    __: RequireTeacherDep,
) -> dict:
    """Autosave professor edits to the Feedback Review workspace."""
    draft = get_quiz_draft(course_id, quiz_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Quiz draft not found.")
    return save_feedback_workspace(
        course_id,
        quiz_id,
        draft,
        body.submissions or [],
        created_by=request.session.get("user_name", "Instructor"),
    )


class ApproveFeedbackRequest(BaseModel):
    submissions: list[dict] = []


@router.post("/quizzes/{quiz_id}/agentic-feedback/approve")
def approve_agentic_feedback_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: QuizIdPath,
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

    course = canvas.get_course(course_id)
    approved_subs = body.submissions or []
    count = 0
    errors: list[dict] = []

    # Map submission_id -> attempt from the saved workspace so we push comments
    # against the same Canvas attempt the feedback was generated for.
    attempts_by_sub: dict[int, int] = {}
    for ws_sub in (draft.get("feedback_workspace") or {}).get("submissions") or []:
        try:
            sid = int(ws_sub.get("submission_id") or ws_sub.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if sid:
            try:
                attempts_by_sub[sid] = int(ws_sub.get("attempt") or 1)
            except (TypeError, ValueError):
                attempts_by_sub[sid] = 1

    for item in approved_subs:
        sub_id = item.get("submission_id")
        comments = item.get("comments") or {}
        if not sub_id or not comments:
            continue
        try:
            sid = int(sub_id)
            payload = {
                int(k) if str(k).isdigit() else k: {"comment": str(v)}
                for k, v in comments.items()
            }
            update_quiz_submission_comments(
                course,
                int(canvas_quiz_id),
                sid,
                attempt=attempts_by_sub.get(sid, 1),
                question_payload=payload,
            )
            count += 1
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid submission payload: {exc}"
            ) from exc
        except Exception as exc:
            # Keep pushing remaining submissions; report this one back.
            logger.warning(
                "Failed to push feedback for submission %s on quiz %s: %s",
                sid,
                quiz_id,
                exc,
            )
            errors.append({"submission_id": sid, "error": str(exc)[:300]})

    update_quiz_draft(
        course_id=course_id,
        quiz_id=quiz_id,
        patch={
            "agentic_feedback_last_run": time.time(),
        },
        created_by=request.session.get("user_name", "Instructor"),
    )
    response = {"status": "success", "pushed_submissions": count}
    if errors:
        response["errors"] = errors
        response["status"] = "partial"
    return response


@router.post("/quizzes/{quiz_id}/publish")
def publish_quiz_endpoint(
    course_id: CourseIdDep,
    canvas: CanvasClientDep,
    quiz_id: QuizIdPath,
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

    course = canvas.get_course(course_id)
    publish_canvas_quiz(course, int(canvas_quiz_id))

    update_quiz_draft(
        course_id=course_id,
        quiz_id=quiz_id,
        patch={"published": True},
        created_by=request.session.get("user_name", "Instructor"),
    )
    return {"status": "success", "published": True, "canvas_quiz_id": int(canvas_quiz_id)}


# ==============================================================================
# User Profile & Memory API Endpoints
# ==============================================================================

@router.get("/user/profile")
def get_user_profile_endpoint(
    request: Request,
    _: RequireLtiLaunchDep,
) -> dict:
    """Return user profile and active professor memories count."""
    user_id = request.session.get("canvas_user_id") or request.session.get("user_email") or "default_user"
    user_email = request.session.get("user_email", "")
    user_name = request.session.get("user_name", "Instructor")
    course_id = request.session.get("canvas_course_id")
    profile = get_user_profile(user_id, user_email=user_email, user_name=user_name)
    active_mems = get_active_memories_for_generation(user_id, course_id)
    return {
        "profile": profile,
        "active_memories_count": len(active_mems),
        "current_course_id": course_id,
        "user_role": request.session.get("user_role", "Teacher"),
    }


@router.put("/user/profile")
def update_user_profile_endpoint(
    body: UpdateProfileRequest,
    request: Request,
    _: RequireLtiLaunchDep,
) -> dict:
    """Update user master memory toggle."""
    user_id = request.session.get("canvas_user_id") or request.session.get("user_email") or "default_user"
    profile = get_user_profile(user_id)
    profile["memory_enabled"] = body.memory_enabled
    save_user_profile(user_id, profile)
    return {"status": "success", "profile": profile}


@router.post("/user/memories")
def add_user_memory_endpoint(
    body: AddMemoryRequest,
    request: Request,
    _: RequireLtiLaunchDep,
) -> dict:
    """Add a new memory (global or course-specific)."""
    user_id = request.session.get("canvas_user_id") or request.session.get("user_email") or "default_user"
    try:
        item = add_user_memory(user_id, body.text, body.course_id)
        return {"status": "success", "memory": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/user/memories/{memory_id}")
def toggle_user_memory_endpoint(
    memory_id: str,
    body: ToggleMemoryRequest,
    request: Request,
    _: RequireLtiLaunchDep,
) -> dict:
    """Toggle a specific memory on or off."""
    user_id = request.session.get("canvas_user_id") or request.session.get("user_email") or "default_user"
    found = toggle_user_memory(user_id, memory_id, body.enabled, body.course_id)
    if not found:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"status": "success"}


@router.delete("/user/memories/{memory_id}")
def delete_user_memory_endpoint(
    memory_id: str,
    request: Request,
    course_id: int | str | None = None,
    _: RequireLtiLaunchDep = None,
) -> dict:
    """Delete a specific memory."""
    user_id = request.session.get("canvas_user_id") or request.session.get("user_email") or "default_user"
    deleted = delete_user_memory(user_id, memory_id, course_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"status": "success"}

