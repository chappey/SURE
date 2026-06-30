"""Generate a demo course outline via the configured LLM provider.

Keeps the LLM/course logic in `app/` so utilities (utils/generate_demo_course.py)
only orchestrate Canvas + slide rendering, never duplicate generation logic.
"""

from __future__ import annotations

import logging

from app.llm.catalog import ModelEntry, get_default_model_id, resolve_model
from app.llm.registry import generate_json as provider_generate_json
from app.schemas import DemoCourse

logger = logging.getLogger(__name__)


def _build_prompt(topic: str, num_modules: int, slides_per_module: int) -> str:
    return f"""You are an expert instructional designer building a short demo course.

Create a coherent introductory course on the topic: "{topic}".

Requirements:
- course_title: a concise, descriptive course title.
- course_code: a short code like "DEMO-101".
- Generate exactly {num_modules} modules, ordered as a logical learning progression.
- Each module: a clear name (prefix with "Week N:"), a one-sentence summary, and
  exactly {slides_per_module} lecture slides.
- Each slide: a short title and 3-6 concise bullet points of real, teachable content.
- Bullets must contain substantive, factual material suitable for generating quiz
  questions later. Avoid filler, meta-commentary, or placeholders.
"""


def generate_demo_course(
    topic: str,
    num_modules: int = 3,
    slides_per_module: int = 6,
    model_id: str | None = None,
) -> tuple[DemoCourse, ModelEntry]:
    """Generate a structured demo course using the selected model from the catalog."""
    entry = resolve_model(model_id or get_default_model_id())

    prompt = _build_prompt(topic, num_modules, slides_per_module)
    logger.info(
        "Generating demo course on %r via %s (%s / %s)",
        topic,
        entry.label,
        entry.provider,
        entry.model,
    )

    schema = DemoCourse.model_json_schema()
    text = provider_generate_json(entry, prompt, schema)

    course = DemoCourse.model_validate_json(text)
    if not course.modules:
        raise ValueError("Generated demo course has no modules.")
    return course, entry
