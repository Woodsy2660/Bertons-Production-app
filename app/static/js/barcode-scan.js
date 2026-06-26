/**
 * Barcode scanner support for batch-number fields.
 *
 * - USB handheld scanners (keyboard wedge + Enter)
 * - Device camera (BarcodeDetector API, html5-qrcode fallback)
 * - GS1-128 / Data Matrix / QR → AI (10) batch/lot extraction
 */
(function () {
    "use strict";

    const SCAN_CHAR_GAP_MS = 80;
    const MIN_CODE_LENGTH = 2;
    const HTML5_QRCODE_URL = "/static/js/vendor/html5-qrcode.min.js";
    /** Camera: square QR / Data Matrix on label (left of batch number). */
    const CAMERA_BARCODE_FORMATS = ["qr_code", "data_matrix"];
    /** Handheld gun may also read GS1-128 linear barcodes. */
    const BARCODE_FORMATS = ["code_128", "data_matrix", "qr_code"];

    const CAMERA_HINT =
        "Scan the square QR code on the label — it sits to the left of the printed batch number.";
    const CAMERA_HINT_LIVE =
        "Fill the gold square with the QR code only (not the batch number text).";

    const scanState = new WeakMap();
    const lastScanByInput = new WeakMap();
    const cameraState = {
        modal: null,
        viewport: null,
        errorEl: null,
        hintEl: null,
        activeInput: null,
        stream: null,
        video: null,
        rafId: null,
        detector: null,
        html5Scanner: null,
        usingHtml5: false,
        closed: true,
        lastCameraDecode: null,
    };

    function getState(input) {
        if (!scanState.has(input)) {
            scanState.set(input, { buffer: "", lastKeyAt: 0, scanning: false });
        }
        return scanState.get(input);
    }

    function normalizeCode(raw) {
        return String(raw || "")
            .trim()
            .replace(/[\r\n]+/g, "");
    }

    function resolveScanValue(raw) {
        const extract = window.GS1Parse?.extractBatchLot;
        if (!extract) {
            return { value: normalizeCode(raw), gs1: null, batchLot: null, isGs1: false };
        }

        const { batchLot, parsed, productionDate, count, looksGs1 } = extract(raw);

        if (batchLot) {
            return {
                value: batchLot,
                gs1: parsed,
                batchLot,
                productionDate,
                count,
                isGs1: true,
                raw: normalizeCode(raw),
            };
        }

        if (looksGs1) {
            return {
                value: null,
                gs1: parsed,
                batchLot: null,
                productionDate,
                count,
                isGs1: true,
                raw: normalizeCode(raw),
            };
        }

        return {
            value: normalizeCode(raw),
            gs1: parsed,
            batchLot: null,
            productionDate: null,
            count: null,
            isGs1: false,
            raw: normalizeCode(raw),
        };
    }

    function shouldDebounce(input, key) {
        if (!key) return true;
        const last = lastScanByInput.get(input);
        if (last === key) return true;
        lastScanByInput.set(input, key);
        return false;
    }

    async function lookupBarcode(code, input) {
        const batchId = input.dataset.batchId;
        const formType = input.dataset.formType;
        if (!batchId || !formType) return null;

        try {
            const response = await fetch(
                `/api/batches/${batchId}/barcode-lookup?code=${encodeURIComponent(code)}&form_type=${encodeURIComponent(formType)}&field=${encodeURIComponent(input.name)}`,
                { headers: { Accept: "application/json" } }
            );
            if (!response.ok) return null;
            const data = await response.json();
            return data.prefill || null;
        } catch {
            return null;
        }
    }

    function applyPrefill(form, prefill) {
        if (!form || !prefill) return;
        for (const [name, value] of Object.entries(prefill)) {
            const el = form.querySelector(`[name="${name}"], [name="${name}[]"]`);
            if (!el || el === document.activeElement) continue;
            if (el.type === "checkbox") {
                el.checked = value === "Y" || value === true;
            } else {
                el.value = value == null ? "" : String(value);
            }
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
        }
    }

    function setFieldStatus(input, text, state) {
        const status = input?.closest(".barcode-field")?.querySelector(".barcode-field-status");
        if (!status) return;
        status.textContent = text;
        status.dataset.state = state;
    }

    /**
     * Central decode hook — GS1 AI (10) is applied to the batch field here
     * via input.value + input/change events (batch set at those two lines).
     */
    async function commitScan(input, code) {
        const resolved = resolveScanValue(code);
        const debounceKey = resolved.batchLot || resolved.raw || resolved.value;
        if (shouldDebounce(input, debounceKey)) return;

        if (resolved.isGs1 && !resolved.batchLot) {
            console.warn("[GS1] No AI (10) batch/lot in barcode:", resolved.raw, resolved.gs1);
            setFieldStatus(
                input,
                `No batch in GS1 barcode (raw: ${resolved.raw})`,
                "error"
            );
            input.dispatchEvent(
                new CustomEvent("barcode-scanned", {
                    bubbles: true,
                    detail: {
                        raw: resolved.raw,
                        gs1: resolved.gs1,
                        batchLot: null,
                        productionDate: resolved.productionDate,
                        count: resolved.count,
                        prefill: null,
                        source: "scan",
                    },
                })
            );
            return;
        }

        const valueToSet = resolved.value;
        if (!valueToSet || valueToSet.length < MIN_CODE_LENGTH) return;

        input.value = valueToSet;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));

        const form = input.closest("form");
        const prefill = await lookupBarcode(valueToSet, input);
        applyPrefill(form, prefill);

        const statusLabel = resolved.batchLot
            ? `Batch: ${resolved.batchLot}`
            : `Scanned: ${valueToSet}`;
        setFieldStatus(input, statusLabel, "scanned");
        window.setTimeout(() => {
            const status = input.closest(".barcode-field")?.querySelector(".barcode-field-status");
            if (status && status.dataset.state === "scanned") {
                status.textContent = "Camera: scan QR left of batch no. on label";
                status.dataset.state = "idle";
            }
        }, 2500);

        input.dispatchEvent(
            new CustomEvent("barcode-scanned", {
                bubbles: true,
                detail: {
                    raw: resolved.raw || valueToSet,
                    code: valueToSet,
                    gs1: resolved.gs1,
                    batchLot: resolved.batchLot,
                    productionDate: resolved.productionDate,
                    count: resolved.count,
                    prefill,
                    source: "scan",
                },
            })
        );
    }

    function onKeyDown(input, event) {
        const state = getState(input);
        const now = Date.now();

        if (event.key === "Enter") {
            const fromBuffer =
                state.buffer.length >= MIN_CODE_LENGTH ? state.buffer : "";
            const fromInput = input.value;
            const code = fromBuffer || fromInput;

            if (normalizeCode(code).length >= MIN_CODE_LENGTH) {
                event.preventDefault();
                event.stopPropagation();
                commitScan(input, code);
            }

            state.buffer = "";
            state.scanning = false;
            state.lastKeyAt = now;
            return;
        }

        if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }

        if (now - state.lastKeyAt > SCAN_CHAR_GAP_MS) {
            state.buffer = "";
            state.scanning = false;
        }

        state.buffer += event.key;
        state.scanning = true;
        state.lastKeyAt = now;
    }

    function attachContext(input) {
        const root = document.getElementById("form-save-root");
        if (root) {
            input.dataset.batchId = root.dataset.batchId || "";
            input.dataset.formType = root.dataset.formType || "";
        }
    }

    function enhanceInput(input) {
        if (input.dataset.barcodeBound === "1") return;
        input.dataset.barcodeBound = "1";
        attachContext(input);
        input.setAttribute("autocomplete", "off");
        input.setAttribute("autocapitalize", "off");
        input.setAttribute("spellcheck", "false");
        input.addEventListener("keydown", (event) => onKeyDown(input, event));

        input.addEventListener("focus", () => {
            const status = input.closest(".barcode-field")?.querySelector(".barcode-field-status");
            if (status && status.dataset.state === "idle") {
                status.textContent = "Ready for handheld scanner…";
            }
        });

        input.addEventListener("blur", () => {
            const state = getState(input);
            state.buffer = "";
            state.scanning = false;
            const status = input.closest(".barcode-field")?.querySelector(".barcode-field-status");
            if (status && status.dataset.state === "idle") {
                status.textContent = "Camera: scan QR left of batch no. on label";
            }
        });
    }

    function bindScanButtons(root) {
        root.querySelectorAll("[data-barcode-scan-trigger]").forEach((button) => {
            button.addEventListener("click", () => {
                const input = document.getElementById(button.dataset.barcodeScanTrigger);
                if (!input) return;
                input.focus();
                input.select();
                setFieldStatus(input, "Ready for handheld scanner…", "ready");
            });
        });
    }

    function bindCameraButtons(root) {
        root.querySelectorAll("[data-barcode-camera-trigger]").forEach((button) => {
            button.addEventListener("click", () => {
                const input = document.getElementById(button.dataset.barcodeCameraTrigger);
                if (!input) return;
                openCameraScan(input);
            });
        });
    }

    function ensureCameraModal() {
        if (cameraState.modal) return;

        const modal = document.createElement("div");
        modal.id = "barcode-camera-modal";
        modal.className = "barcode-camera-modal";
        modal.hidden = true;
        modal.innerHTML = `
            <div class="barcode-camera-panel" role="dialog" aria-modal="true" aria-labelledby="barcode-camera-title">
                <header class="barcode-camera-header">
                    <h3 id="barcode-camera-title">Scan label QR code</h3>
                    <button type="button" class="barcode-camera-close touch-target" data-barcode-camera-close aria-label="Close camera scanner">Close</button>
                </header>
                <div class="barcode-camera-guide">
                    <div class="barcode-camera-guide-diagram" aria-hidden="true">
                        <div class="guide-qr-box">QR</div>
                        <div class="guide-batch-text">Batch number</div>
                    </div>
                    <p class="barcode-camera-guide-text">
                        On the pallet/carton label, use the <strong>square QR code to the left</strong> of the batch number.
                        The batch number will fill in automatically.
                    </p>
                </div>
                <div id="barcode-camera-viewport" class="barcode-camera-viewport"></div>
                <p class="barcode-camera-hint">${CAMERA_HINT_LIVE}</p>
                <p class="barcode-camera-error" hidden></p>
            </div>
        `;
        document.body.appendChild(modal);

        cameraState.modal = modal;
        cameraState.viewport = modal.querySelector("#barcode-camera-viewport");
        cameraState.errorEl = modal.querySelector(".barcode-camera-error");
        cameraState.hintEl = modal.querySelector(".barcode-camera-hint");

        modal.querySelector("[data-barcode-camera-close]").addEventListener("click", closeCameraScan);
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeCameraScan();
        });
    }

    function showCameraError(message) {
        if (!cameraState.errorEl) return;
        cameraState.errorEl.textContent = message;
        cameraState.errorEl.hidden = !message;
    }

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${src}"]`)) {
                resolve();
                return;
            }
            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error("Could not load scanner library"));
            document.head.appendChild(script);
        });
    }

    function supportsBarcodeDetector() {
        return typeof window.BarcodeDetector === "function";
    }

    async function stopNativeCamera() {
        if (cameraState.rafId) {
            cancelAnimationFrame(cameraState.rafId);
            cameraState.rafId = null;
        }
        if (cameraState.stream) {
            cameraState.stream.getTracks().forEach((track) => track.stop());
            cameraState.stream = null;
        }
        if (cameraState.video) {
            cameraState.video.pause();
            cameraState.video.srcObject = null;
            cameraState.video.remove();
            cameraState.video = null;
        }
        cameraState.detector = null;
    }

    async function stopHtml5Camera() {
        if (cameraState.html5Scanner) {
            try {
                const state = cameraState.html5Scanner.getState();
                if (state === 2) {
                    await cameraState.html5Scanner.stop();
                }
                await cameraState.html5Scanner.clear();
            } catch {
                /* ignore stop errors */
            }
            cameraState.html5Scanner = null;
        }
        cameraState.usingHtml5 = false;
    }

    function showCameraLoading(message) {
        if (!cameraState.viewport) return;
        cameraState.viewport.innerHTML = `
            <div class="barcode-camera-loading" role="status" aria-live="polite">
                <span class="barcode-camera-spinner" aria-hidden="true"></span>
                <span>${message || "Starting camera…"}</span>
            </div>
        `;
    }

    async function stopCamera() {
        await stopHtml5Camera();
        await stopNativeCamera();
        cameraState.lastCameraDecode = null;
        if (cameraState.viewport) {
            cameraState.viewport.innerHTML = "";
        }
    }

    async function handleCameraSuccess(code) {
        if (cameraState.lastCameraDecode === code) return;
        cameraState.lastCameraDecode = code;

        const input = cameraState.activeInput;
        await closeCameraScan();
        if (input) {
            await commitScan(input, code);
            input.focus();
        }
    }

    function mountNativePreview(video) {
        cameraState.viewport.innerHTML = "";
        const live = document.createElement("div");
        live.className = "barcode-camera-live";
        live.innerHTML = `
            <div class="barcode-camera-overlay" aria-hidden="true">
                <div class="barcode-camera-target barcode-camera-target--square">
                    <span class="barcode-camera-target-label">QR</span>
                </div>
            </div>
        `;
        live.insertBefore(video, live.firstChild);
        cameraState.viewport.appendChild(live);
    }

    async function startNativeCamera() {
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error("Camera not supported in this browser");
        }
        if (!supportsBarcodeDetector()) {
            throw new Error("Native scanner not available");
        }

        cameraState.detector = new BarcodeDetector({ formats: CAMERA_BARCODE_FORMATS });
        cameraState.stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 },
            },
            audio: false,
        });

        const video = document.createElement("video");
        video.setAttribute("playsinline", "true");
        video.setAttribute("webkit-playsinline", "true");
        video.setAttribute("autoplay", "true");
        video.muted = true;
        video.className = "barcode-camera-video";
        cameraState.video = video;
        mountNativePreview(video);
        video.srcObject = cameraState.stream;
        await video.play();

        if (cameraState.hintEl) {
            cameraState.hintEl.textContent = CAMERA_HINT_LIVE;
        }

        let busy = false;
        const tick = async () => {
            if (cameraState.closed || !cameraState.video || busy) {
                if (!cameraState.closed) {
                    cameraState.rafId = requestAnimationFrame(tick);
                }
                return;
            }
            busy = true;
            try {
                const codes = await cameraState.detector.detect(cameraState.video);
                const pick =
                    codes.find((c) => c.format === "qr_code" && c.rawValue) ||
                    codes.find((c) => c.format === "data_matrix" && c.rawValue) ||
                    codes.find((c) => c.rawValue);
                if (pick?.rawValue) {
                    await handleCameraSuccess(pick.rawValue);
                    busy = false;
                    return;
                }
            } catch {
                /* detection frame failed — keep scanning */
            }
            busy = false;
            cameraState.rafId = requestAnimationFrame(tick);
        };
        cameraState.rafId = requestAnimationFrame(tick);
    }

    function squareScanBoxSize(viewfinderWidth, viewfinderHeight) {
        const size = Math.min(
            Math.floor(Math.min(viewfinderWidth, viewfinderHeight) * 0.58),
            240
        );
        const edge = Math.max(size, 180);
        return { width: edge, height: edge };
    }

    function html5ScanConfig() {
        const config = {
            fps: 10,
            qrbox: squareScanBoxSize,
            aspectRatio: 1.0,
            videoConstraints: {
                facingMode: "environment",
                width: { ideal: 1280 },
                height: { ideal: 720 },
            },
        };

        if (typeof Html5QrcodeSupportedFormats !== "undefined") {
            config.formatsToSupport = [
                Html5QrcodeSupportedFormats.QR_CODE,
                Html5QrcodeSupportedFormats.DATA_MATRIX,
            ];
        }

        return config;
    }

    async function startHtml5Camera() {
        await loadScript(HTML5_QRCODE_URL);
        if (typeof window.Html5Qrcode !== "function") {
            throw new Error("Scanner library failed to load");
        }

        const readerId = "barcode-camera-reader";
        cameraState.viewport.innerHTML = `<div id="${readerId}" class="barcode-camera-reader"></div>`;

        cameraState.html5Scanner = new Html5Qrcode(readerId, { verbose: false });
        cameraState.usingHtml5 = true;

        const onScan = async (decodedText) => {
            await handleCameraSuccess(decodedText);
        };
        const config = html5ScanConfig();

        try {
            await cameraState.html5Scanner.start(
                { facingMode: "environment" },
                config,
                onScan,
                () => {}
            );
        } catch {
            const cameras = await Html5Qrcode.getCameras();
            if (!cameras || cameras.length === 0) {
                throw new Error("No camera found on this device");
            }
            const backCamera =
                cameras.find((cam) => /back|rear|environment/i.test(cam.label)) ||
                cameras[cameras.length - 1];
            await cameraState.html5Scanner.start(
                backCamera.id,
                config,
                onScan,
                () => {}
            );
        }

        if (cameraState.hintEl) {
            cameraState.hintEl.textContent = CAMERA_HINT_LIVE;
        }
    }

    async function openCameraScan(input) {
        if (!window.isSecureContext) {
            setFieldStatus(
                input,
                "Camera requires HTTPS or localhost",
                "error"
            );
            return;
        }

        ensureCameraModal();
        attachContext(input);
        cameraState.activeInput = input;
        cameraState.closed = false;
        cameraState.lastCameraDecode = null;
        cameraState.modal.hidden = false;
        document.body.classList.add("barcode-camera-open");
        showCameraError("");
        showCameraLoading("Starting camera…");
        if (cameraState.hintEl) {
            cameraState.hintEl.textContent = CAMERA_HINT;
        }
        setFieldStatus(input, "Opening camera…", "ready");

        try {
            await startHtml5Camera();
        } catch (err) {
            try {
                await stopCamera();
                showCameraLoading("Starting camera (alternate mode)…");
                await startNativeCamera();
            } catch (fallbackErr) {
                showCameraError(
                    fallbackErr.message || err.message || "Could not start camera"
                );
                showCameraLoading("Camera preview unavailable");
                setFieldStatus(input, "Camera unavailable — use gun or type", "error");
            }
        }
    }

    async function closeCameraScan() {
        cameraState.closed = true;
        await stopCamera();
        if (cameraState.modal) {
            cameraState.modal.hidden = true;
        }
        document.body.classList.remove("barcode-camera-open");
        cameraState.activeInput = null;
    }

    function init() {
        document.querySelectorAll("[data-barcode-scan]").forEach(enhanceInput);
        bindScanButtons(document);
        bindCameraButtons(document);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.BertonBarcode = {
        lookupBarcode,
        commitScan,
        normalizeCode,
        resolveScanValue,
        openCameraScan,
        closeCameraScan,
        parseGS1: window.GS1Parse?.parseGS1,
    };
})();