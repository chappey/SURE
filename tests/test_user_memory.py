from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from fastapi.testclient import TestClient

from app.storage import (
    add_user_memory,
    delete_user_memory,
    get_active_memories_for_generation,
    get_user_profile,
    save_user_profile,
    toggle_user_memory,
)
from app.generation import _build_prompt


class TestUserProfileStorage:
    def test_get_user_profile_initializes_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.CACHE_DIR", tmp_path)

        profile = get_user_profile(
            user_id="prof_upasna",
            user_email="uchaudhu@kent.edu",
            user_name="Upasna Chaudhry",
        )
        assert profile["user_id"] == "prof_upasna"
        assert profile["user_email"] == "uchaudhu@kent.edu"
        assert profile["user_name"] == "Upasna Chaudhry"
        assert profile["memory_enabled"] is True
        assert profile["global_memories"] == []
        assert profile["course_memories"] == {}

        # Second load returns existing profile
        profile2 = get_user_profile("prof_upasna")
        assert profile2["user_email"] == "uchaudhu@kent.edu"

    def test_add_and_toggle_and_delete_global_memory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.CACHE_DIR", tmp_path)

        mem = add_user_memory("prof_upasna", "Prefer 'trigonal planar' over 'planar'")
        assert mem["text"] == "Prefer 'trigonal planar' over 'planar'"
        assert mem["enabled"] is True
        assert mem["id"].startswith("mem_")

        # Active check
        active = get_active_memories_for_generation("prof_upasna", course_id=72)
        assert "Prefer 'trigonal planar' over 'planar'" in active

        # Toggle off
        toggle_res = toggle_user_memory("prof_upasna", mem["id"], enabled=False)
        assert toggle_res is True

        active_after_toggle = get_active_memories_for_generation("prof_upasna", course_id=72)
        assert len(active_after_toggle) == 0

        # Delete
        del_res = delete_user_memory("prof_upasna", mem["id"])
        assert del_res is True
        profile = get_user_profile("prof_upasna")
        assert len(profile["global_memories"]) == 0

    def test_add_course_specific_memory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.CACHE_DIR", tmp_path)

        add_user_memory("prof_upasna", "Global: Emphasize definitions", course_id=None)
        add_user_memory("prof_upasna", "Course 72: Molecular geometry focus", course_id=72)
        add_user_memory("prof_upasna", "Course 99: Other course focus", course_id=99)

        # For course 72: global + course 72
        active_72 = get_active_memories_for_generation("prof_upasna", course_id=72)
        assert len(active_72) == 2
        assert "Global: Emphasize definitions" in active_72
        assert "Course 72: Molecular geometry focus" in active_72
        assert "Course 99: Other course focus" not in active_72

        # When memory_enabled is False: returns empty list
        profile = get_user_profile("prof_upasna")
        profile["memory_enabled"] = False
        save_user_profile("prof_upasna", profile)

        active_disabled = get_active_memories_for_generation("prof_upasna", course_id=72)
        assert active_disabled == []


class TestPromptInjection:
    def test_build_prompt_includes_professor_memories(self):
        prompt = _build_prompt(
            week_name="Week 3",
            material_text="VSEPR Theory slide deck",
            num_mc=4,
            num_tf=1,
            num_matching=0,
            mc_options=4,
            matching_pairs=3,
            include_answer_feedback=False,
            professor_memories=[
                "Prefer 'trigonal planar' over 'planar'",
                "Focus questions on molecular geometry",
            ],
        )

        assert "Professor Tastes, Terminology & Style Preferences (MUST follow strictly):" in prompt
        assert "* Prefer 'trigonal planar' over 'planar'" in prompt
        assert "* Focus questions on molecular geometry" in prompt

    def test_build_prompt_omits_section_when_no_memories(self):
        prompt = _build_prompt(
            week_name="Week 3",
            material_text="VSEPR Theory slide deck",
            num_mc=4,
            num_tf=1,
            num_matching=0,
            mc_options=4,
            matching_pairs=3,
            include_answer_feedback=False,
            professor_memories=[],
        )

        assert "Professor Tastes, Terminology & Style Preferences" not in prompt


class TestProfileApiEndpoints:
    def test_profile_endpoints(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.CACHE_DIR", tmp_path)
        from main import app
        from app.dependencies import require_lti_launch

        app.dependency_overrides[require_lti_launch] = lambda: None

        try:
            with TestClient(app) as client:
                # 1. GET profile
                resp = client.get(
                    "/api/user/profile",
                    headers={"origin": "https://easylearn.nathanchappie.com"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "profile" in data
                assert data["profile"]["memory_enabled"] is True

                # 2. POST memory
                resp_post = client.post(
                    "/api/user/memories",
                    json={"text": "Prefer 'trigonal planar' over 'planar'", "course_id": None},
                    headers={"origin": "https://easylearn.nathanchappie.com"},
                )
                assert resp_post.status_code == 200
                post_data = resp_post.json()
                mem_id = post_data["memory"]["id"]
                assert post_data["memory"]["text"] == "Prefer 'trigonal planar' over 'planar'"

                # 3. PUT toggle memory
                resp_put = client.put(
                    f"/api/user/memories/{mem_id}",
                    json={"enabled": False, "course_id": None},
                    headers={"origin": "https://easylearn.nathanchappie.com"},
                )
                assert resp_put.status_code == 200
                assert resp_put.json()["status"] == "success"

                # 4. PUT profile toggle master
                resp_master = client.put(
                    "/api/user/profile",
                    json={"memory_enabled": False},
                    headers={"origin": "https://easylearn.nathanchappie.com"},
                )
                assert resp_master.status_code == 200
                assert resp_master.json()["profile"]["memory_enabled"] is False

                # 5. DELETE memory
                resp_del = client.delete(
                    f"/api/user/memories/{mem_id}",
                    headers={"origin": "https://easylearn.nathanchappie.com"},
                )
                assert resp_del.status_code == 200
                assert resp_del.json()["status"] == "success"
        finally:
            app.dependency_overrides.clear()
