#!/usr/bin/env node
// Pull the standalone diagram SVG out of an archify-delivered HTML file.
//
// archify `deliver` writes one self-contained HTML whose diagram is a single
// inline <svg> (brand icons may nest more <svg> inside it — that's fine, we take
// the outermost span). The inline tag has no xmlns and leans on <html
// data-theme=...> for light/dark, neither of which survives on its own. This
// script lifts first `<svg` … last `</svg>`, injects the SVG namespace, and
// stamps data-theme on the root so the file renders correctly when officecli
// embeds it into a .docx / .pptx / .xlsx (all three accept SVG pictures).
//
// Zero dependency, no browser. PNG rasterisation is a separate step and needs
// Chrome (see SKILL.md); most Office use wants the SVG anyway.
//
//   node extract-svg.mjs <archify.html> <out.svg> [--theme light|dark]

import { readFileSync, writeFileSync } from "node:fs";

const [, , inPath, outPath, ...rest] = process.argv;
if (!inPath || !outPath) {
  console.error("usage: extract-svg.mjs <archify.html> <out.svg> [--theme light|dark]");
  process.exit(2);
}

let theme = "light";
for (let i = 0; i < rest.length; i++) {
  if (rest[i] === "--theme") theme = rest[++i];
}
if (theme !== "light" && theme !== "dark") {
  console.error(`--theme must be light or dark, got ${JSON.stringify(theme)}`);
  process.exit(2);
}

const html = readFileSync(inPath, "utf8");
const open = html.indexOf("<svg");
const close = html.lastIndexOf("</svg>");
if (open === -1 || close === -1 || close < open) {
  console.error(`no <svg>…</svg> found in ${inPath} — was it produced by 'archify deliver'?`);
  process.exit(1);
}
let svg = html.slice(open, close + "</svg>".length);

// End of the opening <svg ...> tag.
const tagEnd = svg.indexOf(">");
let head = svg.slice(0, tagEnd);
const body = svg.slice(tagEnd);

if (!/\sxmlns=/.test(head)) head += ' xmlns="http://www.w3.org/2000/svg"';
if (/xlink:/.test(svg) && !/xmlns:xlink=/.test(head)) {
  head += ' xmlns:xlink="http://www.w3.org/1999/xlink"';
}
if (/\sdata-theme=/.test(head)) {
  head = head.replace(/\sdata-theme="[^"]*"/, ` data-theme="${theme}"`);
} else {
  head += ` data-theme="${theme}"`;
}

const out = `<?xml version="1.0" encoding="UTF-8"?>\n${head}${body}\n`;
writeFileSync(outPath, out, "utf8");
console.error(`wrote ${outPath} (${out.length} bytes, theme=${theme})`);
