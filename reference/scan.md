# scan.md — Figma evidence from the clipboard (fig-kiwi) → screen folders

Load for `creator [<dir>]` (no scan in the dir yet) and `update [<dir>]` (a scan exists). The only source is the macOS clipboard
after ⌘C in Figma: the HTML flavor carries the full fig-kiwi scene of the selection (masters, overrides, slots,
variables, vector geometry). Works on read-only files; no token, no plugin, no socket. The raw payload is decoded on
disk and never enters the model context. Engine notes: `reference/SCANNER_NOTES.md`. Output tree: `skills/figma/SKILL.md`.

```bash
R="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/awesome-figma}"; CONF="$HOME/.config/awesome-figma"
# DIR = the argument (absolute, or relative to $PWD); none → ~/Downloads/<slug of the copied root frame or page>.
# `update` without an argument → $(cat "$CONF/last_dir").
SCANNER="$R/scripts/figma_deep_scan.py"          # figclip = $R/bin/figclip (dump | rest | check | icons)
```

Screen folder = **semantic** `<screen>_<case>` (Step 4), never the raw frame name. Per screen: `raw.json`
(REST-shaped, from `figclip rest`) · `context.txt` · `summary.txt` · `tokens.txt` · `screenshot.png` (⌘⇧C, may be
missing → WARN) · `diff_vs_<base>.txt` (variants). Icons: `ICON "<name>" (W×H)` inline in context + `icons.json`; the SVG files come from §3b (`figclip icons`).

---

## 1. Get the payload

Ask once, in Vietnamese: *"Trong Figma mở file Design → chọn frame gốc chứa các màn (hoặc ⌘A trên page) → ⌘C → nhắn
'đã copy'. Đừng dán vào chat."* Then:

```bash
DIR="<dir>"; mkdir -p "$DIR/_scan/clips" "$DIR/screens/noise"; mkdir -p "$CONF"; printf '%s' "$DIR" > "$CONF/last_dir"
figclip dump "$DIR/_scan/clips/$(date +%Y%m%d-%H%M%S).clip.json"      # prints meta.fileKey · node count · html KB
```

| Problem | Fix |
|---|---|
| `Clipboard has no Figma payload` | clipboard changed since ⌘C → ask to ⌘C again (pasting elsewhere may overwrite it) |
| payload has 1 screen but the design has many | user copied one frame → ask for the root frame / ⌘A; with `update` that is fine (only that screen is compared) |
| `fileKey` differs from manifest | Design file vs earlier draft copy — node-ids are stable across duplicates, keep going, note it in index |

## 2. Split into screens and scan

Top-level copied nodes = children of the non-internal CANVAS in `nodeChanges`; a root frame → its children.
Screens = phone-sized frames (380–480 × 700–1000 px). For each screen node `<id>`:

```bash
D="$DIR/screens/<tmp_name>"; mkdir -p "$D"
figclip rest "$CLIP" "<id>" "$D/raw.json"                      # resolves instances/overrides/slots/swaps, drops hidden
python3 "$SCANNER" --context --tokens --exclude "Status Bar" "Bottom Bar" "Scroll Edge Effect" -o "$D" -- "$D/raw.json"
python3 "$SCANNER" --summary --exclude "Status Bar" "Bottom Bar" "Scroll Edge Effect" -o "$D" -- "$D/raw.json"
```

`figclip rest` flags: `--plugin-compat` (legacy field set, only for comparing against old baselines) · `--keep-hidden`
(emit hidden nodes as empty shells — never for real evidence). Default = rich: true `layoutMode/padding/gap/sizing`
(instance overrides applied), constraints, absolute children, min/max, effects (inner/drop shadow, blur — `GLASS` is
dropped on purpose), per-side borders/dashes, blend, rotation, mask, text truncation/vertical align/auto-size, prototype
links (`→ … NAVIGATE "<frame>"` = navigation evidence), numeric `fontWeight`; the scanner prefers these and only infers
when absent. Dictionary: `reference/context-format.md`.

Also write `_scan/DESIGN_TOKENS.txt` by running the scanner once on the root node with `--tokens` (or merge per-screen
`tokens.txt`).

## 3. Screenshots

Read-only files cannot be exported by script. For every **new or changed** screen ask: *"Chọn frame `<name>` → ⌘⇧C
(Copy as PNG)"* → `figclip dump --png "$D/screenshot.png"`. Missing screenshot → `Status: WARN no-screenshot` in
`index.md`; it never blocks the plan (cross-validation in Step 4a is then skipped for that screen).

### 3b. Icons → SVG (only the static glyphs the evidence uses)

```bash
figclip icons "$CLIP" "<id>" "$D"        # → $D/icons/ic_<glyph>_<W>x<H>.svg + $D/icons/ICONS.md
```

Runs after the scanner (`icons.json` = the ids it flattened to `ICON`). For each id the nearest glyph INSTANCE ≤ 48 px
is exported (background shapes dropped), `viewBox = 0 0 W H` of the glyph box, file `ic_<slug>_<W>x<H>.svg`; a generic
layer name falls back to the leaf name — ask Design to name icon layers or map by hand in `[ASSETS]`. Classifier:
IMAGE fill / content-like name / ≥ 3 same-name siblings with different geometry / imported artwork → `dynamic` (listed,
not written; `--include-dynamic` forces); colour-variable fill or ≤ 2 colours → `static`; else `unsure`. Plain shapes
(grabber, divider) → `kind=shape`, draw in code. One file per component, `ICONS.md` lists every reuse with node-ids.
`no geometry in payload` = old dump → ⌘C again. Dev imports `icons/*.svg` as Vector Assets.

## 4. Cross-validate + curate (mandatory)

- 4a cross-validate (when a screenshot exists): context node not visible in the screenshot → drop; element in the
  screenshot missing from context → investigate (`SCANNER_NOTES` filters).
- 4b semantic naming `<screen>_<case>`: read TEXT nodes + diff against sibling screens + screenshot
  (`frame_12` → `standings_playoff_row`); main screen without a case → `<screen>`. Rename the temp folder.
- 4c cluster variants: `python3 "$R/scripts/screen_cluster.py" "$DIR"` → `_scan/clusters.json` (`K01` base +
  variants) + `screens/<variant>/diff_vs_<base>.txt`. Copy-and-tweak screens are **variants, never noise**. Idempotent.
- 4c′ UI map: `python3 "$R/scripts/ui_map.py" "$DIR"` → `_scan/UI_MAP.md` + `ui_map.json`: one logical screen per
  cluster with its designed states (name tokens, variant diffs, text cues), `→ NAVIGATE` edges in/out (targets resolved
  by Figma name), `⚠ thiếu` hints (loading without error, list without empty, dead-end targets). Everything INFERRED,
  never a gate; consumers read it first. Re-run after every curation change (needs `index.md` names).
- 4d noise → `screens/noise/`: junk frames (`group_<n>`/`frame_<n>` adding no content) with reason; names containing
  `copy/old/backup/wip/test` → collect, ask the user once. "keep screen X" → move back.
- 4e `_scan/index.md`: `| Folder | Original Figma name | node-id | Cluster | Case description | Status |`.
- 4f `_scan/manifest.json`: `figma_file_key = meta.fileKey`, `root_node`, `screens` (active only) with `node_id`,
  `scanned_at`, `content_hash` = sha256(`context.txt`), `screenshot_hash` (or null), `source: "clipboard"`,
  `clip: "_scan/clips/<file>"`, `n_active`, `n_clusters`. No other tool's keys.
- 4g dictionary: `cp "$R/reference/context-format.md" "$DIR/_scan/CONTEXT_FORMAT.md"` — the tree must be readable
  without this plugin.

## 5. Handoff — the scan is the end of `creator`

Report the output path, active/noise counts, the UI map line, screens without screenshot, then stop:

```text
Scan done: <dir> — <n> active screens (<m> noise), <k> without screenshot.
UI map: <j> logical screens · <s> with a state in the name · <e> NAVIGATE edges (<u> leaving the clipboard) · <h> missing-state hints → _scan/UI_MAP.md
next: read _scan/UI_MAP.md and _scan/index.md first; screens/<name>/context.txt is the UI authority (dictionary: _scan/CONTEXT_FORMAT.md).
```

`creator` never continues into planning or code: the tree is evidence only.

## 7. `update [<dir>]` — a scan exists, the user ⌘C'd again (default dir: `$CONF/last_dir`)

One command does check **and** apply. Never re-scan the whole dir by hand; key = node-id (manifest `screens`).

```bash
figclip check "$DIR" [clip.json]        # dumps the clipboard when no clip is given → _scan/CHANGES.md
```

1. **Check**: per screen in the payload `rest` → scanner → sha256(`context.txt`) vs manifest `content_hash` →
   `_scan/CHANGES.md` with `changed / new / unchanged / unknown` (+ line-diff counts). Print the table.
   `unknown` = not in the selection, never "deleted" — untouched. Nothing changed and nothing new → say so and stop.
2. **Apply — changed**: overwrite the folder's evidence files (keep the folder name; rename only when the case meaning
   changed) → screenshot request (§3) when the visual changed → manifest `scanned_at`/hashes, index description →
   short property diff (previous `clip.json` vs new).
3. **Apply — new**: scan into a temp folder → semantic name diffed against **all** existing screens (§4b) → screenshot
   request → curate (a look-alike is a cluster variant, not noise) → append manifest + `index.md`.
4. `screen_cluster.py` → `ui_map.py` → regenerate `DESIGN_TOKENS.txt` and `CONTEXT_FORMAT.md` → report the CHANGES table.

First `update` after a feature was scanned by the retired WebSocket source reports every screen `changed` (different
source, same design) → apply once = re-baseline. No `remove`: surplus screens go to `screens/noise/` by hand.

## 8. CLI quick reference

```text
figclip dump <out.json> [--png <file>]                # clipboard → decoded scene / PNG
figclip rest <clip.json> <nodeId> <out.json> [--plugin-compat] [--keep-hidden]
figclip check <feature-dir> [clip.json]               # → _scan/CHANGES.md
figclip icons <clip.json> <nodeId> <screen-dir> [--icon-max N]   # → <screen-dir>/icons/*.svg + ICONS.md (filter = context.txt)
figma_deep_scan.py [--context] [--tokens] [--summary] [--exclude NAME…] [--keep-decorative] [--margin N]
                   [--split-screens] [-o DIR] -- <raw.json>
screen_cluster.py <feature-dir> [--threshold 0.8] [--dry-run]
ui_map.py <feature-dir> [--dry-run]            # _scan/UI_MAP.md + ui_map.json (after screen_cluster.py)
```

Context dictionary for reading `context.txt`: `reference/context-format.md` (copied into each scan as `_scan/CONTEXT_FORMAT.md`).
