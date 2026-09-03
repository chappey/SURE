import sys
sys.path.insert(0, '/app')
import os, json
from app.schemas import DraftQuiz
from app.llm.catalog import ModelEntry
from app.llm.providers.openrouter import generate_json

schema = DraftQuiz.model_json_schema()
print('schema chars', len(json.dumps(schema)))
prompt = """You are a university CS instructor writing a formative quiz for students who studied ONLY the material below.

Week/Module: CPU Scheduling

Hard requirements:
- The quiz MUST have exactly 1 questions in total.
- Generate exactly 1 multiple_choice_question items. Each multiple_choice_question must have exactly 4 answer options (one correct with answer_weight=100, the remaining 3 incorrect with answer_weight=0).

Grounding rules (non-negotiable):
- Use ONLY facts, definitions, complexities, algorithms, and mechanisms that appear in the material.
- Exactly ONE option has answer_weight=100; all other options answer_weight=0.

Format:
- question_name: short label (e.g. "Q1: Big-O upper bound").
- question_text: clear stem (simple HTML like <p> is OK).
- difficulty: 'easy', 'medium', or 'hard'.
- correct_comments: one short sentence
- incorrect_comments: one short sentence
- quiz_title: concise title like "CPU Quiz".

Course material (sole source of truth):
CPU scheduling - Round Robin uses time quantum, FCFS is first come first served, SJF is shortest job first. Round Robin is preemptive. FCFS can cause convoy effect. SJF is optimal for average waiting time but needs burst time prediction.
"""

entry = ModelEntry(id='minimax-m3-free', label='MiniMax M3 (Free)', provider='openrouter', model='minimax/minimax-m3:free', default=True, expects_free=True, structured_output='native')
print('testing minimax/minimax-m3:free via provider generate_json...')
try:
    text = generate_json(entry, prompt, schema)
    print('RAW TEXT len', len(text))
    print(text[:4000])
    q = DraftQuiz.model_validate_json(text)
    print('VALIDATED ok questions:', len(q.questions))
    for qq in q.questions:
        print(qq.model_dump())
    print('SUCCESS')
except Exception as e:
    print('FAILED', e)
    import traceback; traceback.print_exc()
