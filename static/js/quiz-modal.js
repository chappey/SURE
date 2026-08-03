/* Results panel: comprehensive teaching insights & Chart.js visualizations */

let modalQuizId = null;
let activeChartInstances = {};

function openQuizModal(quizId, title) {
    modalQuizId = quizId;
    document.getElementById("quiz-modal-title").textContent = title
        ? `Results & Comprehension · ${title}`
        : "Results & Comprehension";
    document.getElementById("quiz-modal-overlay").classList.add("open");
    document.body.style.overflow = "hidden";
    loadQuizResults(quizId);
}

function closeQuizModal() {
    const overlay = document.getElementById("quiz-modal-overlay");
    if (!overlay || !overlay.classList.contains("open")) return;
    destroyCharts();
    overlay.classList.remove("open");
    document.body.style.overflow = "";
    modalQuizId = null;
}

function onModalOverlayClick(event) {
    if (event.target === document.getElementById("quiz-modal-overlay")) {
        closeQuizModal();
    }
}

function destroyCharts() {
    Object.keys(activeChartInstances).forEach(id => {
        if (activeChartInstances[id]) {
            activeChartInstances[id].destroy();
        }
    });
    activeChartInstances = {};
}

async function loadQuizResults(quizId) {
    const el = document.getElementById("modal-results");
    if (!el) return;
    destroyCharts();
    el.innerHTML = `<p class="text-muted-inline" style="padding: 2rem; text-align: center;"><i class="fa-solid fa-spinner fa-spin"></i> Loading comprehension analytics…</p>`;

    try {
        const [statsRes, quizRes] = await Promise.all([
            fetch(`/api/quizzes/${quizId}/stats`),
            fetch(`/api/quizzes/${quizId}`)
        ]);
        const stats = statsRes.ok ? await statsRes.json() : null;
        const draft = quizRes.ok ? await quizRes.json() : null;

        if (modalQuizId !== quizId) return;

        renderResults(el, quizId, stats, draft);
    } catch (err) {
        console.error("Error loading results:", err);
        el.innerHTML = `<p class="error-cell">Could not load results.</p>`;
    }
}

function switchStatsTab(tabName) {
    document.querySelectorAll(".stats-tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tabName);
    });
    document.querySelectorAll(".stats-panel").forEach(panel => {
        panel.classList.toggle("active", panel.id === `stats-panel-${tabName}`);
    });
}

function renderResults(el, quizId, stats, draft) {
    destroyCharts();

    const processed = (draft && draft.agentic_feedback_processed) || {};
    const workspaceSubs = ((draft && draft.feedback_workspace) || {}).submissions || [];
    const done = Math.max(
        Object.keys(processed).length,
        workspaceSubs.filter(s => (s.questions || []).some(q => (q.ai_feedback || "").trim())).length
    );
    const subs = stats && stats.available ? (stats.submission_count || 0) : 0;
    const gradeDist = (stats && stats.grade_distribution) || {};
    const passRate = gradeDist.pass_rate != null ? gradeDist.pass_rate : 0.0;
    const scoreAvg = stats && stats.score_average != null ? Number(stats.score_average).toFixed(1) : "—";
    const scoreMedian = stats && stats.score_median != null ? Number(stats.score_median).toFixed(1) : scoreAvg;
    const misconceptionMat = (stats && stats.misconception_matrix) || {};
    const highRiskMisconceptions = misconceptionMat.high_confidence_wrong || 0;

    // Actions CTA
    const actionsHtml = `
        <button type="button" class="btn btn-primary btn-sm" data-quiz-id="${escapeAttr(quizId)}" onclick="closeQuizModal(); loadFeedbackWorkspace(this.dataset.quizId)">
            <i class="fa-solid fa-wand-magic-sparkles"></i> Open Feedback Workspace
        </button>`;

    // KPI Summary Grid
    const kpiHtml = `
        <div class="stats-kpi-grid">
            <div class="kpi-card">
                <div class="kpi-icon blue"><i class="fa-solid fa-users"></i></div>
                <div class="kpi-data">
                    <span class="kpi-val">${subs}</span>
                    <span class="kpi-lbl">Total Submissions</span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon green"><i class="fa-solid fa-circle-check"></i></div>
                <div class="kpi-data">
                    <span class="kpi-val">${passRate}%</span>
                    <span class="kpi-lbl">Pass Rate (≥ 70%)</span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon purple"><i class="fa-solid fa-chart-line"></i></div>
                <div class="kpi-data">
                    <span class="kpi-val">${scoreAvg}</span>
                    <span class="kpi-lbl">Class Average Score</span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-icon ${highRiskMisconceptions > 0 ? 'red' : 'amber'}">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                </div>
                <div class="kpi-data">
                    <span class="kpi-val">${highRiskMisconceptions}</span>
                    <span class="kpi-lbl">High-Risk Misconceptions</span>
                </div>
            </div>
        </div>`;

    // Navigation Tabs
    const tabsHtml = `
        <div class="stats-tab-nav">
            <button type="button" class="stats-tab-btn active" data-tab="overview" onclick="switchStatsTab('overview')">
                <i class="fa-solid fa-chart-pie"></i> Overview & Tiers
            </button>
            <button type="button" class="stats-tab-btn" data-tab="questions" onclick="switchStatsTab('questions')">
                <i class="fa-solid fa-list-check"></i> Question & Distractor Analysis
            </button>
            <button type="button" class="stats-tab-btn" data-tab="misconceptions" onclick="switchStatsTab('misconceptions')">
                <i class="fa-solid fa-brain"></i> Misconception Matrix
            </button>
            <button type="button" class="stats-tab-btn" data-tab="topics" onclick="switchStatsTab('topics')">
                <i class="fa-solid fa-layer-group"></i> Topic Mastery
            </button>
        </div>`;

    // Content Questions
    const questions = (stats && stats.questions) || [];
    const topicMastery = (stats && stats.topic_mastery) || [];

    // Panel 1: Overview
    const overviewPanel = `
        <div class="stats-panel active" id="stats-panel-overview">
            <div class="chart-grid-2">
                <div class="chart-card">
                    <div class="chart-card-head">
                        <h6 class="chart-card-title"><i class="fa-solid fa-chart-pie"></i> Grade Distribution Tiers</h6>
                    </div>
                    <div class="chart-canvas-box">
                        <canvas id="canvas-grade-dist"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <div class="chart-card-head">
                        <h6 class="chart-card-title"><i class="fa-solid fa-fire"></i> Top Learning Gap Areas</h6>
                    </div>
                    <div id="overview-struggle-list">
                        ${renderStruggleList(questions)}
                    </div>
                </div>
            </div>
        </div>`;

    // Panel 2: Questions & Distractors
    const questionsPanel = `
        <div class="stats-panel" id="stats-panel-questions">
            <div class="chart-card" style="margin-bottom: 1.25rem;">
                <div class="chart-card-head">
                    <h6 class="chart-card-title"><i class="fa-solid fa-chart-bar"></i> Per-Question Accuracy (%)</h6>
                </div>
                <div class="chart-canvas-box" style="min-height: 260px;">
                    <canvas id="canvas-question-accuracy"></canvas>
                </div>
            </div>
            <h5 class="modal-section-title" style="margin: 1.25rem 0 0.75rem;"><i class="fa-solid fa-sliders"></i> Option-Level Distractor Analysis</h5>
            <div id="distractor-analysis-list">
                ${renderDistractorCards(questions)}
            </div>
        </div>`;

    // Panel 3: Misconception Matrix
    const misconceptionsPanel = `
        <div class="stats-panel" id="stats-panel-misconceptions">
            <div class="misconception-grid">
                <div class="misconception-box high-risk">
                    <span class="misconception-title"><i class="fa-solid fa-triangle-exclamation"></i> High-Risk Misconception</span>
                    <span class="misconception-count">${misconceptionMat.high_confidence_wrong || 0}</span>
                    <span class="misconception-desc">Students were highly confident but answered incorrectly (Priority for lecture re-teaching).</span>
                </div>
                <div class="misconception-box mastery">
                    <span class="misconception-title"><i class="fa-solid fa-award"></i> Confident Mastery</span>
                    <span class="misconception-count">${misconceptionMat.high_confidence_correct || 0}</span>
                    <span class="misconception-desc">Students answered correctly with strong self-confidence.</span>
                </div>
                <div class="misconception-box gap">
                    <span class="misconception-title"><i class="fa-solid fa-graduation-cap"></i> Recognized Gap</span>
                    <span class="misconception-count">${misconceptionMat.low_confidence_wrong || 0}</span>
                    <span class="misconception-desc">Students felt uncertain and missed the question (Awareness of study need).</span>
                </div>
                <div class="misconception-box uncertain">
                    <span class="misconception-title"><i class="fa-solid fa-circle-question"></i> Lucky / Uncertain</span>
                    <span class="misconception-count">${misconceptionMat.low_confidence_correct || 0}</span>
                    <span class="misconception-desc">Students answered correctly despite low confidence.</span>
                </div>
            </div>
            <div class="chart-card" style="margin-top: 1rem;">
                <div class="chart-card-head">
                    <h6 class="chart-card-title"><i class="fa-solid fa-brain"></i> Confidence vs. Accuracy Breakdown</h6>
                </div>
                <div class="chart-canvas-box">
                    <canvas id="canvas-misconception-chart"></canvas>
                </div>
            </div>
        </div>`;

    // Panel 4: Topic Mastery
    const topicsPanel = `
        <div class="stats-panel" id="stats-panel-topics">
            <div class="chart-card">
                <div class="chart-card-head">
                    <h6 class="chart-card-title"><i class="fa-solid fa-layer-group"></i> Concept & Skill Area Mastery (%)</h6>
                </div>
                <div class="chart-canvas-box" style="min-height: 280px;">
                    <canvas id="canvas-topic-mastery"></canvas>
                </div>
            </div>
        </div>`;

    el.innerHTML = `
        <div class="stats-container">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                <p class="text-muted-inline" style="margin: 0;">Automated teaching analytics generated from Canvas submissions.</p>
                <div>${actionsHtml}</div>
            </div>
            ${kpiHtml}
            ${tabsHtml}
            ${overviewPanel}
            ${questionsPanel}
            ${misconceptionsPanel}
            ${topicsPanel}
        </div>`;

    // Initialize Chart.js visualizations asynchronously
    setTimeout(() => {
        initCharts(stats, draft);
    }, 50);
}

function renderStruggleList(questions) {
    if (!questions || !questions.length) {
        return `<p class="text-muted-inline">No question statistics available yet.</p>`;
    }

    const sorted = [...questions].sort((a, b) => (a.correct_pct || 0) - (b.correct_pct || 0));
    const topStruggles = sorted.slice(0, 4);

    return topStruggles.map((q, idx) => {
        const stem = htmlToPlainText(q.question_text || q.question_name || `Question ${idx + 1}`);
        const pct = q.correct_pct != null ? q.correct_pct : (q.responses ? Math.round((q.correct_count / q.responses) * 100) : 0);
        const barClass = pct >= 70 ? "good" : (pct >= 40 ? "mid" : "poor");
        return `
            <div class="qstat-row" style="margin-bottom: 0.75rem;">
                <span class="qstat-name" title="${escapeAttr(stem)}" style="font-size: 0.84rem;">${escapeHtml(stem)}</span>
                <div class="qstat-track">
                    <div class="qstat-fill ${barClass}" style="width:${pct}%"></div>
                </div>
                <span class="qstat-pct">${pct}%</span>
            </div>`;
    }).join("");
}

function renderDistractorCards(questions) {
    if (!questions || !questions.length) {
        return `<p class="text-muted-inline">No multiple-choice distractor data available.</p>`;
    }

    return questions.map((q, idx) => {
        const stem = htmlToPlainText(q.question_text || q.question_name || `Question ${idx + 1}`);
        const answers = q.answers || [];
        if (!answers.length) {
            return "";
        }

        const optionsHtml = answers.map(a => {
            const isCorr = a.correct;
            const pct = a.percentage != null ? a.percentage : 0;
            const fillClass = isCorr ? "correct" : "wrong";
            return `
                <div class="distractor-opt-row">
                    <span class="distractor-opt-text">${isCorr ? '<i class="fa-solid fa-check text-success"></i> ' : ''}${escapeHtml(a.text || 'Option')}</span>
                    <div class="distractor-opt-bar-track">
                        <div class="distractor-opt-bar-fill ${fillClass}" style="width: ${pct}%"></div>
                    </div>
                    <span class="distractor-opt-pct">${pct}%</span>
                </div>`;
        }).join("");

        return `
            <div class="distractor-card">
                <div class="distractor-head">
                    <span class="distractor-qname">Q${idx + 1}. ${escapeHtml(stem)}</span>
                    <span class="badge ${q.correct_pct >= 70 ? 'badge-success' : 'badge-warning'}">${q.correct_pct}% Correct</span>
                </div>
                <div class="distractor-opt-list">
                    ${optionsHtml}
                </div>
            </div>`;
    }).filter(Boolean).join("") || `<p class="text-muted-inline">No option-level distractor data present for essay or custom items.</p>`;
}

function initCharts(stats, draft) {
    if (typeof Chart === "undefined") {
        console.warn("Chart.js library not loaded yet.");
        return;
    }

    // 1. Grade Distribution Donut Chart
    const gradeCanvas = document.getElementById("canvas-grade-dist");
    if (gradeCanvas) {
        const dist = (stats && stats.grade_distribution) || {};
        activeChartInstances["grade"] = new Chart(gradeCanvas, {
            type: "doughnut",
            data: {
                labels: ["Mastery (≥90%)", "Proficient (70-89%)", "Developing (50-69%)", "Struggling (<50%)"],
                datasets: [{
                    data: [
                        dist.mastery_count || 0,
                        dist.proficient_count || 0,
                        dist.developing_count || 0,
                        dist.struggling_count || 0
                    ],
                    backgroundColor: ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444"],
                    borderWidth: 2,
                    borderColor: "#ffffff"
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom" }
                }
            }
        });
    }

    // 2. Question Accuracy Bar Chart
    const questions = (stats && stats.questions) || [];
    const accCanvas = document.getElementById("canvas-question-accuracy");
    if (accCanvas && questions.length) {
        const labels = questions.map((q, i) => `Q${i + 1}`);
        const data = questions.map(q => q.correct_pct != null ? q.correct_pct : 0);
        const bgColors = data.map(v => v >= 70 ? "rgba(34, 197, 94, 0.75)" : (v >= 40 ? "rgba(245, 158, 11, 0.75)" : "rgba(239, 68, 68, 0.75)"));

        activeChartInstances["accuracy"] = new Chart(accCanvas, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: "Accuracy Rate (%)",
                    data: data,
                    backgroundColor: bgColors,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { min: 0, max: 100, ticks: { callback: v => v + "%" } }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }

    // 3. Misconceptions Chart
    const misCanvas = document.getElementById("canvas-misconception-chart");
    if (misCanvas) {
        const mat = (stats && stats.misconception_matrix) || {};
        activeChartInstances["misconception"] = new Chart(misCanvas, {
            type: "bar",
            data: {
                labels: ["Student Confidence vs Accuracy Breakdown"],
                datasets: [
                    { label: "High-Risk Misconceptions", data: [mat.high_confidence_wrong || 0], backgroundColor: "#ef4444" },
                    { label: "Confident Mastery", data: [mat.high_confidence_correct || 0], backgroundColor: "#22c55e" },
                    { label: "Recognized Gap", data: [mat.low_confidence_wrong || 0], backgroundColor: "#f59e0b" },
                    { label: "Uncertain / Lucky", data: [mat.low_confidence_correct || 0], backgroundColor: "#3b82f6" }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { stacked: true },
                    y: { stacked: true }
                },
                plugins: {
                    legend: { position: "bottom" }
                }
            }
        });
    }

    // 4. Topic Mastery Horizontal Bar Chart
    const topicCanvas = document.getElementById("canvas-topic-mastery");
    const topics = (stats && stats.topic_mastery) || [];
    if (topicCanvas) {
        const tLabels = topics.length ? topics.map(t => t.topic) : ["General Concept"];
        const tData = topics.length ? topics.map(t => t.accuracy_pct) : [stats && stats.score_average ? Number(stats.score_average) : 75];

        activeChartInstances["topic"] = new Chart(topicCanvas, {
            type: "bar",
            data: {
                labels: tLabels,
                datasets: [{
                    label: "Topic Mastery (%)",
                    data: tData,
                    backgroundColor: "rgba(99, 102, 241, 0.8)",
                    borderRadius: 6
                }]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { min: 0, max: 100, ticks: { callback: v => v + "%" } }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }
}

async function processAgenticFeedback(quizId) {
    closeQuizModal();
    await loadFeedbackWorkspace(quizId, { force: false });
}

