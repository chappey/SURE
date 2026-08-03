/* Feedback Review Workspace: inspect, edit, regenerate, and push student feedback comments to Canvas. */

let currentFeedbackData = null;
let feedbackAutosaveTimer = null;
let feedbackWorkspaceQuizId = null;

const CONFIDENCE_CHIP_CLASS = {
    "Not at all confident": "confidence-chip confidence-1",
    "Slightly confident": "confidence-chip confidence-2",
    "Moderately confident": "confidence-chip confidence-3",
    "Very confident": "confidence-chip confidence-4",
    "Completely confident": "confidence-chip confidence-5",
};

async function loadFeedbackWorkspace(quizId, { force = false } = {}) {
    switchView("feedback-review");
    feedbackWorkspaceQuizId = quizId;
    const container = document.getElementById("feedback-submissions-container");
    const statusEl = document.getElementById("feedback-review-status");

    // Fast path: show saved workspace immediately when not forcing regenerate.
    if (!force) {
        try {
            const cachedRes = await fetch(`/api/quizzes/${quizId}/agentic-feedback/workspace`);
            if (cachedRes.ok) {
                const cached = await cachedRes.json();
                if (cached.submissions && cached.submissions.length) {
                    currentFeedbackData = cached;
                    renderFeedbackWorkspace(cached);
                    if (statusEl) {
                        statusEl.innerHTML = `<span class="type-badge badge-matching"><i class="fa-solid fa-floppy-disk"></i> Saved draft</span> Syncing new submissions…`;
                    }
                }
            }
        } catch (_) { /* fall through to preview */ }
    }

    if (statusEl && (!currentFeedbackData || force)) {
        statusEl.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${force ? "Regenerating feedback…" : "Loading submissions…"}`;
    }
    if (container && (!currentFeedbackData || !currentFeedbackData.submissions || !currentFeedbackData.submissions.length || force)) {
        container.innerHTML = `<div class="empty-cell" style="padding: 3rem;"><i class="fa-solid fa-spinner fa-spin" style="font-size: 1.5rem; color: var(--brand-primary);"></i><p style="margin-top: 0.75rem;">${force ? "Regenerating AI comments from source material…" : "Loading feedback workspace…"}</p></div>`;
    }

    try {
        const res = await fetch(`/api/quizzes/${quizId}/agentic-feedback/preview`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: Boolean(force) })
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Could not load feedback preview.");
        }
        currentFeedbackData = await res.json();
        renderFeedbackWorkspace(currentFeedbackData);
    } catch (err) {
        console.error("Error loading feedback preview:", err);
        if (container && (!currentFeedbackData || !currentFeedbackData.submissions || !currentFeedbackData.submissions.length)) {
            container.innerHTML = `<div class="glass-card" style="padding: 2rem; text-align: center; color: var(--danger);">
                <i class="fa-solid fa-circle-exclamation" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
                <h4>Could not load student submissions</h4>
                <p style="color: var(--text-muted); font-size: 0.875rem;">${escapeHtml(err.message)}</p>
                <button type="button" class="btn btn-secondary btn-sm" style="margin-top: 1rem;" onclick="switchView('quizzes')">Return to Quiz Library</button>
            </div>`;
        } else if (statusEl) {
            statusEl.innerHTML = `<span class="type-badge badge-tf">Sync issue</span> ${escapeHtml(err.message)}`;
        }
    }
}

function confidenceChipHtml(label) {
    const plain = htmlToPlainText(label || "Not reported");
    const cls = CONFIDENCE_CHIP_CLASS[plain] || "confidence-chip confidence-unknown";
    return `<span class="${cls}">${escapeHtml(plain)}</span>`;
}

function collectWorkspaceSubmissionsFromDom() {
    if (!currentFeedbackData || !currentFeedbackData.submissions) return [];
    return currentFeedbackData.submissions.map((sub, sIndex) => {
        const questions = (sub.questions || []).map((q, qIndex) => {
            const textarea = document.getElementById(`fb-comment-${sIndex}-${qIndex}`);
            return {
                ...q,
                ai_feedback: textarea ? textarea.value : (q.ai_feedback || "")
            };
        });
        return { ...sub, questions };
    });
}

function scheduleFeedbackAutosave() {
    if (feedbackAutosaveTimer) clearTimeout(feedbackAutosaveTimer);
    feedbackAutosaveTimer = setTimeout(() => {
        saveFeedbackWorkspaceDraft().catch(err => console.warn("Autosave failed:", err));
    }, 800);
}

async function saveFeedbackWorkspaceDraft() {
    if (!currentFeedbackData || !currentFeedbackData.quiz_id) return;
    const submissions = collectWorkspaceSubmissionsFromDom();
    currentFeedbackData.submissions = submissions;
    const res = await fetch(`/api/quizzes/${currentFeedbackData.quiz_id}/agentic-feedback/workspace`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ submissions })
    });
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(parseApiDetail(data) || "Could not save feedback draft.");
    }
    const statusEl = document.getElementById("feedback-review-status");
    if (statusEl && !statusEl.innerHTML.includes("fa-spinner")) {
        statusEl.innerHTML = `<span class="type-badge badge-matching"><i class="fa-solid fa-floppy-disk"></i> Saved</span> Edits stored — switch courses anytime.`;
    }
}

function renderFeedbackWorkspace(data) {
    const container = document.getElementById("feedback-submissions-container");
    const titleEl = document.getElementById("feedback-quiz-title");
    const metaEl = document.getElementById("feedback-meta-summary");
    const statusEl = document.getElementById("feedback-review-status");

    if (titleEl) titleEl.textContent = data.quiz_title || "Quiz Feedback Review";
    if (metaEl) {
        metaEl.textContent = `${data.submissions ? data.submissions.length : 0} Submissions Ready • ${data.questions ? data.questions.length : 0} Questions`;
    }
    if (statusEl) {
        const sourceNote = data.source_available
            ? "Grounded in course materials."
            : "No stored source text — regenerate quiz later to attach materials.";
        const genNote = data.generated_new
            ? ` Generated ${data.generated_new} new.`
            : "";
        statusEl.innerHTML = `<span class="type-badge badge-matching"><i class="fa-solid fa-eye"></i> Review Mode</span> ${sourceNote}${genNote}`;
    }

    if (!container) return;
    container.innerHTML = "";

    if (!data.submissions || data.submissions.length === 0) {
        container.innerHTML = `<div class="glass-card" style="padding: 2.5rem; text-align: center; color: var(--text-muted);">
            <i class="fa-solid fa-user-clock" style="font-size: 2rem; margin-bottom: 0.5rem;"></i>
            <p>No completed student submissions found in Canvas yet for this quiz.</p>
            <button type="button" class="btn btn-secondary btn-sm" style="margin-top: 0.75rem;" onclick="switchView('quizzes')">Back to Quiz Library</button>
        </div>`;
        return;
    }

    data.submissions.forEach((sub, sIndex) => {
        const card = document.createElement("div");
        card.className = "glass-card";
        card.style.marginBottom = "1.25rem";

        let questionsHTML = "";
        (sub.questions || []).forEach((q, qIndex) => {
            const isCorrect = q.score > 0;
            const qText = escapeHtml(htmlToPlainText(q.question_text));
            const choice = escapeHtml(htmlToPlainText(q.student_answer || "No response"));
            const explanation = escapeHtml(htmlToPlainText(q.explanation || "None provided"));
            const verdictIcon = isCorrect
                ? `<i class="fa-solid fa-circle-check choice-correct" title="Correct" aria-label="Correct"></i>`
                : `<i class="fa-solid fa-circle-xmark choice-incorrect" title="Incorrect" aria-label="Incorrect"></i>`;
            questionsHTML += `
                <div class="feedback-question-row" style="padding: 1rem; border: 1px solid var(--border-light); border-radius: 6px; margin-top: 0.75rem; background: var(--bg-surface);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                        <strong style="font-size: 0.9rem;">Q${qIndex + 1}: ${qText}</strong>
                        <span class="type-badge ${isCorrect ? 'badge-matching' : 'badge-tf'}">${isCorrect ? 'Correct' : 'Needs Review'}</span>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; font-size: 0.82rem; background: var(--bg-subtle); padding: 0.65rem 0.85rem; border-radius: 4px; margin-bottom: 0.75rem;">
                        <div><strong style="color: var(--text-muted);">Student Choice:</strong> ${verdictIcon} ${choice}</div>
                        <div><strong style="color: var(--text-muted);">Confidence:</strong> ${confidenceChipHtml(q.confidence)}</div>
                        <div style="grid-column: 1 / -1;"><strong style="color: var(--text-muted);">Explanation:</strong> <em>"${explanation}"</em></div>
                    </div>
                    <div class="form-group" style="margin-bottom: 0.25rem;">
                        <label style="font-size: 0.8rem; font-weight: 600; color: var(--brand-primary);"><i class="fa-solid fa-wand-magic-sparkles"></i> AI Feedback Comment for Student:</label>
                        <textarea id="fb-comment-${sIndex}-${qIndex}" rows="3" class="fb-comment-input" data-s="${sIndex}" data-q="${qIndex}" style="width: 100%; font-size: 0.85rem; padding: 0.5rem; border-radius: 4px; border: 1px solid var(--border);">${escapeHtml(q.ai_feedback || "")}</textarea>
                    </div>
                </div>
            `;
        });

        const scoreLine = formatScoreDisplay(
            sub.score,
            sub.points_possible != null ? sub.points_possible : data.points_possible
        );
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border-light);">
                <div>
                    <h4 style="margin: 0; font-size: 1.05rem;">${escapeHtml(sub.user_name || "Student")}</h4>
                    ${scoreLine ? `<span style="font-size: 0.78rem; color: var(--text-muted);">Score: ${escapeHtml(scoreLine)}</span>` : ""}
                </div>
                <button type="button" class="btn btn-secondary btn-sm" onclick="loadFeedbackWorkspace('${escapeAttr(data.quiz_id)}', { force: true })"><i class="fa-solid fa-arrows-rotate"></i> Regenerate</button>
            </div>
            ${questionsHTML}
        `;
        container.appendChild(card);
    });

    container.querySelectorAll(".fb-comment-input").forEach(el => {
        el.addEventListener("input", scheduleFeedbackAutosave);
    });
}

async function approveAndPushFeedback() {
    if (!currentFeedbackData || !currentFeedbackData.submissions) return;

    const pushBtn = document.getElementById("btn-approve-push");
    const originalHTML = pushBtn ? pushBtn.innerHTML : "Approve & Push to Canvas";
    if (pushBtn) {
        pushBtn.disabled = true;
        pushBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Pushing to Canvas...`;
    }

    try {
        await saveFeedbackWorkspaceDraft();
        const submissions = collectWorkspaceSubmissionsFromDom();
        const approvedSubmissions = submissions.map((sub) => {
            const comments = {};
            (sub.questions || []).forEach((q) => {
                comments[q.question_id != null ? q.question_id : q.q_index] = q.ai_feedback || "";
            });
            return {
                submission_id: sub.submission_id,
                user_id: sub.user_id,
                comments: comments
            };
        });

        const res = await fetch(`/api/quizzes/${currentFeedbackData.quiz_id}/agentic-feedback/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ submissions: approvedSubmissions })
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Failed to push feedback to Canvas.");
        }

        alert("Feedback comments successfully approved and pushed to Canvas!");
        switchView("quizzes");
    } catch (err) {
        console.error("Error pushing feedback:", err);
        alert(`Could not push feedback: ${err.message}`);
    } finally {
        if (pushBtn) {
            pushBtn.disabled = false;
            pushBtn.innerHTML = originalHTML;
        }
    }
}

