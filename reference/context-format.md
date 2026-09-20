# context-format.md — dictionary for reading `context.txt`

Load before reading screen evidence. Values are evidence, cited as `L<n>`, never
copied into code directly; colours and sizes should reach code through the project's theme tokens.
`context.txt` is a node tree; indentation = parent/child. Only properties that differ from Figma defaults are printed.

## Node line

```
TYPE "Name" (W×H[, w=fill][, h=fill]) | fill=COLOR | scrim=COLOR | stateLayer=COLOR | r=RADIUS | opacity=N%
  layout=DIRECTION, gap=N, padding=(top=N left=N right=N bottom=N), align=ALIGN, scroll=SCROLL
```

`w=fill` / `h=fill`: the node stretches to the parent's inner size → `fillMaxWidth()` / `fillMaxHeight()`
(`matchParentSize()` inside a Box); the px value is the rendered size at mock width. Absent → fixed/hug size.

| Type | Meaning → Compose |
|---|---|
| `FRAME` | container → `Column` / `Row` / `Box` |
| `INSTANCE` | component instance → a composable (reuse before drawing anew) |
| `TEXT` | text → `Text()` |
| `RECTANGLE` / `ELLIPSE` / `LINE` | shape, image placeholder, circle, divider → `Box` + background / `AsyncImage` / `HorizontalDivider` |
| `GROUP` | visual group, usually an overlay → `Box` |
| `ICON` | flattened vector → `Icon()` (asset from `figclip icons`, `[ASSETS]`) |

## Layout

| Property | Meaning → Compose |
|---|---|
| `layout=ROW` / `COLUMN` / `STACK` | `Row` / `Column` / `Box` |
| `layout=SINGLE` | one-child wrapper kept for its padding (v5.4) → `Box` with that padding |
| `gap=N` · `gap=[N, M]` | `Arrangement.spacedBy(N)` · unequal gaps → explicit `Spacer`s |
| `padding=(top=N left=M …)` | inner padding, this layer only (`rules/12`: never repeated on the child) |
| `align=center` / `start` | cross-axis alignment |
| `scroll=HORIZONTAL` / `VERTICAL` | `LazyRow` / `LazyColumn` |
| `constraints=(h=LEFT_RIGHT v=BOTTOM)` | pin inside a parent without auto-layout (or an `absolute` child): `LEFT/RIGHT/CENTER/LEFT_RIGHT/SCALE` × `TOP/BOTTOM/CENTER/TOP_BOTTOM/SCALE` → `Box` + `align`; `LEFT_RIGHT` = fill |
| `minW=N` `minH=N` `maxW=N` `maxH=N` | designer min/max → `widthIn` / `heightIn` |
| `absolute` + `position=… offset=(x, y)` | child outside the parent's flow (badge, divider, overlay) → `Box` + `Modifier.align(...).offset(...)`, never a Row/Column slot |
| `→ ON_CLICK NAVIGATE "Screen"` · `→ DRAG CLOSE` · `→ ON_CLICK BACK` · `→ AFTER_TIMEOUT …` | prototype link: trigger → action → destination Figma name (map to the folder via `_scan/index.md`; `target not set in Figma` = blank). Navigation evidence, not UI |
| `mode=Set=Mode` | variable mode pinned on the subtree (Light/Dark…) |

## Visual

| Property | Meaning → Compose |
|---|---|
| `fill=#RRGGBB` (`(N%)` = alpha) | background → theme colour token; `fill=[IMAGE]` → `AsyncImage` |
| `scrim=#000000 (32%)` | dim layer of an `Overlay`/`Scrim` wrapper around a dialog/sheet (v5.4: kept, children = the sheet) → `ModalBottomSheet(scrimColor)` / `Dialog`, never a background on the content |
| `stateLayer=COLOR` | Material `State-layer` around a button/list label (v5.4: kept for padding + text) → ripple colour; its `padding=` is the button's inner padding |
| `fill=[GRADIENT_LINEAR 90° #AA 0% → #BB 70% → #CC 100%]` | angle (0° = left→right, 90° = top→bottom) + stops → `Brush.linearGradient(colorStops)`; `GRADIENT_RADIAL` / `ANGULAR` / `DIAMOND` → `radialGradient` / `sweepGradient`; legacy `fill=[GRADIENT …]` (< v5.2) has no angle → direction from screenshot |
| `r=N` · `r=tl=A tr=B br=C bl=D` | corner radius, uniform or per corner → `RoundedCornerShape` |
| `opacity=N%` | `Modifier.alpha` |
| `stroke=COLOR Wpx inside` · `stroke=COLOR sides(b=1) inside` · `stroke=… dashed(10,5)` | border; some sides only → `drawBehind { drawLine }`; dashed → `PathEffect.dashPathEffect` |
| `shadow=COLOR offset=(x,y) blur=N` · `innerShadow=…` | drop / inner shadow → `Modifier.shadow` or custom draw |
| `blur=N` · `blur=N bg` | layer blur / background blur |
| `overflow=hidden` | `Modifier.clip(shape)` |
| `material=glass` | named glass layer (Figma's own `GLASS` effect is dropped on purpose) |
| `blend=LINEAR_DODGE` … | non-normal blend mode → `graphicsLayer` / `drawWithContent` |
| `rotation=N°` | rotated node (ccw positive); the size shown is the rotated box → `Modifier.rotate(-N)` on the unrotated size |
| `mask=alpha` / `mask=luminance` | this node masks the siblings **after** it → `clip(shape)` or `BlendMode.DstIn` |

## Text

```
TEXT "Name" (W×H)
  text="…", size=N, weight=N, font=FAMILY, color=#RRGGBB, letterSpacing=N, lineHeight=N|N%,
  fontStyle=italic, textDecoration=underline|strikethrough, textCase=upper|lower|title, align=CENTER,
  maxLines=N, overflow=ellipsis, vAlign=center|bottom, autoSize=height|fixed|truncate
```

- `size` px = sp; `weight` numeric (400 normal, 500 medium, 600 semibold, 700 bold); `font` is the design font —
  code uses the theme family (`rules/04`), never `fontFamily = FontFamily("…")`.
- `letterSpacing` / `lineHeight` absent → default. `lineHeight=N%` = percent of font size.
- `maxLines` = the designer's value when set, else estimated from the box height (INFERRED). `overflow=ellipsis` =
  truncation ON → `TextOverflow.Ellipsis` with `maxLines`.
- `vAlign` = vertical alignment inside a fixed-height box. `autoSize=height` = fixed width, wraps (`fillMaxWidth()`,
  no fixed height); `fixed` = fixed box; `truncate` = fixed box that clips; absent = hugs both ways.
- `textCase` → `uppercase()` / `lowercase()` / title case in code, never a hardcoded transformed string.

## Images and overlays

`RECTANGLE "Thumb" (266×149) | fill=[IMAGE] | r=8` + `[IMAGE placeholder] aspectRatio=1.79` → `AsyncImage` with
`aspectRatio(1.79f).clip(RoundedCornerShape(8))`. `GROUP "Badge" (24×14)` + `position=bottom-left offset=(4, 4)` →
inside a `Box`: `align(BottomStart).offset(x = 4, y = -4)`.

## Rules when extracting blueprint rows

1. Cite exact values with `L<n>`; an absent property is the Figma default, never fabricated.
2. Hierarchy is evidence; semantic boundaries are decided in the blueprint (after screenshot validation when one exists).
3. Images and icons are asset dependencies, never invented resources; `stroke inside` stays part of the visual spec.
4. Heuristics (estimated `maxLines`, inferred fill, gradient direction on legacy scans) are INFERRED/UNKNOWN.
