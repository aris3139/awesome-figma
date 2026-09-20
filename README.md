# awesome-figma

Turn a Figma selection into structured, line-citable screen evidence — from the clipboard, with no Figma token, plugin
or draft copy. Select the frames in Figma, press ⌘C, run one command: every screen becomes a folder with a `context.txt`
that says exactly what is on it (layout, spacing, text, colours, states, navigation links), plus a UI map that shows how
many logical screens and states the design really has.

This is the scanner behind the [awesome](https://github.com/aris3139/awesome-plugin) pipeline, published on its own so a
team can scan designs without the rest of that workflow.

## Requirements

- macOS (the payload is read from the system clipboard) · Claude Code with plugins enabled
- `python3` 3.10+ · `node` 22+ and `bun` (for `scripts/figclip`)

## Install

```bash
claude plugin marketplace add aris3139/awesome-figma
claude plugin install awesome@aris-figma
cd "$(claude plugin details awesome@aris-figma 2>/dev/null | grep -o '/.*awesome' | head -1)/scripts/figclip" && bun install   # once, in the installed plugin dir
```

The plugin is named `awesome` so the command reads `/awesome:figma …`. Do **not** install it on a machine that already has the
full `awesome` pipeline plugin — same name, it would collide; that plugin already contains this scanner.

Development: clone, symlink into the skills directory (`ln -s <clone> ~/.claude/skills/awesome-figma`), `bun install`
in `scripts/figclip`. Skills reload live; `/reload-plugins` after editing anything else.

## Use

| Want | Do |
|---|---|
| Scan a design | In Figma select the root frame (or ⌘A on the page) → ⌘C → `/awesome:figma creator <dir>` — `<dir>` optional, default `~/Downloads/<name-of-the-copied-frame>` |
| Design changed | ⌘C again → `/awesome:figma update [<dir>]` — default: the last scanned dir. Prints `changed / new / unchanged / unknown` per screen and applies it |
| Screenshots (optional) | Select a frame → ⌘⇧C → the skill saves it as ground truth; missing screenshots are a warning, never a stop |

Output tree:

```text
<dir>/
  _scan/      manifest.json · index.md (screen list, Figma names, node-ids, clusters) · clusters.json · UI_MAP.md · ui_map.json
              DESIGN_TOKENS.txt · CONTEXT_FORMAT.md (how to read context.txt) · CHANGES.md · clips/ (decoded payloads)
  screens/    <screen>_<case>/  raw.json · context.txt · summary.txt · tokens.txt · screenshot.png · icons.json · icons/*.svg
              noise/            frames filtered out, kept for audit
```

`context.txt` is a node tree with only the properties that differ from Figma defaults: `layout=ROW, gap=8,
padding=(…)`, `w=fill`, `fill=#…`, `r=8`, text `size/weight/lineHeight/letterSpacing/maxLines`, `→ ON_CLICK NAVIGATE
"Screen"`, overlays as `scrim=`, button labels under `stateLayer=`. The full dictionary is `reference/context-format.md`
and travels with every scan as `_scan/CONTEXT_FORMAT.md`.

`UI_MAP.md` groups look-alike screens into one logical screen per cluster and lists its designed states, navigation
edges and hints such as "list without an empty state" — everything inferred from names, diffs and text, marked as such.

## How it works

`⌘C` → the HTML clipboard flavor carries a fig-kiwi scene → `figclip dump` (decode on disk; the raw never enters the
model) → `figclip rest` (resolve instances, overrides, slots, swaps, render-time variants; drop hidden nodes) →
`figma_deep_scan.py` (filters, layout/padding/gap from true auto-layout values, overlay and state-layer handling,
tokens) → `screen_cluster.py` (variants around a base screen, unified diffs) → `ui_map.py`. Engine notes:
`reference/SCANNER_NOTES.md`.

## Layout

```text
.claude-plugin/     plugin.json (name awesome) · marketplace.json (aris-figma)
skills/figma/       the skill (creator · update)
reference/          scan.md (procedure) · context-format.md (dictionary) · SCANNER_NOTES.md (engine)
scripts/            figma_deep_scan.py · feature_layout.py · screen_cluster.py · ui_map.py · regress.py · release.sh · figclip/
bin/                figclip · awesome-figma-sync
tests/              scanner regressions on real payload shapes, clustering, UI map, layout
```

## Development

```bash
python3 -m unittest discover -s tests
bash -n bin/* scripts/release.sh && claude plugin validate .
```

One CHANGELOG bullet per change; `scripts/release.sh patch|minor|major` tags `awesome--vX.Y.Z` and publishes the
GitHub Release. Changing a file or field of the output tree is a **major** bump: the `awesome` plugin reads it.

## License

MIT — see `LICENSE`. Vendored third-party code and notices: `scripts/figclip/THIRD_PARTY.md` (two MIT files from
georg3103/figma-clipboard-mcp and allan-simon/figma-kiwi-protocol; npm deps `kiwi-schema`, `fzstd`, both MIT).
