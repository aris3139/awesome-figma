# awesome-figma — repo rules for Claude Code sessions opened here

- Source of truth for the `awesome-figma` repo (plugin name `awesome`, skill `figma`, so the command is `/awesome:figma`) (`~/.claude/skills/awesome-figma` is a symlink to this clone). Edit here, commit here.
- Every behaviour change adds one bullet under `## Unreleased` in `CHANGELOG.md` (`<area>: what — why`).
- Never edit `version` in `.claude-plugin/plugin.json` by hand — `scripts/release.sh patch|minor|major` does it.
- `python3 -m unittest discover -s tests` and `bash -n bin/* scripts/release.sh` before pushing.
- Git identity here is `aris <aris3139@users.noreply.github.com>` — never a work identity.
- The output contract (`_scan/*`, `screens/*/context.txt`, `CONTEXT_FORMAT.md`) is consumed by the `awesome` plugin: changing a field or file name is a **major** bump and needs a matching `awesome` release.
