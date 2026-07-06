# Agentic Feedback — Feature Spec

EasyLearn generates Canvas quizzes from course materials. This document describes
**agentic feedback**: personalized per-question comments for students at grade time,
driven by their confidence rating and self-explanation.

---

## Problem

Today, optional **static** feedback (`include_answer_feedback`) bakes one
`correct_comments` / `incorrect_comments` string into each Canvas question at deploy.
Every student sees the same text based only on right/wrong.

Agentic feedback replaces that with **dynamic** comments written per submission after
the student completes the quiz.

---

## Student experience (Canvas-native)

For each **content question**, the deployed quiz includes two extra **ungraded** questions:

| Meta question | Canvas type | Purpose |
|---------------|-------------|---------|
| Confidence | Multiple choice (Likert) | How confident were you in your answer? |
| Explanation | Essay | Why did you choose that answer? |

Meta questions are tagged `[Agentic]` in `question_name` and appear immediately after
their parent content question.

When the assignment is **graded**, the student sees **AI-generated feedback** on each
content question — not static correct/incorrect HTML.

---

## Instructor experience (EasyLearn dashboard)

1. Enable **Feedback** when generating a quiz (mutually exclusive with static
   answer explanations).
2. Deploy to Canvas as usual. EasyLearn stores a mapping of Canvas question IDs
   (content ↔ confidence ↔ explanation).
3. After students submit, open **Quiz Details** in the library view and click
   **Generate Feedback** (v1).
4. EasyLearn reads submissions, calls the LLM per content question, and writes
   personalized comments via the Canvas Quiz Submissions API.
5. Release grades in Canvas as usual; students see the generated feedback.

The optional end-of-quiz **survey** (`include_feedback` / `[Feedback]` prefix) collects
Likert ratings about the quiz itself and is orthogonal to per-question feedback.

---

## Delivery mechanism

Static feedback uses question-level fields:

- `correct_comments_html` / `incorrect_comments_html`

Agentic feedback uses **per-submission question comments**:

```
PUT /api/v1/courses/:course_id/quizzes/:quiz_id/submissions/:id

{
  "quiz_submissions": [{
    "attempt": 1,
    "questions": {
      "<content_question_canvas_id>": {
        "comment": "<AI-generated personalized feedback>"
      }
    }
  }]
}
```

OAuth scope required: `url:PUT|/api/v1/courses/:course_id/quizzes/:quiz_id/submissions/:id`

When agentic feedback is enabled, content questions deploy **without** static
correct/incorrect comments.

---

## AI behavior

For each content question, the model receives:

- Question stem and correct answer
- Student's chosen answer and whether it was correct
- Confidence label (5-point scale)
- Student's explanation text

The model produces a short comment that:

1. **Calibrates tone to confidence** — e.g. high confidence + wrong → respectful
   correction; low confidence + correct → encouraging; high confidence + correct → affirm
   and extend.
2. **Responds to the explanation** — references their reasoning, addresses
   misconceptions, reinforces good thinking.

Output is plain text suitable for Canvas `comment` fields.

---

## Data stored on quiz draft

```json
{
  "includes_agentic_feedback": true,
  "agentic_feedback": {
    "enabled": true,
    "questions": [
      {
        "content_index": 0,
        "content_canvas_id": 101,
        "confidence_canvas_id": 102,
        "explanation_canvas_id": 103
      }
    ]
  },
  "agentic_feedback_processed": {
    "45678": {
      "processed_at": 1710000000.0,
      "questions": 5
    }
  },
  "agentic_feedback_last_run": 1710000000.0
}
```

Question ID mapping is created at deploy time (Canvas assigns IDs). Without mapping,
the process endpoint returns an error asking to redeploy.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/quizzes/{quiz_id}/agentic-feedback/process` | Batch-process unprocessed submissions |

Optional JSON body: `{ "force": false }` — re-process already-handled submissions when
`force` is true.

Response:

```json
{
  "processed": 3,
  "skipped": 1,
  "errors": [],
  "submissions": [
    { "submission_id": 45678, "user_id": 12, "questions": 5 }
  ]
}
```

---

## Code map

| Path | Role |
|------|------|
| `app/agentic_feedback.py` | Meta questions, prompt, LLM comment generation |
| `app/deployment.py` | Interleave meta questions; capture Canvas IDs |
| `app/quizzes_service.py` | Orchestrate batch processing |
| `app/canvas_courses.py` | Submission fetch + comment update helpers |
| `app/llm/registry.py` | `generate_text()` for unstructured feedback |
| `app/routers/api.py` | Process endpoint; generate/deploy flags |
| `templates/dashboard.html` | Toggle + Generate button in quiz details |

---

## v1 scope

- Instructor-triggered batch button (no webhooks, no background workers)
- Idempotent processing (skip already-processed submission IDs unless `force`)
- Instructor-only; students remain entirely in Canvas
- Single-process deployment constraint unchanged

---

## Future work

- Auto-run on new submissions (polling or Canvas events)
- Student preview in EasyLearn
- Store source material on draft for richer grounding
- Matching-question-specific feedback logic
