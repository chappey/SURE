import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config

config.CACHE_DIR = Path("/tmp/easylearn-eval-cache")
config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

import time
from app.generation import generate_weekly_quiz
from app.llm.fallback import fallback_models

# Simulate production prompt: week_name + material
material = """
Operating Systems - CPU Scheduling
- FCFS: First Come First Served, non-preemptive, convoy effect
- SJF: Shortest Job First, optimal average waiting time, needs burst prediction, can be preemptive (SRTF) or non-preemptive
- Round Robin: time quantum, preemptive, good for time sharing, performance depends on quantum size
- Priority Scheduling: priority numbers, can cause starvation, aging solves starvation
- Multilevel Queue: multiple queues with different scheduling algorithms
- Multilevel Feedback Queue: adapts, aging, can move between queues
Big-O: FCFS O(n), SJF sorting O(n log n) if sorting needed
Mechanisms: Dispatch latency, context switch overhead, preemption points, quantum expiration interrupt
""" * 5  # make longer

queue = fallback_models(requested_id=None)
print("AUTO QUEUE", [m.model for m in queue])
print("AUTO FIRST", queue[0].id if queue else None)

start = time.time()
try:
    quiz, model = generate_weekly_quiz(
        week_name="Week 3 - CPU Scheduling",
        material_text=material,
        num_mc=3,
        num_tf=1,
        num_matching=1,
        mc_options=4,
        matching_pairs=4,
        include_answer_feedback=False,
        custom_instructions="",
        model_id=None  # Auto
    )
    elapsed = time.time() - start
    print(f"SUCCESS model={model.id} provider={model.provider} model={model.model} elapsed={elapsed:.1f}s")
    print(f"quiz_title={quiz.quiz_title} questions={len(quiz.questions)}")
    for i, q in enumerate(quiz.questions):
        print(f" Q{i+1} {q.question_type} {q.difficulty} {q.question_name} answers={len(q.answers)}")
        # validate weights
        weights = [a.answer_weight for a in q.answers]
        print(f"   weights {weights}")
    import json
    print(json.dumps(quiz.model_dump(), indent=2)[:4000])
except Exception as e:
    elapsed = time.time() - start
    print(f"FAILED after {elapsed:.1f}s {e}")
    import traceback; traceback.print_exc()
