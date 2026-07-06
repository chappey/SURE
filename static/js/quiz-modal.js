/* Quiz detail modal: tabbed Overview / Feedback / Survey with visualizations. */

let modalQuizId = null;

function openQuizModal(quizId, title) {
    modalQuizId = quizId;
    document.getElementById("quiz-modal-title").textContent = title || "Quiz Details";
    document.getElementById("quiz-modal-overlay").classList.add("open");
    document.body.style.overflow = "hidden";
    switchModalTab("overview");
    loadQuizModalData(quizId);
}

function closeQuizModal() {
    const overlay = document.getElementById("quiz-modal-overlay");
    if (!overlay || !overlay.classList.contains("open")) return;
    overlay.classList.remove("open");
    document.body.style.overflow = "";
    modalQuizId = null;
}

function onModalOverlayClick(event) {
    if (event.target === document.getElementById("quiz-modal-overlay")) {
        closeQuizModal();
    }
}

function switchModalTab(tab) {
    document.querySelectorAll(".modal-tab").forEach(t => {
        t.classList.toggle("active", t.dataset.tab === tab);
    });
    document.querySelectorAll(".modal-tab-panel").forEach(p => {
        p.classList.toggle("active", p.id === `modal-tab-${tab}`);
    });
}

async function loadQuizModalData(quizId) {
    const overviewEl = document.getElementById("modal-tab-overview");
    const feedbackEl = document.getElementById("modal-tab-feedback");
    const surveyEl = document.getElementById("modal-tab-survey");
    const loading = `<p class="text-muted-inline"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</p>`;
    overviewEl.innerHTML = loading;
    feedbackEl.innerHTML = loading;
    surveyEl.innerHTML = loading;

    try {
        const [statsRes, surveyRes, quizRes] = await Promise.all([
            fetch(`/api/quizzes/${quizId}/stats`),
            fetch(`/api/quizzes/${quizId}/feedback`),
            fetch(`/api/quizzes/${quizId}`)
        ]);
        const stats = statsRes.ok ? await statsRes.json() : null;
        const survey = surveyRes.ok ? await surveyRes.json() : null;
        const quizDraft = quizRes.ok ? await quizRes.json() : null;

        if (modalQuizId !== quizId) return; // modal was closed or switched

        renderModalOverview(overviewEl, stats);
        renderModalFeedback(feedbackEl, quizId, quizDraft);
        renderModalSurvey(surveyEl, survey);
    } catch (err) {
        console.error("Error loading quiz details:", err);
        overviewEl.innerHTML = `<p class="error-cell">Could not load details.</p>`;
        feedbackEl.innerHTML = "";
        surveyEl.innerHTML = "";
    }
}

/* ---------- Overview tab ---------- */

function isMetaQuestionName(name) {
    const n = String(name || "");
    return n.startsWith("[Agentic]") || n.startsWith("[Feedback]");
}

function renderModalOverview(el, stats) {
    if (!stats || !stats.available) {
        el.innerHTML = `<p class="text-muted-inline">No submission statistics yet. Statistics appear after students submit.</p>`;
        return;
    }

    const avg = stats.score_average != null ? Number(stats.score_average).toFixed(1) : "—";
    const high = stats.score_high ?? "—";
    const low = stats.score_low ?? "—";
    const stdev = stats.score_stdev != null ? Number(stats.score_stdev).toFixed(1) : "—";

    let html = `
        <div class="stat-cards">
            <div class="stat-card">
                <span class="stat-value">${escapeHtml(stats.submission_count ?? 0)}</span>
                <span class="stat-label">Submissions</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${escapeHtml(avg)}</span>
                <span class="stat-label">Avg score</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${escapeHtml(high)} / ${escapeHtml(low)}</span>
                <span class="stat-label">High / Low</span>
            </div>
            <div class="stat-card">
                <span class="stat-value">${escapeHtml(stdev)}</span>
                <span class="stat-label">Std dev</span>
            </div>
        </div>`;

    const contentQs = (stats.questions || []).filter(q => !isMetaQuestionName(q.question_name));
    if (contentQs.length) {
        html += `<h5 class="modal-section-title">Per-question correct rate</h5>`;
        contentQs.forEach((q, idx) => {
            const total = q.responses || 0;
            const pct = total ? Math.round((q.correct_count / total) * 100) : 0;
            const name = q.question_name || `Question ${idx + 1}`;
            const barClass = pct >= 70 ? "good" : (pct >= 40 ? "mid" : "poor");
            html += `
                <div class="qstat-row">
                    <span class="qstat-name" title="${escapeAttr(name)}">${escapeHtml(name)}</span>
                    <div class="qstat-track">
                        <div class="qstat-fill ${barClass}" style="width:${pct}%"></div>
                    </div>
                    <span class="qstat-pct">${pct}% <span class="qstat-n">(${total})</span></span>
                </div>`;
        });
    }

    el.innerHTML = html;
}

/* ---------- Feedback tab (agentic) ---------- */

function renderModalFeedback(el, quizId, quizDraft) {
    if (!quizDraft || !quizDraft.includes_agentic_feedback) {
        el.innerHTML = `
            <p class="text-muted-inline">AI feedback is not enabled for this quiz.
            Enable "Include feedback" when generating a quiz to collect per-question confidence and
            explanations, then generate personalized comments here.</p>`;
        return;
    }

    const processed = quizDraft.agentic_feedback_processed || {};
    const processedEntries = Object.entries(processed);
    const lastRun = quizDraft.agentic_feedback_last_run;

    let processedHTML = "";
    if (processedEntries.length) {
        processedHTML = `
            <h5 class="modal-section-title">Processed submissions</h5>
            <table class="modal-mini-table">
                <thead><tr><th>Submission</th><th>Student</th><th>Comments</th><th>When</th></tr></thead>
                <tbody>
                    ${processedEntries.map(([subId, info]) => `
                        <tr>
                            <td>#${escapeHtml(subId)}</td>
                            <td>${escapeHtml(info.user_id ?? "—")}</td>
                            <td>${escapeHtml(info.questions ?? "—")}</td>
                            <td>${escapeHtml(formatTimestamp(info.processed_at))}</td>
                        </tr>`).join("")}
                </tbody>
            </table>`;
    }

    el.innerHTML = `
        <p class="text-muted-inline">Generate personalized comments from each student's confidence
        rating and written explanation. Students see comments on their graded submission in Canvas.</p>
        <p><strong>Processed:</strong> ${processedEntries.length} submission(s)${lastRun ? ` · Last run: ${escapeHtml(formatTimestamp(lastRun))}` : ""}</p>
        <div class="agentic-feedback-actions">
            <button class="btn btn-primary btn-sm" id="btn-agentic-process" onclick="processAgenticFeedback('${escapeAttr(quizId)}', false)">
                <i class="fa-solid fa-wand-magic-sparkles"></i> Generate Feedback
            </button>
            <button class="btn btn-secondary btn-sm" id="btn-agentic-reprocess" onclick="processAgenticFeedback('${escapeAttr(quizId)}', true)">
                Re-process all
            </button>
        </div>
        <div id="agentic-process-status"></div>
        ${processedHTML}`;
}

async function processAgenticFeedback(quizId, force) {
    const statusEl = document.getElementById("agentic-process-status");
    const btn = document.getElementById("btn-agentic-process");
    const btn2 = document.getElementById("btn-agentic-reprocess");
    if (statusEl) statusEl.innerHTML = `<p class="text-muted-inline"><i class="fa-solid fa-spinner fa-spin"></i> Generating feedback… this can take a while for many submissions.</p>`;
    if (btn) btn.disabled = true;
    if (btn2) btn2.disabled = true;

    try {
        const res = await fetch(`/api/quizzes/${quizId}/agentic-feedback/process`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(parseApiDetail(data) || "Processing failed");

        let html = `<p class="agentic-success"><strong>Done.</strong> Processed ${escapeHtml(data.processed)} submission(s)`;
        if (data.skipped) html += `, skipped ${escapeHtml(data.skipped)} already processed`;
        html += `.</p>`;
        if (data.errors && data.errors.length) {
            const messages = data.errors.slice(0, 3)
                .map(e => `Submission ${escapeHtml(e.submission_id ?? "?")}: ${escapeHtml(e.error ?? "unknown error")}`)
                .join("<br>");
            html += `<p class="error-cell" style="text-align:left;">${escapeHtml(String(data.errors.length))} error(s):<br>${messages}</p>`;
        }
        if (statusEl) statusEl.innerHTML = html;

        // Refresh the processed table
        if (modalQuizId === quizId) {
            const quizRes = await fetch(`/api/quizzes/${quizId}`);
            if (quizRes.ok) {
                const draft = await quizRes.json();
                const status = statusEl ? statusEl.innerHTML : "";
                renderModalFeedback(document.getElementById("modal-tab-feedback"), quizId, draft);
                const newStatus = document.getElementById("agentic-process-status");
                if (newStatus) newStatus.innerHTML = status;
            }
        }
    } catch (err) {
        if (statusEl) statusEl.innerHTML = `<p class="error-cell">${escapeHtml(err.message)}</p>`;
        if (btn) btn.disabled = false;
        if (btn2) btn2.disabled = false;
    }
}

/* ---------- Survey tab ---------- */

function renderModalSurvey(el, survey) {
    if (!survey || !survey.has_feedback) {
        el.innerHTML = `<p class="text-muted-inline">No survey on this quiz. Enable "Include survey at the end of the quiz" when generating to collect student opinions.</p>`;
        return;
    }
    if (!survey.questions.length) {
        el.innerHTML = `<p class="text-muted-inline">Survey enabled, but no responses yet.</p>`;
        return;
    }

    let html = "";
    survey.questions.forEach(fq => {
        const max = Math.max(...Object.values(fq.distribution || {}), 1);
        const total = fq.total_responses || 0;
        let bars = "";
        (fq.likert_labels || []).forEach(label => {
            const count = (fq.distribution || {})[label] || 0;
            const pct = (count / max) * 100;
            bars += `
                <div class="feedback-bar-row">
                    <span class="feedback-bar-label">${escapeHtml(label)}</span>
                    <div class="feedback-bar-track"><div class="feedback-bar-fill" style="width:${pct}%"></div></div>
                    <span>${escapeHtml(count)}</span>
                </div>`;
        });
        html += `
            <div class="survey-question-block">
                <strong>${escapeHtml(fq.question_name)}</strong>
                <span class="text-muted-inline"> · ${escapeHtml(total)} response(s)</span>
                ${bars}
            </div>`;
    });
    el.innerHTML = html;
}
