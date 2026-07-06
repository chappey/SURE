/* App bootstrap: session, course switching, view routing. */

let loadedModules = [];
let loadedCourses = [];
let loadedModels = [];
let currentActiveQuiz = null;
let currentCourseId = null;

window.addEventListener("DOMContentLoaded", () => {
    loadWorkspace();
    updateLayoutSummary();
    syncFeedbackToggles();
    document.getElementById("include-answer-feedback").addEventListener("change", syncFeedbackToggles);
    document.getElementById("include-agentic-feedback").addEventListener("change", syncFeedbackToggles);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeQuizModal();
    });
});

function switchView(view) {
    document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
    document.getElementById(`view-${view}`).classList.add("active");
    document.querySelectorAll(".nav-item").forEach(n => {
        n.classList.toggle("active", n.dataset.view === view);
    });
    if (view === "quizzes") fetchQuizzesOverview();
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
    await fetchSession();
    await fetchCourseInfo();
    await fetchCourses();
    await fetchModels();
    await fetchModules();
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
        await loadWorkspace();
    } catch (err) {
        alert(`Course switch failed: ${err.message}`);
        if (select && previous) select.value = String(previous);
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
