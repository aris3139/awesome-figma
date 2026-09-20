# Changelog

One bullet per change under `## Unreleased`, in the same commit as the change, shaped `<area>: what — why`.
`scripts/release.sh patch|minor|major` moves the section under the new version and publishes it as the GitHub Release
notes. Bump: **patch** = wording or bug fix · **minor** = new flag/file/behaviour that keeps old scans readable ·
**major** = the output contract changes (a file or field in `_scan/` or `screens/*/context.txt` renamed, removed or
re-meaning) — consumers such as the `awesome` plugin must follow.

## Unreleased

## 1.0.0 — 2026-09-20

- Extracted from `awesome` 2.0.0 as a standalone plugin: skill `figma` (`creator [<dir>]`, `update [<dir>]`), clipboard decoder `figclip` (dump · rest · check · icons), scanner `figma_deep_scan.py` 5.4, `screen_cluster.py`, `ui_map.py`, `regress.py`, references `scan.md` · `context-format.md` · `SCANNER_NOTES.md`, 28 tests
- Output goes to the directory the caller names; default `~/Downloads/<slug>`; `update` defaults to the last scanned dir (`~/.config/awesome-figma/last_dir`)
- Every scan writes `_scan/CONTEXT_FORMAT.md` (the dictionary matching the scanner version) so a consumer can read `context.txt` without this plugin
- No pipeline coupling: no `_inputs/`, no `.active`, no blueprint steps — the tree is evidence only

