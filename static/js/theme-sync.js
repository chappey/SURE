/**
 * Best-effort sync of Canvas brand CSS variables when EasyLearn is embedded
 * in a same-origin Canvas iframe. Falls back silently to static defaults.
 */
(function () {
    function readParentVar(name) {
        var parentRoot = window.parent.document.documentElement;
        var value = window.parent.getComputedStyle(parentRoot).getPropertyValue(name).trim();
        return value || null;
    }

    function applyCanvasBrand() {
        if (window.self === window.top) {
            return;
        }

        var root = document.documentElement;
        var primary =
            readParentVar("--ic-brand-primary") ||
            readParentVar("--ic-brand-button--primary-bgd");
        var link = readParentVar("--ic-link-color");
        var navBg = readParentVar("--ic-brand-global-nav-bgd");

        if (primary) {
            root.style.setProperty("--brand-primary", primary);
            root.style.setProperty("--accent-blue", primary);
            root.style.setProperty("--link-color", link || primary);
        } else if (link) {
            root.style.setProperty("--link-color", link);
            root.style.setProperty("--brand-primary", link);
            root.style.setProperty("--accent-blue", link);
        }

        if (navBg) {
            root.style.setProperty("--nav-bg", navBg);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", applyCanvasBrand);
    } else {
        applyCanvasBrand();
    }
})();
