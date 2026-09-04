---
name: diagram-to-office
description: Turn an architecture / workflow / sequence / dataflow / lifecycle diagram into a picture embedded in a .docx, .pptx, or .xlsx. Bridges the archify skill (diagram → self-contained HTML + SVG) and officecli (SVG/PNG → Office document). Use when the user asks to put a diagram, architecture map, or flow chart into a Word doc, slide deck, or spreadsheet.
---

# diagram-to-office

Two skills already do the halves; this one wires them together.

- **archify** (`.agents/skills/archify/`) — authors a validated diagram and renders
  it to one self-contained HTML file with an inline `<svg>`. No third-party
  service, no deps, runs on Node ≥ 18.
- **officecli** — reads/edits `.docx` `.xlsx` `.pptx`; its `image`/`picture`
  element accepts **SVG** on all three formats. Single binary, install:
  `curl -fsSL https://d.officecli.ai/install.sh | bash` (already bundled in this
  project's Docker image — see `services/officecli.py`, exposed to the bot as the
  `office_*` tools; that runtime path is separate from this coding-agent skill).

## Which route

| Want | Route |
|---|---|
| Rich, styled, validated diagram (5 types, showcase quality, brand icons) | **archify → SVG → officecli** (below) |
| Quick flow chart, editable as native Word/PPT shapes, no styling needs | `officecli add <file> <parent> --type diagram --format flowchart --prop text='<mermaid>'` — Mermaid straight in, no archify |

## archify → SVG → Office

Run archify commands from `.agents/skills/archify/`. Set
`ARCHIFY_UPDATE_CHECK_DISABLED=1` to skip its optional version ping.

```bash
cd .agents/skills/archify
export ARCHIFY_UPDATE_CHECK_DISABLED=1

# 1. Author + render. Types: architecture | workflow | sequence | dataflow | lifecycle.
#    Author spec.json per archify/SKILL.md (read one schema + one example first).
node bin/archify.mjs validate <type> spec.json --quality showcase --json
node bin/archify.mjs deliver  <type> spec.json /tmp/diagram.html --quality showcase --json

# 2. Lift the standalone SVG out of the HTML (zero-dep, no browser).
#    --theme light for documents on a white page; dark for dark decks.
cd -
node .agents/skills/diagram-to-office/scripts/extract-svg.mjs /tmp/diagram.html /tmp/diagram.svg --theme light
```

Then embed. Exact `--prop` names vary by element — **run `officecli help <fmt> <elem>`
instead of guessing** (`officecli help pptx picture`, `officecli help docx image`,
`officecli help xlsx image`):

```bash
# PowerPoint — picture on a slide
officecli create deck.pptx
officecli add deck.pptx '/slide[1]' --type picture --prop <src-prop>=/tmp/diagram.svg --prop <size/pos props>

# Word — image in the body (inline types insert at a text anchor; see officecli SKILL.md "Anchored insertion")
officecli add report.docx /body --type paragraph --prop text="Architecture" --prop style=Heading1
officecli add report.docx /body --type image --prop <src-prop>=/tmp/diagram.svg

# Excel — image floating on a sheet
officecli add sheet.xlsx /Sheet1 --type image --prop <src-prop>=/tmp/diagram.svg

officecli close <file>   # flush before anything non-officecli reads it
```

## PNG instead of SVG

Only if a target rejects SVG. archify's rasteriser is a **reader capability inside
the delivered HTML** (export button) — headless PNG needs Chrome/Chromium:

```bash
cd .agents/skills/archify
node bin/archify.mjs visual-check /tmp/diagram.html --json   # writes screenshots when Chrome is present; status "skipped" without it
```

No Chrome on the box → use the SVG route; every Office format supports it.

## Prerequisites

- Node ≥ 18 (archify + the extractor).
- `officecli` on PATH (install line above) — **not present on the dev machine by
  default**; it is in the c2a Docker image.
- Chrome/Chromium **only** for the optional PNG path.

## Verified

`archify deliver` → `extract-svg.mjs` produces well-formed standalone SVG
(`xmlns` injected, `viewBox` kept, `data-theme` stamped) for architecture,
sequence, and lifecycle types — measured 2026-09-04 on Node 24. The `officecli
add` step is documented, not run here (binary absent on this machine).
