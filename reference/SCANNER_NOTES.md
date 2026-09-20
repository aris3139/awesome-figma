# SCANNER_NOTES — engine internals of `figma_deep_scan.py` + `scripts/figclip/` (clipboard source)

Not loaded by the skills; read when changing the scanner/mapper or debugging odd evidence.

## Pipeline

`⌘C in Figma` → HTML clipboard flavor (`figmeta` + base64 fig-kiwi; markers are HTML-escaped `&lt;!--(figmeta)`, the
dumper unescapes) → `figclip_dump.mjs` (`figparse.js`, MIT: deflate schema block + zstd scene block → `nodeChanges`,
`blobs`) → `kiwi_to_rest.mjs` (resolve → REST-V1-shaped JSON) → `figma_deep_scan.py` (filters, compute, rename,
context/summary/tokens).

## Mapper rules (verified on real payloads, 2026-09-15/17)

| Rule | Detail |
|---|---|
| Tree | `parentIndex.guid` + fractional `position`; `transform` (affine, relative) × `size` → `absoluteBoundingBox` |
| Keys | override paths and ids use `overrideKey ?? guid` (pre-variant guid); ids `I<inst>;<key>` like REST |
| `guidPath` | instance chain + target node only — intermediate frames are **not** in the path |
| Instances | children come from the SYMBOL master; nested instance props = outer `symbolOverrides[path].componentPropAssignments` merged over own |
| Props | `componentPropRefs.defID` may be a variant-level child def; assignments live on the set-level parent (`parentPropDefId`) → walk the chain; missing assignment → def default |
| Slots | `SLOT_CONTENT_ID` ref ↔ `slotContentIdValue.guid`; content lives on "Internal Only Canvas"; emitted as `SLOT` with the placeholder key in the id path |
| Swaps | `symbolOverrides.overriddenSymbolID`, else `OVERRIDDEN_SYMBOL_ID` prop → assignment or INSTANCE_SWAP def default; swapped instance takes the component-set name |
| Render-time variant | prop bound to a variable mode → `symbolID` is stale; `derivedSymbolData` names the laid-out children → pick the sibling variant (same state group) that owns them |
| Visibility | `visible` flag, override `visible`, `VISIBLE` prop (+ default); any `derivedSymbolData` entry for a node = rendered → forces visible |
| Text | override `textData.characters` > `TEXT_DATA` prop > master default; numeric weight from `derivedTextData.fontMetaData[0].fontWeight` (matches Figma) |
| Paints | `color` is already resolved (variable alias kept in `colorVar`); gradients → stops + handle positions; IMAGE → placeholder |
| Radius | four `rectangle*CornerRadius` resolved **override-aware** (instance override wins — the `Avatar r=104` case); equal → `cornerRadius`, else `topLeftRadius…` |
| Override-aware reads | every visual/layout field goes through `g(f) = override ?? master` (`stack*` padding/spacing/grow/sizing, radius corners, strokeWeight/Align, frameMaskDisabled, blendMode, mask, text fields, prototypeInteractions) — 2026-09-17 audit: 45 padding, 43 grow, 74–84 radius overrides were previously read from the master |
| Constraints | `horizontal/verticalConstraint` MIN/MAX/CENTER/STRETCH/SCALE → REST `constraints` (LEFT/RIGHT/CENTER/LEFT_RIGHT/SCALE…), emitted when not MIN/MIN |
| Absolute | `stackPositioning=ABSOLUTE` → `layoutPositioning: ABSOLUTE` |
| Borders | `borderStrokeWeightsIndependent` → `individualStrokeWeights {top,right,bottom,left}`; `dashPattern` → `strokeDashes` |
| Effects | `INNER_SHADOW`, `DROP_SHADOW`, `BACKGROUND_BLUR`, `FOREGROUND_BLUR` passed through; **`GLASS` dropped** (iOS liquid-glass, decision 2026-09-17); `blendMode` ≠ NORMAL emitted |
| Mask | `mask: true` → `isMask` + `maskType` (ALPHA default / LUMINANCE) |
| Rotation | `atan2(-m10, m00)` of the local transform → `rotation` (deg, ccw positive) when > 0.5°; the bbox stays the rotated one |
| Min/max | `minSize/maxSize.value` → `minWidth/minHeight/maxWidth/maxHeight` |
| Text extras | `textAlignVertical`, `textAutoResize` (NONE/HEIGHT/WIDTH_AND_HEIGHT/TRUNCATE), `textTruncation`, `paragraphSpacing`, `textCase`, `textDecoration`, italic from the font style, `lineHeightUnit` PIXELS/PERCENT/AUTO (Kiwi `RAW` = multiplier → PERCENT×100) + `lineHeightPercentFontSize`, `maxLines` |
| Interactions | `prototypeInteractions[].actions[]` → `interactions [{trigger, action, destination{id,name,type}, url, transition}]`; sentinel `4294967295:4294967295` = destination not set |
| Variable modes | `variableModeBySetMap` → `variableModes ["Set=Mode"]` only when the VARIABLE_SET is in the payload (library sets are `assetRef` → unnamed → skipped) |
| Dropped | hidden nodes (unless `--keep-hidden`). VECTOR leaves stay in rich mode (the scanner flattens their containers to `ICON`; `--plugin-compat` drops them like the old plugin) |

Flags: default rich (`layoutMode`, `itemSpacing`, `padding*`, `primary/counterAxisSizingMode`, `*AlignItems`,
`layoutWrap`, child `layoutGrow`/`layoutAlign`, `layoutPositioning`, `constraints`, `min/max*`, `effects`, `opacity`,
`blendMode`, `rotation`, `isMask`, `strokeWeight/Align`, `individualStrokeWeights`, `strokeDashes`, `clipsContent`,
`maxLines`, text extras, `interactions`, `variableModes`);
`--plugin-compat` = legacy field set for baseline comparisons; `--keep-hidden` = hidden nodes as empty shells.

## Scanner filters (drop junk nodes)

| Filter | Description |
|---|---|
| Off-screen | node entirely outside the viewport |
| Hidden | `visible: false` or `opacity: 0` (rare with clipboard — already dropped upstream) |
| Clipped/GONE | child < 30 % visible inside its parent |
| Zero-size | width = 0 and height = 0 |
| Empty SLOT | SLOT with no children |
| Decorative | Glass Effect, Blur, State-layer… — by name, **unless the subtree carries TEXT** (v5.4): an `Overlay`/`Scrim` around a dialog or a `State-layer` around a button label is kept, its fill becomes `scrim=`/`stateLayer=` |
| SVG flatten | vector subtrees → `ICON`: GROUP/FRAME/BOOLEAN/SLOT with ≥2 descendants; INSTANCE only when it holds a real VECTOR and is ≤96px (glyph component, not a shapes-only chip/card); a wrapper with a single glyph INSTANCE child yields to the child; a lone VECTOR ≥12px is an ICON too. `--exclude` names drop at any depth, case-insensitive |
| Wrapper collapse | FRAME/GROUP with 1 child, no visuals **and no padding** → promote the child (v5.4: a wrapper with explicit or ≥ 2 px inferred padding stays as `layout=SINGLE, padding=…`; a ≤ 96 px frame around one glyph still collapses to the ICON) |
| Empty container | no children, no visuals |

## Scanner compute

Explicit auto-layout (`layoutMode` present) wins: `layout=ROW/COLUMN`, `gap` (dropped for `SPACE_BETWEEN`), `padding`
4 sides, `align`, `wrap`, `w=fill`/`h=fill` from child `layoutGrow` / `layoutAlign=STRETCH`; `_layoutSource=explicit`.
`absolute` children are excluded from direction/gap/padding inference and keep their `constraints`; flow children of an
explicit auto-layout parent drop `constraints` (Figma ignores them there). `attach_common()` adds blend, rotation, mask,
absolute, constraints, min/max, interactions (press/hover `SWAP_STATE` feedback filtered out) and modes to every result,
ICON results included. Effects: `DROP_SHADOW` → `shadow`, `INNER_SHADOW` → `innerShadow`, blurs → `blur` (first of each).
Fallback inference from bounding boxes (legacy behaviour): direction from dx/dy, gaps between siblings, padding =
parent − children bounds, alignment by centers, scroll when children exceed the parent, FILL when a child spans the
siblings' union within ≤ 40 px, `arrangement=SPACE_BETWEEN` heuristic, `maxLines ≈ h/(size×1.4)`, effects from named
layers (`material=glass`, `effect=blur+shadow`) when no `effects[]`.

Names: layer names are kept exactly as Design wrote them (the `Frame 12345` auto-rename was removed 2026-09-17 —
Design now names frames). Only TEXT layers named `Title`/`Label`/`Description`/`Time` take their text content as name.

## Known gaps

1. Icons (`figclip icons`, details in `scan.md §3b`): composed from `vectorNetworkBlob` rescaled by `size/normalizedSize`;
   gradients → first stop; IMAGE fills skipped; BOOLEAN_OPERATION children emitted as separate paths (no real union);
   `exportSettings` absent from clipboard payloads; needs dumps with base64 blobs.
2. Screenshots need a manual ⌘⇧C per screen.
3. `fontMetaData` can hold several style runs; the first entry's weight is used (`textData.styleOverrideTable` mixed
   runs are not split into spans).
4. Style names (`styleIdForText/Fill/Effect`) and library variable sets are `assetRef` keys — the style node is not in
   the clipboard payload, so tokens carry values, not names.
4b. `derivedSymbolData.fillGeometry` (rendered geometry of instance children) is not used yet; icons are composed from
   `vectorNetworkBlob` rescaled by `size/normalizedSize`.
5. Format is undocumented; the schema is self-describing (embedded in every payload) so decoding survives version
   bumps, but new semantics (like render-time variants) show up as evidence gaps — compare against screenshots.

Retired 2026-09-16: the TalkToFigma WebSocket source (no layout tokens, no effects, volatile channel).
