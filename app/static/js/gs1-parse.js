/**
 * GS1 Application Identifier parser for pallet/carton labels.
 * Supports element strings (with/without FNC1/GS) and human-readable (NN)value form.
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
        "240": 0,
        "241": 0,
        "410": 13,
        "414": 13,
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

    window.GS1Parse = {
        parseGS1,
        extractBatchLot,
        GS1_AI_LENGTHS,
        GS_CHAR,
    };
})();