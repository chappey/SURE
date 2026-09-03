import os, json
from openai import OpenAI

api_key=os.environ.get('OPENROUTER_API_KEY','')
print('key present:', bool(api_key), 'len', len(api_key))
if not api_key:
    print('NO KEY')
    raise SystemExit
client=OpenAI(base_url='https://openrouter.ai/api/v1', api_key=api_key, timeout=60, default_headers={"HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER",""), "X-Title": os.environ.get("OPENROUTER_APP_NAME","EasyLearn")})

# test free router simple json_object
try:
    r=client.chat.completions.create(model='openrouter/free', messages=[{'role':'user','content':'Say hello in JSON: {\"hello\": \"world\"}'}], response_format={'type':'json_object'}, temperature=0.2)
    print('openrouter/free json_object OK', r.choices[0].message.content[:800])
    print('model used:', r.model, 'id:', r.id)
except Exception as e:
    print('FAILED json_object', e)
    import traceback; traceback.print_exc()

# test json_schema
try:
    schema={'type':'object','properties':{'hello':{'type':'string'}},'required':['hello'],'additionalProperties':False}
    r=client.chat.completions.create(model='openrouter/free', messages=[{'role':'user','content':'Say hello'}], response_format={'type':'json_schema','json_schema':{'name':'test','strict':True,'schema':schema}}, temperature=0.2)
    print('openrouter/free json_schema OK', r.choices[0].message.content[:800])
    print('model used:', r.model)
except Exception as e:
    print('FAILED json_schema', e)
    import traceback; traceback.print_exc()

# test full quiz schema - minimal
try:
    from app.schemas import DraftQuiz
    schema = DraftQuiz.model_json_schema()
    print('DraftQuiz schema keys:', list(schema.keys())[:5])
    prompt = """You are a university CS instructor. Generate a quiz with exactly 1 multiple_choice_question with 4 options. Use ONLY this material: CPU scheduling.”
    The quiz MUST have exactly 1 questions in total.
    - Generate exactly 1 multiple_choice_question items. Each multiple_choice_question must have exactly 4 answer options (one correct with answer_weight=100, the remaining 3 incorrect with answer_weight=0).
    Format: question_name, question_text, difficulty easy/medium/hard, quiz_title.
    Course material: CPU scheduling - Round Robin, FCFS, SJF.
    """
    from app.llm.catalog import ModelEntry
    from app.llm.providers.openrouter import generate_json
    entry = ModelEntry(id="test-free", label="Free Router", provider="openrouter", model="openrouter/free")
    text = generate_json(entry, prompt, schema)
    print('FULL QUIZ json_schema via provider OK:', text[:3000])
    # validate
    q = DraftQuiz.model_validate_json(text)
    print('VALIDATED questions:', len(q.questions), 'first:', q.questions[0].model_dump() if q.questions else None)
except Exception as e:
    print('FAILED full quiz', e)
    import traceback; traceback.print_exc()
