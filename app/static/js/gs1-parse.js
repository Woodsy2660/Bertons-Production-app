/**
 * GS1 Application Identifier parser for pallet/carton labels.
 * Supports element strings (with/without FNC1/GS) and human-readable (NN)value form.
 *
 * Diagnostic helpers (parseGS1Detailed, AI_NAMES, interpretAiValue, prefill candidates)
 * support /debug/scan-inspector without changing extractBatchLot behaviour used by forms.
 */
(function () {
    "use strict";

    const GS_CHAR = "\x1d";
    const AIM_PREFIX_RE = /^\][A-Za-z]\d/;

    /** Data length after AI; 0 = variable (terminated by GS or end). */
    const GS1_AI_LENGTHS = {
        "00": 18,
        "01": 14,
        "02": 14,
        "10": 0,
        "11": 6,
        "12": 6,
        "13": 6,
        "15": 6,
        "16": 6,
        "17": 6,
        "20": 2,
        "21": 0,
        "22": 0,
        "30": 0,
        "37": 0,
        "90": 0,
        "91": 0,
        "92": 0,
        "93": 0,
        "94": 0,
        "95": 0,
        "96": 0,
        "97": 0,
        "98": 0,
        "99": 0,
        "240": 0,
        "241": 0,
        "410": 13,
        "414": 13,
    };

    const AI_NAMES = {
        "00": "SSCC",
        "01": "GTIN",
        "02": "GTIN of contained trade items",
        "10": "Batch / lot number",
        "11": "Production date",
        "12": "Due date",
        "13": "Packaging date",
        "15": "Best before date",
        "16": "Sell by date",
        "17": "Expiry date",
        "20": "Variant number",
        "21": "Serial number",
        "22": "Consumer product variant",
        "30": "Variable count",
        "37": "Count of trade items",
        "90": "Information mutually agreed",
        "91": "Company internal",
        "92": "Company internal",
        "93": "Company internal",
        "94": "Company internal",
        "95": "Company internal",
        "96": "Company internal",
        "97": "Company internal",
        "98": "Company internal",
        "99": "Company internal",
        "240": "Additional product id",
        "241": "Customer part number",
        "410": "Ship to / deliver to GLN",
        "414": "GLN of physical location",
    };

    /**
     * Map GS1 AIs → Final Pallet Count (FOR PK 012A) candidate field keys
     * for future prefill (diagnostic / storage shape only — not wired to forms yet).
     */
    const FINAL_PALLET_COUNT_AI_MAP = {
        "02": {
            form_field: "bottle_code",
            form_label: "Bottle code / GTIN contained",
            form_region: "header",
        },
        "01": {
            form_field: "gtin",
            form_label: "GTIN (01)",
            form_region: "header",
        },
        "10": {
            form_field: "batch_lot",
            form_label: "Batch / lot (pallet tag match)",
            form_region: "header",
        },
        "11": {
            form_field: "prn_date",
            form_label: "PRN date (production)",
            form_region: "reading.bottles",
        },
        "17": {
            form_field: "expiry_date",
            form_label: "Expiry date",
            form_region: "header",
        },
        "37": {
            form_field: "high",
            form_label: "Count / quantity → High (finished)",
            form_region: "reading.finished",
        },
        "90": {
            form_field: "pallet_no",
            form_label: "Pallet number (internal AI 90)",
            form_region: "reading.bottles",
        },
        "00": {
            form_field: "sscc",
            form_label: "SSCC",
            form_region: "header",
        },
    };

    const AI_MATCH_LENGTHS = [2, 3, 4];

    function stripAimPrefix(raw) {
        const s = String(raw || "");
        return AIM_PREFIX_RE.test(s) ? s.slice(3) : s;
    }

    function isHumanReadableGs1(s) {
        return /\(\d{2,4}\)/.test(s);
    }

    function parseHumanReadableGs1(s) {
        const result = {};
        const re = /\((\d{2,4})\)([\s\S]*?)(?=\(\d{2,4}\)|$)/g;
        let match;
        while ((match = re.exec(s)) !== null) {
            const ai = match[1];
            if (GS1_AI_LENGTHS[ai] === undefined) continue;
            let value = match[2];
            const gsIndex = value.indexOf(GS_CHAR);
            if (gsIndex !== -1) {
                value = value.slice(0, gsIndex);
            }
            result[ai] = value;
        }
        return result;
    }

    function matchAiAt(element, index) {
        for (const len of AI_MATCH_LENGTHS) {
            if (index + len > element.length) continue;
            const ai = element.slice(index, index + len);
            if (GS1_AI_LENGTHS[ai] !== undefined) {
                return ai;
            }
        }
        return null;
    }

    function parseElementString(s) {
        const result = {};
        let i = 0;

        while (i < s.length) {
            if (s[i] === GS_CHAR) {
                i += 1;
                continue;
            }

            const ai = matchAiAt(s, i);
            if (!ai) {
                i += 1;
                continue;
            }

            i += ai.length;
            const fixedLen = GS1_AI_LENGTHS[ai];
            let value;

            if (fixedLen > 0) {
                value = s.slice(i, i + fixedLen);
                i += fixedLen;
            } else {
                const gsIndex = s.indexOf(GS_CHAR, i);
                if (gsIndex === -1) {
                    value = s.slice(i);
                    i = s.length;
                } else {
                    value = s.slice(i, gsIndex);
                    i = gsIndex + 1;
                }
            }

            result[ai] = value;
        }

        return result;
    }

    /**
     * Detailed element-string parse with offsets (for inspector diagnostics).
     */
    function parseElementStringDetailed(s) {
        const fields = [];
        let i = 0;
        const consumed = new Array(s.length).fill(false);

        while (i < s.length) {
            if (s[i] === GS_CHAR) {
                consumed[i] = true;
                i += 1;
                continue;
            }

            const ai = matchAiAt(s, i);
            if (!ai) {
                i += 1;
                continue;
            }

            const aiStart = i;
            for (let k = 0; k < ai.length; k++) consumed[aiStart + k] = true;
            i += ai.length;
            const fixedLen = GS1_AI_LENGTHS[ai];
            let value;
            let valueStart = i;
            let valueEnd;

            if (fixedLen > 0) {
                value = s.slice(i, i + fixedLen);
                valueEnd = i + fixedLen;
                for (let k = valueStart; k < valueEnd && k < s.length; k++) consumed[k] = true;
                i = valueEnd;
            } else {
                const gsIndex = s.indexOf(GS_CHAR, i);
                if (gsIndex === -1) {
                    value = s.slice(i);
                    valueEnd = s.length;
                    for (let k = valueStart; k < valueEnd; k++) consumed[k] = true;
                    i = s.length;
                } else {
                    value = s.slice(i, gsIndex);
                    valueEnd = gsIndex;
                    for (let k = valueStart; k < valueEnd; k++) consumed[k] = true;
                    consumed[gsIndex] = true;
                    i = gsIndex + 1;
                }
            }

            const known = AI_NAMES[ai] !== undefined;
            fields.push({
                ai,
                name: AI_NAMES[ai] || "Unknown AI",
                known,
                rawValue: value,
                interpreted: interpretAiValue(ai, value),
                aiStart,
                valueStart,
                valueEnd,
                lengthMode: fixedLen > 0 ? "fixed" : "variable",
                expectedLength: fixedLen > 0 ? fixedLen : null,
            });
        }

        let leftover = "";
        for (let j = 0; j < s.length; j++) {
            if (!consumed[j] && s[j] !== GS_CHAR) leftover += s[j];
        }

        return { fields, leftover };
    }

    function parseHumanReadableDetailed(s) {
        const fields = [];
        const re = /\((\d{2,4})\)([\s\S]*?)(?=\(\d{2,4}\)|$)/g;
        let match;
        while ((match = re.exec(s)) !== null) {
            const ai = match[1];
            let value = match[2];
            const gsIndex = value.indexOf(GS_CHAR);
            if (gsIndex !== -1) value = value.slice(0, gsIndex);
            const known = GS1_AI_LENGTHS[ai] !== undefined;
            fields.push({
                ai,
                name: AI_NAMES[ai] || (known ? "AI (unlisted name)" : "Unknown AI"),
                known: AI_NAMES[ai] !== undefined,
                rawValue: value,
                interpreted: interpretAiValue(ai, value),
                aiStart: match.index,
                valueStart: match.index + ai.length + 2,
                valueEnd: match.index + match[0].length,
                lengthMode:
                    GS1_AI_LENGTHS[ai] === undefined
                        ? "unknown"
                        : GS1_AI_LENGTHS[ai] > 0
                          ? "fixed"
                          : "variable",
                expectedLength: GS1_AI_LENGTHS[ai] > 0 ? GS1_AI_LENGTHS[ai] : null,
            });
        }
        return { fields, leftover: "" };
    }

    /** YYMMDD → YYYY-MM-DD when plausible. */
    function interpretDateYymmdd(raw) {
        const v = String(raw || "").trim();
        if (!/^\d{6}$/.test(v)) return null;
        const yy = parseInt(v.slice(0, 2), 10);
        const mm = parseInt(v.slice(2, 4), 10);
        const dd = parseInt(v.slice(4, 6), 10);
        if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return null;
        const year = yy >= 70 ? 1900 + yy : 2000 + yy;
        return `${year}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    }

    function interpretAiValue(ai, rawValue) {
        const v = String(rawValue ?? "");
        if (["11", "12", "13", "15", "16", "17"].includes(ai)) {
            const d = interpretDateYymmdd(v);
            return d || v;
        }
        if (ai === "37" || ai === "30") {
            const n = parseInt(v, 10);
            return Number.isFinite(n) ? n : v;
        }
        return v;
    }

    /** Berton pallet-tag batch format, e.g. MO-041488-120405 (often QR payload without GS1 AIs). */
    const PLAIN_BATCH_RE = /^[A-Z]{2,4}-\d{4,8}-\d{4,8}$/;

    function isPlainBatchCode(s) {
        return PLAIN_BATCH_RE.test(String(s || "").trim());
    }

    function startsWithGs1Ai(s) {
        return matchAiAt(String(s || ""), 0) !== null;
    }

    function hasGs1Structure(raw, s) {
        if (isHumanReadableGs1(s)) return true;
        if (String(raw || "").includes(GS_CHAR)) return true;
        if (AIM_PREFIX_RE.test(String(raw || ""))) return true;
        return startsWithGs1Ai(s);
    }

    function parseGS1(raw) {
        let s = stripAimPrefix(String(raw || "").trim());
        if (!s) return {};

        if (isHumanReadableGs1(s)) {
            return parseHumanReadableGs1(s);
        }

        if (!hasGs1Structure(raw, s)) {
            return {};
        }

        return parseElementString(s);
    }

    /**
     * Full diagnostic parse for the scan inspector.
     */
    function parseGS1Detailed(raw) {
        const rawExact = String(raw ?? "");
        const trimmed = rawExact.trim();
        const aimStripped = stripAimPrefix(trimmed);
        const aimPrefix = AIM_PREFIX_RE.test(trimmed) ? trimmed.slice(0, 3) : null;

        let mode = "none";
        let detailed = { fields: [], leftover: "" };

        if (!trimmed) {
            return {
                rawExact,
                rawTrimmed: trimmed,
                aimPrefix,
                aimStripped,
                mode,
                fields: [],
                leftover: "",
                length: rawExact.length,
                prefillCandidates: buildPrefillCandidates({}, {}),
            };
        }

        if (isHumanReadableGs1(aimStripped)) {
            mode = "human_readable";
            detailed = parseHumanReadableDetailed(aimStripped);
        } else if (hasGs1Structure(rawExact, aimStripped)) {
            mode = "element_string";
            detailed = parseElementStringDetailed(aimStripped);
        } else if (isPlainBatchCode(aimStripped)) {
            mode = "plain_batch";
            detailed = {
                fields: [
                    {
                        ai: "10",
                        name: AI_NAMES["10"],
                        known: true,
                        rawValue: aimStripped,
                        interpreted: aimStripped,
                        lengthMode: "plain",
                        notes: "Plain batch QR (non-GS1 structure)",
                    },
                ],
                leftover: "",
            };
        } else {
            mode = "unparsed";
            detailed = { fields: [], leftover: aimStripped };
        }

        const byAi = {};
        for (const f of detailed.fields) {
            byAi[f.ai] = f.rawValue;
        }

        const interpretedByAi = {};
        for (const f of detailed.fields) {
            interpretedByAi[f.ai] = f.interpreted;
        }

        return {
            rawExact,
            rawTrimmed: trimmed,
            aimPrefix,
            aimStripped,
            mode,
            fields: detailed.fields,
            leftover: detailed.leftover || "",
            length: rawExact.length,
            parsed: byAi,
            prefillCandidates: buildPrefillCandidates(byAi, interpretedByAi),
        };
    }

    /**
     * Structured shape for future Final Pallet Count prefill.
     * Does not write to any form — diagnostic storage only.
     */
    function buildPrefillCandidates(rawByAi, interpretedByAi) {
        const candidates = {};
        const sources = {};
        for (const [ai, meta] of Object.entries(FINAL_PALLET_COUNT_AI_MAP)) {
            const raw = rawByAi[ai];
            if (raw === undefined || raw === null || raw === "") continue;
            const value =
                interpretedByAi[ai] !== undefined ? interpretedByAi[ai] : interpretAiValue(ai, raw);
            candidates[meta.form_field] = value;
            sources[meta.form_field] = {
                ai,
                ai_name: AI_NAMES[ai] || null,
                raw_value: raw,
                form_label: meta.form_label,
                form_region: meta.form_region,
            };
        }
        return {
            form_type: "final_pallet_count",
            doc_number: "FOR PK 012A",
            candidates,
            sources,
        };
    }

    function extractBatchLot(raw) {
        const normalized = String(raw || "").trim();
        const s = stripAimPrefix(normalized);
        if (!s) {
            return {
                batchLot: null,
                parsed: {},
                productionDate: null,
                count: null,
                looksGs1: false,
            };
        }

        if (isPlainBatchCode(s) && !hasGs1Structure(raw, s)) {
            return {
                batchLot: s,
                parsed: {},
                productionDate: null,
                count: null,
                looksGs1: false,
            };
        }

        const parsed = parseGS1(raw);
        const batchLot = parsed["10"] || null;
        const looksGs1 = hasGs1Structure(raw, s) && Object.keys(parsed).length > 0;

        return {
            batchLot,
            parsed,
            productionDate: parsed["11"] || null,
            count: parsed["37"] || null,
            looksGs1,
        };
    }

    /** Render raw string with control characters made visible. */
    function formatRawVisible(raw) {
        const s = String(raw ?? "");
        let out = "";
        for (let i = 0; i < s.length; i++) {
            const code = s.charCodeAt(i);
            const ch = s[i];
            if (code === 29) {
                out += "<GS>";
            } else if (code === 28) {
                out += "<FS>";
            } else if (code === 30) {
                out += "<RS>";
            } else if (code === 4) {
                out += "<EOT>";
            } else if (code < 32) {
                out += `\\x${code.toString(16).padStart(2, "0")}`;
            } else if (code === 127) {
                out += "<DEL>";
            } else {
                out += ch;
            }
        }
        return out;
    }

    function formatRawHex(raw) {
        const s = String(raw ?? "");
        const parts = [];
        for (let i = 0; i < s.length; i++) {
            parts.push(s.charCodeAt(i).toString(16).padStart(2, "0"));
        }
        return parts.join(" ");
    }

    window.GS1Parse = {
        parseGS1,
        parseGS1Detailed,
        extractBatchLot,
        interpretAiValue,
        buildPrefillCandidates,
        formatRawVisible,
        formatRawHex,
        GS1_AI_LENGTHS,
        AI_NAMES,
        FINAL_PALLET_COUNT_AI_MAP,
        GS_CHAR,
    };
})();
