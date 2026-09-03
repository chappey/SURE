import sys
sys.path.insert(0, '/app')
import os, json, time
from openai import OpenAI
from app.schemas import DraftQuiz

client = OpenAI(base_url='https://openrouter.ai/api/v1', api_key=os.environ.get('OPENROUTER_API_KEY'), timeout=60, default_headers={"HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER",""), "X-Title": os.environ.get("OPENROUTER_APP_NAME","EasyLearn")})

schema = DraftQuiz.model_json_schema()
# use same prompt as test_generate_quiz but simpler
prompt = """You are a university CS instructor writing a formative quiz for students who studied ONLY the material below.

Week/Module: CPU Scheduling

Hard requirements:
- The quiz MUST have exactly 2 questions in total.
- Generate exactly 2 multiple_choice_question items. Each multiple_choice_question must have exactly 4 answer options (one correct with answer_weight=100, the remaining 3 incorrect with answer_weight=0).

Grounding rules:
- Use ONLY facts in material.
- Exactly ONE option has answer_weight=100.

Format:
- question_name, question_text, difficulty easy/medium/hard, quiz_title.
- correct_comments and incorrect_comments empty.

Course material:
CPU scheduling - FCFS, SJF, Round Robin with quantum.
"""

for i in range(5):
    print(f"\n=== ATTEMPT {i+1} ===")
    try:
        t0=time.time()
        resp = client.chat.completions.create(
            model="openrouter/free",
            messages=[{"role":"user","content": prompt}],
            temperature=0.2,
            response_format={"type":"json_schema","json_schema":{"name":"weekly_quiz","strict":True,"schema": schema}}
        )
        print("model:", resp.model, "id:", resp.id)
        text = resp.choices[0].message.content
        print("raw len", len(text) if text else 0)
        print(text[:2000] if text else "EMPTY")
        if text:
            try:
                q = DraftQuiz.model_validate_json(text)
                print("VALIDATED", len(q.questions))
            except Exception as e:
                print("VALIDATION FAILED", e)
                # try parse
                # try fallback json_object manually
                pass
        else:
            print("EMPTY RESPONSE")
        print(f"time {time.time()-t0:.1f}s")
    except Exception as e:
        print("EXCEPTION", e)
        import traceback; traceback.print_exc()
        # try fallback json_object
        try:
            resp2 = client.chat.completions.create(
                model="openrouter/free",
                messages=[{"role":"user","content": prompt + "\n\nRespond with ONLY valid JSON matching the WeeklyQuiz schema. No markdown."}],
                temperature=0.2,
                response_format={"type":"json_object"}
            )
            print("fallback json_object model:", resp2.model)
            print(resp2.choices[0].message.content[:2000])
        except Exception as e2:
            print("fallback also failed", e2)
    time.sleep(1)
