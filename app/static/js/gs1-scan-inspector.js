/**
 * GS1 Scan Inspector — diagnostic only (/debug/scan-inspector).
 * Isolated from production forms. Stores structured prefill candidates in sessionStorage.
 */
(function () {
    "use strict";

    const HISTORY_KEY = "berton_gs1_inspector_history";
    const PREFILL_KEY = "berton_gs1_prefill_candidates";
    const MAX_HISTORY = 30;

    const SAMPLE_HUMAN =
        "(02)09331288015587(11)260501(10)6121(37)504(90)16211646";

    function $(id) {
        return document.getElementById(id);
    }

    function loadHistory() {
        try {
            return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || "[]");
        } catch {
            return [];
        }
    }

    function saveHistory(items) {
        sessionStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
    }

    function storePrefill(prefill, meta) {
        const payload = {
            ...prefill,
            captured_at: new Date().toISOString(),
            source: meta || {},
        };
        sessionStorage.setItem(PREFILL_KEY, JSON.stringify(payload));
        // Also keep a short list of recent candidate snapshots for comparison
        try {
            const listKey = PREFILL_KEY + "_list";
            const list = JSON.parse(sessionStorage.getItem(listKey) || "[]");
            list.unshift(payload);
            sessionStorage.setItem(listKey, JSON.stringify(list.slice(0, MAX_HISTORY)));
        } catch {
            /* ignore */
        }
        return payload;
    }

    function escapeHtml(s) {
        return String(s ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function renderVisibleRaw(raw) {
        const visible = window.GS1Parse.formatRawVisible(raw);
        // Highlight <GS> markers
        return escapeHtml(visible).replace(
            /&lt;GS&gt;/g,
            '<span class="gs-mark">&lt;GS&gt;</span>'
        );
    }

    function renderResult(entry) {
        const panel = $("gs1-result-panel");
        if (!panel || !entry) return;
        panel.hidden = false;

        const d = entry.detailed;
        $("gs1-raw-length").textContent = String(d.length ?? 0);
        $("gs1-parse-mode").textContent = d.mode || "—";
        $("gs1-symbology").textContent = entry.symbology || "not reported";
        $("gs1-raw-visible").innerHTML = renderVisibleRaw(d.rawExact);
        $("gs1-raw-hex").textContent = window.GS1Parse.formatRawHex(d.rawExact);
        $("gs1-raw-json").textContent = JSON.stringify(d.rawExact);
        $("gs1-prefill-json").textContent = JSON.stringify(entry.prefillStored || d.prefillCandidates, null, 2);

        const tbody = $("gs1-ai-tbody");
        tbody.innerHTML = "";
        if (!d.fields || !d.fields.length) {
            tbody.innerHTML =
                '<tr><td colspan="6" class="text-muted">No Application Identifiers parsed.</td></tr>';
        } else {
            for (const f of d.fields) {
                const tr = document.createElement("tr");
                const notes = [];
                if (!f.known) notes.push("unknown / unlisted AI");
                if (f.notes) notes.push(f.notes);
                if (f.lengthMode === "fixed" && f.expectedLength != null) {
                    const actual = String(f.rawValue ?? "").length;
                    if (actual !== f.expectedLength) {
                        notes.push(`length ${actual} ≠ expected ${f.expectedLength}`);
                    }
                }
                tr.innerHTML = `
                    <td><code>${escapeHtml(f.ai)}</code></td>
                    <td>${escapeHtml(f.name)}</td>
                    <td><code>${escapeHtml(f.rawValue)}</code></td>
                    <td>${escapeHtml(String(f.interpreted ?? ""))}</td>
                    <td>${escapeHtml(f.lengthMode || "—")}</td>
                    <td class="${!f.known ? "flag-error" : ""}">${escapeHtml(notes.join("; ") || "—")}</td>
                `;
                tbody.appendChild(tr);
            }
        }

        const leftoverEl = $("gs1-leftover");
        if (d.leftover) {
            leftoverEl.hidden = false;
            leftoverEl.textContent = `Leftover / unconsumed characters: ${JSON.stringify(d.leftover)}`;
        } else {
            leftoverEl.hidden = true;
            leftoverEl.textContent = "";
        }

        const unknown = (d.fields || []).filter((f) => !f.known);
        const unkEl = $("gs1-unknown");
        if (unknown.length) {
            unkEl.hidden = false;
            unkEl.textContent =
                "Unknown or unlisted AIs: " + unknown.map((f) => f.ai).join(", ");
        } else {
            unkEl.hidden = true;
        }

        renderHistory();
    }

    function renderHistory() {
        const box = $("gs1-history");
        const empty = $("gs1-history-empty");
        if (!box) return;
        const items = loadHistory();
        // Keep empty node; rebuild list items
        box.querySelectorAll(".history-item").forEach((el) => el.remove());
        if (!items.length) {
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        items.forEach((item, index) => {
            const el = document.createElement("div");
            el.className = "history-item" + (index === 0 ? " active" : "");
            const vis = window.GS1Parse.formatRawVisible(item.raw).slice(0, 80);
            const n = Object.keys(item.prefillStored?.candidates || {}).length;
            el.innerHTML = `
                <div class="flex flex-wrap justify-between gap-2">
                    <strong>#${items.length - index}</strong>
                    <span class="text-muted text-sm">${escapeHtml(item.at || "")}</span>
                </div>
                <code class="text-sm">${escapeHtml(vis)}${item.raw.length > 80 ? "…" : ""}</code>
                <p class="text-sm text-muted mt-1">
                    ${item.detailed?.fields?.length || 0} AI(s) ·
                    ${n} prefill field(s) ·
                    ${escapeHtml(item.symbology || "symbology n/a")}
                </p>
            `;
            el.addEventListener("click", () => renderResult(item));
            box.appendChild(el);
        });
    }

    function processRaw(raw, meta) {
        if (!window.GS1Parse?.parseGS1Detailed) {
            console.error("GS1Parse not loaded");
            return;
        }
        const detailed = window.GS1Parse.parseGS1Detailed(raw);
        const prefillStored = storePrefill(detailed.prefillCandidates, {
            symbology: meta?.symbology || null,
            mode: detailed.mode,
        });
        const entry = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            at: new Date().toISOString(),
            raw: detailed.rawExact,
            symbology: meta?.symbology || null,
            detailed,
            prefillStored,
        };
        const hist = loadHistory();
        hist.unshift(entry);
        saveHistory(hist);
        renderResult(entry);
        return entry;
    }

    function init() {
        const root = $("gs1-inspector-root");
        if (!root) return;

        // Sample Orora-style human-readable string from the SPEC
        $("gs1-sample-btn")?.addEventListener("click", () => {
            $("gs1-paste-input").value = SAMPLE_HUMAN;
            processRaw(SAMPLE_HUMAN, { symbology: "sample (human-readable)" });
        });

        $("gs1-parse-btn")?.addEventListener("click", () => {
            const raw = $("gs1-paste-input")?.value ?? "";
            processRaw(raw, { symbology: "manual paste" });
        });

        $("gs1-clear-history-btn")?.addEventListener("click", () => {
            sessionStorage.removeItem(HISTORY_KEY);
            renderHistory();
            $("gs1-result-panel").hidden = true;
        });

        // Capture camera / scanner events from barcode-scan.js without filling production fields
        document.addEventListener("barcode-scanned", (ev) => {
            const detail = ev.detail || {};
            // Prefer full raw; fall back to value
            const raw = detail.raw != null ? detail.raw : detail.value;
            if (raw == null || raw === "") return;
            // Only handle events from our debug input
            const input = $("gs1-scan-input");
            if (detail.inputId && detail.inputId !== "gs1-scan-input") return;
            // barcode-scan may not set inputId — accept if focus is our field or always on this page
            processRaw(String(raw), {
                symbology: detail.symbology || detail.format || "scanner",
            });
            if ($("gs1-paste-input")) {
                $("gs1-paste-input").value = String(raw);
            }
        });

        // Also intercept when the bound scan input is filled (wedge scanners)
        const scanInput = $("gs1-scan-input");
        if (scanInput) {
            scanInput.addEventListener("change", () => {
                if (scanInput.value) {
                    processRaw(scanInput.value, { symbology: "scan field change" });
                }
            });
        }

        renderHistory();
        const hist = loadHistory();
        if (hist[0]) renderResult(hist[0]);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
