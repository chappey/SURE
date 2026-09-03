let cachedQuizzesMap = {};

function formatRelativeTime(ts) {
    if (!ts) return "";
    const now = Date.now();
    const ms = typeof ts === "number" && ts < 1e11 ? ts * 1000 : Number(ts);
    if (isNaN(ms) || ms <= 0) return "";
    const diffSec = Math.round((now - ms) / 1000);
    if (diffSec < 45) return "Edited just now";
    if (diffSec < 90) return "Edited 1 min ago";
    if (diffSec < 3600) return `Edited ${Math.round(diffSec / 60)} mins ago`;
    const d = new Date(ms);
    const today = new Date();
    const isToday = d.toDateString() === today.toDateString();
    const timeStr = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (isToday) return `Edited today at ${timeStr}`;
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return `Edited yesterday at ${timeStr}`;
    return `Edited ${d.toLocaleDateString([], { month: "short", day: "numeric" })} at ${timeStr}`;
}

async function fetchQuizzesOverview() {
    const tbody = document.getElementById("quizzes-table-body");
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Loading...</td></tr>`;
    try {
        const res = await fetch("/api/quizzes/overview");
        if (!res.ok) throw new Error("Failed to load quizzes");
        const quizzes = await res.json();
        cachedQuizzesMap = {};
        if (quizzes.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No quizzes yet. Create one from the Create page.</td></tr>`;
            return;
        }
        tbody.innerHTML = "";
        quizzes.forEach(q => {
            cachedQuizzesMap[q.id] = q;
            const tr = document.createElement("tr");
            const status = q.status || (q.deployed ? "deployed" : "draft");
            const canvasUrl = q.quiz_url || null;
            const hasCanvas = Boolean(q.canvas_quiz_id || canvasUrl);
            const title = q.title || "Quiz";
            const id = q.id;

            const commentsHtml = commentsStatusHtml(q, status);
            const actionsHtml = rowActionsHtml(q, status, hasCanvas, canvasUrl, id, title);
            const timeStr = formatRelativeTime(q.updated_at || q.created_at);
            const authorStr = q.created_by ? `&bull; by ${escapeHtml(q.created_by)}` : "";

            tr.dataset.quizId = String(id);
            tr.id = `quiz-row-${id}`;
            tr.innerHTML = `
                <td>
                    <div class="quiz-title-cell">
                        <span class="quiz-title-text" style="font-weight: 600; color: var(--text-body);">${escapeHtml(title)}</span>
                        <div class="quiz-title-meta">
                            <span>${escapeHtml(timeStr)}</span>
                            ${authorStr ? `<span>${authorStr}</span>` : ''}
                        </div>
                    </div>
                </td>
                <td>${escapeHtml(q.module_name || "—")}</td>
                <td><span class="badge-qcount">${q.questions_count != null ? q.questions_count : 0} Qs</span></td>
                <td><span class="status-badge status-${escapeAttr(status)}">${escapeHtml(status)}</span></td>
                <td class="comments-cell">${commentsHtml}</td>
                <td class="action-cell">${actionsHtml}</td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error loading quizzes:", err);
        tbody.innerHTML = `<tr><td colspan="6" class="error-cell">Error loading quizzes</td></tr>`;
    }
}

function commentsStatusHtml(q, status) {
    if (status === "draft") return "—";
    const pending = q.feedback_pending;
    const done = q.feedback_done;
    const subs = q.submission_count;
    if (subs == null && (done == null || done === 0)) {
        return `<span class="text-muted-inline">—</span>`;
    }
    if (subs === 0) {
        return `<span class="text-muted-inline">No submissions yet</span>`;
    }
    if (pending != null && pending > 0) {
        return `<span class="comments-pending">${escapeHtml(pending)} need comments</span>`;
    }
    if (subs != null && pending === 0) {
        return `<span class="comments-ok">All written</span>`;
    }
    if (done > 0) {
        return `<span class="comments-ok">${escapeHtml(done)} written</span>`;
    }
    return `<span class="text-muted-inline">—</span>`;
}

/**
 * Render primary action button + 3-dots portal menu trigger for each quiz row.
 * Values ride in data-* attributes — never interpolated into inline JS strings.
 */
function rowActionsHtml(q, status, hasCanvas, canvasUrl, id, title) {
    let primaryBtn = "";

    if (status === "draft") {
        primaryBtn = `<button type="button" class="btn btn-primary btn-sm" data-action="loadDraft" data-quiz-id="${escapeAttr(id)}">Edit</button>`;
    } else if (hasCanvas) {
        primaryBtn = `<button type="button" class="btn btn-primary btn-sm" data-action="loadFeedbackWorkspace" data-quiz-id="${escapeAttr(id)}"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate feedback</button>`;
    } else {
        primaryBtn = `<button type="button" class="btn btn-secondary btn-sm" data-action="loadDraft" data-quiz-id="${escapeAttr(id)}">Edit</button>`;
    }

    const menuTriggerBtn = `<button type="button" class="action-icon-btn" data-action="openGlobalQuizMenu" data-quiz-id="${escapeAttr(id)}" title="More options"><i class="fa-solid fa-ellipsis-vertical"></i></button>`;

    return `<div style="display: flex; align-items: center; gap: 0.5rem;">${primaryBtn}${menuTriggerBtn}</div>`;
}

// Delegated dispatcher: one listener handles every data-action button,
// so untrusted values never need to appear inside inline handler strings.
document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const quizId = el.dataset.quizId;
    switch (el.dataset.action) {
        case "loadDraft":
            loadDraft(quizId);
            break;
        case "loadFeedbackWorkspace":
            loadFeedbackWorkspace(quizId);
            break;
        case "openGlobalQuizMenu":
            openGlobalQuizMenu(e, quizId, el);
            break;
        case "menuEdit":
            closeGlobalQuizMenu();
            loadDraft(quizId);
            break;
        case "menuResults": {
            const q = cachedQuizzesMap[quizId] || {};
            closeGlobalQuizMenu();
            openQuizModal(quizId, q.title || "Quiz");
            break;
        }
        case "menuPublish":
            closeGlobalQuizMenu();
            publishQuiz(quizId);
            break;
        case "menuUndeploy":
            closeGlobalQuizMenu();
            undeployQuiz(quizId);
            break;
        case "menuDelete":
            closeGlobalQuizMenu();
            deleteDraft(quizId);
            break;
    }
});

function openGlobalQuizMenu(event, quizId, triggerEl) {
    if (event) {
        event.stopPropagation();
    }
    const q = cachedQuizzesMap[quizId] || {};
    const status = q.status || (q.deployed ? "deployed" : "draft");
    // Only allow http(s) links from server data into href positions.
    const rawUrl = q.quiz_url || null;
    const canvasUrl = rawUrl && /^https?:\/\//i.test(String(rawUrl)) ? rawUrl : null;
    const hasCanvas = Boolean(q.canvas_quiz_id || canvasUrl);
    const targetBtn = triggerEl || (event && event.currentTarget);

    const globalMenu = document.getElementById("global-quiz-menu");
    if (!globalMenu) return;

    if (globalMenu.style.display === "flex" && globalMenu.dataset.activeId === String(quizId)) {
        closeGlobalQuizMenu();
        return;
    }

    const items = [];

    if (status === "draft") {
        items.push(`<button type="button" class="menu-item" data-action="menuEdit" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-pen-to-square"></i> Edit in Builder</button>`);
        items.push(`<button type="button" class="menu-item warning" data-action="menuDelete" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-trash"></i> Delete Draft</button>`);
    } else {
        if (hasCanvas && canvasUrl) {
            items.push(`<a href="${escapeAttr(canvasUrl)}" target="_blank" rel="noopener noreferrer" class="menu-item" onclick="closeGlobalQuizMenu();"><i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Canvas</a>`);
        }
        items.push(`<button type="button" class="menu-item" data-action="menuEdit" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-pen-to-square"></i> Edit in Builder</button>`);
        items.push(`<button type="button" class="menu-item" data-action="menuResults" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-chart-pie"></i> View Results</button>`);

        if (status === "deployed") {
            items.push(`<button type="button" class="menu-item" data-action="menuPublish" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-globe"></i> Publish in Canvas</button>`);
        }

        items.push(`<button type="button" class="menu-item warning" data-action="menuUndeploy" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-rotate-left"></i> Un-deploy (Reset to Draft)</button>`);
        items.push(`<button type="button" class="menu-item warning" data-action="menuDelete" data-quiz-id="${escapeAttr(quizId)}"><i class="fa-solid fa-trash"></i> Delete Draft</button>`);
    }

    globalMenu.innerHTML = items.join('');
    if (targetBtn) {
        const rect = targetBtn.getBoundingClientRect();
        const leftPos = Math.max(10, rect.right - 220);
        const topPos = rect.bottom + 6;
        globalMenu.style.cssText = `position: fixed !important; top: ${topPos}px !important; left: ${leftPos}px !important; width: 220px !important; min-width: 220px !important; display: flex !important; flex-direction: column !important; background-color: #FFFFFF !important; border: 1px solid #C7D1D8 !important; border-radius: 8px !important; box-shadow: 0 10px 30px rgba(0,0,0,0.25) !important; padding: 0.4rem 0 !important; z-index: 10050 !important;`;
    }
    globalMenu.dataset.activeId = String(quizId);
}

function closeGlobalQuizMenu() {
    const globalMenu = document.getElementById("global-quiz-menu");
    if (globalMenu) {
        globalMenu.style.display = "none";
        globalMenu.dataset.activeId = "";
    }
}

// Close global menu when clicking outside (and not on the 3-dots trigger button)
document.addEventListener("click", (e) => {
    const globalMenu = document.getElementById("global-quiz-menu");
    if (globalMenu && globalMenu.style.display !== "none" && !globalMenu.contains(e.target) && !e.target.closest("[data-action='openGlobalQuizMenu']")) {
        closeGlobalQuizMenu();
    }
});

function highlightQuizRow(quizId) {
    const row = document.getElementById(`quiz-row-${quizId}`) || document.querySelector(`tr[data-quiz-id="${quizId}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.remove("row-highlight-pulse");
    void row.offsetWidth;
    row.classList.add("row-highlight-pulse");
    setTimeout(() => {
        row.classList.remove("row-highlight-pulse");
    }, 2600);
}

async function deleteDraft(quizId) {
    const q = cachedQuizzesMap[quizId] || {};
    const title = q.title || "this quiz draft";
    if (!confirm(`Are you sure you want to delete "${title}"? This cannot be undone.`)) return;

    try {
        const res = await fetch(`/api/quizzes/${quizId}`, { method: "DELETE" });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || "Could not delete draft");
        }
        if (currentDraftQuiz && String(currentDraftQuiz.id) === String(quizId)) {
            clearDraftEditor();
        }
        await fetchQuizzesOverview();
    } catch (err) {
        console.error("Error deleting quiz draft:", err);
        alert(err.message || "Failed to delete quiz draft.");
    }
}

window.addEventListener("resize", closeGlobalQuizMenu);

async function loadDraft(quizId) {
    try {
        const res = await fetch(`/api/quizzes/${quizId}`);
        if (!res.ok) throw new Error("Could not load draft");
        currentActiveQuiz = await res.json();
        currentDraftQuiz = currentActiveQuiz;
        switchView("generator");
        renderQuizUI();
    } catch (err) {
        alert(err.message);
    }
}

async function undeployQuiz(quizId) {
    if (!confirm("Are you sure you want to un-deploy this quiz? This will reset its state back to a draft in EasyLearn so you can edit or re-test deployment.")) return;
    try {
        const res = await fetch(`/api/quizzes/${quizId}/undeploy`, { method: "POST" });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Could not un-deploy quiz");
        }
        if (currentDraftQuiz && String(currentDraftQuiz.id) === String(quizId)) {
            currentDraftQuiz.deployed = false;
        }
        await fetchQuizzesOverview();
    } catch (err) {
        alert(`Un-deploy failed: ${err.message}`);
    }
}

function processAgenticFeedback(quizId) {
    return loadFeedbackWorkspace(quizId);
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
