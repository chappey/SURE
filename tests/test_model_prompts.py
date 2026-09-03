import pytest
from app.llm.catalog import load_catalog, resolve_model
from app.generation import _build_prompt, generate_weekly_quiz


def test_catalog_loads_prompt_instructions():
    """Verify models in ai_models.json have prompt_instructions."""
    models = load_catalog()
    assert len(models) > 0

    gemini_entry = next((m for m in models if m.id == "or-gemini-3.5-flash-lite"), None)
    assert gemini_entry is not None
    assert len(gemini_entry.prompt_instructions) >= 2
    assert any("LaTeX" in inst for inst in gemini_entry.prompt_instructions)
    assert any("Unicode" in inst for inst in gemini_entry.prompt_instructions)


def test_build_prompt_domain_neutral():
    """Verify _build_prompt does not have hardcoded CS instructor or Big-O bias."""
    prompt = _build_prompt(
        week_name="Week 4: Molecular Geometry",
        material_text="VSEPR theory explains molecular shapes.",
        num_mc=2,
        num_tf=1,
        num_matching=0,
        mc_options=4,
        matching_pairs=3,
        include_answer_feedback=True,
        course_name="General Chemistry I",
    )

    # Base persona should be domain-neutral with course name
    assert "You are a university instructor teaching 'General Chemistry I'" in prompt
    assert "university CS instructor" not in prompt

    # Grounding rules should be domain-neutral
    assert "Big-O" not in prompt
    assert "OS mechanisms" not in prompt
    assert "Formatting & Syntax: Write chemical formulas, exponents, and mathematical expressions using standard Unicode" in prompt
    assert "Do NOT use raw LaTeX enclosing tokens" in prompt


def test_build_prompt_model_instructions_injected():
    """Verify model-specific generation rules are injected when present."""
    custom_inst = [
        "Do NOT use LaTeX math syntax.",
        "Format chemical formulas with standard Unicode or simple HTML.",
    ]

    prompt = _build_prompt(
        week_name="Week 2",
        material_text="Test material",
        num_mc=1,
        num_tf=1,
        num_matching=0,
        mc_options=4,
        matching_pairs=3,
        include_answer_feedback=False,
        model_instructions=custom_inst,
    )

    assert "- Model-Specific Generation Rules (Mandatory):" in prompt
    assert "  * Do NOT use LaTeX math syntax." in prompt
    assert "  * Format chemical formulas with standard Unicode or simple HTML." in prompt


def test_build_prompt_without_course_name():
    """Verify persona fallback when course_name is not provided."""
    prompt = _build_prompt(
        week_name="Week 1",
        material_text="Intro",
        num_mc=1,
        num_tf=0,
        num_matching=0,
        mc_options=4,
        matching_pairs=3,
        include_answer_feedback=False,
    )

    assert "You are a university instructor writing a formative quiz" in prompt
