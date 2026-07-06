/* Quiz Library view: overview table, draft loading, publish. */

async function fetchQuizzesOverview() {
    const tbody = document.getElementById("quizzes-table-body");
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Loading...</td></tr>`;
    try {
        const res = await fetch("/api/quizzes/overview");
        if (!res.ok) throw new Error("Failed to load quizzes");
        const quizzes = await res.json();
        if (quizzes.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">No quizzes in this course workspace yet. Create one in the Create Quiz view.</td></tr>`;
            return;
        }
        tbody.innerHTML = "";
        quizzes.forEach(q => {
            const tr = document.createElement("tr");
            const status = q.status || (q.deployed ? "deployed" : "draft");
            const canvasUrl = q.quiz_url || null;
            const hasCanvas = Boolean(q.canvas_quiz_id || canvasUrl);
            const chips = [];
            if (q.includes_agentic_feedback) {
                chips.push(`<span class="feature-chip chip-feedback" title="AI feedback: confidence + explanation per question"><i class="fa-solid fa-comment-dots"></i> Feedback</span>`);
            }
            if (q.includes_feedback) {
                chips.push(`<span class="feature-chip chip-survey" title="End-of-quiz survey"><i class="fa-solid fa-square-poll-vertical"></i> Survey</span>`);
            }
            tr.innerHTML = `
                <td>
                    <div class="quiz-title-cell">${escapeHtml(q.title)}</div>
                    <div class="quiz-chips">${chips.join("")}</div>
                </td>
                <td>${escapeHtml(q.module_name || "—")}</td>
                <td>${escapeHtml(q.questions_count || q.question_count || "—")}</td>
                <td><span class="status-badge status-${escapeAttr(status)}">${escapeHtml(status)}</span></td>
                <td class="action-cell">
                    ${hasCanvas && canvasUrl ? `<a href="${escapeAttr(canvasUrl)}" target="_blank" class="btn btn-secondary btn-sm btn-link">Canvas</a>` : ""}
                    ${status === "draft" ? `<button class="btn btn-secondary btn-sm" onclick="loadDraft('${escapeAttr(q.id)}')">Edit</button>` : ""}
                    ${status === "deployed" ? `<button class="btn btn-primary btn-sm" onclick="publishQuiz('${escapeAttr(q.id)}')">Publish</button>` : ""}
                    ${hasCanvas ? `<button class="btn btn-secondary btn-sm" data-quiz-id="${escapeAttr(q.id)}" data-quiz-title="${escapeAttr(q.title)}" onclick="openQuizModal(this.dataset.quizId, this.dataset.quizTitle)">Details</button>` : ""}
                </td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error loading quizzes:", err);
        tbody.innerHTML = `<tr><td colspan="5" class="error-cell">Error loading quizzes</td></tr>`;
    }
}

async function loadDraft(quizId) {
    try {
        const res = await fetch(`/api/quizzes/${quizId}`);
        if (!res.ok) throw new Error("Could not load draft");
        currentActiveQuiz = await res.json();
        switchView("generator");
        renderQuizUI();
    } catch (err) {
        alert(err.message);
    }
}

async function publishQuiz(quizId) {
    try {
        const res = await fetch(`/api/quizzes/${quizId}/publish`, { method: "POST" });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Publish failed");
        }
        await fetchQuizzesOverview();
    } catch (err) {
        alert(`Publish failed: ${err.message}`);
    }
}
