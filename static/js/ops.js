(function () {
    const $ = (id) => document.getElementById(id);

    function usd(n) {
        if (n === null || n === undefined || Number.isNaN(Number(n))) return "n/a";
        return "$" + Number(n).toFixed(4);
    }

    function when(ts) {
        if (!ts) return "—";
        const d = new Date(ts * 1000);
        return d.toLocaleString();
    }

    function pill(status) {
        const cls = status === "down" ? "pill-down" : status === "degraded" ? "pill-degraded" : "pill-up";
        return `<span class="pill ${cls}">${status}</span>`;
    }

    function bar(used, limit) {
        if (!limit) return "";
        const pct = Math.min(100, (used / limit) * 100);
        const cls = pct >= 100 ? "crit" : pct >= 80 ? "warn" : "";
        return `<div class="bar ${cls}"><span style="width:${pct.toFixed(1)}%"></span></div>`;
    }

    function render(data) {
        $("ops-updated").textContent = "Updated " + when(data.generated_at) + " · auto-refresh 15s";

        const b = data.budgets || {};
        const today = data.today || {};
        const week = data.week || {};
        $("ops-stats").innerHTML = [
            ["Spend today", usd(today.spend_usd), bar(today.spend_usd, b.global_spend_limit_usd) +
                `<div class="sub">cap ${usd(b.global_spend_limit_usd)}</div>`],
            ["Spend 7d", usd(week.spend_usd), `<div class="sub">${week.calls || 0} calls</div>`],
            ["Calls today", String(today.calls || 0), bar(today.calls, b.global_call_limit) +
                `<div class="sub">cap ${b.global_call_limit}</div>`],
            ["Failures today", String(today.failures || 0), `<div class="sub">${today.successes || 0} ok</div>`],
            ["Tokens today", Number(today.tokens || 0).toLocaleString(), ""],
        ].map(([label, value, extra]) =>
            `<div class="ops-stat"><div class="label">${label}</div><div class="value">${value}</div>${extra || ""}</div>`
        ).join("");

        const or = data.openrouter || {};
        if (!or.configured) {
            $("ops-openrouter").textContent = "OPENROUTER_API_KEY is not set.";
        } else if (or.ok) {
            const rem = or.limit_remaining;
            const lim = or.limit;
            const rawLabel = String(or.label || "API key");
            const label = rawLabel.startsWith("sk-") ? "API key" : rawLabel;
            $("ops-openrouter").innerHTML =
                `<strong>${escapeHtml(label)}</strong>` +
                (or.is_free_tier ? " · free tier" : " · paid") +
                `<div>Used ${usd(or.usage)} · remaining ${usd(rem)}` +
                (lim != null ? ` of ${usd(lim)}` : "") +
                `</div>` +
                bar(typeof rem === "number" && typeof lim === "number" ? (lim - rem) : 0, lim || 0);
        } else {
            $("ops-openrouter").innerHTML =
                `<span class="pill pill-down">unreachable</span> ${or.error || ""}`;
        }

        const users = data.spend_by_user || [];
        $("ops-users").innerHTML = users.length
            ? users.map((u) => `<tr>
                <td>${escapeHtml(u.user_name || u.user_id || "unknown")}<div class="ops-muted">${escapeHtml(u.user_id || "")}</div></td>
                <td class="num">${u.calls}</td>
                <td class="num">${u.failures}</td>
                <td class="num">${Number(u.tokens || 0).toLocaleString()}</td>
                <td class="num">${usd(u.spend_usd)}</td>
              </tr>`).join("")
            : `<tr><td colspan="5" class="ops-muted">No LLM calls recorded today.</td></tr>`;

        const weekModels = {};
        (data.spend_by_model || []).forEach((m) => { weekModels[m.model_id] = m; });
        $("ops-models").innerHTML = (data.models || []).map((m) => {
            const w = weekModels[m.id] || {};
            return `<tr>
                <td>${escapeHtml(m.label)}<div class="ops-muted">${escapeHtml(m.model)}</div></td>
                <td>${pill(m.status)}</td>
                <td class="num">${w.calls || 0}</td>
                <td class="num">${w.failures || 0}</td>
                <td class="num">${usd(w.spend_usd)}</td>
                <td>${escapeHtml(m.last_error || "")}</td>
              </tr>`;
        }).join("");

        $("ops-calls").innerHTML = (data.recent_calls || []).map((c) => `<tr>
            <td>${when(c.ts)}</td>
            <td>${escapeHtml(c.user_name || c.user_id || "—")}</td>
            <td>${escapeHtml(c.purpose || "")}</td>
            <td>${escapeHtml(c.model_id || c.model || "")}</td>
            <td>${c.success ? '<span class="pill pill-ok">ok</span>' : '<span class="pill pill-fail">fail</span>'}</td>
            <td class="num">${c.latency_ms != null ? Math.round(c.latency_ms) : "—"}</td>
            <td class="num">${usd(c.cost_usd)}</td>
          </tr>`).join("") || `<tr><td colspan="7" class="ops-muted">No calls yet.</td></tr>`;

        const limits = data.limits || {};
        $("ops-alert-config").textContent = limits.alert_webhook_configured
            ? "Webhook configured. Duplicate events are coalesced for ALERT_MIN_INTERVAL_SECONDS."
            : "ALERT_WEBHOOK_URL is not set — events are logged and stored but not pushed.";

        $("ops-alerts").innerHTML = (data.recent_alerts || []).map((a) =>
            `<li><div class="when">${when(a.ts)} · ${escapeHtml(a.severity)} · ${escapeHtml(a.kind)}</div>${escapeHtml(a.message)}</li>`
        ).join("") || `<li class="ops-muted">No alerts yet.</li>`;

        $("ops-limits").innerHTML = [
            ["Generate / min / user", limits.generate_per_min],
            ["Feedback / min / user", limits.feedback_per_min],
            ["User daily spend", usd(limits.user_daily_spend_usd)],
            ["Global daily spend", usd(limits.global_daily_spend_usd)],
            ["User daily LLM calls", limits.user_daily_llm_calls],
            ["Global daily LLM calls", limits.global_daily_llm_calls],
            ["Circuit failures to open", limits.circuit_failures],
            ["Circuit open (seconds)", limits.circuit_open_seconds],
        ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    async function load() {
        const res = await fetch("/ops/api/overview", { credentials: "same-origin" });
        if (res.status === 401) {
            window.location = "/ops/login";
            return;
        }
        if (!res.ok) throw new Error("overview " + res.status);
        render(await res.json());
    }

    $("ops-refresh").addEventListener("click", () => load().catch((e) => {
        $("ops-updated").textContent = "Refresh failed: " + e.message;
    }));
    load().catch((e) => { $("ops-updated").textContent = "Load failed: " + e.message; });
    setInterval(() => load().catch(() => {}), 15000);
})();
