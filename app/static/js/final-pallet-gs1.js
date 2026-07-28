/**
 * Final Pallet Count — GS1 pallet-label scan prefill.
 *
 * Knox Capture (Parse GS1 on) wedges a bracketed AI string into the "Scan pallet"
 * field and appends Enter. We POST to the server parser and pre-fill editable
 * form fields (pallet #, quantity/high, PRN date). Manual entry remains fully usable.
 */
(function () {
    "use strict";

    const SCAN_INPUT_ID = "final-pallet-gs1-scan";
    const PREFILL_KEYS = ["pallet_no", "high", "prn_date"];

    function $(sel, root) {
        return (root || document).querySelector(sel);
    }

    function setStatus(el, text, state) {
        if (!el) return;
        el.textContent = text || "";
        el.dataset.state = state || "idle";
    }

    function clearScanMarkers(root) {
        root.querySelectorAll(".from-scan").forEach((el) => {
            el.classList.remove("from-scan");
            el.removeAttribute("data-from-scan");
        });
        root.querySelectorAll(".scan-prefill-badge").forEach((el) => el.remove());
    }

    function markFromScan(input) {
        if (!input) return;
        input.classList.add("from-scan");
        input.dataset.fromScan = "1";
        const wrap = input.closest("div");
        if (wrap && !wrap.querySelector(".scan-prefill-badge")) {
            const badge = document.createElement("span");
            badge.className = "scan-prefill-badge prefill-hint";
            badge.textContent = "(from scan)";
            const label = wrap.querySelector("label.berton-label");
            if (label) label.appendChild(badge);
            else wrap.insertBefore(badge, wrap.firstChild);
        }
        // Drop the badge when the operator edits the value
        const onEdit = () => {
            input.classList.remove("from-scan");
            input.removeAttribute("data-from-scan");
            wrap?.querySelector(".scan-prefill-badge")?.remove();
            input.removeEventListener("input", onEdit);
        };
        input.addEventListener("input", onEdit, { once: true });
    }

    function applyPrefill(root, prefill) {
        if (!prefill) return [];
        const filled = [];
        for (const key of PREFILL_KEYS) {
            const value = prefill[key];
            if (value == null || value === "") continue;
            // Fill every matching named input across Bottles + Finished forms
            root.querySelectorAll(`[name="${key}"]`).forEach((input) => {
                if (input.disabled || input.readOnly) return;
                input.value = value;
                try {
                    input.defaultValue = value;
                } catch {
                    /* ignore */
                }
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                markFromScan(input);
                filled.push(key);
            });
        }
        return filled;
    }

    function renderFlags(container, flags) {
        if (!container) return;
        container.innerHTML = "";
        if (!flags || !flags.length) return;

        flags.forEach((flag) => {
            const div = document.createElement("div");
            const level = flag.level || "info";
            div.className =
                level === "error"
                    ? "berton-alert berton-alert-error scan-flag"
                    : level === "warn"
                      ? "berton-alert berton-alert-warn scan-flag"
                      : "berton-alert berton-alert-info scan-flag";
            div.setAttribute("role", "status");
            div.textContent = flag.message || flag.code || "";
            container.appendChild(div);
        });
    }

    function summaryLine(data) {
        const f = data.fields || {};
        const parts = [];
        if (f.pallet_no) parts.push(`Pallet ${f.pallet_no}`);
        if (f.quantity || f.high) parts.push(`Qty ${f.quantity || f.high}`);
        if (f.batch) parts.push(`Batch ${f.batch}`);
        if (f.prn_date) parts.push(`Date ${f.prn_date}`);
        return parts.length ? parts.join(" · ") : "Scan parsed";
    }

    async function parseScan(batchId, raw) {
        const res = await fetch(
            `/api/batches/${batchId}/forms/final_pallet_count/gs1-scan`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                },
                credentials: "same-origin",
                body: JSON.stringify({ raw }),
            }
        );
        let data = null;
        try {
            data = await res.json();
        } catch {
            data = null;
        }
        if (!res.ok) {
            const detail =
                (data && (data.detail || data.message)) ||
                `Scan parse failed (${res.status})`;
            throw new Error(
                typeof detail === "string" ? detail : JSON.stringify(detail)
            );
        }
        return data;
    }

    function bind(root) {
        const input = document.getElementById(SCAN_INPUT_ID);
        if (!input || input.dataset.gs1Bound === "1") return;
        input.dataset.gs1Bound = "1";

        const batchId = root.dataset.batchId;
        if (!batchId) return;

        const statusEl = $(".js-final-pallet-scan-status", root);
        const flagsEl = $(".js-final-pallet-scan-flags", root);
        let lastRaw = "";
        let inFlight = false;

        const run = async (raw) => {
            const text = (raw || "").trim();
            if (!text || text === lastRaw || inFlight) return;
            inFlight = true;
            lastRaw = text;
            setStatus(statusEl, "Parsing scan…", "ready");
            clearScanMarkers(document.getElementById("form-save-root") || document);

            try {
                const data = await parseScan(batchId, text);
                if (!data.ok && (!data.ais || !Object.keys(data.ais).length)) {
                    renderFlags(flagsEl, data.flags || []);
                    setStatus(
                        statusEl,
                        (data.flags && data.flags[0] && data.flags[0].message) ||
                            "Could not read scan",
                        "error"
                    );
                    return;
                }

                const formRoot =
                    document.getElementById("form-save-root") || document;
                const filled = applyPrefill(formRoot, data.prefill || {});
                renderFlags(flagsEl, data.flags || []);

                if (filled.length) {
                    setStatus(statusEl, summaryLine(data), "scanned");
                } else {
                    setStatus(
                        statusEl,
                        "Scan read but no form fields filled — check flags below",
                        "error"
                    );
                }

                // Clear wedge buffer so the next scan can replace it cleanly
                input.select();
            } catch (err) {
                console.warn("[final-pallet-gs1]", err);
                setStatus(
                    statusEl,
                    err.message || "Could not parse scan",
                    "error"
                );
                renderFlags(flagsEl, [
                    {
                        level: "error",
                        code: "request_failed",
                        message: err.message || "Could not parse scan",
                    },
                ]);
                lastRaw = "";
            } finally {
                inFlight = false;
            }
        };

        // Knox wedge ends with Enter
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                ev.preventDefault();
                run(input.value);
            }
        });

        // Fallback: paste or change without Enter
        input.addEventListener("change", () => run(input.value));

        // Focus styling hint
        input.addEventListener("focus", () => {
            if (statusEl && statusEl.dataset.state === "idle") {
                setStatus(statusEl, "Ready — press scanner trigger", "ready");
            }
        });
    }

    function init() {
        const root = document.querySelector(".js-final-pallet-scan-card");
        if (!root) return;
        bind(root);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
