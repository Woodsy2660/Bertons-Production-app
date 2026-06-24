/**
 * Incremental form saves with offline queue/retry.
 * Readings save per-entry; headers and atomic forms auto-save on change.
 */
(function () {
    "use strict";

    const QUEUE_KEY = "berton_form_save_queue";
    const DEBOUNCE_MS = 900;
    const RETRY_INTERVAL_MS = 30000;

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
                data[el.name] = el.checked ? (el.value || "Y") : "N";
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

    function setStatus(bar, state, message) {
        if (!bar) return;
        bar.dataset.state = state;
        bar.textContent = message;
        bar.hidden = false;
    }

    async function postJson(url, body) {
        const response = await fetch(url, {
            method: "POST",
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
            const detail =
                (payload && (payload.detail || payload.message)) ||
                response.statusText ||
                "Save failed";
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
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

    function appendReadingRow(reading, formType) {
        const tbody = document.getElementById("readings-tbody");
        if (!tbody) return;

        const empty = tbody.querySelector(".readings-empty");
        if (empty) empty.remove();

        const tr = document.createElement("tr");
        let sectionCell = "";
        if (formType === "carton_qc" || formType === "final_pallet_count") {
            sectionCell = `<td class="px-3 py-2">${reading.section || ""}</td>`;
        }

        tr.innerHTML = `
            <td class="px-3 py-2">${reading.sequence}</td>
            <td class="px-3 py-2">${reading.captured_at}</td>
            <td class="px-3 py-2">${reading.operator_identifier}</td>
            ${sectionCell}
            <td class="px-3 py-2 text-[var(--berton-text-muted)]">${reading.summary || ""}</td>
        `;
        tbody.appendChild(tr);

        const countEl = document.getElementById("readings-count");
        if (countEl) {
            const current = parseInt(countEl.textContent, 10) || 0;
            countEl.textContent = String(Math.max(current, reading.sequence));
        }

        const completePanel = document.getElementById("form-complete-panel");
        if (completePanel) completePanel.hidden = false;
    }

    function resetReadingForm(form, keepOperator) {
        const operator = keepOperator
            ? form.querySelector('[name="operator_identifier"]')?.value
            : "";

        form.reset();

        if (keepOperator && operator) {
            const opSelect = form.querySelector('[name="operator_identifier"]');
            if (opSelect) opSelect.value = operator;
        }

        const timeInput = form.querySelector('[name="captured_at"]');
        if (timeInput && !timeInput.value) {
            const now = new Date();
            timeInput.value = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
        }
    }

    function bindReadingForm(form, batchId, formType, bar) {
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
                appendReadingRow(result.reading, formType);
                const countEl = document.getElementById("readings-count");
                if (countEl && result.reading_count) {
                    countEl.textContent = String(result.reading_count);
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

        const save = async () => {
            const body = formToObject(form);
            const payloadKey = JSON.stringify(body);
            if (payloadKey === lastPayload) return;

            const url =
                saveKind === "header"
                    ? `/api/batches/${batchId}/forms/${formType}/header`
                    : `/api/batches/${batchId}/forms/${formType}/draft`;
            const queueId = `${saveKind}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

            setStatus(bar, "saving", "Saving…");

            try {
                await postJson(url, body);
                lastPayload = payloadKey;
                setStatus(bar, "saved", "Saved");
                window.setTimeout(() => {
                    if (bar.dataset.state === "saved") bar.hidden = true;
                }, 1500);
            } catch (err) {
                queueItem({ id: queueId, url, body, type: saveKind });
                setStatus(bar, "queued", "Offline — changes kept locally, will retry");
                updateQueuedCount(bar);
                console.warn("Auto-save failed, queued locally:", err.message);
            }
        };

        const schedule = () => {
            window.clearTimeout(timer);
            timer = window.setTimeout(save, DEBOUNCE_MS);
        };

        form.addEventListener("input", schedule);
        form.addEventListener("change", schedule);

        form.addEventListener("submit", async (event) => {
            if (form.dataset.submitMode === "draft-only") {
                event.preventDefault();
                window.clearTimeout(timer);
                await save();
            }
        });
    }

    function bindSubmitPanel(panel, batchId, formType, bar) {
        panel.addEventListener("submit", async (event) => {
            event.preventDefault();
            setStatus(bar, "saving", "Marking form complete…");

            try {
                await postJson(`/api/batches/${batchId}/forms/${formType}/submit`, {});
                setStatus(bar, "saved", "Form marked complete");
                window.location.href = `/batches/${batchId}`;
            } catch (err) {
                setStatus(bar, "error", `Could not submit — ${err.message}. Try again.`);
            }
        });
    }

    function bindAtomicSubmit(form, batchId, formType, bar) {
        form.addEventListener("submit", async (event) => {
            const submitter = event.submitter;
            const action = submitter?.value || "save";

            if (action !== "submit") return;

            event.preventDefault();
            const body = { ...formToObject(form), action: "submit" };

            setStatus(bar, "saving", "Submitting form…");
            try {
                const result = await postJson(
                    `/api/batches/${batchId}/forms/${formType}/draft`,
                    body
                );
                window.location.href = result.redirect || `/batches/${batchId}`;
            } catch (err) {
                setStatus(bar, "error", `Submit failed — ${err.message}. Your draft is still saved.`);
            }
        });
    }

    function init() {
        const root = document.getElementById("form-save-root");
        if (!root) return;

        const batchId = root.dataset.batchId;
        const formType = root.dataset.formType;
        const bar = document.getElementById("form-save-status");

        document.querySelectorAll("form.js-reading-form").forEach((form) => {
            bindReadingForm(form, batchId, formType, bar);
        });

        document.querySelectorAll("form.js-auto-save-header").forEach((form) => {
            bindAutoSaveForm(form, batchId, formType, "header", bar);
        });

        document.querySelectorAll("form.js-auto-save-draft").forEach((form) => {
            bindAutoSaveForm(form, batchId, formType, "draft", bar);
            bindAtomicSubmit(form, batchId, formType, bar);
        });

        const completePanel = document.getElementById("form-complete-panel");
        if (completePanel) {
            bindSubmitPanel(completePanel, batchId, formType, bar);
        }

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