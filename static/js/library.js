let cachedQuizzesMap = {};

async function fetchQuizzesOverview() {
    const tbody = document.getElementById("quizzes-table-body");
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Loading...</td></tr>`;
    try {
        const res = await fetch("/api/quizzes/overview");
        if (!res.ok) throw new Error("Failed to load quizzes");
        const quizzes = await res.json();
        cachedQuizzesMap = {};
        if (quizzes.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">No quizzes yet. Create one from the Create page.</td></tr>`;
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

            tr.innerHTML = `
                <td>
                    <div class="quiz-title-cell">${escapeHtml(title)}</div>
                </td>
                <td>${escapeHtml(q.module_name || "—")}</td>
                <td><span class="status-badge status-${escapeAttr(status)}">${escapeHtml(status)}</span></td>
                <td class="comments-cell">${commentsHtml}</td>
                <td class="action-cell">${actionsHtml}</td>`;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("Error loading quizzes:", err);
        tbody.innerHTML = `<tr><td colspan="5" class="error-cell">Error loading quizzes</td></tr>`;
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
 */
function rowActionsHtml(q, status, hasCanvas, canvasUrl, id, title) {
    let primaryBtn = "";

    if (status === "draft") {
        primaryBtn = `<button type="button" class="btn btn-primary btn-sm" onclick="loadDraft('${escapeAttr(id)}')">Edit</button>`;
    } else if (hasCanvas) {
        primaryBtn = `<button type="button" class="btn btn-primary btn-sm" onclick="loadFeedbackWorkspace('${escapeAttr(id)}')"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate feedback</button>`;
    } else {
        primaryBtn = `<button type="button" class="btn btn-secondary btn-sm" onclick="loadDraft('${escapeAttr(id)}')">Edit</button>`;
    }

    const menuTriggerBtn = `<button type="button" class="action-icon-btn" onclick="openGlobalQuizMenu(event, '${escapeAttr(id)}')" title="More options"><i class="fa-solid fa-ellipsis-vertical"></i></button>`;

    return `<div style="display: flex; align-items: center; gap: 0.5rem;">${primaryBtn}${menuTriggerBtn}</div>`;
}

function openGlobalQuizMenu(event, quizId) {
    event.stopPropagation();
    const q = cachedQuizzesMap[quizId] || {};
    const status = q.status || (q.deployed ? "deployed" : "draft");
    const canvasUrl = q.quiz_url || null;
    const hasCanvas = Boolean(q.canvas_quiz_id || canvasUrl);
    const title = q.title || "Quiz";
    const targetBtn = event.currentTarget;

    const globalMenu = document.getElementById("global-quiz-menu");
    if (!globalMenu) return;

    if (globalMenu.style.display === "flex" && globalMenu.dataset.activeId === String(quizId)) {
        closeGlobalQuizMenu();
        return;
    }

    const items = [];

    if (status === "draft") {
        items.push(`<button type="button" class="menu-item" onclick="closeGlobalQuizMenu(); loadDraft('${escapeAttr(quizId)}');"><i class="fa-solid fa-pen-to-square"></i> Edit in Builder</button>`);
    } else {
        if (hasCanvas && canvasUrl) {
            items.push(`<a href="${escapeAttr(canvasUrl)}" target="_blank" class="menu-item" onclick="closeGlobalQuizMenu();"><i class="fa-solid fa-arrow-up-right-from-square"></i> Open in Canvas</a>`);
        }
        items.push(`<button type="button" class="menu-item" onclick="closeGlobalQuizMenu(); loadDraft('${escapeAttr(quizId)}');"><i class="fa-solid fa-pen-to-square"></i> Edit in Builder</button>`);
        items.push(`<button type="button" class="menu-item" onclick="closeGlobalQuizMenu(); openQuizModal('${escapeAttr(quizId)}', '${escapeAttr(title)}');"><i class="fa-solid fa-chart-pie"></i> View Results</button>`);

        if (status === "deployed") {
            items.push(`<button type="button" class="menu-item" onclick="closeGlobalQuizMenu(); publishQuiz('${escapeAttr(quizId)}');"><i class="fa-solid fa-globe"></i> Publish in Canvas</button>`);
        }

        items.push(`<button type="button" class="menu-item warning" onclick="closeGlobalQuizMenu(); undeployQuiz('${escapeAttr(quizId)}');"><i class="fa-solid fa-rotate-left"></i> Un-deploy (Reset to Draft)</button>`);
    }

    globalMenu.innerHTML = items.join('');
    const rect = targetBtn.getBoundingClientRect();
    const leftPos = Math.max(10, rect.right - 220);
    const topPos = rect.bottom + 6;
    globalMenu.style.cssText = `position: fixed !important; top: ${topPos}px !important; left: ${leftPos}px !important; width: 220px !important; min-width: 220px !important; display: flex !important; flex-direction: column !important; background-color: #FFFFFF !important; border: 1px solid #C7D1D8 !important; border-radius: 8px !important; box-shadow: 0 10px 30px rgba(0,0,0,0.25) !important; padding: 0.4rem 0 !important; z-index: 10000 !important;`;
    globalMenu.dataset.activeId = String(quizId);
}

function closeGlobalQuizMenu() {
    const globalMenu = document.getElementById("global-quiz-menu");
    if (globalMenu) {
        globalMenu.style.display = "none";
        globalMenu.dataset.activeId = "";
    }
}

document.addEventListener("click", (e) => {
    const globalMenu = document.getElementById("global-quiz-menu");
    if (globalMenu && !globalMenu.contains(e.target)) {
        closeGlobalQuizMenu();
    }
});

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
