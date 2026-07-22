import * as pdfjsLib from "/static/vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";

const DEFAULT_ZOOM = 1;
const MIN_ZOOM = 0.75;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.25;

/**
 * @param {string | Uint8Array | ArrayBuffer} source
 * @param {object} [options]
 */
async function loadPdfDocument(source, options = {}) {
    const taskOptions = { ...options };
    if (typeof source === "string") {
        // Fetch as ArrayBuffer with session cookies. Avoids range-request /
        // path quirks that can fail on revisit while first load appeared fine.
        if (!source.startsWith("blob:")) {
            const response = await fetch(source, {
                credentials: "same-origin",
                headers: { Accept: "application/pdf" },
            });
            if (!response.ok) {
                let detail = "";
                try {
                    const body = await response.json();
                    detail = body?.detail ? `: ${body.detail}` : "";
                } catch {
                    /* ignore non-JSON error body */
                }
                throw new Error(`PDF request failed (${response.status})${detail}`);
            }
            const buffer = await response.arrayBuffer();
            if (!buffer || buffer.byteLength < 5) {
                throw new Error("PDF response was empty");
            }
            taskOptions.data = buffer;
        } else {
            taskOptions.url = source;
        }
    } else {
        taskOptions.data = source;
    }
    return pdfjsLib.getDocument(taskOptions).promise;
}

function createPageShell(pageNumber) {
    const shell = document.createElement("div");
    shell.className = "reference-pdf-page-shell";
    shell.dataset.pageNumber = String(pageNumber);
    shell.innerHTML = `
        <div class="reference-pdf-page-label">Page ${pageNumber}</div>
        <div class="reference-pdf-page-canvas-host"></div>
    `;
    return shell;
}

async function renderPageToShell(pdf, pageNumber, shell, baseScale, zoom) {
    if (shell.dataset.rendered === "true") {
        return;
    }
    const host = shell.querySelector(".reference-pdf-page-canvas-host");
    if (!host) {
        return;
    }

    const page = await pdf.getPage(pageNumber);
    const unscaled = page.getViewport({ scale: 1 });
    const fitScale = baseScale / unscaled.width;
    const viewport = page.getViewport({ scale: fitScale * zoom });
    const outputScale = window.devicePixelRatio || 1;

    const canvas = document.createElement("canvas");
    canvas.className = "reference-pdf-page-canvas";
    const context = canvas.getContext("2d");
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;

    const transform =
        outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

    host.replaceChildren(canvas);
    await page.render({
        canvasContext: context,
        viewport,
        transform,
    }).promise;

    shell.dataset.rendered = "true";
    shell.classList.add("is-rendered");
}

function setupLazyRendering(pdf, pagesHost, baseScale, getZoom) {
    const shells = [...pagesHost.querySelectorAll(".reference-pdf-page-shell")];
    const observer = new IntersectionObserver(
        (entries) => {
            for (const entry of entries) {
                if (!entry.isIntersecting) {
                    continue;
                }
                const shell = entry.target;
                const pageNumber = Number(shell.dataset.pageNumber);
                renderPageToShell(pdf, pageNumber, shell, baseScale, getZoom()).catch(
                    (err) => console.error("PDF page render failed", err),
                );
            }
        },
        { root: null, rootMargin: "400px 0px", threshold: 0.01 },
    );

    for (const shell of shells) {
        observer.observe(shell);
    }
    return observer;
}

function setStatus(viewer, state, message = "") {
    viewer.classList.remove(
        "reference-pdf-viewer--loading",
        "reference-pdf-viewer--ready",
        "reference-pdf-viewer--error",
    );
    viewer.classList.add(`reference-pdf-viewer--${state}`);
    const status = viewer.querySelector(".reference-pdf-status");
    if (status) {
        status.textContent = message;
        status.hidden = state === "ready";
    }
}

function measurePageWidth(pagesHost, viewer) {
    const width = pagesHost?.clientWidth || viewer?.clientWidth || 0;
    if (width > 0) {
        return width;
    }
    const column = viewer?.closest(".reference-docs-section, .reference-preview-column, main");
    return column?.clientWidth || 800;
}

function updateZoomLabel(viewer, zoom) {
    const label = viewer.querySelector(".reference-pdf-zoom-value");
    if (label) {
        label.textContent = `${Math.round(zoom * 100)}%`;
    }
}

async function mountViewer(viewer) {
    const url = viewer.dataset.pdfUrl;
    const pagesHost = viewer.querySelector(".reference-pdf-pages");
    if (!url || !pagesHost) {
        return;
    }

    let zoom = Number(viewer.dataset.initialZoom || DEFAULT_ZOOM);
    let pdf = null;
    let baseScale = measurePageWidth(pagesHost, viewer);
    let observer = null;

    const rerenderAll = async () => {
        if (!pdf) {
            return;
        }
        const shells = pagesHost.querySelectorAll(".reference-pdf-page-shell");
        for (const shell of shells) {
            shell.dataset.rendered = "false";
            shell.classList.remove("is-rendered");
            const host = shell.querySelector(".reference-pdf-page-canvas-host");
            if (host) {
                host.replaceChildren();
            }
        }
        if (observer) {
            observer.disconnect();
        }
        baseScale = measurePageWidth(pagesHost, viewer);
        observer = setupLazyRendering(pdf, pagesHost, baseScale, () => zoom);
        const first = pagesHost.querySelector(".reference-pdf-page-shell");
        if (first) {
            await renderPageToShell(
                pdf,
                Number(first.dataset.pageNumber),
                first,
                baseScale,
                zoom,
            );
        }
    };

    const block = viewer.closest(".reference-doc-block");
    const zoomInBtn = block?.querySelector('[data-action="zoom-in"]');
    const zoomOutBtn = block?.querySelector('[data-action="zoom-out"]');
    const zoomResetBtn = block?.querySelector('[data-action="zoom-reset"]');

    const applyZoom = async (nextZoom) => {
        zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
        viewer.dataset.currentZoom = String(zoom);
        updateZoomLabel(viewer, zoom);
        await rerenderAll();
    };

    zoomInBtn?.addEventListener("click", () => applyZoom(zoom + ZOOM_STEP));
    zoomOutBtn?.addEventListener("click", () => applyZoom(zoom - ZOOM_STEP));
    zoomResetBtn?.addEventListener("click", () => applyZoom(DEFAULT_ZOOM));

    let resizeTimer = null;
    window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => rerenderAll(), 150);
    });

    setStatus(viewer, "loading", "Loading document…");
    try {
        pdf = await loadPdfDocument(url);
        pagesHost.replaceChildren();
        for (let i = 1; i <= pdf.numPages; i += 1) {
            pagesHost.appendChild(createPageShell(i));
        }
        setStatus(viewer, "ready");
        updateZoomLabel(viewer, zoom);
        await rerenderAll();
    } catch (err) {
        console.error("Failed to load reference PDF", err);
        const msg = err?.message || "Unknown error";
        setStatus(
            viewer,
            "error",
            `Could not load this PDF. ${msg} Use Open full page or re-upload if the file is missing.`
        );
        const fallback = viewer.dataset.fallbackUrl || viewer.dataset.pdfUrl;
        if (fallback) {
            const link = viewer.querySelector(".reference-pdf-fallback-link");
            if (link) {
                link.href = fallback;
                link.textContent = "Open PDF directly";
                link.hidden = false;
            }
        }
    }
}

/**
 * @param {File} file
 * @param {HTMLElement} viewer
 */
export async function mountViewerFromFile(file, viewer) {
    const buffer = await file.arrayBuffer();
    const blobUrl = URL.createObjectURL(new Blob([buffer], { type: "application/pdf" }));
    viewer.dataset.pdfUrl = blobUrl;
    await mountViewer(viewer);
}

export function initReferencePdfViewers(root = document) {
    const viewers = root.querySelectorAll("[data-reference-pdf-viewer][data-pdf-url]");
    for (const viewer of viewers) {
        if (viewer.dataset.mounted === "true") {
            continue;
        }
        viewer.dataset.mounted = "true";
        mountViewer(viewer);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initReferencePdfViewers());
} else {
    initReferencePdfViewers();
}