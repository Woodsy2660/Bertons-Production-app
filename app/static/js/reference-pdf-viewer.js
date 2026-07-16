/**
 * Reference PDF Viewer
 *
 * Uses native browser PDF viewing for iOS Safari (which has excellent native support)
 * and PDF.js for other browsers.
 *
 * Compatibility: Safari 13+, Chrome 80+, Firefox 75+, Edge 80+
 * - Avoids replaceChildren() (Safari 14+ only)
 * - Avoids optional chaining ?. (Safari 13.1+ only)
 * - Wraps all initialization in error handling
 */

(function() {
    "use strict";

    var DEFAULT_ZOOM = 1;
    var MIN_ZOOM = 0.75;
    var MAX_ZOOM = 2.5;
    var ZOOM_STEP = 0.25;

    /**
     * Safe replacement for element.replaceChildren(...children)
     * Works in Safari 13 and older browsers that don't support replaceChildren
     */
    function replaceChildrenSafe(parent, newChildren) {
        // Clear existing children
        while (parent.firstChild) {
            parent.removeChild(parent.firstChild);
        }
        // Add new children (if any)
        if (newChildren) {
            if (Array.isArray(newChildren)) {
                newChildren.forEach(function(child) {
                    parent.appendChild(child);
                });
            } else {
                parent.appendChild(newChildren);
            }
        }
    }

    /**
     * Detect iOS devices (iPhone, iPad, iPod)
     * All iOS browsers use WebKit, so PDF.js has compatibility issues on all of them.
     */
    function isIOSDevice() {
        try {
            var ua = navigator.userAgent || "";
            // Check for iPhone, iPad, iPod
            if (/iPhone|iPad|iPod/.test(ua)) {
                return true;
            }
            // iPad on iOS 13+ reports as Mac, but supports touch
            if (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1) {
                return true;
            }
            return false;
        } catch (e) {
            console.warn("isIOSDevice detection failed:", e);
            return false;
        }
    }

    /**
     * Show fallback link and error state
     */
    function showFallback(viewer, message) {
        message = message || "Could not load PDF preview — tap the link to open it.";
        viewer.classList.remove("reference-pdf-viewer--loading");
        viewer.classList.add("reference-pdf-viewer--error");

        var status = viewer.querySelector(".reference-pdf-status");
        if (status) {
            status.textContent = message;
            status.hidden = false;
        }

        // Make sure fallback link is visible
        var fallbackLink = viewer.querySelector(".reference-pdf-fallback-link");
        if (fallbackLink) {
            fallbackLink.style.display = "block";
        }
    }

    /**
     * Mount native PDF viewing for iOS devices using <iframe> element
     * iOS Safari has excellent built-in PDF support via iframe
     */
    function mountNativeViewer(viewer) {
        var url = viewer.dataset.pdfUrl;
        var pagesHost = viewer.querySelector(".reference-pdf-pages");

        if (!url || !pagesHost) {
            console.warn("Native PDF viewer: missing url or pagesHost", url, pagesHost);
            showFallback(viewer, "PDF viewer configuration error");
            return;
        }

        console.log("Mounting native iOS PDF viewer for:", url);

        try {
            // Create native PDF embed using iframe (works better than <object> on iOS)
            var container = document.createElement("div");
            container.className = "reference-pdf-native-container";

            var iframe = document.createElement("iframe");
            iframe.src = url;
            iframe.className = "reference-pdf-native-embed";
            iframe.setAttribute("title", "PDF document");
            // Allow fullscreen and PDF interactions
            iframe.setAttribute("allow", "fullscreen");

            container.appendChild(iframe);

            // Clear and append (compatible with older Safari)
            replaceChildrenSafe(pagesHost, container);

            // Hide zoom controls for native viewer (iOS handles its own zoom)
            var block = viewer.closest(".reference-doc-block");
            if (block) {
                var zoomControls = block.querySelector(".reference-pdf-zoom-controls");
                if (zoomControls) {
                    zoomControls.style.display = "none";
                }
            }

            // Mark as ready
            viewer.classList.remove("reference-pdf-viewer--loading");
            viewer.classList.add("reference-pdf-viewer--ready", "reference-pdf-viewer--native");

            var status = viewer.querySelector(".reference-pdf-status");
            if (status) {
                status.hidden = true;
            }

            // Hide the fallback link since we have native viewing
            var fallbackLink = viewer.querySelector(".reference-pdf-fallback-link");
            if (fallbackLink) {
                fallbackLink.style.display = "none";
            }
        } catch (err) {
            console.error("Failed to mount native PDF viewer:", err);
            showFallback(viewer, "Could not load PDF viewer");
        }
    }

    // PDF.js implementation for non-iOS browsers
    var pdfjsLib = null;
    var pdfjsLoaded = false;
    var pdfjsLoadPromise = null;

    function loadPdfJs() {
        if (pdfjsLoaded) {
            return Promise.resolve(pdfjsLib);
        }
        if (pdfjsLoadPromise) {
            return pdfjsLoadPromise;
        }

        pdfjsLoadPromise = new Promise(function(resolve, reject) {
            // Use dynamic import for PDF.js
            import("/static/vendor/pdfjs/pdf.min.mjs")
                .then(function(module) {
                    pdfjsLib = module;
                    pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.mjs";
                    pdfjsLoaded = true;
                    resolve(pdfjsLib);
                })
                .catch(function(err) {
                    console.error("Failed to load PDF.js:", err);
                    reject(err);
                });
        });

        return pdfjsLoadPromise;
    }

    /**
     * @param {string | Uint8Array | ArrayBuffer} source
     * @param {object} [options]
     */
    function loadPdfDocument(source, options) {
        options = options || {};
        return loadPdfJs().then(function(lib) {
            var taskOptions = Object.assign({}, options);
            if (typeof source === "string") {
                taskOptions.url = source;
                if (source.indexOf("blob:") !== 0) {
                    taskOptions.withCredentials = true;
                }
            } else {
                taskOptions.data = source;
            }
            return lib.getDocument(taskOptions).promise;
        });
    }

    function createPageShell(pageNumber) {
        var shell = document.createElement("div");
        shell.className = "reference-pdf-page-shell";
        shell.dataset.pageNumber = String(pageNumber);
        shell.innerHTML =
            '<div class="reference-pdf-page-label">Page ' + pageNumber + '</div>' +
            '<div class="reference-pdf-page-canvas-host"></div>';
        return shell;
    }

    function renderPageToShell(pdf, pageNumber, shell, baseScale, zoom) {
        if (shell.dataset.rendered === "true") {
            return Promise.resolve();
        }
        var host = shell.querySelector(".reference-pdf-page-canvas-host");
        if (!host) {
            return Promise.resolve();
        }

        return pdf.getPage(pageNumber).then(function(page) {
            var unscaled = page.getViewport({ scale: 1 });
            var fitScale = baseScale / unscaled.width;
            var viewport = page.getViewport({ scale: fitScale * zoom });
            var outputScale = window.devicePixelRatio || 1;

            var canvas = document.createElement("canvas");
            canvas.className = "reference-pdf-page-canvas";
            var context = canvas.getContext("2d");
            canvas.width = Math.floor(viewport.width * outputScale);
            canvas.height = Math.floor(viewport.height * outputScale);
            canvas.style.width = Math.floor(viewport.width) + "px";
            canvas.style.height = Math.floor(viewport.height) + "px";

            var transform =
                outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

            // Clear and append canvas (compatible with older Safari)
            replaceChildrenSafe(host, canvas);

            return page.render({
                canvasContext: context,
                viewport: viewport,
                transform: transform,
            }).promise.then(function() {
                shell.dataset.rendered = "true";
                shell.classList.add("is-rendered");
            });
        });
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

    function mountPdfjsViewer(viewer) {
        var url = viewer.dataset.pdfUrl;
        var pagesHost = viewer.querySelector(".reference-pdf-pages");
        if (!url || !pagesHost) {
            return Promise.resolve();
        }

        var zoom = Number(viewer.dataset.initialZoom || DEFAULT_ZOOM);
        var pdf = null;
        var baseScale = measurePageWidth(pagesHost, viewer);
        var observer = null;

        var rerenderAll = function() {
            if (!pdf) {
                return Promise.resolve();
            }
            var shells = pagesHost.querySelectorAll(".reference-pdf-page-shell");
            Array.prototype.forEach.call(shells, function(shell) {
                shell.dataset.rendered = "false";
                shell.classList.remove("is-rendered");
                var host = shell.querySelector(".reference-pdf-page-canvas-host");
                if (host) {
                    replaceChildrenSafe(host);
                }
            });
            if (observer) {
                observer.disconnect();
            }
            baseScale = measurePageWidth(pagesHost, viewer);
            observer = setupLazyRendering(pdf, pagesHost, baseScale, function() { return zoom; });
            var first = pagesHost.querySelector(".reference-pdf-page-shell");
            if (first) {
                return renderPageToShell(
                    pdf,
                    Number(first.dataset.pageNumber),
                    first,
                    baseScale,
                    zoom
                );
            }
            return Promise.resolve();
        };

        var block = viewer.closest(".reference-doc-block");
        var zoomInBtn = block && block.querySelector('[data-action="zoom-in"]');
        var zoomOutBtn = block && block.querySelector('[data-action="zoom-out"]');
        var zoomResetBtn = block && block.querySelector('[data-action="zoom-reset"]');

        var applyZoom = function(nextZoom) {
            zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
            viewer.dataset.currentZoom = String(zoom);
            updateZoomLabel(viewer, zoom);
            rerenderAll();
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

        return loadPdfDocument(url)
            .then(function(loadedPdf) {
                pdf = loadedPdf;
                replaceChildrenSafe(pagesHost);
                for (var i = 1; i <= pdf.numPages; i++) {
                    pagesHost.appendChild(createPageShell(i));
                }
                setStatus(viewer, "ready");
                updateZoomLabel(viewer, zoom);
                return rerenderAll();
            })
            .catch(function(err) {
                console.error("Failed to load reference PDF:", err);
                showFallback(viewer, "Could not load PDF preview — use the link below to open it.");
            });
    }

    /**
     * Mount viewer - chooses native or PDF.js based on device
     */
    function mountViewer(viewer) {
        try {
            if (isIOSDevice()) {
                console.log("iOS device detected, using native PDF viewer");
                mountNativeViewer(viewer);
                return Promise.resolve();
            } else {
                console.log("Non-iOS device, using PDF.js");
                return mountPdfjsViewer(viewer);
            }
        } catch (err) {
            console.error("Error mounting PDF viewer:", err);
            showFallback(viewer, "Could not load PDF viewer");
            return Promise.resolve();
        }
    }

    /**
     * @param {File} file
     * @param {HTMLElement} viewer
     */
    function mountViewerFromFile(file, viewer) {
        return file.arrayBuffer().then(function(buffer) {
            var blobUrl = URL.createObjectURL(new Blob([buffer], { type: "application/pdf" }));
            viewer.dataset.pdfUrl = blobUrl;
            return mountViewer(viewer);
        });
    }

    function initReferencePdfViewers(root) {
        root = root || document;
        var viewers = root.querySelectorAll("[data-reference-pdf-viewer][data-pdf-url]");
        console.log("initReferencePdfViewers: found", viewers.length, "viewers");
        Array.prototype.forEach.call(viewers, function(viewer) {
            if (viewer.dataset.mounted === "true") {
                return;
            }
            viewer.dataset.mounted = "true";
            mountViewer(viewer);
        });
    }

    // Export for global usage
    if (typeof window !== "undefined") {
        window.ReferencePdfViewer = {
            init: initReferencePdfViewers,
            mountFromFile: mountViewerFromFile,
            isIOS: isIOSDevice
        };
    }

    // Auto-initialize on DOM ready with error handling
    function safeInit() {
        try {
            console.log("PDF viewer: initializing...");
            initReferencePdfViewers();
        } catch (err) {
            console.error("PDF viewer initialization failed:", err);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", safeInit);
    } else {
        safeInit();
    }

})();

// ES module exports for import usage
export function initReferencePdfViewers(root) {
    if (window.ReferencePdfViewer) {
        window.ReferencePdfViewer.init(root);
    }
}

export function mountViewerFromFile(file, viewer) {
    if (window.ReferencePdfViewer) {
        return window.ReferencePdfViewer.mountFromFile(file, viewer);
    }
    return Promise.resolve();
}
