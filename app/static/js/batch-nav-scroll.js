/**
 * Remember scroll position on the run detail page when opening a form,
 * then restore it when returning (back link, cancel, or mark complete).
 */
(function () {
    "use strict";

    const SCROLL_KEY_PREFIX = "berton-batch-scroll-";

    function scrollKey(batchId) {
        return `${SCROLL_KEY_PREFIX}${batchId}`;
    }

    function saveScroll(batchId) {
        if (!batchId) return;
        sessionStorage.setItem(scrollKey(batchId), String(window.scrollY));
    }

    function restoreScroll(batchId) {
        if (!batchId) return;

        const raw = sessionStorage.getItem(scrollKey(batchId));
        if (raw == null) return;

        const y = Number.parseInt(raw, 10);
        if (!Number.isFinite(y)) {
            sessionStorage.removeItem(scrollKey(batchId));
            return;
        }

        const apply = () => window.scrollTo(0, y);
        apply();
        requestAnimationFrame(apply);
        window.setTimeout(apply, 50);
        window.setTimeout(apply, 200);
        sessionStorage.removeItem(scrollKey(batchId));
    }

    function initDetailPage() {
        const root = document.querySelector(".batch-detail[data-batch-id]");
        if (!root) return;

        const batchId = root.dataset.batchId;
        restoreScroll(batchId);

        root.querySelectorAll("a.form-card[href], a[href*='/complete']").forEach((link) => {
            link.addEventListener("click", () => saveScroll(batchId));
        });
    }

    function init() {
        initDetailPage();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();