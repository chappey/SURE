"""Eval every catalog model with expects_free=True against a 1-question DraftQuiz.

Usage (repo root):
  uv run --no-sync python test_curated.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config
from app.llm.catalog import load_catalog
from app.llm.providers.openrouter import generate_json
from app.schemas import DraftQuiz, validate_questions

# Keep the eval from sitting on a dead endpoint for the full 300s production timeout.
config.LLM_TIMEOUT_SECONDS = 90

PROMPT = """You are a university CS instructor writing a formative quiz for students who studied ONLY the material below.

Week/Module: CPU Scheduling

Hard requirements:
- The quiz MUST have exactly 1 questions in total.
- Generate exactly 1 multiple_choice_question items. Each multiple_choice_question must have exactly 4 answer options (one correct with answer_weight=100, the remaining 3 incorrect with answer_weight=0).

Grounding rules:
- Use ONLY facts in material.
- Exactly ONE option has answer_weight=100.

Format:
- question_name, question_text, difficulty easy/medium/hard, quiz_title.
- correct_comments and incorrect_comments: leave both as empty strings.
- quiz_title: concise title.

Course material:
CPU scheduling - Round Robin uses time quantum, FCFS first come first served with convoy effect, SJF optimal average waiting time but needs burst prediction.
"""


def main() -> None:
    eval_cache = Path("/tmp/easylearn-eval-cache")
    eval_cache.mkdir(parents=True, exist_ok=True)
    config.CACHE_DIR = eval_cache

    load_catalog.cache_clear()
    models = [e for e in load_catalog() if e.expects_free]
    if not models:
        print("No expects_free models in catalog.")
        sys.exit(1)

    schema = DraftQuiz.model_json_schema()
    results: list[dict] = []
    print(f"Testing {len(models)} free catalog models (timeout {config.LLM_TIMEOUT_SECONDS}s)\n")

    for entry in models:
        print(f"=== TEST {entry.model} ===", flush=True)
        t0 = time.time()
        row: dict = {
            "id": entry.id,
            "label": entry.label,
            "model": entry.model,
            "structured_output": entry.structured_output,
        }
        try:
            text = generate_json(entry, PROMPT, schema)
            dt = time.time() - t0
            quiz = DraftQuiz.model_validate_json(text)
            validate_questions(quiz)
            q = quiz.questions[0]
            weights = [a.answer_weight for a in q.answers]
            print(
                f"PASS {dt:.1f}s questions={len(quiz.questions)} "
                f"type={q.question_type} options={len(q.answers)} weights={weights}",
                flush=True,
            )
            row.update(
                {
                    "ok": True,
                    "seconds": round(dt, 1),
                    "questions": len(quiz.questions),
                    "question_type": q.question_type,
                    "options": len(q.answers),
                    "weights": weights,
                    "quiz_title": quiz.quiz_title,
                    "error": "",
                }
            )
        except Exception as exc:
            dt = time.time() - t0
            print(f"FAIL {dt:.1f}s {exc}", flush=True)
            traceback.print_exc()
            row.update(
                {
                    "ok": False,
                    "seconds": round(dt, 1),
                    "error": str(exc)[:400],
                }
            )
        results.append(row)
        time.sleep(1)

    passed = [r for r in results if r.get("ok")]
    failed = [r for r in results if not r.get("ok")]
    print("\n===== SUMMARY =====")
    print(f"pass {len(passed)}/{len(results)}")
    for r in results:
        status = "PASS" if r.get("ok") else "FAIL"
        print(f"  {status:4} {r['seconds']:6.1f}s  {r['model']}  {r.get('error','')[:120]}")

    out = Path(config.CACHE_DIR) / "ops" / "free_model_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
