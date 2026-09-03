/**
 * Professor Profile & Personal Memory System
 * Handles personal preference storage, terminology guidelines, and generator integration.
 */

let currentUserProfile = null;
let currentMemoryScope = 'global'; // 'global' | 'course'
let profileCourseId = null;

async function initUserProfile() {
    try {
        const resp = await fetch('/api/user/profile');
        if (!resp.ok) return;
        const data = await resp.json();
        currentUserProfile = data.profile;
        profileCourseId = data.current_course_id;

        updateGeneratorMemoryBadge(data.active_memories_count, data.profile ? data.profile.memory_enabled : true);
    } catch (err) {
        console.warn('Failed to load user profile & memory:', err);
    }
}

function updateGeneratorMemoryBadge(activeCount, isEnabled) {
    const badge = document.getElementById('generator-memory-badge');
    const badgeText = document.getElementById('generator-memory-badge-text');
    if (!badge || !badgeText) return;

    if (!isEnabled) {
        badge.style.display = 'inline-flex';
        badge.style.background = '#F1F5F9';
        badge.style.borderColor = '#CBD5E1';
        badge.style.color = '#64748B';
        badgeText.textContent = 'Memory paused';
        return;
    }

    badge.style.display = 'inline-flex';
    badge.style.background = '#EEF2FF';
    badge.style.borderColor = '#C7D2FE';
    badge.style.color = '#4338CA';

    if (activeCount > 0) {
        badgeText.textContent = `${activeCount} preference${activeCount === 1 ? '' : 's'} active`;
    } else {
        badgeText.textContent = 'Memory active (0 rules)';
    }
}

function openProfileModal() {
    const overlay = document.getElementById('profile-modal-overlay');
    if (!overlay) return;

    renderProfileModalContent();
    overlay.style.display = 'flex';
}

function closeProfileModal() {
    const overlay = document.getElementById('profile-modal-overlay');
    if (overlay) overlay.style.display = 'none';
}

function onProfileOverlayClick(event) {
    if (event.target && event.target.id === 'profile-modal-overlay') {
        closeProfileModal();
    }
}

function switchMemoryScope(scope) {
    currentMemoryScope = scope;

    const tabGlobal = document.getElementById('tab-global-memories');
    const tabCourse = document.getElementById('tab-course-memories');
    if (tabGlobal && tabCourse) {
        tabGlobal.classList.toggle('active', scope === 'global');
        tabCourse.classList.toggle('active', scope === 'course');
    }

    renderMemoryList();
}

function renderProfileModalContent() {
    if (!currentUserProfile) return;

    // Header info
    const avatarEl = document.getElementById('profile-modal-avatar');
    const name = currentUserProfile.user_name || 'Instructor';
    if (avatarEl) {
        avatarEl.textContent = name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase() || 'IN';
    }

    const titleEl = document.getElementById('profile-modal-title');
    if (titleEl) titleEl.textContent = name;

    const subEl = document.getElementById('profile-modal-subtitle');
    if (subEl) {
        const email = currentUserProfile.user_email ? ` &bull; ${currentUserProfile.user_email}` : '';
        subEl.innerHTML = `Instructor Preferences & AI Memory${email}`;
    }

    const courseLabel = document.getElementById('profile-course-id-label');
    if (courseLabel) {
        courseLabel.textContent = profileCourseId ? `Course ${profileCourseId}` : 'Current Course';
    }

    // Master toggle
    const masterToggle = document.getElementById('master-memory-toggle');
    if (masterToggle) {
        masterToggle.checked = currentUserProfile.memory_enabled !== false;
    }

    renderMemoryList();
}

function renderMemoryList() {
    const container = document.getElementById('memory-list-container');
    if (!container || !currentUserProfile) return;

    let items = [];
    if (currentMemoryScope === 'course') {
        const cid = String(profileCourseId || '');
        const courseMems = currentUserProfile.course_memories || {};
        items = courseMems[cid] || [];
    } else {
        items = currentUserProfile.global_memories || [];
    }

    if (items.length === 0) {
        const emptyMsg = currentMemoryScope === 'course'
            ? 'No course-specific preferences yet. Add guidelines or terminology unique to this course below.'
            : 'No global preferences yet. Add terminology tastes or style rules that apply across all your courses below.';
        container.innerHTML = `
            <div style="text-align: center; padding: 2rem 1rem; color: var(--text-muted); font-size: 0.85rem;">
                <i class="fa-regular fa-lightbulb" style="font-size: 1.5rem; margin-bottom: 0.5rem; display: block; opacity: 0.6;"></i>
                ${emptyMsg}
            </div>
        `;
        return;
    }

    // escapeHtml is provided globally by util.js
    const safeEscape = typeof escapeHtml === 'function' ? escapeHtml : (s => s || '');

    container.innerHTML = items.map(m => `
        <div class="memory-item-row ${m.enabled === false ? 'disabled' : ''}" data-memory-id="${m.id}">
            <input type="checkbox" class="memory-item-checkbox" ${m.enabled !== false ? 'checked' : ''} 
                onchange="onToggleMemoryItem('${m.id}', this.checked)" title="Toggle active/inactive">
            <span class="memory-item-text">${safeEscape(m.text)}</span>
            <button type="button" class="memory-item-del-btn" onclick="onDeleteMemoryItem('${m.id}')" title="Delete preference">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        </div>
    `).join('');
}

async function toggleMasterMemory(enabled) {
    if (!currentUserProfile) return;
    try {
        const resp = await fetch('/api/user/profile', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ memory_enabled: enabled })
        });
        if (resp.ok) {
            currentUserProfile.memory_enabled = enabled;
            recalculateActiveBadge();
        }
    } catch (err) {
        console.error('Failed to update memory setting:', err);
    }
}

async function submitNewMemory() {
    const input = document.getElementById('new-memory-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    const courseId = currentMemoryScope === 'course' ? profileCourseId : null;

    try {
        const resp = await fetch('/api/user/memories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, course_id: courseId })
        });

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            alert(errData.detail || 'Could not add preference.');
            return;
        }

        const data = await resp.json();
        input.value = '';

        if (courseId) {
            const cid = String(courseId);
            currentUserProfile.course_memories = currentUserProfile.course_memories || {};
            currentUserProfile.course_memories[cid] = currentUserProfile.course_memories[cid] || [];
            currentUserProfile.course_memories[cid].push(data.memory);
        } else {
            currentUserProfile.global_memories = currentUserProfile.global_memories || [];
            currentUserProfile.global_memories.push(data.memory);
        }

        renderMemoryList();
        recalculateActiveBadge();
    } catch (err) {
        console.error('Failed to add memory:', err);
    }
}

async function onToggleMemoryItem(memoryId, enabled) {
    const courseId = currentMemoryScope === 'course' ? profileCourseId : null;
    try {
        const resp = await fetch(`/api/user/memories/${memoryId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled, course_id: courseId })
        });

        if (resp.ok) {
            updateLocalMemoryEnabled(memoryId, enabled, courseId);
            renderMemoryList();
            recalculateActiveBadge();
        }
    } catch (err) {
        console.error('Failed to toggle memory item:', err);
    }
}

async function onDeleteMemoryItem(memoryId) {
    if (!confirm('Are you sure you want to delete this preference?')) return;
    const courseId = currentMemoryScope === 'course' ? profileCourseId : null;
    const url = courseId ? `/api/user/memories/${memoryId}?course_id=${courseId}` : `/api/user/memories/${memoryId}`;

    try {
        const resp = await fetch(url, { method: 'DELETE' });
        if (resp.ok) {
            removeLocalMemory(memoryId, courseId);
            renderMemoryList();
            recalculateActiveBadge();
        }
    } catch (err) {
        console.error('Failed to delete memory item:', err);
    }
}

function updateLocalMemoryEnabled(memoryId, enabled, courseId) {
    if (!currentUserProfile) return;
    const lists = [];
    if (courseId) {
        const cid = String(courseId);
        if (currentUserProfile.course_memories && currentUserProfile.course_memories[cid]) {
            lists.push(currentUserProfile.course_memories[cid]);
        }
    } else {
        if (currentUserProfile.global_memories) lists.push(currentUserProfile.global_memories);
        if (currentUserProfile.course_memories) {
            Object.values(currentUserProfile.course_memories).forEach(l => lists.push(l));
        }
    }

    for (const list of lists) {
        const item = list.find(m => m.id === memoryId);
        if (item) {
            item.enabled = enabled;
            break;
        }
    }
}

function removeLocalMemory(memoryId, courseId) {
    if (!currentUserProfile) return;
    if (courseId) {
        const cid = String(courseId);
        if (currentUserProfile.course_memories && currentUserProfile.course_memories[cid]) {
            currentUserProfile.course_memories[cid] = currentUserProfile.course_memories[cid].filter(m => m.id !== memoryId);
        }
    } else {
        if (currentUserProfile.global_memories) {
            currentUserProfile.global_memories = currentUserProfile.global_memories.filter(m => m.id !== memoryId);
        }
        if (currentUserProfile.course_memories) {
            for (const cid in currentUserProfile.course_memories) {
                currentUserProfile.course_memories[cid] = currentUserProfile.course_memories[cid].filter(m => m.id !== memoryId);
            }
        }
    }
}

function recalculateActiveBadge() {
    if (!currentUserProfile) return;
    let count = 0;
    if (currentUserProfile.memory_enabled !== false) {
        (currentUserProfile.global_memories || []).forEach(m => {
            if (m.enabled !== false) count++;
        });
        if (profileCourseId && currentUserProfile.course_memories) {
            const courseList = currentUserProfile.course_memories[String(profileCourseId)] || [];
            courseList.forEach(m => {
                if (m.enabled !== false) count++;
            });
        }
    }
    updateGeneratorMemoryBadge(count, currentUserProfile.memory_enabled !== false);
}

document.addEventListener('DOMContentLoaded', () => {
    initUserProfile();
});
