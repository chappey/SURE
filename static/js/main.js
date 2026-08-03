/* App bootstrap: session, course switching, view routing. */

let loadedModules = [];
let loadedCourses = [];
let loadedModels = [];
let currentDraftQuiz = null;
let currentActiveQuiz = null;
let currentCourseId = null;
let modulesReady = false;
let modelsReady = false;

const SIDEBAR_KEY = "easylearn_sidebar";
const CREATE_COL_KEY = "easylearn_create_col_width";
const LOGO_CAP = "fa-solid fa-graduation-cap logo-icon";
const LOGO_EXPAND = "fa-solid fa-angle-right logo-icon";

window.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initPanelSplitter();
    setGeneratorLoading(true);
    loadWorkspace();
    updateLayoutSummary();
    syncFeedbackToggles();
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeQuizModal();
    });
});

function initSidebar() {
    const collapseBtn = document.getElementById("sidebar-collapse-btn");
    const logoBtn = document.getElementById("sidebar-logo-btn");
    const logoIcon = document.getElementById("sidebar-logo-icon");
    applySidebarState(localStorage.getItem(SIDEBAR_KEY) === "collapsed");

    // Only one collapse control when expanded: the « button.
    if (collapseBtn) {
        collapseBtn.addEventListener("click", () => setSidebarCollapsed(true));
    }

    // Collapsed: single icon is the cap; hover → → ; click → expand. Cap never
    // sits next to an arrow — one icon element, class swapped on hover only.
    if (logoBtn && logoIcon) {
        logoBtn.addEventListener("mouseenter", () => {
            if (!document.body.classList.contains("sidebar-collapsed")) return;
            logoIcon.className = LOGO_EXPAND;
        });
        logoBtn.addEventListener("mouseleave", () => {
            if (!document.body.classList.contains("sidebar-collapsed")) return;
            logoIcon.className = LOGO_CAP;
        });
        logoBtn.addEventListener("click", (e) => {
            if (!document.body.classList.contains("sidebar-collapsed")) {
                // Expanded: logo is not a toggle (use « only).
                e.preventDefault();
                return;
            }
            setSidebarCollapsed(false);
        });
    }
}

function setSidebarCollapsed(collapsed) {
    applySidebarState(collapsed);
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "collapsed" : "expanded");
}

function applySidebarState(collapsed) {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    const collapseBtn = document.getElementById("sidebar-collapse-btn");
    const logoBtn = document.getElementById("sidebar-logo-btn");
    const logoIcon = document.getElementById("sidebar-logo-icon");
    if (collapseBtn) {
        collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
        collapseBtn.title = "Collapse menu";
        collapseBtn.hidden = collapsed;
    }
    if (logoIcon) {
        logoIcon.className = LOGO_CAP;
    }
    if (logoBtn) {
        if (collapsed) {
            logoBtn.title = "Expand menu";
            logoBtn.setAttribute("aria-label", "Expand menu");
        } else {
            logoBtn.title = "EasyLearn";
            logoBtn.setAttribute("aria-label", "EasyLearn");
        }
    }
}

/** Drag the vertical bar between Create form and quiz preview. */
function initPanelSplitter() {
    const grid = document.getElementById("create-grid");
    const splitter = document.getElementById("panel-splitter");
    if (!grid || !splitter) return;

    const saved = parseInt(localStorage.getItem(CREATE_COL_KEY), 10);
    if (saved && saved >= 240 && saved <= 560) {
        grid.style.setProperty("--create-col-width", `${saved}px`);
    }

    let dragging = false;

    const onMove = (e) => {
        if (!dragging) return;
        const rect = grid.getBoundingClientRect();
        let w = e.clientX - rect.left;
        w = Math.max(240, Math.min(560, w));
        grid.style.setProperty("--create-col-width", `${w}px`);
    };

    const onUp = () => {
        if (!dragging) return;
        dragging = false;
        document.body.classList.remove("is-resizing-panels");
        splitter.classList.remove("is-dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        const raw = getComputedStyle(grid).getPropertyValue("--create-col-width").trim();
        const px = parseInt(raw, 10);
        if (px) localStorage.setItem(CREATE_COL_KEY, String(px));
    };

    splitter.addEventListener("mousedown", (e) => {
        e.preventDefault();
        dragging = true;
        document.body.classList.add("is-resizing-panels");
        splitter.classList.add("is-dragging");
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

function switchView(view) {
    if (view !== "feedback-review" && typeof saveFeedbackWorkspaceDraft === "function" && currentFeedbackData) {
        saveFeedbackWorkspaceDraft().catch(() => {});
    }
    document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
    document.getElementById(`view-${view}`).classList.add("active");
    document.querySelectorAll(".nav-item").forEach(n => {
        n.classList.toggle("active", n.dataset.view === view);
    });
    const heading = document.getElementById("page-heading");
    const sub = document.getElementById("page-subheading");
    if (view === "quizzes") {
        if (heading) heading.textContent = "Quiz Library";
        if (sub) sub.textContent = "Saved and deployed quizzes for this course.";
        fetchQuizzesOverview();
    } else if (view === "feedback-review") {
        if (heading) heading.textContent = "Feedback Review Workspace";
        if (sub) sub.textContent = "Inspect, edit, and approve student feedback comments before sending to Canvas.";
    } else {
        if (heading) heading.textContent = "Create quiz";
        if (sub) sub.textContent = "Build a quiz from your course materials and send it to Canvas.";
    }
}

function authModeLabel(mode) {
    const labels = {
        oauth: "Canvas OAuth",
        oauth_pending: "Authorization required",
        anonymous: "Not signed in",
    };
    return labels[mode] || mode;
}

function applySessionToProfile(session) {
    const profileName = document.querySelector(".user-name");
    const roleEl = document.querySelector(".user-role");
    const avatar = document.querySelector(".avatar");
    const notice = document.getElementById("auth-notice");

    const displayName = session.user_name || session.user_email || "Unknown user";
    if (profileName) profileName.innerText = displayName;

    let roleText = authModeLabel(session.auth_mode);
    if (session.user_role) roleText = `${session.user_role} · ${roleText}`;
    if (roleEl) roleEl.innerText = roleText;

    if (avatar) {
        const initials = displayName.split(/\s+/).map(n => n[0]).join("").toUpperCase().slice(0, 2);
        avatar.innerText = initials || "?";
    }

    if (notice) {
        if (session.auth_mode === "oauth_pending") {
            notice.hidden = false;
            notice.textContent = "Complete Canvas authorization to load course data.";
            notice.className = "auth-notice auth-notice-warn";
        } else {
            notice.hidden = true;
            notice.textContent = "";
        }
    }

    if (session.canvas_course_id) {
        currentCourseId = session.canvas_course_id;
    }
}

function setSourceStatus(message, kind = "") {
    const el = document.getElementById("source-status");
    if (!el) return;
    if (!message) {
        el.hidden = true;
        el.textContent = "";
        el.className = "source-status";
        return;
    }
    el.hidden = false;
    el.textContent = message;
    el.className = kind ? `source-status source-status-${kind}` : "source-status";
}

function setGeneratorLoading(isLoading) {
    const moduleSelect = document.getElementById("module-select");
    const modelSelect = document.getElementById("model-select");
    const materialList = document.getElementById("material-list-container");
    const generateBtn = document.getElementById("btn-generate");
    const wrappers = document.querySelectorAll(".select-wrapper");

    wrappers.forEach(w => w.classList.toggle("is-loading", isLoading));
    if (materialList) materialList.classList.toggle("is-loading", isLoading);

    if (moduleSelect && !modulesReady) moduleSelect.disabled = true;
    if (modelSelect && !modelsReady) modelSelect.disabled = true;

    if (!isLoading) {
        if (moduleSelect && modulesReady) moduleSelect.disabled = false;
        if (modelSelect && modelsReady) modelSelect.disabled = false;
    }

    updateGenerateEnabled();
    if (generateBtn && isLoading) generateBtn.disabled = true;
}

function updateGenerateEnabled() {
    const generateBtn = document.getElementById("btn-generate");
    if (!generateBtn) return;
    // Leave disabled during in-flight generation (btn shows spinner text).
    if (generateBtn.dataset.generating === "1") return;
    generateBtn.disabled = !(modulesReady && modelsReady);
}

async function fetchSession() {
    try {
        const res = await fetch("/api/session");
        if (res.status === 401) { window.location.reload(); return; }
        if (!res.ok) throw new Error("Failed to load session");
        const session = await res.json();
        applySessionToProfile(session);
        return session;
    } catch (err) {
        console.error("Error fetching session:", err);
        const profileName = document.querySelector(".user-name");
        const roleEl = document.querySelector(".user-role");
        if (profileName) profileName.innerText = "Session unavailable";
        if (roleEl) roleEl.innerText = "Re-launch from Canvas";
    }
}

async function loadWorkspace() {
    setGeneratorLoading(true);
    modulesReady = false;
    modelsReady = false;
    setSourceStatus("Loading course data…", "pending");
    await fetchSession();
    // Paint independently as each request settles — do not block on the slowest.
    await Promise.allSettled([
        fetchCourseInfo(),
        fetchCourses(),
        fetchModels(),
        fetchModules({ refresh: false }),
    ]);
    setGeneratorLoading(false);
    if (modulesReady) {
        setSourceStatus("Modules ready", "ok");
        window.setTimeout(() => setSourceStatus(""), 1200);
    }
}

function populateCourseSelect(courses, selectedId) {
    const select = document.getElementById("course-switcher");
    select.innerHTML = "";
    if (!courses.length) {
        select.innerHTML = `<option value="">No courses available</option>`;
        return;
    }
    courses.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.course_code || c.id}: ${c.name}`;
        select.appendChild(opt);
    });
    if (selectedId) {
        select.value = String(selectedId);
    }
}

async function fetchCourses() {
    try {
        const res = await fetch("/api/courses");
        if (!res.ok) throw new Error("Failed to list courses");
        loadedCourses = await res.json();
        populateCourseSelect(loadedCourses, currentCourseId);
    } catch (err) {
        console.error("Error fetching courses:", err);
        const select = document.getElementById("course-switcher");
        if (currentCourseId) {
            populateCourseSelect([], currentCourseId);
        } else {
            select.innerHTML = `<option value="">Could not load courses</option>`;
        }
    }
}

async function switchCourse(courseId) {
    if (!courseId || String(courseId) === String(currentCourseId)) return;
    const select = document.getElementById("course-switcher");
    const previous = currentCourseId;
    if (select) select.disabled = true;
    modulesReady = false;
    setGeneratorLoading(true);
    setSourceStatus("Switching course…", "pending");
    try {
        const res = await fetch("/api/courses/switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ course_id: parseInt(courseId) })
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(parseApiDetail(data) || "Could not switch course");
        }
        resetPreview();
        // Lean reload: session + models stay; only course-scoped data refreshes.
        await Promise.allSettled([
            fetchCourseInfo(),
            fetchModules({ refresh: false }),
        ]);
        if (modulesReady) {
            setSourceStatus("Modules ready", "ok");
            window.setTimeout(() => setSourceStatus(""), 1200);
        }
    } catch (err) {
        alert(`Course switch failed: ${err.message}`);
        if (select && previous) select.value = String(previous);
        setSourceStatus("Course switch failed", "error");
    } finally {
        if (select) select.disabled = false;
        setGeneratorLoading(false);
    }
}

async function fetchCourseInfo() {
    try {
        const res = await fetch("/api/course-info");
        if (res.status === 401) { window.location.reload(); return; }
        if (!res.ok) throw new Error("Failed to load course details");
        const data = await res.json();
        currentCourseId = data.id;
        populateCourseSelect(loadedCourses.length ? loadedCourses : [{
            id: data.id,
            name: data.name,
            course_code: data.course_code
        }], data.id);

        const profileName = document.querySelector(".user-name");
        if (profileName && data.user_name) profileName.innerText = data.user_name;

        const avatar = document.querySelector(".avatar");
        if (avatar && data.user_name) {
            avatar.innerText = data.user_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
        }
    } catch (err) {
        console.error("Error fetching course info:", err);
        const headerTitle = document.querySelector(".header-title p");
        if (headerTitle && !currentCourseId) {
            headerTitle.textContent = "Could not load course — re-launch EasyLearn from Canvas.";
        }
    }
}
