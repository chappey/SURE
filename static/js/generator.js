/* Generator view: models, modules, generation, preview editing, deploy. */

let currentStep = 1;
let stepInterval = null;

/* ---------- Models ---------- */

function modelStorageKey() {
    return currentCourseId ? `easylearn_model_${currentCourseId}` : "easylearn_model_default";
}

async function fetchModels() {
    try {
        const res = await fetch("/api/models");
        if (!res.ok) throw new Error("Failed to load models");
        loadedModels = await res.json();
        populateModelSelect();
    } catch (err) {
        console.error("Error loading models:", err);
        const select = document.getElementById("model-select");
        select.innerHTML = `<option value="">Models unavailable</option>`;
    }
}

function populateModelSelect() {
    const select = document.getElementById("model-select");
    select.innerHTML = "";

    if (!loadedModels.length) {
        select.innerHTML = `<option value="">No models configured</option>`;
        return;
    }

    const storedId = sessionStorage.getItem(modelStorageKey());

    loadedModels.forEach(model => {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.label;
        if (!model.available) {
            opt.disabled = true;
            opt.title = "Not configured on server (missing API key)";
        }
        select.appendChild(opt);
    });

    const preferred = loadedModels.find(m => m.id === storedId && m.available)
        || loadedModels.find(m => m.default && m.available)
        || loadedModels.find(m => m.available)
        || loadedModels[0];
    if (preferred) {
        select.value = preferred.id;
    }
    onModelChange();
}

function onModelChange() {
    const select = document.getElementById("model-select");
    const model = loadedModels.find(m => m.id === select.value);
    if (select.value && model?.available) {
        sessionStorage.setItem(modelStorageKey(), select.value);
    }
}

function selectedModelLabel() {
    const select = document.getElementById("model-select");
    const model = loadedModels.find(m => m.id === select.value);
    return model ? model.label : "AI model";
}

/* ---------- Modules & materials ---------- */

async function fetchModules() {
    const moduleSelect = document.getElementById("module-select");
    moduleSelect.innerHTML = `<option value="">Loading course modules...</option>`;
    try {
        const res = await fetch("/api/modules");
        if (res.status === 401) { window.location.reload(); return; }
        if (!res.ok) throw new Error("Failed to fetch course modules");
        loadedModules = await res.json();
        moduleSelect.innerHTML = "";
        if (loadedModules.length === 0) {
            moduleSelect.innerHTML = `<option value="">No modules with PDF/PPTX materials</option>`;
            document.getElementById("material-list-container").innerHTML =
                `<p class="material-empty">No modules contain supported materials (PDF or PPTX).</p>`;
            return;
        }
        loadedModules.forEach(mod => {
            const opt = document.createElement("option");
            opt.value = mod.id;
            opt.innerText = mod.name;
            moduleSelect.appendChild(opt);
        });
        onModuleChange();
    } catch (err) {
        console.error("Error fetching modules:", err);
        moduleSelect.innerHTML = `<option value="">Error loading course modules</option>`;
    }
}

function onModuleChange() {
    const moduleSelect = document.getElementById("module-select");
    const selectedId = moduleSelect.value;
    if (!selectedId) return;

    const selectedMod = loadedModules.find(m => String(m.id) === String(selectedId));
    const container = document.getElementById("material-list-container");
    container.innerHTML = "";

    if (!selectedMod || !selectedMod.items || selectedMod.items.length === 0) {
        container.innerHTML = `<p class="material-empty">No file attachments in this module.</p>`;
        return;
    }

    selectedMod.items.forEach(item => {
        const div = document.createElement("div");
        div.className = "material-item";
        div.innerHTML = `
            <input type="checkbox" id="mat-${escapeAttr(item.id)}" value="${escapeAttr(item.id)}" checked>
            <label class="material-name" for="mat-${escapeAttr(item.id)}" style="margin: 0; text-transform: none; font-weight: normal; cursor: pointer; flex: 1;">
                ${escapeHtml(item.title)}
            </label>
            <span class="material-meta">${escapeHtml(item.size)}</span>
        `;
        container.appendChild(div);
    });

    const selectedText = moduleSelect.options[moduleSelect.selectedIndex].text;
    const prefix = selectedText.split(":")[0];
    document.getElementById("quiz-title").value = `${prefix} Quiz`;
}

/* ---------- Question type rows + layout summary ---------- */

function toggleQtype(key) {
    const body = document.getElementById(`qtype-body-${key}`);
    const chevron = document.getElementById(`qtype-chevron-${key}`);
    const toggle = chevron ? chevron.closest(".qtype-toggle") : null;
    if (!body) return;
    const isHidden = body.hidden;
    body.hidden = !isHidden;
    if (toggle) toggle.setAttribute("aria-expanded", String(isHidden));
}

function updateLayoutSummary() {
    const mc = readCount("count-mc");
    const tf = readCount("count-tf");
    const matching = readCount("count-matching");
    const totalQs = mc + tf + matching;
    const totalPoints =
        mc * readPoints("points-mc") +
        tf * readPoints("points-tf") +
        matching * readPoints("points-matching");
    const qLabel = totalQs === 1 ? "question" : "questions";
    const pLabel = totalPoints === 1 ? "point" : "points";
    const el = document.getElementById("layout-summary-text");
    if (el) el.innerHTML = `${totalQs} ${qLabel} &bull; ${totalPoints} ${pLabel} total`;
}

function syncFeedbackToggles() {
    const staticEl = document.getElementById("include-answer-feedback");
    const agenticEl = document.getElementById("include-agentic-feedback");
    if (!staticEl || !agenticEl) return;
    if (agenticEl.checked) {
        staticEl.checked = false;
        staticEl.disabled = true;
    } else {
        staticEl.disabled = false;
    }
    if (staticEl.checked) {
        agenticEl.checked = false;
        agenticEl.disabled = true;
    } else {
        agenticEl.disabled = false;
    }
}

/* ---------- Generation progress animation ---------- */

function animateSteps() {
    currentStep = 1;
    const modelLabel = selectedModelLabel();
    document.getElementById("gen-loader-title").innerText = `Generating Quiz via ${modelLabel}...`;
    const updateStepUI = () => {
        for (let i = 1; i <= 4; i++) {
            const el = document.getElementById(`step-${i}`);
            if (i < currentStep) {
                el.className = "step-item completed";
                if (i === 1) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Extracted course materials.`;
                if (i === 2) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Checked context and parameters.`;
                if (i === 3) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> JSON generated & validated.`;
                if (i === 4) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Ready.`;
            } else if (i === currentStep) {
                el.className = "step-item active";
                if (i === 1) el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Downloading and extracting materials...`;
                if (i === 2) el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Analyzing conceptual topics...`;
                if (i === 3) el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Generating structured JSON via ${escapeHtml(modelLabel)}...`;
                if (i === 4) el.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Formatting preview controls...`;
            } else {
                el.className = "step-item";
                if (i === 1) el.innerHTML = `<i class="fa-regular fa-circle"></i> Extracting slide & note text...`;
                if (i === 2) el.innerHTML = `<i class="fa-regular fa-circle"></i> Analyzing conceptual material...`;
                if (i === 3) el.innerHTML = `<i class="fa-regular fa-circle"></i> Generating structured JSON...`;
                if (i === 4) el.innerHTML = `<i class="fa-regular fa-circle"></i> Rendering question controls...`;
            }
        }
    };

    updateStepUI();
    stepInterval = setInterval(() => {
        if (currentStep < 3) {
            currentStep++;
            updateStepUI();
        }
    }, 1800);
}

function completeAllSteps() {
    clearInterval(stepInterval);
    for (let i = 1; i <= 4; i++) {
        const el = document.getElementById(`step-${i}`);
        el.className = "step-item completed";
        if (i === 1) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Downloaded & extracted course materials.`;
        if (i === 2) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Analysis complete.`;
        if (i === 3) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Structured JSON generated & validated.`;
        if (i === 4) el.innerHTML = `<i class="fa-solid fa-circle-check"></i> Question controls rendered.`;
    }
}

/* ---------- Generate ---------- */

async function triggerQuizGeneration() {
    const moduleSelect = document.getElementById("module-select");
    const moduleId = moduleSelect.value;
    if (!moduleId) {
        alert("Please select a target course module.");
        return;
    }

    const checkedBoxes = document.querySelectorAll("#material-list-container input[type='checkbox']:checked");
    const fileIds = Array.from(checkedBoxes).map(cb => parseInt(cb.value));

    if (fileIds.length === 0) {
        alert("Please select at least one material file.");
        return;
    }

    const quizTitle = document.getElementById("quiz-title").value.trim();
    if (!quizTitle) {
        alert("Please specify a quiz title.");
        return;
    }

    const numMc = readCount("count-mc");
    const numTf = readCount("count-tf");
    const numMatching = readCount("count-matching");
    const pointsMc = readPoints("points-mc");
    const pointsTf = readPoints("points-tf");
    const pointsMatching = readPoints("points-matching");
    const mcOptions = Math.max(2, parseInt(document.getElementById("mc-options").value) || 4);
    const matchingPairs = Math.max(3, parseInt(document.getElementById("matching-pairs").value) || 4);

    if (numMc + numTf + numMatching === 0) {
        alert("Please request a count of at least 1 question of any type.");
        return;
    }

    const modelSelect = document.getElementById("model-select");
    const modelId = modelSelect.value;
    const selectedModel = loadedModels.find(m => m.id === modelId);
    if (!modelId || !selectedModel || !selectedModel.available) {
        alert("Please select an available AI model.");
        return;
    }

    document.getElementById("preview-placeholder").style.display = "none";
    document.getElementById("quiz-preview-content").style.display = "none";
    document.getElementById("gen-loader").style.display = "flex";
    document.getElementById("success-banner").style.display = "none";

    animateSteps();

    try {
        const includeFeedback = document.getElementById("include-feedback").checked;
        const includeAnswerFeedback = document.getElementById("include-answer-feedback").checked;
        const includeAgenticFeedback = document.getElementById("include-agentic-feedback").checked;
        const res = await fetch("/api/generate-quiz", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                module_id: moduleId,
                quiz_title: quizTitle,
                file_ids: fileIds,
                question_types: {
                    multiple_choice: numMc,
                    true_false: numTf,
                    matching: numMatching
                },
                points_per_type: {
                    multiple_choice: pointsMc,
                    true_false: pointsTf,
                    matching: pointsMatching
                },
                mc_options: mcOptions,
                matching_pairs: matchingPairs,
                include_feedback: includeFeedback,
                include_answer_feedback: includeAnswerFeedback,
                include_agentic_feedback: includeAgenticFeedback,
                model_id: modelId
            })
        });

        if (!res.ok) {
            let data = {};
            try { data = await res.json(); } catch (_) {}
            throw new Error(parseApiDetail(data) || "Could not generate quiz. Please try again.");
        }

        currentActiveQuiz = await res.json();
        currentActiveQuiz.includes_feedback = includeFeedback;
        currentActiveQuiz.includes_answer_feedback = includeAnswerFeedback;
        currentActiveQuiz.includes_agentic_feedback = includeAgenticFeedback;

        completeAllSteps();

        setTimeout(() => {
            document.getElementById("gen-loader").style.display = "none";
            renderQuizUI();
        }, 850);

    } catch (err) {
        clearInterval(stepInterval);
        console.error("Error generating quiz:", err);
        alert(err.message || "Could not generate quiz. Please try again.");
        document.getElementById("gen-loader").style.display = "none";
        document.getElementById("preview-placeholder").style.display = "flex";
    }
}

function regenerateQuestions() {
    triggerQuizGeneration();
}

/* ---------- Preview rendering ---------- */

function renderQuizUI() {
    if (!currentActiveQuiz) return;

    const feedbackEl = document.getElementById("include-feedback");
    const answerFbEl = document.getElementById("include-answer-feedback");
    const agenticEl = document.getElementById("include-agentic-feedback");
    if (feedbackEl && currentActiveQuiz.includes_feedback != null) {
        feedbackEl.checked = Boolean(currentActiveQuiz.includes_feedback);
    }
    if (answerFbEl && currentActiveQuiz.includes_answer_feedback != null) {
        answerFbEl.checked = Boolean(currentActiveQuiz.includes_answer_feedback);
    }
    if (agenticEl && currentActiveQuiz.includes_agentic_feedback != null) {
        agenticEl.checked = Boolean(currentActiveQuiz.includes_agentic_feedback);
    }
    syncFeedbackToggles();

    const agenticOn = Boolean(currentActiveQuiz.includes_agentic_feedback);

    document.getElementById("preview-quiz-title").innerText = currentActiveQuiz.quiz_title;

    const totalPoints = currentActiveQuiz.questions.reduce((sum, q) => sum + parseInt(q.points_possible || 1), 0);
    document.getElementById("preview-meta-tag").innerText = `${currentActiveQuiz.questions.length} Questions • ${totalPoints} Points total`;

    const container = document.getElementById("questions-list-container");
    container.innerHTML = "";

    currentActiveQuiz.questions.forEach((q, qIndex) => {
        const card = document.createElement("div");
        card.className = "question-card";
        card.id = `q-card-${qIndex}`;

        let typeBadgeClass = "badge-mc";
        let typeLabel = "Multiple Choice";
        if (q.question_type === "true_false_question") {
            typeLabel = "True/False";
            typeBadgeClass = "badge-tf";
        } else if (q.question_type === "matching_question") {
            typeLabel = "Matching";
            typeBadgeClass = "badge-matching";
        }

        let answersHTML = "";
        if (q.question_type === "matching_question") {
            q.answers.forEach(ans => {
                answersHTML += `
                    <div class="answer-option correct">
                        <i class="fa-solid fa-left-right" style="color: var(--accent-blue);"></i>
                        <span style="font-weight: 500; margin-right: 0.5rem;">${escapeHtml(ans.answer_text)}</span>
                        <i class="fa-solid fa-arrow-right-long" style="color: var(--text-muted); margin: 0 0.5rem;"></i>
                        <span style="color: var(--success); font-weight: 600;">${escapeHtml(ans.answer_match_right)}</span>
                    </div>
                `;
            });
        } else {
            q.answers.forEach(ans => {
                const isCorrect = ans.answer_weight === 100;
                answersHTML += `
                    <div class="answer-option ${isCorrect ? 'correct' : 'incorrect'}">
                        <i class="${isCorrect ? 'fa-solid fa-circle-check' : 'fa-regular fa-circle'}"></i>
                        <span style="flex: 1;">${escapeHtml(ans.answer_text)}</span>
                        ${ans.answer_comments ? `<span style="font-size: 0.75rem; color: var(--accent-blue); font-style: italic;">(${escapeHtml(ans.answer_comments)})</span>` : ''}
                    </div>
                `;
            });
        }

        const points = q.points_possible || 1;
        const ptLabel = points === 1 ? "pt" : "pts";

        let explanationsHTML = "";
        if (q.correct_comments || q.incorrect_comments) {
            explanationsHTML = `<div class="answer-explanations">`;
            if (q.correct_comments) {
                explanationsHTML += `
                    <div class="explanation-row correct">
                        <i class="fa-solid fa-circle-check"></i>
                        <span>${escapeHtml(q.correct_comments)}</span>
                    </div>`;
            }
            if (q.incorrect_comments) {
                explanationsHTML += `
                    <div class="explanation-row incorrect">
                        <i class="fa-solid fa-circle-xmark"></i>
                        <span>${escapeHtml(q.incorrect_comments)}</span>
                    </div>`;
            }
            explanationsHTML += `</div>`;
        }

        // Per-question feedback toggle (only meaningful when quiz-level feedback is on)
        const fbEnabled = q.feedback_enabled !== false;
        const feedbackToggleHTML = agenticOn ? `
            <label class="q-feedback-toggle ${fbEnabled ? 'on' : ''}" title="Collect confidence + explanation for this question and generate AI feedback">
                <input type="checkbox" ${fbEnabled ? 'checked' : ''} onchange="toggleQuestionFeedback(${qIndex}, this.checked)">
                <i class="fa-solid fa-comment-dots"></i> AI feedback
            </label>` : "";

        const explanationEditor = q.question_type === 'matching_question'
            ? `
                <div class="form-group">
                    <label>Feedback (shown after submission)</label>
                    <textarea id="edit-correct-comments-${qIndex}" rows="2" placeholder="Explanation shown to students">${escapeHtml(q.correct_comments || '')}</textarea>
                </div>`
            : `
                <div class="form-group">
                    <label>Correct answer feedback</label>
                    <textarea id="edit-correct-comments-${qIndex}" rows="2" placeholder="Shown when answered correctly">${escapeHtml(q.correct_comments || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>Incorrect answer feedback</label>
                    <textarea id="edit-incorrect-comments-${qIndex}" rows="2" placeholder="Shown when answered incorrectly">${escapeHtml(q.incorrect_comments || '')}</textarea>
                </div>`;

        card.innerHTML = `
            <div class="question-meta">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span style="color: var(--text-muted);">Question ${qIndex + 1}</span>
                    <span class="type-badge ${typeBadgeClass}">${typeLabel}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    ${feedbackToggleHTML}
                    <span style="color: var(--text-muted);">${points} ${ptLabel}</span>
                </div>
            </div>
            <div class="question-title" id="q-text-${qIndex}">${q.question_text}</div>

            <div class="answers-list" id="q-answers-list-${qIndex}">
                ${answersHTML}
            </div>

            ${explanationsHTML}

            <div class="q-actions">
                <button class="action-icon-btn" onclick="toggleEditForm(${qIndex})">
                    <i class="fa-solid fa-pen-to-square"></i> Edit
                </button>
            </div>

            <div class="editor-form" id="editor-form-${qIndex}" style="display: none;">
                <div class="form-group">
                    <label>Question Text</label>
                    <textarea id="edit-qtext-${qIndex}" rows="2">${escapeHtml(q.question_text)}</textarea>
                </div>
                <div class="form-group">
                    <label>Answers & Pair Matching</label>
                    <div style="display: flex; flex-direction: column; gap: 0.5rem;" id="edit-answers-container-${qIndex}">
                        ${q.question_type === 'matching_question' ?
                            q.answers.map((ans, aIndex) => `
                                <div style="display: flex; gap: 0.5rem; align-items: center;">
                                    <span style="font-size: 0.85rem; color: var(--text-muted); width: 20px;">${aIndex + 1}:</span>
                                    <input type="text" style="padding: 0.5rem; flex: 1;" id="edit-anstext-${qIndex}-${aIndex}" value="${escapeAttr(ans.answer_text)}" placeholder="Left Prompt">
                                    <i class="fa-solid fa-arrow-right-long" style="color: var(--accent-blue);"></i>
                                    <input type="text" style="padding: 0.5rem; flex: 1;" id="edit-ansmatch-${qIndex}-${aIndex}" value="${escapeAttr(ans.answer_match_right)}" placeholder="Right Match">
                                </div>
                            `).join('')
                        :
                            q.answers.map((ans, aIndex) => `
                                <div style="display: flex; gap: 0.5rem; align-items: center;">
                                    <input type="radio" name="edit-correct-${qIndex}" value="${aIndex}" ${ans.answer_weight === 100 ? 'checked' : ''}>
                                    <input type="text" style="padding: 0.5rem; flex: 1;" id="edit-anstext-${qIndex}-${aIndex}" value="${escapeAttr(ans.answer_text)}">
                                </div>
                            `).join('')
                        }
                    </div>
                </div>
                ${explanationEditor}
                <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem;">
                    <button class="btn btn-secondary" style="padding: 0.5rem 1rem; width: auto; font-size: 0.85rem;" onclick="toggleEditForm(${qIndex})">Cancel</button>
                    <button class="btn btn-primary" style="padding: 0.5rem 1rem; width: auto; font-size: 0.85rem;" onclick="saveQuestionEdit(${qIndex})">Save Changes</button>
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    document.getElementById("quiz-preview-content").style.display = "flex";
}

function toggleQuestionFeedback(qIndex, enabled) {
    if (!currentActiveQuiz || !currentActiveQuiz.questions[qIndex]) return;
    currentActiveQuiz.questions[qIndex].feedback_enabled = enabled;
    const toggle = document.querySelector(`#q-card-${qIndex} .q-feedback-toggle`);
    if (toggle) toggle.classList.toggle("on", enabled);
}

function toggleEditForm(qIndex) {
    const form = document.getElementById(`editor-form-${qIndex}`);
    const isVisible = form.style.display === "block";
    form.style.display = isVisible ? "none" : "block";
}

function saveQuestionEdit(qIndex) {
    const qText = document.getElementById(`edit-qtext-${qIndex}`).value;
    const q = currentActiveQuiz.questions[qIndex];
    q.question_text = qText;

    const correctCommentsEl = document.getElementById(`edit-correct-comments-${qIndex}`);
    if (correctCommentsEl) q.correct_comments = correctCommentsEl.value.trim();
    const incorrectCommentsEl = document.getElementById(`edit-incorrect-comments-${qIndex}`);
    if (incorrectCommentsEl) q.incorrect_comments = incorrectCommentsEl.value.trim();

    if (q.question_type === 'matching_question') {
        q.answers.forEach((ans, aIndex) => {
            const ansText = document.getElementById(`edit-anstext-${qIndex}-${aIndex}`).value;
            const matchText = document.getElementById(`edit-ansmatch-${qIndex}-${aIndex}`).value;
            ans.answer_text = ansText;
            ans.answer_match_left = ansText;
            ans.answer_match_right = matchText;
        });
    } else {
        const checkedRadio = document.querySelector(`input[name="edit-correct-${qIndex}"]:checked`);
        const correctRadioVal = checkedRadio ? parseInt(checkedRadio.value) : 0;

        q.answers.forEach((ans, aIndex) => {
            const ansText = document.getElementById(`edit-anstext-${qIndex}-${aIndex}`).value;
            ans.answer_text = ansText;
            ans.answer_weight = (correctRadioVal === aIndex) ? 100 : 0;
        });
    }

    renderQuizUI();
}

function resetPreview() {
    currentActiveQuiz = null;
    document.getElementById("quiz-preview-content").style.display = "none";
    document.getElementById("preview-placeholder").style.display = "flex";
    document.getElementById("success-banner").style.display = "none";
}

/* ---------- Deploy ---------- */

async function deployQuiz() {
    if (!currentActiveQuiz) return;

    const moduleSelect = document.getElementById("module-select");
    const moduleId = moduleSelect.value;
    if (!moduleId) {
        alert("Please select a module first.");
        return;
    }

    const deployBtn = document.querySelector("button[onclick='deployQuiz()']");
    const originalHTML = deployBtn.innerHTML;
    deployBtn.disabled = true;
    deployBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Deploying...`;

    try {
        const includeFeedback = document.getElementById("include-feedback").checked;
        const includeAgenticFeedback = document.getElementById("include-agentic-feedback").checked;
        const res = await fetch("/api/deploy-quiz", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                module_id: moduleId,
                quiz: currentActiveQuiz,
                include_feedback: includeFeedback,
                include_agentic_feedback: includeAgenticFeedback
            })
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Server error during deployment");
        }

        const data = await res.json();

        const banner = document.getElementById("success-banner");
        banner.style.display = "flex";
        banner.innerHTML = `
            <i class="fa-solid fa-circle-check"></i>
            <div>
                <strong>Deploy successful!</strong> Quiz has been uploaded.
                <a href="${escapeAttr(data.quiz_url)}" target="_blank" class="link-canvas">
                    View in Canvas <i class="fa-solid fa-arrow-up-right-from-square"></i>
                </a>
            </div>
        `;

        document.getElementById("success-banner").scrollIntoView({ behavior: 'smooth' });

    } catch (err) {
        console.error("Error deploying quiz:", err);
        alert(`Quiz Deployment Failed: ${err.message}`);
    } finally {
        deployBtn.disabled = false;
        deployBtn.innerHTML = originalHTML;
    }
}
