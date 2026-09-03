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

/**
 * Render text with safe formatting tags (sub, sup, b, i, em, strong, code, br, p)
 * and clean common LaTeX syntax artifacts so formulas like sp^3, H2O, or $\text{...}$
 * display cleanly without breaking layout or executing arbitrary script.
 */
function renderSafeRichText(value) {
    if (value === null || value === undefined) return "";
    let str = String(value);

    // 1. Clean common LaTeX artifacts:
    // e.g. $\text{sp}^3$ or \( \text{sp}^3 \) -> sp<sup>3</sup>
    str = str.replace(/\$(.*?)\$/g, "$1");
    str = str.replace(/\\\((.*?)\\\)/g, "$1");
    str = str.replace(/\\\[(.*?)\\\]/g, "$1");
    str = str.replace(/\\text\{([^}]+)\}/g, "$1");
    str = str.replace(/\\ce\{([^}]+)\}/g, "$1");
    str = str.replace(/\\mathrm\{([^}]+)\}/g, "$1");

    // Replace LaTeX ^3 or ^{3} with <sup>3</sup>, _2 or _{2} with <sub>2</sub>
    str = str.replace(/\^\{([^}]+)\}/g, "<sup>$1</sup>");
    str = str.replace(/\^([0-9a-zA-Z+-]+)/g, "<sup>$1</sup>");
    str = str.replace(/_\{([^}]+)\}/g, "<sub>$1</sub>");
    str = str.replace(/_([0-9a-zA-Z+-]+)/g, "<sub>$1</sub>");

    // 2. Escape all characters except allowed safe formatting tags
    const escaped = escapeHtml(str);

    // 3. Re-enable safe tags that were escaped
    return escaped
        .replace(/&lt;(\/?)sub&gt;/gi, "<$1sub>")
        .replace(/&lt;(\/?)sup&gt;/gi, "<$1sup>")
        .replace(/&lt;(\/?)b&gt;/gi, "<$1b>")
        .replace(/&lt;(\/?)strong&gt;/gi, "<$1strong>")
        .replace(/&lt;(\/?)i&gt;/gi, "<$1i>")
        .replace(/&lt;(\/?)em&gt;/gi, "<$1em>")
        .replace(/&lt;(\/?)code&gt;/gi, "<$1code>")
        .replace(/&lt;(\/?)p&gt;/gi, "<$1p>")
        .replace(/&lt;br\s*\/?&gt;/gi, "<br>");
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
