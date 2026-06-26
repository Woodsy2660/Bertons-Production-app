/**
 * GS1 parser tests — run: node tests/test_gs1_parse.mjs
 * Loads gs1-parse.js in a minimal browser-like global.
 */

import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import vm from "vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gs1Source = readFileSync(
    join(__dirname, "../app/static/js/gs1-parse.js"),
    "utf8"
);

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(gs1Source, sandbox);

const { parseGS1, extractBatchLot, GS_CHAR } = sandbox.window.GS1Parse;

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

const example = "(37)1512(10)MO-041488-120405(11)260408(240)22";
const parsed = parseGS1(example);
assert(parsed["10"] === "MO-041488-120405", `AI 10 human-readable: ${parsed["10"]}`);
assert(parsed["37"] === "1512", `AI 37: ${parsed["37"]}`);
assert(parsed["11"] === "260408", `AI 11: ${parsed["11"]}`);
assert(parsed["240"] === "22", `AI 240: ${parsed["240"]}`);

const withGs = `37${1512}${GS_CHAR}10MO-041488-120405${GS_CHAR}11260408${GS_CHAR}24022`;
const element = parseGS1(withGs);
assert(element["10"] === "MO-041488-120405", `AI 10 element+GS: ${element["10"]}`);
assert(element["37"] === "1512", `AI 37 element: ${element["37"]}`);

const withAim = `]C1371512${GS_CHAR}10MO-041488-120405`;
const aim = parseGS1(withAim);
assert(aim["10"] === "MO-041488-120405", `AI 10 after AIM strip: ${aim["10"]}`);

const lot = extractBatchLot(example);
assert(lot.batchLot === "MO-041488-120405", "extractBatchLot");
assert(lot.count === "1512", "extract count");
assert(lot.productionDate === "260408", "extract prod date");

const plainQr = "MO-041488-120405";
const plain = extractBatchLot(plainQr);
assert(plain.batchLot === "MO-041488-120405", `plain QR batch: ${plain.batchLot}`);
assert(!plain.looksGs1, "plain QR must not be treated as GS1");
assert(Object.keys(plain.parsed).length === 0, "plain QR must not false-parse AIs");

console.log("All GS1 parser tests passed.");