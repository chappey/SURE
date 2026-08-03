/* Shared helpers: escaping, parsing, numeric field reads. */

function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
    return escapeHtml(value);
}

/** Strip HTML tags/entities to plain text; still escape before inserting into HTML. */
function htmlToPlainText(value) {
    if (value === null || value === undefined) return "";
    let text = String(value);
    text = text.replace(/<br\s*\/?>/gi, "\n");
    text = text.replace(/<\/p\s*>/gi, "\n");
    text = text.replace(/<[^>]+>/g, "");
    text = text
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/gi, "'");
    text = text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n");
    return text.trim();
}

function formatScoreDisplay(score, pointsPossible) {
    if (score === null || score === undefined || score === "") return "";
    const earned = Number(score);
    if (Number.isNaN(earned)) return "";
    const possible = Number(pointsPossible);
    if (!Number.isNaN(possible) && possible > 0) {
        const pct = Math.round((earned / possible) * 100);
        const earnedLabel = Number.isInteger(earned) ? String(earned) : earned.toFixed(1);
        const possibleLabel = Number.isInteger(possible) ? String(possible) : possible.toFixed(1);
        return `${earnedLabel}/${possibleLabel} (${pct}%)`;
    }
    return String(earned);
}

function parseApiDetail(data) {
    if (!data || data.detail === undefined || data.detail === null) return null;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
        return data.detail.map(item => item.msg || String(item)).join(" ");
    }
    return String(data.detail);
}

function readCount(id) {
    return Math.max(0, parseInt(document.getElementById(id).value) || 0);
}

function readPoints(id) {
    return Math.max(1, parseInt(document.getElementById(id).value) || 1);
}

function formatTimestamp(epochSeconds) {
    if (!epochSeconds) return "";
    return new Date(epochSeconds * 1000).toLocaleString();
}
