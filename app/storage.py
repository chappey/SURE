"""On-disk store for quiz drafts and Canvas module snapshots.

Persistence contract (see .cursor/rules/05-persistence.mdc):
- ALL JSON writes go through ``write_json_atomic`` — never hand-roll ``open("w")``.
  A torn write here silently loses an instructor's quiz draft.
- Read-modify-write of a draft goes through ``update_quiz_draft`` so the
  read+write is serialized under ``_STORE_LOCK`` and cannot interleave.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.config import CACHE_DIR
from app.dependencies import validate_quiz_id

logger = logging.getLogger(__name__)

# Serializes writes within this process. FastAPI runs sync handlers in a thread
# pool, so concurrent writes to the same file ARE possible without this.
# NOTE: process-local only — multiple workers/replicas still need shared storage
# (see .cursor/rules/04-lti-canvas.mdc scaling landmine).
_STORE_LOCK = threading.RLock()


def write_json_atomic(path: Path, data: Any) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Writes to a temp file on the same filesystem, fsyncs, then ``os.replace``s
    into place — so a crash mid-write can never leave a truncated/corrupt file.
    The only sanctioned way to persist JSON in this app.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_course_dir(course_id: str | int) -> Path:
    """Return the course cache directory, creating it if needed."""
    safe_id = str(course_id)
    if not re.fullmatch(r"[0-9]{1,20}", safe_id):
        raise ValueError(f"Invalid course id: {course_id!r}")
    path = CACHE_DIR / "courses" / safe_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quiz_path(course_id: str | int, quiz_id: str) -> Path:
    # Defense-in-depth: quiz_id comes from URL path params — reject anything
    # that could traverse out of the course's quizzes directory.
    validate_quiz_id(str(quiz_id))
    return get_course_dir(course_id) / "quizzes" / f"{quiz_id}.json"


def save_quiz_draft(
    course_id: str | int,
    quiz_id: str,
    quiz_data: dict[str, Any],
    created_by: str = "Instructor",
) -> None:
    """Save a generated quiz draft to disk.

    Does not mutate ``quiz_data``; writes a copy so callers can keep using their object.
    """
    record = dict(quiz_data)
    record["created_by"] = created_by
    now = time.time()
    record.setdefault("created_at", now)
    record.setdefault("updated_at", now)

    with _STORE_LOCK:
        write_json_atomic(_quiz_path(course_id, quiz_id), record)


def update_quiz_draft(
    course_id: str | int,
    quiz_id: str,
    patch: dict[str, Any],
    created_by: str | None = None,
) -> dict[str, Any] | None:
    """Race-safe read-modify-write of a draft: apply ``patch`` to the latest copy.

    The read and write happen under ``_STORE_LOCK`` so two concurrent updates
    cannot clobber each other. Returns the updated record, or None if missing.
    """
    with _STORE_LOCK:
        current = get_quiz_draft(course_id, quiz_id)
        if current is None:
            return None
        current.update(patch)
        if created_by is not None:
            current["created_by"] = created_by
        now = time.time()
        current.setdefault("created_at", now)
        current["updated_at"] = now
        write_json_atomic(_quiz_path(course_id, quiz_id), current)
        return current


def delete_quiz_draft(course_id: str | int, quiz_id: str) -> bool:
    """Delete a quiz draft file from disk under _STORE_LOCK. Returns True if deleted."""
    with _STORE_LOCK:
        file_path = _quiz_path(course_id, quiz_id)
        if file_path.is_file():
            file_path.unlink()
            return True
        return False


def get_quiz_draft(course_id: str | int, quiz_id: str) -> dict[str, Any] | None:
    """Load a generated quiz draft from disk."""
    file_path = _quiz_path(course_id, quiz_id)
    if not file_path.is_file():
        return None
    try:
        with file_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read quiz draft %s: %s", file_path, exc)
        return None


def list_quizzes(course_id: str | int) -> list[dict[str, Any]]:
    """List quiz drafts for a course, newest edited first."""
    quizzes_dir = get_course_dir(course_id) / "quizzes"
    if not quizzes_dir.is_dir():
        return []

    quizzes: list[dict[str, Any]] = []
    for file_path in quizzes_dir.glob("*.json"):
        try:
            with file_path.open(encoding="utf-8") as f:
                data = json.load(f)
            created_at = data.get("created_at", file_path.stat().st_mtime)
            updated_at = data.get("updated_at") or created_at
            quizzes.append(
                {
                    "id": file_path.stem,
                    "title": data.get("quiz_title", "Untitled Quiz"),
                    "questions_count": len(data.get("questions", [])),
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "created_by": data.get("created_by", "Instructor"),
                    "deployed": data.get("deployed", False),
                    "published": data.get("published", False),
                    "canvas_quiz_id": data.get("canvas_quiz_id") or data.get("quiz_id"),
                    "module_id": data.get("module_id"),
                    "module_name": data.get("module_name"),
                    "includes_agentic_feedback": data.get("includes_agentic_feedback", False),
                }
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable quiz file %s: %s", file_path, exc)

    quizzes.sort(key=lambda item: item["updated_at"], reverse=True)
    return quizzes


def save_course_modules(course_id: str | int, modules_data: list[dict[str, Any]]) -> None:
    """Save the Canvas modules list for a course."""
    with _STORE_LOCK:
        write_json_atomic(get_course_dir(course_id) / "modules.json", modules_data)


def get_cached_modules(course_id: str | int) -> list[dict[str, Any]] | None:
    """Return cached modules if present.

    Cache lives until an explicit refresh (``GET /api/modules?refresh=1``).
    """
    file_path = get_course_dir(course_id) / "modules.json"
    if not file_path.is_file():
        return None
    try:
        with file_path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read modules cache %s: %s", file_path, exc)
        return None


# ==============================================================================
# User Profile & Professor Memory Persistence
# ==============================================================================

def _sanitize_user_key(user_id: str | int) -> str:
    """Return a safe filesystem directory name for a user identifier."""
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id)).strip("._")
    return sanitized or "default_user"


def get_user_dir(user_id: str | int) -> Path:
    """Return the profile directory for a user, creating it if needed."""
    key = _sanitize_user_key(user_id)
    path = CACHE_DIR / "users" / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_profile_path(user_id: str | int) -> Path:
    return get_user_dir(user_id) / "profile.json"


def get_user_profile(
    user_id: str | int,
    user_email: str | None = None,
    user_name: str | None = None,
) -> dict[str, Any]:
    """Load or initialize a user profile record."""
    file_path = _user_profile_path(user_id)
    with _STORE_LOCK:
        if file_path.is_file():
            try:
                with file_path.open(encoding="utf-8") as f:
                    data = json.load(f)
                    changed = False
                    if user_email and data.get("user_email") != user_email:
                        data["user_email"] = user_email
                        changed = True
                    if user_name and data.get("user_name") != user_name:
                        data["user_name"] = user_name
                        changed = True
                    if changed:
                        write_json_atomic(file_path, data)
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read user profile %s: %s", file_path, exc)

        now = time.time()
        default_profile: dict[str, Any] = {
            "user_id": str(user_id),
            "user_email": user_email or "",
            "user_name": user_name or "Instructor",
            "memory_enabled": True,
            "global_memories": [],
            "course_memories": {},
            "created_at": now,
            "updated_at": now,
        }
        write_json_atomic(file_path, default_profile)
        return default_profile


def save_user_profile(user_id: str | int, profile: dict[str, Any]) -> dict[str, Any]:
    """Save updated user profile atomically."""
    with _STORE_LOCK:
        profile["updated_at"] = time.time()
        file_path = _user_profile_path(user_id)
        write_json_atomic(file_path, profile)
        return profile


def add_user_memory(
    user_id: str | int,
    text: str,
    course_id: int | str | None = None,
) -> dict[str, Any]:
    """Add a new memory entry either globally or to a specific course."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Memory text cannot be empty.")

    memory_item: dict[str, Any] = {
        "id": f"mem_{secrets.token_hex(6)}",
        "text": cleaned,
        "enabled": True,
        "created_at": time.time(),
        "course_id": str(course_id) if course_id is not None else None,
    }

    with _STORE_LOCK:
        profile = get_user_profile(user_id)
        if course_id is not None:
            cid_str = str(course_id)
            course_mems = profile.setdefault("course_memories", {})
            mems_list = course_mems.setdefault(cid_str, [])
            mems_list.append(memory_item)
        else:
            profile.setdefault("global_memories", []).append(memory_item)

        save_user_profile(user_id, profile)
        return memory_item


def delete_user_memory(
    user_id: str | int,
    memory_id: str,
    course_id: int | str | None = None,
) -> bool:
    """Delete a memory entry by ID."""
    with _STORE_LOCK:
        profile = get_user_profile(user_id)
        deleted = False

        if course_id is not None:
            cid_str = str(course_id)
            course_mems = profile.get("course_memories", {})
            if cid_str in course_mems:
                orig_len = len(course_mems[cid_str])
                course_mems[cid_str] = [m for m in course_mems[cid_str] if m.get("id") != memory_id]
                deleted = len(course_mems[cid_str]) < orig_len
        else:
            global_mems = profile.get("global_memories", [])
            orig_len = len(global_mems)
            profile["global_memories"] = [m for m in global_mems if m.get("id") != memory_id]
            deleted = len(profile["global_memories"]) < orig_len

            if not deleted:
                for cid, mems in profile.get("course_memories", {}).items():
                    c_orig_len = len(mems)
                    profile["course_memories"][cid] = [m for m in mems if m.get("id") != memory_id]
                    if len(profile["course_memories"][cid]) < c_orig_len:
                        deleted = True
                        break

        if deleted:
            save_user_profile(user_id, profile)
        return deleted


def toggle_user_memory(
    user_id: str | int,
    memory_id: str,
    enabled: bool,
    course_id: int | str | None = None,
) -> bool:
    """Toggle the enabled status of a memory."""
    with _STORE_LOCK:
        profile = get_user_profile(user_id)
        found = False
        all_lists: list[list[dict[str, Any]]] = []

        if course_id is not None:
            cid_str = str(course_id)
            if cid_str in profile.get("course_memories", {}):
                all_lists.append(profile["course_memories"][cid_str])
        else:
            all_lists.append(profile.get("global_memories", []))
            for mems in profile.get("course_memories", {}).values():
                all_lists.append(mems)

        for mems in all_lists:
            for m in mems:
                if m.get("id") == memory_id:
                    m["enabled"] = enabled
                    found = True
                    break
            if found:
                break

        if found:
            save_user_profile(user_id, profile)
        return found


def get_active_memories_for_generation(
    user_id: str | int,
    course_id: int | str | None = None,
) -> list[str]:
    """Return active preferences formatted as prompt constraint strings."""
    profile = get_user_profile(user_id)
    if not profile.get("memory_enabled", True):
        return []

    active: list[str] = []
    # Global memories
    for m in profile.get("global_memories", []):
        if m.get("enabled", True) and m.get("text"):
            active.append(m["text"].strip())

    # Course-specific memories
    if course_id is not None:
        cid_str = str(course_id)
        for m in profile.get("course_memories", {}).get(cid_str, []):
            if m.get("enabled", True) and m.get("text"):
                active.append(m["text"].strip())

    return active
