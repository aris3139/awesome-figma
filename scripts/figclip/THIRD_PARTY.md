# Third-party code in `scripts/figclip/`

## Vendored files

### `figparse.js` — from [georg3103/figma-clipboard-mcp](https://github.com/georg3103/figma-clipboard-mcp)
fig-kiwi container parsing (deflate schema + zstd scene) and macOS clipboard read. Used unmodified except import paths.

MIT License — Copyright (c) 2026 georg3103

### `svg.mjs` — from [allan-simon/figma-kiwi-protocol](https://github.com/allan-simon/figma-kiwi-protocol)
`vectorNetworkBlob` / `commandsBlob` → SVG path. **Modified** in this repo (2026-09-18): `commandsBlobToPath` and
`vectorNetworkBlobToPath` are wrapped in try/catch and bounds-check each command so a truncated or corrupt blob returns
`null` instead of throwing (`RangeError`). The original functions are kept as `*Unsafe`.

MIT License — Copyright (c) 2026 Allan Simon

MIT permission notice (applies to both files above):

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
> rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
> persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice
> and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS
> PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
> MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
> HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
> ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## npm dependencies (not vendored; installed by `bun install`)

- `kiwi-schema` — Evan Wallace, MIT — https://github.com/evanw/kiwi
- `fzstd` — Arjun Barrett, MIT — https://github.com/101arrowz/fzstd

## Ideas, not code

The verifier/gate design borrows *patterns* seen in several Claude Code toolkits (a delegation block for subagents,
a unit-status vocabulary, "never trust the builder's summary", a compaction guard). No text or code from proprietary
toolkits is copied; wording here is our own.
