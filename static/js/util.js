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
