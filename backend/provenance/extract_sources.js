#!/usr/bin/env node
// Snapshot the TerraScope Observatory SOURCES id map into pinned JSON.
// Usage: node extract_sources.js <collections.html> <out.json>
const fs = require("fs");
const [,, htmlPath, outPath] = process.argv;
const html = fs.readFileSync(htmlPath, "utf8");
const marker = "const SOURCES = ";
const start = html.indexOf(marker);
if (start < 0) { console.error("SOURCES block not found"); process.exit(1); }
const arrStart = start + marker.length;
const arrEnd = html.indexOf("\n];", arrStart);
if (arrEnd < 0) { console.error("SOURCES block end not found"); process.exit(1); }
const literal = html.slice(arrStart, arrEnd + 2);
let sources;
try { sources = eval(literal); } catch (e) { console.error("SOURCES parse failed: " + e.message); process.exit(1); }
if (!Array.isArray(sources) || sources.length !== 14) {
  console.error("expected 14 sections, got " + (Array.isArray(sources) ? sources.length : typeof sources));
  process.exit(1);
}
// 9-ovni: folder holds 39, b1's page carried 36 at snapshot time. These 3 ids
// come verbatim from b1's handoff (2026-10-04T21:02Z, pulled from the folder
// listing). Dedupe by filename so a later page update cannot double-count.
const NINE_OVNI_EXTRA = [
  ["image0036.jpg", "1nKENjWmnsWnD0en3QTa5DTnT6tFieezx"],
  ["image0037.jpg", "1jqZDS38wAVQhC90oPln8n7BlT86bVFiL"],
  ["image0038.jpg", "1XymQiWUKlwwEqCFL6QBvnaeISpX65D3H"]
];
const si9o = sources.find(s => s.key === "si9o");
if (!si9o) { console.error("si9o section missing"); process.exit(1); }
const have = new Set(si9o.frames.map(f => f[0]));
for (const f of NINE_OVNI_EXTRA) if (!have.has(f[0])) si9o.frames.push(f);
const out = {
  source_url: "https://sites.hellominds.ai/b1/biotic-model/collections.html",
  extracted_at: new Date().toISOString(),
  note: "frame ids as served by the collections page SOURCES block; 9-ovni supplemented with 3 folder ids from b1 2026-10-04 handoff; images only (side files .dat/.sh/.mpeg excluded); 18-4 v447 absent from the Drive folder by construction, so its 60-entry manifest is the complete truth",
  sections: sources.map(s => ({
    key: s.key,
    label: s.label,
    dt: s.dt || null,
    frames: s.frames.map(f => ({ filename: f[0], drive_id: f[1] }))
  }))
};
fs.writeFileSync(outPath, JSON.stringify(out, null, 1) + "\n");
const total = out.sections.reduce((n, s) => n + s.frames.length, 0);
console.log("sections: " + out.sections.length + ", frames: " + total);
