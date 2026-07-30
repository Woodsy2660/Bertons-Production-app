/**
 * Incremental form saves with offline queue/retry.
 * Readings save per-entry; headers and atomic forms auto-save on change.
 */
(function () {
    "use strict";

    const QUEUE_KEY = "berton_form_save_queue";
    const DEBOUNCE_MS = 900;
    const RETRY_INTERVAL_MS = 30000;
    const DEFAULT_PREVIEW_LIMIT = 5;

    function getQueue() {
        try {
            return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
        } catch {
            return [];
        }
    }

    function setQueue(items) {
        localStorage.setItem(QUEUE_KEY, JSON.stringify(items));
    }

    function formToObject(form) {
        const data = {};
        const multi = {};

        for (const el of form.elements) {
            if (!el.name || el.disabled) continue;
            if (el.type === "submit" || el.type === "button") continue;

            if (el.type === "checkbox") {
                // Multi-select enums use name="field[]" and only checked values
                if (el.name.endsWith("[]")) {
                    const key = el.name.slice(0, -2);
                    if (!multi[key]) multi[key] = [];
                    if (el.checked && el.value !== "") multi[key].push(el.value);
                } else {
                    data[el.name] = el.checked ? (el.value || "Y") : "N";
                }
            } else if (el.type === "radio") {
                if (el.checked) data[el.name] = el.value;
            } else if (el.name.endsWith("[]")) {
                const key = el.name.slice(0, -2);
                if (!multi[key]) multi[key] = [];
                if (el.value !== "") multi[key].push(el.value);
            } else {
                data[el.name] = el.value;
            }
        }

        for (const [key, values] of Object.entries(multi)) {
            data[key] = values;
        }
        return data;
    }

    // Routine mid-edit save feedback is suppressed — operators already know forms auto-save.
    // Only offline queue / hard errors (and submit failures) surface the status bar.
    const QUIET_STATUS_MESSAGES = new Set([
        "Saving…",
        "Saving...",
        "Saved",
        "Saving entry…",
        "Saving entry...",
        "Entry saved",
        "Retrying saved entries…",
        "Retrying saved entries...",
        "All queued entries saved — refreshing…",
        "All queued entries saved - refreshing…",
        "Form marked complete",
        "Marking form complete…",
        "Marking form complete...",
    ]);

    function setStatus(bar, state, message) {
        if (!bar) return;
        if (state === "saved" || state === "saving" || QUIET_STATUS_MESSAGES.has(message)) {
            // Keep quiet for normal progress; clear any leftover banner.
            if (bar.dataset.state === "saved" || bar.dataset.state === "saving" || bar.dataset.state === "idle") {
                bar.hidden = true;
                bar.dataset.state = "idle";
                bar.textContent = "";
            }
            return;
        }
        bar.dataset.state = state;
        bar.textContent = message;
        bar.hidden = false;
    }

    /** User-facing fault only — strip status codes and technical wrappers. */
    function formatUserError(detail, fallback) {
        let msg = "";
        if (typeof detail === "string") {
            msg = detail;
        } else if (Array.isArray(detail)) {
            // FastAPI validation error list
            msg = detail
                .map((item) => {
                    if (typeof item === "string") return item;
                    if (item && item.msg) {
                        const loc = Array.isArray(item.loc)
                            ? item.loc.filter((p) => p !== "body").join(" ")
                            : "";
                        return loc ? `${loc}: ${item.msg}` : item.msg;
                    }
                    return "";
                })
                .filter(Boolean)
                .join("; ");
        } else if (detail && typeof detail === "object" && detail.msg) {
            msg = String(detail.msg);
        } else if (detail != null) {
            msg = String(detail);
        }

        msg = msg
            .replace(/^Failed to (save draft|save form|submit form|add reading|save header|delete entry):\s*/i, "")
            .replace(/^HTTPException[:\s]*/i, "")
            .replace(/^\d{3}:\s*/, "")
            .replace(/^Error:\s*/i, "")
            .trim();

        // Field key → readable (fallback if server still sends raw keys)
        msg = msg
            .replace(/\binitials is required\b/i, "Signature / initials is required")
            .replace(/\boperator_identifier is required\b/i, "Operator is required");

        return msg || fallback || "Something went wrong";
    }

    async function postJson(url, body) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
            },
            body: JSON.stringify(body),
        });

        let payload = null;
        try {
            payload = await response.json();
        } catch {
            payload = null;
        }

        if (!response.ok) {
            const raw =
                (payload && (payload.detail !== undefined ? payload.detail : payload.message)) ||
                null;
            throw new Error(formatUserError(raw, "Something went wrong"));
        }
        return payload;
    }

    function queueItem(item) {
        const queue = getQueue();
        queue.push({ ...item, queuedAt: Date.now() });
        setQueue(queue);
    }

    function removeQueueItem(id) {
        setQueue(getQueue().filter((item) => item.id !== id));
    }

    function updateQueuedCount(bar) {
        const count = getQueue().length;
        const badge = document.getElementById("save-queue-count");
        if (badge) {
            badge.textContent = count ? String(count) : "";
            badge.hidden = count === 0;
        }
        if (count > 0 && bar && bar.dataset.state !== "saving") {
            setStatus(bar, "queued", `${count} saved locally — will retry when online`);
        }
    }

    async function replayQueue(bar) {
        const queue = getQueue();
        if (!queue.length) {
            updateQueuedCount(bar);
            return;
        }

        setStatus(bar, "saving", "Retrying saved entries…");
        let remaining = [];

        for (const item of queue) {
            try {
                await postJson(item.url, item.body);
                removeQueueItem(item.id);
            } catch {
                remaining.push(item);
            }
        }

        if (remaining.length) {
            setStatus(
                bar,
                "queued",
                `${remaining.length} still waiting — will keep retrying`
            );
        } else if (queue.length) {
            setStatus(bar, "saved", "All queued entries saved — refreshing…");
            window.setTimeout(() => window.location.reload(), 800);
        }
        updateQueuedCount(bar);
    }

    function getPreviewLimit(root) {
        const raw = root?.dataset.readingsPreviewLimit;
        const parsed = parseInt(raw || "", 10);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_PREVIEW_LIMIT;
    }

    function hasSectionColumn(formType) {
        return formType === "carton_qc" || formType === "final_pallet_count";
    }

    function buildDeleteCell(canDelete, readingId, batchId, formType) {
        if (!canDelete) return "";
        const redirectTo = window.location.pathname;
        return `<td class="px-2 py-2 text-right w-12">
            <form method="POST"
                  action="/batches/${batchId}/forms/${formType}/readings/${readingId}/delete"
                  class="reading-delete-form inline-flex"
                  onsubmit="return confirm('Delete this entry?');">
                <input type="hidden" name="redirect_to" value="${redirectTo}">
                <button type="submit"
                        class="btn-icon-x"
                        aria-label="Delete entry"
                        title="Delete entry">&times;</button>
            </form>
        </td>`;
    }

    function buildReadingRow(reading, formType, canDelete, batchId) {
        let sectionCell = "";
        if (hasSectionColumn(formType)) {
            sectionCell = `<td class="px-3 py-2">${reading.section || ""}</td>`;
        }

        return `
            <tr data-reading-id="${reading.id}" data-sequence="${reading.sequence}">
                <td class="px-3 py-2">${reading.sequence}</td>
                <td class="px-3 py-2">${reading.captured_at}</td>
                <td class="px-3 py-2">${reading.operator_identifier}</td>
                ${sectionCell}
                <td class="px-3 py-2 text-[var(--berton-text-muted)]">${reading.summary || ""}</td>
                ${buildDeleteCell(canDelete, reading.id, batchId, formType)}
            </tr>
        `;
    }

    function updateReadingsCount(count) {
        const countEl = document.getElementById("readings-count");
        if (countEl) countEl.textContent = String(count);
    }

    function updateShowAllLink(count, batchId, formType, previewLimit) {
        const link = document.getElementById("readings-show-all");
        if (!link) return;

        if (count > previewLimit) {
            link.hidden = false;
            link.textContent = `Show all (${count})`;
            link.href = `/batches/${batchId}/forms/${formType}/entries`;
        } else {
            link.hidden = true;
        }
    }

    function updateCompletePanel(count) {
        const hint = document.getElementById("form-complete-hint");
        const form = document.getElementById("form-complete-form");
        const submitBtn = form?.querySelector('[type="submit"]');
        const hasEntries = count > 0;

        if (hint) hint.hidden = hasEntries;
        if (submitBtn) submitBtn.disabled = !hasEntries;
    }

    function trimPreviewRows(tbody, previewLimit) {
        const rows = Array.from(tbody.querySelectorAll("tr[data-reading-id]"));
        while (rows.length > previewLimit) {
            rows.shift()?.remove();
        }
    }

    function appendReadingRow(reading, formType, canDelete, previewLimit, batchId) {
        const tbody = document.getElementById("readings-tbody");
        if (!tbody) return;

        const empty = tbody.querySelector(".readings-empty");
        if (empty) empty.remove();

        tbody.insertAdjacentHTML("beforeend", buildReadingRow(reading, formType, canDelete, batchId));
        trimPreviewRows(tbody, previewLimit);
    }

    /**
     * Fields that carry across successive "Add entry" submissions until the
     * operator changes them. Includes:
     * - Named barcode/batch fields
     * - Yes/No and Y/N/NA selects (marked data-sticky-reading, or auto-detected)
     */
    const STICKY_READING_FIELDS = new Set([
        "batch_number_pallet_tag",
        "batch_number",
        "label_inkjet_lot", // Finished product line check — lot usually same for the run
        "prn_date", // Final pallet count bottles
        "pallet_no", // Final pallet count bottles
    ]);

    const YN_VALUES = new Set(["Y", "N", "NA", "YES", "NO", "N/A"]);

    function isYesNoSelect(el) {
        if (!el || el.tagName !== "SELECT") return false;
        const vals = Array.from(el.options)
            .map((o) => String(o.value || "").trim())
            .filter(Boolean);
        if (!vals.length) return false;
        return vals.every((v) => YN_VALUES.has(v.toUpperCase()));
    }

    function setControlValue(el, value) {
        if (!el) return;
        if (el.tagName === "SELECT") {
            el.value = value;
            // Keep form.reset() restoring this sticky value next time
            Array.from(el.options).forEach((opt) => {
                opt.defaultSelected = opt.value === value;
            });
            return;
        }
        el.value = value;
        try {
            el.defaultValue = value;
        } catch {
            /* ignore */
        }
    }

    function captureStickyReadingValues(form) {
        const sticky = {};

        const remember = (el) => {
            if (!el || !el.name || el.disabled) return;
            // Skip multi-value checkbox groups (name ends with [])
            if (el.name.endsWith("[]")) return;
            sticky[el.name] = el.value;
        };

        for (const name of STICKY_READING_FIELDS) {
            remember(form.querySelector(`[name="${name}"]`));
        }

        form.querySelectorAll("[data-sticky-reading]").forEach(remember);

        // Safety net: any Yes/No(/NA) select on the reading form
        form.querySelectorAll("select").forEach((el) => {
            if (sticky[el.name] !== undefined) return;
            if (isYesNoSelect(el)) remember(el);
        });

        return sticky;
    }

    function restoreStickyReadingValues(form, sticky) {
        for (const [name, value] of Object.entries(sticky || {})) {
            const el = form.querySelector(`[name="${name}"]`);
            if (!el) continue;
            setControlValue(el, value);
        }
    }

    function resetReadingForm(form, keepOperator) {
        const operator = keepOperator
            ? form.querySelector('[name="operator_identifier"]')?.value
            : "";
        const sticky = captureStickyReadingValues(form);

        form.reset();

        if (keepOperator && operator) {
            const opSelect = form.querySelector('[name="operator_identifier"]');
            if (opSelect) opSelect.value = operator;
        }

        restoreStickyReadingValues(form, sticky);

        const timeInput = form.querySelector('[name="captured_at"]');
        if (timeInput && !timeInput.value) {
            const now = new Date();
            timeInput.value = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
        }
    }

    function bindReadingForm(form, batchId, formType, bar, canDelete, previewLimit) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();

            if (!form.reportValidity()) return;

            const body = formToObject(form);
            const url = `/api/batches/${batchId}/forms/${formType}/readings`;
            const queueId = `reading-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

            setStatus(bar, "saving", "Saving entry…");
            const submitBtn = form.querySelector('[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;

            try {
                const result = await postJson(url, body);
                setStatus(bar, "saved", "Entry saved");
                appendReadingRow(result.reading, formType, canDelete, previewLimit, batchId);
                if (result.reading_count != null) {
                    updateReadingsCount(result.reading_count);
                    updateShowAllLink(result.reading_count, batchId, formType, previewLimit);
                    updateCompletePanel(result.reading_count);
                }
                resetReadingForm(form, true);
                window.setTimeout(() => {
                    if (bar.dataset.state === "saved") bar.hidden = true;
                }, 2000);
            } catch (err) {
                queueItem({ id: queueId, url, body, type: "reading" });
                setStatus(
                    bar,
                    "queued",
                    "Could not reach server — entry kept on this device and queued for retry"
                );
                updateQueuedCount(bar);
                console.warn("Reading save failed, queued locally:", err.message);
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    }

    function bindAutoSaveForm(form, batchId, formType, saveKind, bar) {
        let timer = null;
        let lastPayload = "";
        let inFlight = null;

        const save = async () => {
            const body = formToObject(form);
            const payloadKey = JSON.stringify(body);
            if (payloadKey === lastPayload) return;

            const url =
                saveKind === "header"
                    ? `/api/batches/${batchId}/forms/${formType}/header`
                    : `/api/batches/${batchId}/forms/${formType}/draft`;
            const queueId = `${saveKind}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

            // Quiet on success — static copy already tells operators forms auto-save.
            // Only surface the status bar for offline queue / errors.
            const run = (async () => {
                try {
                    await postJson(url, body);
                    lastPayload = payloadKey;
                    // Clear a previous offline notice once a save succeeds again
                    if (bar && bar.dataset.state === "queued") {
                        bar.hidden = true;
                        bar.dataset.state = "idle";
                        bar.textContent = "";
                    }
                } catch (err) {
                    queueItem({ id: queueId, url, body, type: saveKind });
                    setStatus(bar, "queued", "Offline — changes kept locally, will retry");
                    updateQueuedCount(bar);
                    console.warn("Auto-save failed, queued locally:", err.message);
                }
            })();
            inFlight = run;
            try {
                await run;
            } finally {
                if (inFlight === run) inFlight = null;
            }
        };

        const schedule = (immediate) => {
            window.clearTimeout(timer);
            if (immediate) {
                timer = null;
                save();
                return;
            }
            timer = window.setTimeout(save, DEBOUNCE_MS);
        };

        form.addEventListener("input", () => schedule(false));
        form.addEventListener("change", (event) => {
            // Checkboxes (e.g. Filters used multi-select) save immediately so
            // navigating away before the debounce window does not drop values.
            const t = event.target;
            const isCheck =
                t &&
                (t.type === "checkbox" ||
                    (t.name && String(t.name).endsWith("[]")));
            schedule(Boolean(isCheck));
        });

        // Flush pending debounced save when leaving the page
        const flush = () => {
            if (timer) {
                window.clearTimeout(timer);
                timer = null;
                save();
            }
        };
        window.addEventListener("pagehide", flush);
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") flush();
        });

        form.addEventListener("submit", async (event) => {
            if (form.dataset.submitMode === "draft-only") {
                event.preventDefault();
                window.clearTimeout(timer);
                await save();
            }
        });
    }

    function bindSubmitPanel(batchId, formType, bar) {
        const form = document.getElementById("form-complete-form");
        if (!form) return;

        form.addEventListener("submit", async (event) => {
            event.preventDefault();

            const submitBtn = form.querySelector('[type="submit"]');
            if (submitBtn?.disabled) return;

            setStatus(bar, "saving", "Marking form complete…");

            try {
                await postJson(`/api/batches/${batchId}/forms/${formType}/submit`, {});
                setStatus(bar, "saved", "Form marked complete");
                window.location.href = `/batches/${batchId}`;
            } catch (err) {
                setStatus(bar, "error", formatUserError(err.message, "Could not complete form"));
            }
        });
    }

    function bindAtomicSubmit(form, batchId, formType, bar) {
        form.addEventListener("submit", async (event) => {
            const submitter = event.submitter;
            const action = submitter?.value || "save";

            if (action !== "submit") return;

            // Pick list: require operator to confirm stock codes before complete
            if (formType === "pick_list") {
                const stockCheck = form.querySelector("#pick_list_stock_checked");
                if (stockCheck && !stockCheck.checked) {
                    event.preventDefault();
                    stockCheck.focus();
                    setStatus(
                        bar,
                        "error",
                        "Check the Stock Item codes and tick the confirmation box before completing."
                    );
                    return;
                }
                const confirmed = window.confirm(
                    "Please confirm each Stock Item code is correct.\n\n" +
                        "If extraction from the work order was wrong, edit the code first, then complete."
                );
                if (!confirmed) {
                    event.preventDefault();
                    return;
                }
            }

            event.preventDefault();
            const body = { ...formToObject(form), action: "submit" };
            // Confirmation checkbox is UI-only — not stored on the form payload
            delete body.stock_codes_checked;

            setStatus(bar, "saving", "Marking form complete…");
            try {
                const result = await postJson(
                    `/api/batches/${batchId}/forms/${formType}/draft`,
                    body
                );
                window.location.href = result.redirect || `/batches/${batchId}`;
            } catch (err) {
                setStatus(bar, "error", formatUserError(err.message, "Could not complete form"));
            }
        });
    }

    function init() {
        const root = document.getElementById("form-save-root");
        if (!root) return;

        const batchId = root.dataset.batchId;
        const formType = root.dataset.formType;
        const bar = document.getElementById("form-save-status");
        const canDelete = root.dataset.canDeleteReadings === "true";
        const previewLimit = getPreviewLimit(root);

        document.querySelectorAll("form.js-reading-form").forEach((form) => {
            bindReadingForm(form, batchId, formType, bar, canDelete, previewLimit);
        });

        document.querySelectorAll("form.js-auto-save-header").forEach((form) => {
            bindAutoSaveForm(form, batchId, formType, "header", bar);
        });

        document.querySelectorAll("form.js-auto-save-draft").forEach((form) => {
            bindAutoSaveForm(form, batchId, formType, "draft", bar);
            bindAtomicSubmit(form, batchId, formType, bar);
        });

        bindSubmitPanel(batchId, formType, bar);

        updateQueuedCount(bar);
        replayQueue(bar);

        window.addEventListener("online", () => replayQueue(bar));
        window.setInterval(() => {
            if (getQueue().length) replayQueue(bar);
        }, RETRY_INTERVAL_MS);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();