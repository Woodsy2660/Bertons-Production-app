/**
 * Reference PDF Viewer
 *
 * Uses native browser PDF viewing for iOS Safari (which has excellent native support)
 * and PDF.js for other browsers.
 */

(function() {
    "use strict";

    const DEFAULT_ZOOM = 1;
    const MIN_ZOOM = 0.75;
    const MAX_ZOOM = 2.5;
    const ZOOM_STEP = 0.25;

    /**
     * Detect iOS devices (iPhone, iPad, iPod)
     * All iOS browsers use WebKit, so PDF.js has compatibility issues on all of them.
     */
    function isIOSDevice() {
        const ua = navigator.userAgent;
        // Check for iPhone, iPad, iPod
        if (/iPhone|iPad|iPod/.test(ua)) {
            return true;
        }
        // iPad on iOS 13+ reports as Mac, but supports touch
        if (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1) {
            return true;
        }
        return false;
    }

    /**
     * Mount native PDF viewing for iOS devices using <iframe> element
     * iOS Safari has excellent built-in PDF support via iframe
     */
    function mountNativeViewer(viewer) {
        const url = viewer.dataset.pdfUrl;
        const fallbackUrl = viewer.dataset.fallbackUrl || url;
        const pagesHost = viewer.querySelector(".reference-pdf-pages");

        if (!url || !pagesHost) {
            console.warn("Native PDF viewer: missing url or pagesHost", { url, pagesHost });
            return;
        }

        console.log("Mounting native iOS PDF viewer for:", url);

        // Create native PDF embed using iframe (works better than <object> on iOS)
        const container = document.createElement("div");
        container.className = "reference-pdf-native-container";

        const iframe = document.createElement("iframe");
        iframe.src = url;
        iframe.className = "reference-pdf-native-embed";
        iframe.setAttribute("title", "PDF document");
        iframe.setAttribute("loading", "eager");
        // Allow fullscreen and PDF interactions
        iframe.setAttribute("allow", "fullscreen");

        container.appendChild(iframe);
        pagesHost.replaceChildren(container);

        // Hide zoom controls for native viewer (iOS handles its own zoom)
        const block = viewer.closest(".reference-doc-block");
        const zoomControls = block?.querySelector(".reference-pdf-zoom-controls");
        if (zoomControls) {
            zoomControls.style.display = "none";
        }

        // Mark as ready
        viewer.classList.remove("reference-pdf-viewer--loading");
        viewer.classList.add("reference-pdf-viewer--ready", "reference-pdf-viewer--native");

        const status = viewer.querySelector(".reference-pdf-status");
        if (status) {
            status.hidden = true;
        }

        // Hide the fallback link since we have native viewing
        const fallbackLink = viewer.querySelector(".reference-pdf-fallback-link");
        if (fallbackLink) {
            fallbackLink.style.display = "none";
        }
    }

    // PDF.js implementation for non-iOS browsers
    let pdfjsLib = null;
    let pdfjsLoaded = false;
    let pdfjsLoadPromise = null;

    async function loadPdfJs() {
        if (pdfjsLoaded) {
            return pdfjsLib;
        }
        if (pdfjsLoadPromise) {
            return pdfjsLoadPromise;
        }

        pdfjsLoadPromise = (async () => {
            try {
                const module = await import("/static/vendor/pdfjs/pdf.min.mjs");
                pdfjsLib = module;
                pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
                pdfjsLoaded = true;
                return pdfjsLib;
            } catch (err) {
                console.error("Failed to load PDF.js", err);
                throw err;
            }
        })();

        return pdfjsLoadPromise;
    }

    /**
     * @param {string | Uint8Array | ArrayBuffer} source
     * @param {object} [options]
     */
    async function loadPdfDocument(source, options) {
        options = options || {};
        const lib = await loadPdfJs();
        const taskOptions = Object.assign({}, options);
        if (typeof source === "string") {
            taskOptions.url = source;
            if (source.indexOf("blob:") !== 0) {
                taskOptions.withCredentials = true;
            }
        } else {
            taskOptions.data = source;
        }
        return lib.getDocument(taskOptions).promise;
    }

    function createPageShell(pageNumber) {
        const shell = document.createElement("div");
        shell.className = "reference-pdf-page-shell";
        shell.dataset.pageNumber = String(pageNumber);
        shell.innerHTML =
            '<div class="reference-pdf-page-label">Page ' + pageNumber + '</div>' +
            '<div class="reference-pdf-page-canvas-host"></div>';
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
        canvas.style.width = Math.floor(viewport.width) + "px";
        canvas.style.height = Math.floor(viewport.height) + "px";

        const transform =
            outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

        host.replaceChildren(canvas);
        await page.render({
            canvasContext: context,
            viewport: viewport,
            transform: transform,
        }).promise;

        shell.dataset.rendered = "true";
        shell.classList.add("is-rendered");
    }

    function setupLazyRendering(pdf, pagesHost, baseScale, getZoom) {
        var shells = Array.prototype.slice.call(pagesHost.querySelectorAll(".reference-pdf-page-shell"));
        var observer = new IntersectionObserver(
            function(entries) {
                entries.forEach(function(entry) {
                    if (!entry.isIntersecting) {
                        return;
                    }
                    var shell = entry.target;
                    var pageNumber = Number(shell.dataset.pageNumber);
                    renderPageToShell(pdf, pageNumber, shell, baseScale, getZoom()).catch(
                        function(err) { console.error("PDF page render failed", err); }
                    );
                });
            },
            { root: null, rootMargin: "400px 0px", threshold: 0.01 }
        );

        shells.forEach(function(shell) {
            observer.observe(shell);
        });
        return observer;
    }

    function setStatus(viewer, state, message) {
        message = message || "";
        viewer.classList.remove(
            "reference-pdf-viewer--loading",
            "reference-pdf-viewer--ready",
            "reference-pdf-viewer--error"
        );
        viewer.classList.add("reference-pdf-viewer--" + state);
        var status = viewer.querySelector(".reference-pdf-status");
        if (status) {
            status.textContent = message;
            status.hidden = state === "ready";
        }
    }

    function measurePageWidth(pagesHost, viewer) {
        var width = (pagesHost && pagesHost.clientWidth) || (viewer && viewer.clientWidth) || 0;
        if (width > 0) {
            return width;
        }
        var column = viewer && viewer.closest(".reference-docs-section, .reference-preview-column, main");
        return (column && column.clientWidth) || 800;
    }

    function updateZoomLabel(viewer, zoom) {
        var label = viewer.querySelector(".reference-pdf-zoom-value");
        if (label) {
            label.textContent = Math.round(zoom * 100) + "%";
        }
    }

    async function mountPdfjsViewer(viewer) {
        var url = viewer.dataset.pdfUrl;
        var pagesHost = viewer.querySelector(".reference-pdf-pages");
        if (!url || !pagesHost) {
            return;
        }

        var zoom = Number(viewer.dataset.initialZoom || DEFAULT_ZOOM);
        var pdf = null;
        var baseScale = measurePageWidth(pagesHost, viewer);
        var observer = null;

        var rerenderAll = async function() {
            if (!pdf) {
                return;
            }
            var shells = pagesHost.querySelectorAll(".reference-pdf-page-shell");
            shells.forEach(function(shell) {
                shell.dataset.rendered = "false";
                shell.classList.remove("is-rendered");
                var host = shell.querySelector(".reference-pdf-page-canvas-host");
                if (host) {
                    host.replaceChildren();
                }
            });
            if (observer) {
                observer.disconnect();
            }
            baseScale = measurePageWidth(pagesHost, viewer);
            observer = setupLazyRendering(pdf, pagesHost, baseScale, function() { return zoom; });
            var first = pagesHost.querySelector(".reference-pdf-page-shell");
            if (first) {
                await renderPageToShell(
                    pdf,
                    Number(first.dataset.pageNumber),
                    first,
                    baseScale,
                    zoom
                );
            }
        };

        var block = viewer.closest(".reference-doc-block");
        var zoomInBtn = block && block.querySelector('[data-action="zoom-in"]');
        var zoomOutBtn = block && block.querySelector('[data-action="zoom-out"]');
        var zoomResetBtn = block && block.querySelector('[data-action="zoom-reset"]');

        var applyZoom = async function(nextZoom) {
            zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
            viewer.dataset.currentZoom = String(zoom);
            updateZoomLabel(viewer, zoom);
            await rerenderAll();
        };

        if (zoomInBtn) zoomInBtn.addEventListener("click", function() { applyZoom(zoom + ZOOM_STEP); });
        if (zoomOutBtn) zoomOutBtn.addEventListener("click", function() { applyZoom(zoom - ZOOM_STEP); });
        if (zoomResetBtn) zoomResetBtn.addEventListener("click", function() { applyZoom(DEFAULT_ZOOM); });

        var resizeTimer = null;
        window.addEventListener("resize", function() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() { rerenderAll(); }, 150);
        });

        setStatus(viewer, "loading", "Loading document…");
        try {
            pdf = await loadPdfDocument(url);
            pagesHost.replaceChildren();
            for (var i = 1; i <= pdf.numPages; i++) {
                pagesHost.appendChild(createPageShell(i));
            }
            setStatus(viewer, "ready");
            updateZoomLabel(viewer, zoom);
            await rerenderAll();
        } catch (err) {
            console.error("Failed to load reference PDF", err);
            setStatus(viewer, "error", "Could not load PDF preview — use the link below to open it.");
        }
    }

    /**
     * Mount viewer - chooses native or PDF.js based on device
     */
    async function mountViewer(viewer) {
        try {
            if (isIOSDevice()) {
                console.log("iOS device detected, using native PDF viewer");
                mountNativeViewer(viewer);
            } else {
                console.log("Non-iOS device, using PDF.js");
                await mountPdfjsViewer(viewer);
            }
        } catch (err) {
            console.error("Error mounting PDF viewer:", err);
            setStatus(viewer, "error", "Could not load PDF preview — use the link to open it.");
        }
    }

    /**
     * @param {File} file
     * @param {HTMLElement} viewer
     */
    async function mountViewerFromFile(file, viewer) {
        var buffer = await file.arrayBuffer();
        var blobUrl = URL.createObjectURL(new Blob([buffer], { type: "application/pdf" }));
        viewer.dataset.pdfUrl = blobUrl;
        await mountViewer(viewer);
    }

    function initReferencePdfViewers(root) {
        root = root || document;
        var viewers = root.querySelectorAll("[data-reference-pdf-viewer][data-pdf-url]");
        console.log("initReferencePdfViewers: found", viewers.length, "viewers");
        viewers.forEach(function(viewer) {
            if (viewer.dataset.mounted === "true") {
                return;
            }
            viewer.dataset.mounted = "true";
            mountViewer(viewer);
        });
    }

    // Export for module usage
    if (typeof window !== "undefined") {
        window.ReferencePdfViewer = {
            init: initReferencePdfViewers,
            mountFromFile: mountViewerFromFile,
            isIOS: isIOSDevice
        };
    }

    // Auto-initialize on DOM ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function() {
            console.log("DOMContentLoaded: initializing PDF viewers");
            initReferencePdfViewers();
        });
    } else {
        console.log("Document ready: initializing PDF viewers immediately");
        initReferencePdfViewers();
    }

})();

// ES module exports for import usage
export function initReferencePdfViewers(root) {
    if (window.ReferencePdfViewer) {
        window.ReferencePdfViewer.init(root);
    }
}

export async function mountViewerFromFile(file, viewer) {
    if (window.ReferencePdfViewer) {
        return window.ReferencePdfViewer.mountFromFile(file, viewer);
    }
}
