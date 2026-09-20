---
name: figma
description: Figma screen evidence from the macOS clipboard (⌘C in Figma; read-only files OK, no API token, no plugin) — decode, split into screens, scan each into context.txt, cluster look-alikes, write a UI map, detect what changed. Use for "creator <dir>", "update [<dir>]", "scan figma", "anh vừa copy/⌘C frame", "màn nào đổi", context.txt, UI_MAP, figclip.
argument-hint: "creator [<dir>] | update [<dir>]"
---

# awesome-figma — Figma evidence (scan · curate · change-detect)

Output is **evidence**, never a blueprint or code. The only input is the macOS clipboard after ⌘C in Figma: the HTML
flavor carries the full fig-kiwi scene of the selection (masters, overrides, slots, variables, true layout values,
effects, vector geometry). `figclip dump` decodes it on disk — the raw payload never enters the model. Works on
read-only Design files; no token, no draft copy, no socket.

Procedure: read `${CLAUDE_PLUGIN_ROOT}/reference/scan.md` and follow it. Dictionary for reading `context.txt`:
`reference/context-format.md` (a copy is written into every scan as `_scan/CONTEXT_FORMAT.md`). Engine/mapper rules
only when debugging: `reference/SCANNER_NOTES.md`.

```bash
R="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/awesome-figma}"; CONF="$HOME/.config/awesome-figma"
```

## Two commands

| Command | Target dir | Do (scan.md §) |
|---|---|---|
| `creator [<dir>]` | `<dir>` as given (absolute or relative to `$PWD`); omitted → `~/Downloads/<slug>` where `<slug>` = the copied root frame / page name in kebab-case (ask when it cannot be derived). The dir must not already hold a scan → otherwise STOP "use `update`" | §1 dump → §2 split + `figclip rest` + scanner per screen → §3 screenshots → §3b `figclip icons` → §4 curate / cluster / UI map / index / manifest / dictionary copy → §5 stop and report. Writes `$CONF/last_dir` |
| `update [<dir>]` | `<dir>` as given; omitted → `$CONF/last_dir` (the last scan) | §7: dump → per-screen hash vs manifest → table `changed / new / unchanged / unknown` → **apply**: changed → overwrite evidence, new → curate + add, unknown → untouched → cluster, UI map, index, manifest, tokens. Nothing changed → say so, stop |

Output tree (`<dir>`):

```text
_scan/      manifest.json · index.md · clusters.json · UI_MAP.md · ui_map.json · DESIGN_TOKENS.txt · CONTEXT_FORMAT.md · CHANGES.md · clips/
screens/    <screen>_<case>/  raw.json · context.txt (UI authority) · summary.txt · tokens.txt · screenshot.png · icons.json · icons/ · diff_vs_<base>.txt
            noise/<name>/     filtered frames, kept for audit, never read as evidence
```

Ask once, in Vietnamese: *"Trong Figma mở file Design → chọn frame gốc chứa các màn (hoặc ⌘A trên page) → ⌘C → nhắn
'đã copy'. Đừng dán vào chat."* Screenshots: *"chọn frame → ⌘⇧C (Copy as PNG)"* per new/changed screen →
`figclip dump --png …`; missing = WARN, never a stop.

Force-stops: `creator` on a dir that already has `_scan/manifest.json` → "use `update`" · `update` on a dir without
one → "use `creator`" · no Figma payload in the clipboard (ask to ⌘C again) · no phone-sized frames in the payload.

## Guards

- Never paste-check the payload in chat; never ask for a Figma token, a plugin channel or a draft copy.
- Copy-and-tweak screens are cluster **variants**, never noise; names with `copy/old/backup/wip/test` → ask once.
- `unknown` in `CHANGES.md` means "not in this selection", never "deleted".
- Every curation decision the human makes (names kept, screens to noise) is written to `_scan/index.md` at once.

## Handoff

After `creator`: output path · active/noise counts · the UI map line (logical screens, states, NAVIGATE edges,
missing-state hints) · screens without screenshot · `next:` = what the consumer does with the tree (for the `awesome`
pipeline: load the BA, then `/awesome:plan`; on its own: read `_scan/UI_MAP.md` and `_scan/index.md` first). After
`update`: the CHANGES table and what was replaced/added.
