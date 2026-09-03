/* Generator view: models, modules, generation, preview editing, deploy. */

let currentStep = 1;
let stepInterval = null;
let autoModelId = null;
let autoModelLabel = null;

/* ---------- Models ---------- */

function modelStorageKey() {
    return currentCourseId ? `easylearn_model_${currentCourseId}` : "easylearn_model_default";
}

async function fetchModels() {
    const select = document.getElementById("model-select");
    select.disabled = true;
    const wrapper = select.closest(".select-wrapper");
    if (wrapper) wrapper.classList.add("is-loading");
    try {
        const res = await fetch("/api/models");
        if (!res.ok) throw new Error("Failed to load models");
        const payload = await res.json();
        loadedModels = Array.isArray(payload) ? payload : (payload.models || []);
        autoModelId = Array.isArray(payload) ? null : (payload.auto_model_id || null);
        autoModelLabel = Array.isArray(payload) ? null : (payload.auto_model_label || null);
        populateModelSelect();
        modelsReady = Boolean(autoModelId) || loadedModels.some(m => m.available);
        select.disabled = false;
        updateGenerateEnabled();
    } catch (err) {
        console.error("Error loading models:", err);
        modelsReady = false;
        autoModelId = null;
        autoModelLabel = null;
        select.innerHTML = `<option value="">Models unavailable</option>`;
        updateGenerateEnabled();
    } finally {
        if (wrapper) wrapper.classList.remove("is-loading");
    }
}

function populateModelSelect() {
    const select = document.getElementById("model-select");
    select.innerHTML = "";

    const autoOpt = document.createElement("option");
    autoOpt.value = "";
    autoOpt.textContent = "Auto";
    select.appendChild(autoOpt);

    if (!loadedModels.length) {
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

    if (storedId && loadedModels.some(m => m.id === storedId && m.available)) {
        select.value = storedId;
    } else {
        select.value = "";
        sessionStorage.removeItem(modelStorageKey());
    }
    onModelChange();
}

function onModelChange() {
    const select = document.getElementById("model-select");
    if (!select) return;
    if (select.value) {
        const model = loadedModels.find(m => m.id === select.value);
        if (model?.available) {
            sessionStorage.setItem(modelStorageKey(), select.value);
        }
    } else {
        sessionStorage.removeItem(modelStorageKey());
    }
}

function selectedModelId() {
    const select = document.getElementById("model-select");
    return (select && select.value) ? select.value : null;
}

function selectedModelLabel() {
    const id = selectedModelId();
    if (!id) return autoModelLabel || "Auto";
    const model = loadedModels.find(m => m.id === id);
    return model ? model.label : "AI model";
}

function showPreviewModelLabel(label) {
    const el = document.getElementById("preview-model-label");
    if (!el) return;
    if (label) {
        el.hidden = false;
        el.textContent = `Generated with ${label}`;
    } else {
        el.hidden = true;
        el.textContent = "";
    }
}

/* ---------- Modules & materials ---------- */

async function fetchModules({ refresh = false } = {}) {
    const moduleSelect = document.getElementById("module-select");
    const refreshBtn = document.getElementById("btn-refresh-modules");
    const materialList = document.getElementById("material-list-container");

    modulesReady = false;
    moduleSelect.disabled = true;
    moduleSelect.innerHTML = `<option value="">Loading course modules...</option>`;
    if (materialList) {
        materialList.classList.add("is-loading");
        if (refresh) {
            materialList.innerHTML = `<p class="material-empty">Refreshing from Canvas…</p>`;
        }
    }
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.classList.add("is-spinning");
    }
    updateGenerateEnabled();

    try {
        const url = refresh ? "/api/modules?refresh=1" : "/api/modules";
        const res = await fetch(url);
        if (res.status === 401) { window.location.reload(); return; }
        if (!res.ok) throw new Error("Failed to fetch course modules");
        loadedModules = await res.json();
        moduleSelect.innerHTML = "";
        if (loadedModules.length === 0) {
            moduleSelect.innerHTML = `<option value="">No modules with PDF/PPTX materials</option>`;
            document.getElementById("material-list-container").innerHTML =
                `<p class="material-empty">No modules contain supported materials (PDF or PPTX).</p>`;
            modulesReady = true;
            moduleSelect.disabled = false;
            updateGenerateEnabled();
            return;
        }
        loadedModules.forEach(mod => {
            const opt = document.createElement("option");
            opt.value = mod.id;
            opt.innerText = mod.name;
            moduleSelect.appendChild(opt);
        });
        onModuleChange();
        modulesReady = true;
        moduleSelect.disabled = false;
        updateGenerateEnabled();
        if (typeof setSourceStatus === "function" && refresh) {
            setSourceStatus("Modules refreshed from Canvas", "ok");
            window.setTimeout(() => setSourceStatus(""), 1500);
        }
    } catch (err) {
        console.error("Error fetching modules:", err);
        modulesReady = false;
        moduleSelect.innerHTML = `<option value="">Error loading course modules</option>`;
        if (refresh) {
            alert(err.message || "Could not refresh modules from Canvas.");
            if (typeof setSourceStatus === "function") {
                setSourceStatus("Could not refresh modules", "error");
            }
        }
        updateGenerateEnabled();
    } finally {
        if (materialList) materialList.classList.remove("is-loading");
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.classList.remove("is-spinning");
        }
        const wrapper = moduleSelect.closest(".select-wrapper");
        if (wrapper && modulesReady) wrapper.classList.remove("is-loading");
    }
}

function refreshModules() {
    return fetchModules({ refresh: true });
}

function onModuleChange() {
    const moduleSelect = document.getElementById("module-select");
    const selectedId = moduleSelect.value;
    if (!selectedId) {
        updateLayoutSummary();
        return;
    }

    const selectedMod = loadedModules.find(m => String(m.id) === String(selectedId));
    const container = document.getElementById("material-list-container");
    container.innerHTML = "";

    if (!selectedMod || !selectedMod.items || selectedMod.items.length === 0) {
        container.innerHTML = `<p class="material-empty">No file attachments in this module.</p>`;
        updateLayoutSummary();
        return;
    }

    selectedMod.items.forEach(item => {
        const div = document.createElement("div");
        div.className = "material-item";
        div.innerHTML = `
            <input type="checkbox" id="mat-${escapeAttr(item.id)}" value="${escapeAttr(item.id)}" checked onchange="updateLayoutSummary(); updateGenerateEnabled();">
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
    updateLayoutSummary();
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

function onDifficultyInput(changedLevel) {
    const mc = readCount("count-mc");
    const tf = readCount("count-tf");
    const matching = readCount("count-matching");
    const totalQs = mc + tf + matching;

    let easy = readCount("count-easy");
    let med = readCount("count-medium");
    let hard = readCount("count-hard");

    const currentDiffTotal = easy + med + hard;
    if (currentDiffTotal !== totalQs && totalQs >= 0) {
        const diff = totalQs - currentDiffTotal;
        if (changedLevel === "easy" || changedLevel === "hard") {
            med = Math.max(0, med + diff);
        } else {
            easy = Math.max(0, easy + diff);
        }
        if (document.getElementById("count-easy")) document.getElementById("count-easy").value = easy;
        if (document.getElementById("count-medium")) document.getElementById("count-medium").value = med;
        if (document.getElementById("count-hard")) document.getElementById("count-hard").value = hard;
    }
    updateLayoutSummary();
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

    let easy = readCount("count-easy");
    let med = readCount("count-medium");
    let hard = readCount("count-hard");

    if (easy + med + hard !== totalQs && totalQs >= 0) {
        easy = Math.round(totalQs * 0.25);
        hard = Math.round(totalQs * 0.25);
        med = Math.max(0, totalQs - easy - hard);
        if (document.getElementById("count-easy")) document.getElementById("count-easy").value = easy;
        if (document.getElementById("count-medium")) document.getElementById("count-medium").value = med;
        if (document.getElementById("count-hard")) document.getElementById("count-hard").value = hard;
    }

    const qLabel = totalQs === 1 ? "question" : "questions";
    const pLabel = totalPoints === 1 ? "point" : "points";
    const diffStr = totalQs > 0 ? ` (${easy} Easy, ${med} Medium, ${hard} Hard)` : "";
    const el = document.getElementById("layout-summary-text");
    if (el) el.innerHTML = `${totalQs} ${qLabel}${diffStr} &bull; ${totalPoints} ${pLabel} total`;

    // Update Pre-generation summary card in right panel
    const moduleSelect = document.getElementById("module-select");
    const modText = (moduleSelect && moduleSelect.selectedIndex >= 0 && moduleSelect.value)
        ? moduleSelect.options[moduleSelect.selectedIndex].text
        : "None selected";
    const pregenMod = document.getElementById("pregen-module");
    if (pregenMod) pregenMod.textContent = modText;

    const checkedBoxes = document.querySelectorAll("#material-list-container input[type='checkbox']:checked");
    const pregenFile = document.getElementById("pregen-file");
    if (pregenFile) {
        if (checkedBoxes.length === 0) {
            pregenFile.textContent = "None selected";
        } else if (checkedBoxes.length === 1) {
            const label = checkedBoxes[0].closest(".material-item")?.querySelector(".material-name")?.textContent;
            pregenFile.textContent = label ? label.trim() : "1 file selected";
        } else {
            pregenFile.textContent = `${checkedBoxes.length} files selected`;
        }
    }

    const titleVal = document.getElementById("quiz-title")?.value.trim() || "Week 1 Quiz";
    const pregenTitle = document.getElementById("pregen-title");
    if (pregenTitle) pregenTitle.textContent = titleVal;

    const pregenStruct = document.getElementById("pregen-structure");
    if (pregenStruct) pregenStruct.innerHTML = `${totalQs} ${qLabel}${diffStr} &bull; ${totalPoints} ${pLabel} total`;

    const pregenModel = document.getElementById("pregen-model");
    if (pregenModel) pregenModel.textContent = selectedModelLabel();
}

/** Product always uses AI feedback + Auto model; no professor toggles. */
function syncFeedbackToggles(opts = {}) {
    const shouldRender = opts.render !== false;
    const staticEl = document.getElementById("include-answer-feedback");
    const agenticEl = document.getElementById("include-agentic-feedback");
    if (staticEl) staticEl.checked = false;
    if (agenticEl) agenticEl.checked = true;
    if (shouldRender && currentActiveQuiz) {
        currentActiveQuiz.includes_agentic_feedback = true;
        currentActiveQuiz.includes_answer_feedback = false;
        if (typeof renderQuizUI === "function") {
            renderQuizUI();
        }
    }
}

/* ---------- Generation progress animation ---------- */

function animateSteps() {
    currentStep = 1;
    const overrideId = selectedModelId();
    const titleEl = document.getElementById("gen-loader-title");
    if (overrideId) {
        titleEl.innerText = `Generating Quiz via ${selectedModelLabel()}...`;
    } else {
        titleEl.innerText = "Generating Quiz...";
    }
    const modelLabel = selectedModelLabel();
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
                if (i === 3) el.innerHTML = overrideId
                    ? `<i class="fa-solid fa-spinner fa-spin"></i> Generating structured JSON via ${escapeHtml(modelLabel)}...`
                    : `<i class="fa-solid fa-spinner fa-spin"></i> Generating structured JSON...`;
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

function pollGenerateJob(jobId) {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const r = await fetch(`/api/generate-jobs/${jobId}`);
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    reject(new Error(parseApiDetail(data) || "Could not check generation status."));
                    return;
                }
                if (data.status === "ready") {
                    resolve(data.quiz);
                    return;
                }
                if (data.status === "error") {
                    reject(new Error(data.error || "Could not generate quiz. Please try again."));
                    return;
                }
                setTimeout(poll, 2000);
            } catch (err) {
                reject(err);
            }
        };
        poll();
    });
}

async function triggerQuizGeneration() {
    if (!modulesReady || !modelsReady) {
        alert("Still loading course data. Please wait a moment.");
        return;
    }

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

    if (!autoModelId && !loadedModels.some(m => m.available)) {
        alert("No AI provider is configured on the server.");
        return;
    }

    const generateBtn = document.getElementById("btn-generate");
    if (generateBtn) {
        generateBtn.dataset.generating = "1";
        generateBtn.disabled = true;
    }

    document.getElementById("preview-placeholder").style.display = "none";
    document.getElementById("quiz-preview-content").style.display = "none";
    document.getElementById("gen-loader").style.display = "flex";
    document.getElementById("success-banner").style.display = "none";

    animateSteps();

    try {
        const customInstructions = document.getElementById("custom-instructions")?.value.trim() || "";
        const modelId = selectedModelId();

        const body = {
            module_id: moduleId,
            quiz_title: quizTitle,
            file_ids: fileIds,
            question_types: {
                multiple_choice: numMc,
                true_false: numTf,
                matching: numMatching
            },
            difficulty_counts: {
                easy: readCount("count-easy"),
                medium: readCount("count-medium"),
                hard: readCount("count-hard")
            },
            points_per_type: {
                multiple_choice: pointsMc,
                true_false: pointsTf,
                matching: pointsMatching
            },
            mc_options: mcOptions,
            matching_pairs: matchingPairs,
            include_answer_feedback: false,
            include_agentic_feedback: true,
            custom_instructions: customInstructions,
            model_id: modelId,
        };

        const res = await fetch("/api/generate-quiz", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (!res.ok) {
            let data = {};
            try { data = await res.json(); } catch (_) {}
            throw new Error(parseApiDetail(data) || "Could not generate quiz. Please try again.");
        }

        const { job_id } = await res.json();
        if (!job_id) {
            throw new Error("Server did not start a generation job. Please try again.");
        }
        currentActiveQuiz = await pollGenerateJob(job_id);
        currentActiveQuiz.includes_answer_feedback = false;
        currentActiveQuiz.includes_agentic_feedback = true;
        if (Array.isArray(currentActiveQuiz.questions)) {
            currentActiveQuiz.questions.forEach(q => { q.feedback_enabled = true; });
        }

        completeAllSteps();

        setTimeout(() => {
            document.getElementById("gen-loader").style.display = "none";
            renderQuizUI();
        }, 850);

    } catch (err) {
        clearInterval(stepInterval);
        console.error("Error generating quiz:", err);
        let msg = err.message || "Quiz generation failed. Please try again.";
        if (msg.includes("validation error") || msg.includes("errors.pydantic.dev") || msg.includes("Traceback")) {
            msg = "Quiz generation failed: The selected AI model returned an invalid response format. Please try again or choose another model.";
        }
        alert(msg);
        document.getElementById("gen-loader").style.display = "none";
        document.getElementById("preview-placeholder").style.display = "flex";
    } finally {
        if (generateBtn) {
            generateBtn.dataset.generating = "0";
            updateGenerateEnabled();
        }
    }
}

function regenerateQuestions() {
    triggerQuizGeneration();
}

/* ---------- Preview rendering ---------- */

/** Match deploy order: content item, then optional confidence + explanation metas. */
function canvasTakeLayout(questions, agenticOn) {
    const items = [];
    let canvasPos = 0;
    let feedbackCount = 0;
    (questions || []).forEach((q, qIndex) => {
        canvasPos += 1;
        const contentCanvasNumber = canvasPos;
        const fbEnabled = agenticOn && q.feedback_enabled !== false;
        items.push({
            kind: "content",
            qIndex,
            canvasNumber: contentCanvasNumber,
            feedbackEnabled: fbEnabled,
        });
        if (fbEnabled) {
            canvasPos += 1;
            items.push({
                kind: "confidence",
                qIndex,
                canvasNumber: canvasPos,
                parentCanvasNumber: contentCanvasNumber,
            });
            canvasPos += 1;
            items.push({
                kind: "explanation",
                qIndex,
                canvasNumber: canvasPos,
                parentCanvasNumber: contentCanvasNumber,
            });
            feedbackCount += 2;
        }
    });
    return {
        items,
        contentCount: (questions || []).length,
        feedbackCount,
        canvasItemCount: canvasPos,
    };
}

function appendFeedbackFollowupCard(container, item, parentQuestion) {
    const parentLabel = `Question ${item.parentCanvasNumber}`;
    const isConfidence = item.kind === "confidence";
    const card = document.createElement("div");
    card.className = "question-card feedback-followup-card";
    card.innerHTML = `
        <div class="question-meta">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span class="canvas-q-label">Canvas Q${item.canvasNumber}</span>
                <span class="type-badge badge-feedback">${isConfidence ? "Confidence" : "Explanation"}</span>
            </div>
            <span style="color: var(--text-muted);">0 pts · not graded</span>
        </div>
        <div class="feedback-followup-banner">Question ${item.parentCanvasNumber} Feedback (Not Graded)</div>
        <div class="question-title feedback-followup-text">
            ${isConfidence
                ? `How confident were you in your answer to <strong>${parentLabel}</strong>?`
                : `Briefly explain <strong>why</strong> you chose your answer for <strong>${parentLabel}</strong>.`}
        </div>
    `;
    container.appendChild(card);
}

// Shared global state variables (currentDraftQuiz, currentActiveQuiz) are declared in main.js


function updatePreviewMetaTag(agenticOn) {
    if (!currentDraftQuiz || !currentDraftQuiz.questions) return;
    const questions = currentDraftQuiz.questions;
    const totalPoints = questions.reduce(
        (sum, q) => sum + parseInt(q.points_possible || 1, 10),
        0,
    );
    const contentCount = questions.length;
    const metaEl = document.getElementById("preview-meta-tag");
    if (metaEl) {
        metaEl.innerText = `${contentCount} Questions • ${totalPoints} Points total`;
    }
    const deployHint = document.getElementById("deploy-canvas-count");
    if (deployHint) {
        deployHint.hidden = false;
        deployHint.textContent = `Includes student confidence & explanation prompts in Canvas`;
    }
}

function renderDraftEditor() {
    currentDraftQuiz = currentDraftQuiz || currentActiveQuiz;
    if (!currentDraftQuiz) return;
    currentActiveQuiz = currentDraftQuiz;

    syncFeedbackToggles({ render: false });
    currentDraftQuiz.includes_agentic_feedback = true;

    const titleEl = document.getElementById("preview-quiz-title");
    if (titleEl) {
        if (currentDraftQuiz.deployed) {
            titleEl.innerHTML = `${escapeHtml(currentDraftQuiz.quiz_title)} <span class="type-badge badge-matching" style="margin-left: 0.5rem; font-size: 0.7rem; font-weight: 600; text-transform: uppercase;"><i class="fa-solid fa-circle-check"></i> Deployed</span>`;
        } else {
            titleEl.innerText = currentDraftQuiz.quiz_title;
        }
    }
    updatePreviewMetaTag(true);
    showPreviewModelLabel(currentDraftQuiz.model_label || null);

    // Hide pre-generation placeholder box
    const placeholder = document.getElementById("draft-editor-placeholder") || document.getElementById("preview-placeholder");
    if (placeholder) placeholder.style.display = "none";

    const container = document.getElementById("questions-list-container");
    container.innerHTML = "";

    // Render ONLY actual content questions (Q1..QN)
    (currentDraftQuiz.questions || []).forEach((q, qIndex) => {
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

        const difficulty = (q.difficulty || "medium").toLowerCase();
        let diffIcon = "fa-scale-balanced";
        if (difficulty === "easy") diffIcon = "fa-seedling";
        if (difficulty === "hard") diffIcon = "fa-fire";
        const difficultyBadge = `<span class="badge-difficulty ${difficulty}"><i class="fa-solid ${diffIcon}"></i> ${difficulty}</span>`;

        const points = q.points_possible || 1;
        const ptLabel = points === 1 ? "pt" : "pts";
        const numberLabel = `<span class="canvas-q-label">Q${qIndex + 1}</span>`;

        card.innerHTML = `
            <div class="question-meta">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    ${numberLabel}
                    <span class="type-badge ${typeBadgeClass}">${typeLabel}</span>
                    ${difficultyBadge}
                </div>
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                    <span style="color: var(--text-muted);">${points} ${ptLabel}</span>
                </div>
            </div>
            <div class="question-title" id="q-text-${qIndex}">${escapeHtml(htmlToPlainText(q.question_text))}</div>

            <div class="answers-list" id="q-answers-list-${qIndex}">
                ${answersHTML}
            </div>

            <div class="q-actions">
                <button type="button" class="btn btn-secondary btn-sm" onclick="toggleEditForm(${qIndex})"><i class="fa-solid fa-pen-to-square"></i> Edit</button>
                <button type="button" class="btn btn-danger-subtle btn-sm" onclick="deleteQuestion(${qIndex})" title="Delete Question ${qIndex + 1}"><i class="fa-solid fa-trash-can"></i> Delete</button>
            </div>

            <div class="editor-form" id="editor-form-${qIndex}" style="display: none;">
                <div class="form-group">
                    <label>Question text</label>
                    <textarea id="edit-qtext-${qIndex}" rows="2">${escapeHtml(htmlToPlainText(q.question_text))}</textarea>
                </div>
                <div class="form-group">
                    <label>Answers</label>
                    <div style="display: flex; flex-direction: column; gap: 0.5rem;" id="edit-answers-container-${qIndex}">
                        ${q.question_type === 'matching_question' ?
                            q.answers.map((ans, aIndex) => `
                                <div style="display: flex; gap: 0.5rem; align-items: center;">
                                    <span style="font-size: 0.85rem; color: var(--text-muted); width: 20px;">${aIndex + 1}:</span>
                                    <input type="text" style="padding: 0.5rem; flex: 1;" id="edit-anstext-${qIndex}-${aIndex}" value="${escapeAttr(ans.answer_text)}" placeholder="Left">
                                    <span style="color: var(--text-muted);">→</span>
                                    <input type="text" style="padding: 0.5rem; flex: 1;" id="edit-ansmatch-${qIndex}-${aIndex}" value="${escapeAttr(ans.answer_match_right)}" placeholder="Right">
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
                <div style="display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="toggleEditForm(${qIndex})">Cancel</button>
                    <button type="button" class="btn btn-primary btn-sm" onclick="saveQuestionEdit(${qIndex})">Save</button>
                </div>
            </div>
        `;

        container.appendChild(card);
    });

    const previewContent = document.getElementById("draft-editor-content") || document.getElementById("quiz-preview-content");
    if (previewContent) previewContent.style.display = "flex";

    // Update bottom deploy button state
    const deployBtn = document.querySelector("button[onclick='deployQuiz()']");
    if (deployBtn) {
        if (currentDraftQuiz.deployed) {
            deployBtn.disabled = true;
            deployBtn.innerHTML = `<i class="fa-solid fa-check"></i> Deployed to Canvas`;
        } else {
            deployBtn.disabled = false;
            deployBtn.innerHTML = `Deploy to Canvas`;
        }
    }
}

// Aliases for compatibility
function renderQuizUI() { return renderDraftEditor(); }

function toggleQuestionFeedback(qIndex, enabled) {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft || !draft.questions[qIndex]) return;
    draft.questions[qIndex].feedback_enabled = enabled;
    renderDraftEditor();
}

function toggleEditForm(qIndex) {
    const form = document.getElementById(`editor-form-${qIndex}`);
    if (!form) return;
    const isVisible = form.style.display === "block";
    form.style.display = isVisible ? "none" : "block";
}

async function deleteQuestion(qIndex) {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft || !draft.questions) return;

    if (draft.questions.length <= 1) {
        alert("A quiz must have at least one question. If you wish to discard the entire quiz, click Discard.");
        return;
    }

    const questionNum = qIndex + 1;
    let confirmMsg = `Are you sure you want to delete Question ${questionNum}? This action cannot be undone.`;
    if (draft.deployed) {
        confirmMsg = `This quiz was deployed to Canvas. Deleting Question ${questionNum} will update the draft and reset its deployed status so you can review and re-deploy cleanly. Continue?`;
    }

    if (!confirm(confirmMsg)) return;

    if (draft.id) {
        try {
            const res = await fetch(`/api/quizzes/${draft.id}/questions/${qIndex}`, {
                method: "DELETE",
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Failed to delete question from server.");
            }
            if (data.quiz) {
                currentDraftQuiz = data.quiz;
                currentActiveQuiz = data.quiz;
            } else {
                draft.questions.splice(qIndex, 1);
                if (draft.deployed) draft.deployed = false;
            }
        } catch (err) {
            console.error("Error deleting question:", err);
            alert(err.message || "Could not delete question.");
            return;
        }
    } else {
        draft.questions.splice(qIndex, 1);
        if (draft.deployed) draft.deployed = false;
    }

    renderDraftEditor();
    if (typeof fetchQuizzesOverview === "function") {
        fetchQuizzesOverview().catch(() => {});
    }
}

async function saveQuestionEdit(qIndex) {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft) return;
    const qText = document.getElementById(`edit-qtext-${qIndex}`).value;
    const q = draft.questions[qIndex];
    q.question_text = qText;
    q.correct_comments = "";
    q.incorrect_comments = "";

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

    if (draft.id) {
        try {
            const res = await fetch(`/api/quizzes/${draft.id}/questions/${qIndex}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(q),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok && data.quiz) {
                currentDraftQuiz = data.quiz;
                currentActiveQuiz = data.quiz;
            }
        } catch (err) {
            console.error("Error saving question edit to server:", err);
        }
    }

    renderDraftEditor();
}

let draftSavedBannerTimeout = null;

function dismissDraftSavedBanner() {
    if (draftSavedBannerTimeout) {
        clearTimeout(draftSavedBannerTimeout);
        draftSavedBannerTimeout = null;
    }
    const banner = document.getElementById("draft-saved-banner");
    if (banner) banner.style.display = "none";
}

function promptEditTitle() {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft) return;
    const currentTitle = draft.quiz_title || "Week 1 Quiz";
    const newTitle = prompt("Enter quiz title:", currentTitle);
    if (newTitle !== null && newTitle.trim() && newTitle.trim() !== currentTitle) {
        draft.quiz_title = newTitle.trim();
        const leftInput = document.getElementById("quiz-title");
        if (leftInput) leftInput.value = draft.quiz_title;
        renderDraftEditor();
    }
}

async function saveCurrentDraft() {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft || !draft.questions || draft.questions.length === 0) {
        alert("There is no quiz draft to save.");
        return;
    }

    const saveBtn = document.getElementById("btn-save-draft");
    const originalHtml = saveBtn ? saveBtn.innerHTML : "Save Draft";
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving…`;
    }

    try {
        if (draft.id) {
            const res = await fetch(`/api/quizzes/${draft.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: draft.id,
                    quiz_title: draft.quiz_title,
                    questions: draft.questions,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.detail || "Could not save draft to server.");
            }
            if (data.quiz) {
                currentDraftQuiz = data.quiz;
                currentActiveQuiz = data.quiz;
            }
        }

        renderDraftEditor();

        // Show prominent success banner
        dismissDraftSavedBanner();
        const banner = document.getElementById("draft-saved-banner");
        if (banner) {
            banner.style.display = "flex";
            banner.innerHTML = `
                <div class="banner-message">
                    <i class="fa-solid fa-circle-check"></i>
                    <span>Draft saved! Find this and other drafts in your Quiz Library.</span>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <button type="button" class="btn btn-primary btn-sm" onclick="goToLibraryDraft('${draft.id}')">
                        View in Quiz Library <i class="fa-solid fa-arrow-right"></i>
                    </button>
                    <button type="button" class="action-icon-btn" onclick="dismissDraftSavedBanner()" title="Dismiss"><i class="fa-solid fa-xmark"></i></button>
                </div>
            `;
            banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
            draftSavedBannerTimeout = setTimeout(() => {
                dismissDraftSavedBanner();
            }, 8000);
        }

        if (typeof fetchQuizzesOverview === "function") {
            fetchQuizzesOverview().catch(() => {});
        }

        if (saveBtn) {
            saveBtn.innerHTML = `<i class="fa-solid fa-check"></i> Saved!`;
            setTimeout(() => {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.innerHTML = originalHtml;
                }
            }, 1200);
        }
    } catch (err) {
        console.error("Error saving draft:", err);
        alert(err.message || "Failed to save draft.");
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalHtml;
        }
    }
}

async function goToLibraryDraft(quizId) {
    dismissDraftSavedBanner();
    if (typeof switchView === "function") {
        switchView("quizzes");
    }
    if (typeof fetchQuizzesOverview === "function") {
        await fetchQuizzesOverview();
    }
    if (typeof highlightQuizRow === "function" && quizId) {
        setTimeout(() => highlightQuizRow(quizId), 150);
    }
}

function clearDraftEditor() {
    dismissDraftSavedBanner();
    currentDraftQuiz = null;
    currentActiveQuiz = null;
    const previewContent = document.getElementById("draft-editor-content") || document.getElementById("quiz-preview-content");
    if (previewContent) previewContent.style.display = "none";
    const placeholder = document.getElementById("draft-editor-placeholder") || document.getElementById("preview-placeholder");
    if (placeholder) placeholder.style.display = "flex";
    const banner = document.getElementById("success-banner");
    if (banner) banner.style.display = "none";
    const deployBtn = document.querySelector("button[onclick='deployQuiz()']");
    if (deployBtn) {
        deployBtn.disabled = false;
        deployBtn.innerHTML = `Deploy to Canvas`;
    }
}

// Alias for compatibility
function resetPreview() { return clearDraftEditor(); }

/* ---------- Deploy ---------- */

async function deployQuiz() {
    const draft = currentDraftQuiz || currentActiveQuiz;
    if (!draft) return;

    const moduleSelect = document.getElementById("module-select");
    const moduleId = moduleSelect ? moduleSelect.value : null;
    if (!moduleId) {
        alert("Please select a module first.");
        return;
    }

    const deployBtn = document.querySelector("button[onclick='deployQuiz()']");
    if (deployBtn) {
        deployBtn.disabled = true;
        deployBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Deploying…`;
    }

    try {
        if (draft.questions) {
            draft.questions.forEach(q => { q.feedback_enabled = true; });
        }
        draft.includes_agentic_feedback = true;
        const res = await fetch("/api/deploy-quiz", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                module_id: moduleId,
                quiz: draft,
                include_agentic_feedback: true
            })
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Server error during deployment");
        }

        const data = await res.json();
        draft.deployed = true;
        draft.canvas_quiz_id = data.quiz_id;
        draft.quiz_url = data.quiz_url;
        currentDraftQuiz = draft;
        currentActiveQuiz = draft;

        renderDraftEditor();

        const banner = document.getElementById("success-banner");
        if (banner) {
            banner.style.display = "flex";
            banner.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 1rem;">
                    <div style="display: flex; align-items: center; gap: 0.65rem;">
                        <i class="fa-solid fa-circle-check" style="font-size: 1.25rem; color: var(--success);"></i>
                        <div>
                            <strong style="color: var(--text-body);">Deployed to Canvas</strong>
                            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.1rem;">
                                Quiz sent to Canvas. Publish in Canvas when ready for students.
                            </div>
                        </div>
                    </div>
                    <a href="${escapeAttr(data.quiz_url)}" target="_blank" class="btn btn-primary btn-sm" style="text-decoration: none; white-space: nowrap;">
                        Open in Canvas <i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 0.75rem;"></i>
                    </a>
                </div>
            `;
            banner.scrollIntoView({ behavior: "smooth" });
        }

    } catch (err) {
        console.error("Error deploying quiz:", err);
        alert(`Could not deploy quiz: ${err.message}`);
        if (deployBtn) {
            deployBtn.disabled = false;
            deployBtn.innerHTML = `Deploy to Canvas`;
        }
    }
}
