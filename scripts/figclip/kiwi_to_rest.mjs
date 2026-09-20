// Figma clipboard (fig-kiwi scene) → REST-V1-shaped JSON (the shape figma_deep_scan.py reads)
// so the existing figma_deep_scan.py consumes it unchanged.
// Usage: node kiwi_to_rest.mjs <clip.json> <nodeId sess:local> <out.json>
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { vectorNetworkBlobToPath, colorToHex } from './svg.mjs';

const [, , clipPath, rootId, outPath] = process.argv;
const { message } = JSON.parse(readFileSync(clipPath, 'utf8'));
const nodes = message.nodeChanges;
const gid = (g) => (g ? `${g.sessionID}:${g.localID}` : null);
const byId = new Map(nodes.map((n) => [gid(n.guid), n]));
const okey = (n) => gid(n.overrideKey) || gid(n.guid); // Figma keys override paths by the pre-variant guid
const RICH = !process.argv.includes('--plugin-compat'); // default: emit every field the scanner understands; --plugin-compat mimics the retired plugin filter (baseline comparisons only)
const KEEP_HIDDEN = process.argv.includes('--keep-hidden'); // mimic plugin JSON (hidden nodes present, unmarked)
const DEBUG = process.env.DEBUG_KEY || '';
const argIdx = (f) => process.argv.indexOf(f);
const ICONS_DIR = argIdx('--icons') > 0 ? process.argv[argIdx('--icons') + 1] : null;          // export icon SVGs here
const ICON_FILTER = argIdx('--icon-filter') > 0 ? process.argv[argIdx('--icon-filter') + 1] : null; // context.txt/summary.txt: only ICON lines
const ICON_MAX = argIdx('--icon-max') > 0 ? Number(process.argv[argIdx('--icon-max') + 1]) : 128;   // skip containers bigger than this (image placeholders)
const INCLUDE_DYNAMIC = process.argv.includes('--include-dynamic'); // also write icons classified as dynamic content (logos, thumbnails)
const blobBytes = (i) => { const b = message.blobs?.[i]?.bytes; if (!b) return null; if (b instanceof Uint8Array) return b; if (typeof b === 'string' && b.startsWith('b64:')) return new Uint8Array(Buffer.from(b.slice(4), 'base64')); if (Array.isArray(b)) return new Uint8Array(b); return null; };
const VECTORISH = new Set(['VECTOR', 'ELLIPSE', 'RECTANGLE', 'ROUNDED_RECTANGLE', 'STAR', 'LINE', 'REGULAR_POLYGON', 'BOOLEAN_OPERATION']);
const vectorLeaves = []; const ancestors = []; const masterOf = new Map();
const DEBUG_NAME = process.env.DEBUG_NAME ? new RegExp(process.env.DEBUG_NAME) : null;
const defById = new Map(); for (const n of nodes) for (const d of n.componentPropDefs || []) defById.set(gid(d.id), d);
const swapDefault = (defID) => { let d = defById.get(defID), hops = 0; while (d && hops++ < 4) { const g = d.varValue?.value?.symbolIdValue?.guid || d.initialValue?.guidValue; if (g) return g; d = d.parentPropDefId ? defById.get(gid(d.parentPropDefId)) : null; } return undefined; };
const textDefault = (defID) => { const d = defById.get(defID); return d?.varValue?.value?.textDataValue?.characters ?? d?.initialValue?.textValue ?? d?.initialValue?.textDataValue?.characters; };
const boolDefault = (defID) => { for (const id of defChain(defID)) { const d = defById.get(id); const v = d?.varValue?.value?.boolValue ?? d?.initialValue?.boolValue; if (v !== undefined) return v; } return undefined; };
const symbolKeys = new Set(nodes.filter((n) => n.type === 'SYMBOL').map((n) => gid(n.overrideKey) || gid(n.guid))); // derived paths may name the master itself
const varByKey = new Map(nodes.filter((n) => n.type === 'VARIABLE' && n.key).map((n) => [n.key, n]));
const floatVar = (alias) => { const v = varByKey.get(alias?.assetRef?.key); const e = v?.variableDataValues?.entries?.[0]; return e?.variableData?.value?.floatValue; };
const kids = new Map();
for (const n of nodes) {
  const p = n.parentIndex ? gid(n.parentIndex.guid) : null;
  (kids.get(p) || kids.set(p, []).get(p)).push(n);
}
for (const list of kids.values()) list.sort((a, b) => ((a.parentIndex?.position || '') < (b.parentIndex?.position || '') ? -1 : 1));

// ── helpers ────────────────────────────────────────────────────────────────
const I = { m00: 1, m01: 0, m02: 0, m10: 0, m11: 1, m12: 0 };
const mul = (a, b) => ({
  m00: a.m00 * b.m00 + a.m01 * b.m10, m01: a.m00 * b.m01 + a.m01 * b.m11, m02: a.m00 * b.m02 + a.m01 * b.m12 + a.m02,
  m10: a.m10 * b.m00 + a.m11 * b.m10, m11: a.m10 * b.m01 + a.m11 * b.m11, m12: a.m10 * b.m02 + a.m11 * b.m12 + a.m12,
});
const bbox = (w, size) => {
  const pts = [[0, 0], [size.x, 0], [0, size.y], [size.x, size.y]].map(([x, y]) => [w.m00 * x + w.m01 * y + w.m02, w.m10 * x + w.m11 * y + w.m12]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y };
};
const h2 = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0');
const hex = (c) => `#${h2(c.r)}${h2(c.g)}${h2(c.b)}${c.a < 1 ? h2(c.a) : ''}`;
const WEIGHT = { thin: 100, hairline: 100, extralight: 200, ultralight: 200, light: 300, regular: 400, book: 400, normal: 400, medium: 500, semibold: 600, demibold: 600, bold: 700, extrabold: 800, ultrabold: 800, black: 900, heavy: 900 };
const weightOf = (style = '') => { const s = style.toLowerCase().replace(/\s+/g, ''); for (const k of Object.keys(WEIGHT).sort((a, b) => b.length - a.length)) if (s.includes(k)) return WEIGHT[k]; return 400; };
const TYPE = { ROUNDED_RECTANGLE: 'RECTANGLE', SYMBOL: 'COMPONENT', REGULAR_POLYGON: 'REGULAR_POLYGON' };
const HCON = { MIN: 'LEFT', MAX: 'RIGHT', CENTER: 'CENTER', STRETCH: 'LEFT_RIGHT', SCALE: 'SCALE' }, VCON = { MIN: 'TOP', MAX: 'BOTTOM', CENTER: 'CENTER', STRETCH: 'TOP_BOTTOM', SCALE: 'SCALE' }; // Kiwi constraint → REST

function paint(p) {
  const o = { blendMode: p.blendMode || 'NORMAL', type: p.type };
  if (p.visible === false) o.visible = false;
  if (p.opacity !== undefined && p.opacity !== 1) o.opacity = p.opacity;
  if (p.color) o.color = hex(p.color);
  if (p.stops) o.gradientStops = p.stops.map((s) => ({ color: hex(s.color), position: s.position }));
  if (p.transform && /GRADIENT/.test(p.type)) {
    // REST handles are the inverse of the paint transform applied to (0,.5) (1,.5) (0,1) — prototype approximation
    const t = p.transform, det = t.m00 * t.m11 - t.m01 * t.m10 || 1;
    const inv = (x, y) => ({ x: (t.m11 * (x - t.m02) - t.m01 * (y - t.m12)) / det, y: (-t.m10 * (x - t.m02) + t.m00 * (y - t.m12)) / det });
    o.gradientHandlePositions = [inv(0, 0.5), inv(1, 0.5), inv(0, 1)];
  }
  if (p.type === 'IMAGE') o.scaleMode = p.imageScaleMode || 'FILL';
  return o;
}

// ── resolution context ─────────────────────────────────────────────────────
// Each instance level: { path: [guid…] relative to that instance, overrides: Map(pathKey→override), derived: Map(pathKey→{size,transform}), props: Map(defID→assignment) }
function levelFor(inst, ovAssignments) {
  const overrides = new Map(), derived = new Map(), props = new Map();
  for (const a of ovAssignments || []) props.set(gid(a.defID), a);
  for (const o of inst.symbolData?.symbolOverrides || []) overrides.set(o.guidPath.guids.map(gid).join('>'), o);
  for (const d of inst.derivedSymbolData || []) derived.set(d.guidPath.guids.map(gid).join('>'), d);
  for (const a of inst.componentPropAssignments || []) if (!props.has(gid(a.defID))) props.set(gid(a.defID), a);
  return { overrides, derived, props };
}
// lookup: outermost level first (outer wins), path relative to each level
function resolve(levels, relPaths, pick) {
  for (let i = 0; i < levels.length; i++) { const v = pick(levels[i], relPaths[i]); if (v !== undefined) return v; }
  return undefined;
}
const propValue = (a) => a?.varValue?.value ?? a?.value;
const defChain = (defID) => { const out = [defID]; let d = defById.get(defID), hops = 0; while (d?.parentPropDefId && hops++ < 4) { const pid = gid(d.parentPropDefId); out.push(pid); d = defById.get(pid); } return out; };
const findProp = (levels, defID) => { const ids = defChain(defID); for (let i = 0; i < levels.length; i++) for (const id of ids) { const a = levels[i].props.get(id); if (a) return a; } return undefined; };

let dropped = { vector: 0, hidden: 0, shell: 0 };

function emit(node, world, levels, paths, idPrefix, slotOverrideChildren) {
  if (node.type === 'VECTOR' && !RICH && !ICONS_DIR) { dropped.vector++; return null; } // plugin-compat drops vectors like the old filter did
  const key = paths.map((p) => [...p, okey(node)].join('>'));
  const ov = (field) => resolve(levels, key, (L, k) => L.overrides.get(k)?.[field]);
  const der = (field) => resolve(levels, key, (L, k) => L.derived.get(k)?.[field]);
  const g = (field) => ov(field) ?? node[field]; // override-aware read: instance override wins over the master value
  // visibility: node flag, override, VISIBLE prop
  let visible = ov('visible') ?? node.visible ?? true;
  const visRef = (node.componentPropRefs || []).find((r) => r.componentPropNodeField === 'VISIBLE');
  if (visRef) { const a = findProp(levels, gid(visRef.defID)); const v = propValue(a)?.boolValue ?? boolDefault(gid(visRef.defID)); if (v !== undefined) visible = v;
    if (DEBUG && okey(node) === DEBUG) console.error('DEBUG', okey(node), 'defID', gid(visRef.defID), 'assignment', JSON.stringify(a), 'levels', levels.map((L) => [...L.props.keys()].join(',')).join(' || '), 'node.visible', node.visible, 'ov', ov('visible')); }
  if (DEBUG_NAME && DEBUG_NAME.test(node.name || '')) console.error('DBG', node.type, JSON.stringify(node.name), 'okey', okey(node), 'keys', JSON.stringify(key), 'node.visible', node.visible, 'ov.visible', ov('visible'), 'visRef', visRef ? gid(visRef.defID) + '→' + JSON.stringify(propValue(findProp(levels, gid(visRef.defID)))) : '-', 'chain', visRef ? JSON.stringify(defChain(gid(visRef.defID))) : '-', '=>', visible ? 'SHOW' : 'HIDE');
  // Figma only writes derivedSymbolData for nodes it actually laid out → a derived entry proves the node is rendered (INFERRED, verified on 2 screens)
  if (!visible && (der('size') || der('transform') || der('derivedTextData'))) visible = true;
  if (!visible) { dropped.hidden++; if (!KEEP_HIDDEN) return null; }
  const shell = !visible;

  const size = der('size') || ov('size') || node.size || { x: 0, y: 0 };
  const local = der('transform') || node.transform || I;
  const w = mul(world, local);
  if (ICONS_DIR && VECTORISH.has(node.type) && node.type !== 'BOOLEAN_OPERATION') {
    vectorLeaves.push({ seq: vectorLeaves.length, id: idPrefix ? `${idPrefix};${okey(node)}` : gid(node.guid), node, size, world: w, ancestors: [...ancestors], fills: ov('fillPaints') ?? node.fillPaints, strokes: ov('strokePaints') ?? node.strokePaints, strokeWeight: ov('strokeWeight') ?? node.strokeWeight, opacity: ov('opacity') ?? node.opacity });
    if (node.type === 'VECTOR' && !RICH) { dropped.vector++; return null; }
  }
  if (node.type === 'VECTOR' && !RICH) { dropped.vector++; return null; }
  const kind = node.resizeToFit ? 'GROUP' : (TYPE[node.type] || node.type);
  const out = { id: idPrefix ? `${idPrefix};${okey(node)}` : gid(node.guid), name: ov('name') ?? node.name, type: kind };

  const fills = ov('fillPaints') ?? node.fillPaints; if (fills?.length) out.fills = fills.map(paint);
  const strokes = ov('strokePaints') ?? node.strokePaints; if (strokes?.length) { out.strokes = strokes.map(paint); const sw = g('strokeWeight'); if (RICH && sw !== undefined) out.strokeWeight = sw; const sa = g('strokeAlign'); if (RICH && sa) out.strokeAlign = sa;
    if (RICH && g('borderStrokeWeightsIndependent')) out.individualStrokeWeights = { top: g('borderTopWeight') ?? sw ?? 0, right: g('borderRightWeight') ?? sw ?? 0, bottom: g('borderBottomWeight') ?? sw ?? 0, left: g('borderLeftWeight') ?? sw ?? 0 }; // one-side dividers
    const dp = g('dashPattern'); if (RICH && dp?.length) out.strokeDashes = dp; }
  { const r4 = ['rectangleTopLeftCornerRadius', 'rectangleTopRightCornerRadius', 'rectangleBottomRightCornerRadius', 'rectangleBottomLeftCornerRadius'].map((f) => g(f) ?? 0); // tl tr br bl, override-aware (Avatar r=104 case)
    let cr = g('cornerRadius');
    if (r4.some((v) => v)) { if (r4.every((v) => v === r4[0])) cr = r4[0]; else if (RICH) { out.rectangleCornerRadii = r4; [out.topLeftRadius, out.topRightRadius, out.bottomRightRadius, out.bottomLeftRadius] = r4; cr = undefined; } }
    if (cr !== undefined && cr !== 0) out.cornerRadius = cr; }
  const op = g('opacity'); if (RICH && op !== undefined && op !== 1) out.opacity = op;
  const eff = g('effects'); if (RICH && eff?.length) { const fx = eff.filter((e) => e.visible !== false && e.type !== 'GLASS').map((e) => ({ type: e.type, radius: e.radius, offset: e.offset, spread: e.spread, color: e.color ? hex(e.color) : undefined, showShadowBehindNode: e.showShadowBehindNode || undefined })); if (fx.length) out.effects = fx; } // GLASS = iOS liquid-glass material, intentionally dropped
  const bm = g('blendMode'); if (RICH && bm && bm !== 'NORMAL' && bm !== 'PASS_THROUGH') out.blendMode = bm;
  if (RICH && g('mask')) { out.isMask = true; out.maskType = g('maskType') || 'ALPHA'; } // clips the siblings that follow it
  { const rot = Math.atan2(-local.m10, local.m00) * 180 / Math.PI; if (RICH && Math.abs(rot) > 0.5) out.rotation = +rot.toFixed(1); } // Figma UI rotation (ccw positive); the bbox is already the rotated one
  if (RICH && (kind === 'FRAME' || kind === 'INSTANCE' || kind === 'COMPONENT')) { out.clipsContent = !g('frameMaskDisabled'); const sm = g('stackMode'); if (sm && sm !== 'NONE') { out.layoutMode = sm; out.itemSpacing = g('stackSpacing') ?? 0; out.paddingLeft = g('stackHorizontalPadding') ?? 0; out.paddingTop = g('stackVerticalPadding') ?? 0; out.paddingRight = g('stackPaddingRight') ?? 0; out.paddingBottom = g('stackPaddingBottom') ?? 0; out.primaryAxisSizingMode = g('stackPrimarySizing'); out.counterAxisSizingMode = g('stackCounterSizing'); out.primaryAxisAlignItems = g('stackPrimaryAlignItems'); out.counterAxisAlignItems = g('stackCounterAlignItems'); const sw2 = g('stackWrap'); if (sw2 && sw2 !== 'NO_WRAP') { out.layoutWrap = sw2; if (g('stackCounterSpacing')) out.counterAxisSpacing = g('stackCounterSpacing'); } } }
  if (RICH) { const as = g('stackChildAlignSelf'); if (as) out.layoutAlign = as; const gr = g('stackChildPrimaryGrow'); if (gr) out.layoutGrow = gr;
    if (g('stackPositioning') === 'ABSOLUTE') out.layoutPositioning = 'ABSOLUTE'; // ignores the parent's auto-layout flow (badge/overlay)
    const hc = g('horizontalConstraint'), vc = g('verticalConstraint'); if ((hc && hc !== 'MIN') || (vc && vc !== 'MIN')) out.constraints = { horizontal: HCON[hc] || hc || 'LEFT', vertical: VCON[vc] || vc || 'TOP' };
    const mn = g('minSize')?.value, mx = g('maxSize')?.value; if (mn?.x) out.minWidth = mn.x; if (mn?.y) out.minHeight = mn.y; if (mx?.x) out.maxWidth = mx.x; if (mx?.y) out.maxHeight = mx.y;
    const inter = (g('prototypeInteractions') || []).filter((i) => !i.isDeleted && i.actions?.length);
    const NONE_GUID = '4294967295:4294967295'; // Figma sentinel: destination not set
    if (inter.length) out.interactions = inter.flatMap((i) => i.actions.map((a) => { const tid = a.transitionNodeID && gid(a.transitionNodeID) !== NONE_GUID ? gid(a.transitionNodeID) : null; const dest = tid ? byId.get(tid) : null; return { trigger: i.event?.interactionType, action: a.navigationType || a.connectionType, destination: dest ? { id: tid, name: dest.name, type: dest.type } : tid ? { id: tid } : undefined, url: a.connectionURL, transition: a.transitionType }; }));
    // variable modes (Light/Dark, OS…) — only when the set lives in the payload; library sets (assetRef) cannot be named → skipped
    const vm = g('variableModeBySetMap')?.entries; if (vm?.length) { const modes = vm.map((e) => { const set = e.variableSetID?.guid ? byId.get(gid(e.variableSetID.guid)) : null; const mode = set?.variableSetModes?.find((mm) => gid(mm.id) === gid(e.variableModeID?.guid)); return set && mode ? `${set.name}=${mode.name}` : null; }).filter(Boolean); if (modes.length) out.variableModes = modes; } }
  out.absoluteBoundingBox = bbox(w, size);

  if (node.type === 'TEXT') {
    let chars = ov('textData')?.characters;
    const tRef = (node.componentPropRefs || []).find((r) => r.componentPropNodeField === 'TEXT_DATA');
    if (chars === undefined && tRef) { const a = findProp(levels, gid(tRef.defID)); chars = propValue(a)?.textDataValue?.characters ?? propValue(a)?.textValue ?? textDefault(gid(tRef.defID)); }
    out.characters = chars ?? node.textData?.characters ?? '';
    const fn = ov('fontName') ?? node.fontName ?? {}; const fs = ov('fontSize') ?? node.fontSize ?? 0;
    const lh = g('lineHeight'), ls = g('letterSpacing');
    const metaW = der('derivedTextData')?.fontMetaData?.[0]?.fontWeight ?? node.derivedTextData?.fontMetaData?.[0]?.fontWeight;
    // lineHeight units: PIXELS · PERCENT (of font size) · RAW = multiplier (1.3 = 130 %); none = AUTO
    const lhUnit = !lh ? 'AUTO' : lh.units === 'PIXELS' ? 'PIXELS' : 'PERCENT', lhPct = lh ? (lh.units === 'RAW' ? lh.value * 100 : lh.units === 'PERCENT' ? lh.value : (lh.value / fs) * 100) : 100;
    out.style = { fontFamily: fn.family, fontStyle: fn.style, fontWeight: metaW ?? weightOf(fn.style), fontSize: fs, textAlignHorizontal: g('textAlignHorizontal') ?? 'LEFT',
      letterSpacing: ls ? (ls.units === 'PERCENT' ? (ls.value / 100) * fs : ls.value) : 0,
      lineHeightPx: lh ? (lh.units === 'PIXELS' ? lh.value : (lhPct / 100) * fs) : Math.round(fs * 1.2), lineHeightUnit: lhUnit, lineHeightPercentFontSize: lhUnit === 'PERCENT' ? +lhPct.toFixed(1) : undefined };
    if (RICH) { const st = out.style; const tav = g('textAlignVertical'); if (tav && tav !== 'TOP') st.textAlignVertical = tav;
      const tar = g('textAutoResize'); st.textAutoResize = tar || 'NONE'; const tt = g('textTruncation'); if (tt && tt !== 'DISABLED') st.textTruncation = tt;
      const psp = g('paragraphSpacing'); if (psp) st.paragraphSpacing = psp; const tcs = g('textCase'); if (tcs && tcs !== 'ORIGINAL') st.textCase = tcs; const tdc = g('textDecoration'); if (tdc && tdc !== 'NONE') st.textDecoration = tdc;
      if (/italic|oblique/i.test(fn.style || '')) st.italic = true; }
    const ml = g('maxLines'); if (RICH && ml) out.maxLines = ml;
  }

  // children
  let children = [];
  if (shell) { out.children = []; return out; }
  ancestors.push(out.id);
  const down = (ps, c) => ps; // intermediate frames are not part of guidPath
  if (slotOverrideChildren) children = slotOverrideChildren.map((c) => emit(c, w, levels, down(paths, c), idPrefix, null));
  else if (node.type === 'INSTANCE') {
    let swapped = ov('overriddenSymbolID');
    if (!swapped) { const sRef = (node.componentPropRefs || []).find((r) => r.componentPropNodeField === 'OVERRIDDEN_SYMBOL_ID');
      if (sRef) { const a = findProp(levels, gid(sRef.defID)); swapped = propValue(a)?.symbolIdValue?.guid || propValue(a)?.guidValue || swapDefault(gid(sRef.defID)); } }
    let master = byId.get(gid(swapped || node.symbolData?.symbolID));
    // Variant chosen at render time (e.g. "Mode" bound to a variable mode): derivedSymbolData names the laid-out
    // children — if they are not in this master, pick the sibling variant (same state group) that owns them.
    const L0 = levelFor(node, ov('componentPropAssignments'));
    const directDerived = [...L0.derived.keys()].filter((k) => !k.includes('>'));
    levels.forEach((L, i) => { const pre = key[i] + '>'; for (const dk of L.derived.keys()) if (dk.startsWith(pre) && !dk.slice(pre.length).includes('>')) directDerived.push(dk.slice(pre.length)); });
    if (master && directDerived.length) {
      const subtreeKeys = (root) => { const out = new Set(); const st = [...(kids.get(gid(root.guid)) || [])]; while (st.length) { const c = st.pop(); out.add(okey(c)); st.push(...(kids.get(gid(c.guid)) || [])); } return out; };
      const have = subtreeKeys(master); const missing = directDerived.filter((k) => !have.has(k) && !symbolKeys.has(k));
      if (DEBUG_NAME && DEBUG_NAME.test(node.name || '')) console.error('VDBG', JSON.stringify(node.name), 'keys', JSON.stringify(key), 'directDerived', JSON.stringify(directDerived), 'master', gid(master.guid), 'have', [...have].slice(0, 4), 'missing', JSON.stringify(missing), 'set', gid(master.parentIndex?.guid), 'isStateGroup', byId.get(gid(master.parentIndex?.guid))?.isStateGroup);
      if (missing.length) { const set = byId.get(gid(master.parentIndex?.guid)); if (set?.isStateGroup) { const alt = (kids.get(gid(set.guid)) || []).find((v) => v !== master && (() => { const ks = subtreeKeys(v); return missing.every((k) => ks.has(k)); })()); if (alt) { dropped.variantFix = (dropped.variantFix || 0) + 1; master = alt; } } }
    }
    if (swapped && master && ov('name') === undefined) { const set = byId.get(gid(master.parentIndex?.guid)); out.name = set?.isStateGroup ? set.name : master.name; }
    const mk = master ? kids.get(gid(master.guid)) || [] : [];
    if (master) masterOf.set(out.id, gid(master.guid));
    if (!master || !mk.length) dropped.shell++;
    const newLevels = [...levels, levelFor(node, ov('componentPropAssignments'))], newPaths = [...paths.map((p) => [...p, okey(node)]), []];
    const pfx = idPrefix ? `${idPrefix};${okey(node)}` : `I${gid(node.guid)}`;
    children = mk.map((c) => emit(c, w, newLevels, down(newPaths, c), pfx, null));
  } else {
    const slotRef = (node.componentPropRefs || []).find((r) => r.componentPropNodeField === 'SLOT_CONTENT_ID');
    if (slotRef) {
      const a = findProp(levels, gid(slotRef.defID));
      const content = byId.get(gid(propValue(a)?.slotContentIdValue?.guid));
      out.type = 'SLOT';
      if (content) { const spfx = idPrefix ? `${idPrefix};${okey(node)}` : okey(node); children = (kids.get(gid(content.guid)) || []).map((c) => emit(c, w, levels, down(paths, c), spfx, null)); }
    } else children = (kids.get(gid(node.guid)) || []).map((c) => emit(c, w, levels, down(paths, c), idPrefix, null));
  }
  ancestors.pop();
  children = children.filter(Boolean);
  if (children.length || ['FRAME', 'INSTANCE', 'GROUP', 'SLOT', 'COMPONENT'].includes(out.type)) out.children = children;
  return out;
}

const root = byId.get(rootId);
if (!root) { console.error('node not found', rootId); process.exit(1); }
const rest = emit(root, I, [], [], '', null);
writeFileSync(outPath, JSON.stringify(rest, null, 1));
const count = (n) => 1 + (n.children || []).reduce((a, c) => a + count(c), 0);
console.log(`rest json: ${outPath} | nodes ${count(rest)} | dropped ${JSON.stringify(dropped)}`);

// ── Icon export: containers the scanner flattens to ICON → one SVG each, viewBox = container box ────────────────
if (ICONS_DIR) {
  const inv = (m) => { const det = m.m00 * m.m11 - m.m01 * m.m10 || 1; return { m00: m.m11 / det, m01: -m.m01 / det, m02: (m.m01 * m.m12 - m.m11 * m.m02) / det, m10: -m.m10 / det, m11: m.m00 / det, m12: (m.m10 * m.m02 - m.m00 * m.m12) / det }; };
  const f2 = (v) => (Math.abs(v) < 1e-9 ? 0 : +v.toFixed(3));
  const matAttr = (m) => (Math.abs(m.m00 - 1) < 1e-6 && Math.abs(m.m11 - 1) < 1e-6 && Math.abs(m.m01) < 1e-6 && Math.abs(m.m10) < 1e-6) ? (Math.abs(m.m02) < 1e-6 && Math.abs(m.m12) < 1e-6 ? '' : ` transform="translate(${f2(m.m02)} ${f2(m.m12)})"`) : ` transform="matrix(${f2(m.m00)} ${f2(m.m10)} ${f2(m.m01)} ${f2(m.m11)} ${f2(m.m02)} ${f2(m.m12)})"`;
  const solid = (paints) => (paints || []).find((p) => p.visible !== false && p.type === 'SOLID') || (paints || []).find((p) => p.visible !== false && p.stops?.length);
  const paintAttrs = (p, kind) => { if (!p) return kind === 'fill' ? ' fill="none"' : ''; const c = p.color || p.stops?.[0]?.color; const op = (p.opacity ?? 1) * (c?.a ?? 1); return ` ${kind}="${colorToHex(c)}"` + (op < 0.999 ? ` ${kind}-opacity="${op.toFixed(2)}"` : ''); };
  // filter set from context.txt / summary.txt: ICON "name" (W×H) | ICON "name" W×H
  let allow = null, allowIds = null;
  if (ICON_FILTER) {
    const txt = readFileSync(ICON_FILTER, 'utf8');
    if (ICON_FILTER.endsWith('.json')) { allowIds = new Set(JSON.parse(txt).map((e) => e.id)); }          // icons.json from the scanner: exact node ids
    else { allow = new Set(); for (const m of txt.matchAll(/ICON "([^"]+)" \(?(\d+)×(\d+)/g)) allow.add(`${m[1]}|${m[2]}×${m[3]}`); } // fallback: context.txt names
  }
  const DECOR = new Set(['glass effect', 'blur', 'gradient mask', 'fill + shadow', 'tint + shadow', 'state-layer', 'bounding box', 'state layer', 'scrim', 'overlay']);
  const byRestId = new Map(); const hasText = new Map();
  const walk = (n) => { byRestId.set(n.id, n); let t = n.type === 'TEXT'; for (const c of n.children || []) t = walk(c) || t; hasText.set(n.id, t); return t; }; walk(rest);
  const leavesUnder = new Map(); for (const l of vectorLeaves) for (const a of l.ancestors) (leavesUnder.get(a) || leavesUnder.set(a, []).get(a)).push(l);
  const ICON_TYPES = new Set(['FRAME', 'GROUP', 'INSTANCE', 'SLOT', 'COMPONENT', 'BOOLEAN_OPERATION']);
  const candidates = []; const plainShapes = [];
  const pick = (n, parentPicked) => {
    const b = n.absoluteBoundingBox || {}; const W = Math.round(b.width || 0), H = Math.round(b.height || 0);
    const leaves = leavesUnder.get(n.id) || [];
    let ok = !parentPicked && ICON_TYPES.has(n.type) && leaves.length >= 1 && !hasText.get(n.id) && W > 0 && H > 0 && W <= ICON_MAX && H <= ICON_MAX;
    if (allowIds) ok = allowIds.has(n.id) && leaves.length >= 1;                       // id filter is authoritative (scanner already applied its own filters)
    if (allowIds && allowIds.has(n.id) && !leaves.length) { const self = vectorLeaves.find((l) => l.id === n.id); if (self && W > 0 && H > 0) { candidates.push({ n, W, H, leaves: [self] }); return; } plainShapes.push({ n, W, H }); } // lone VECTOR icon / plain shape
    else if (ok && allow) ok = allow.has(`${n.name}|${W}×${H}`) || allow.has(`${n.name}|${W}×${H - 1}`) || allow.has(`${n.name}|${W - 1}×${H}`) || allow.has(`${n.name}|${W + 1}×${H}`) || allow.has(`${n.name}|${W}×${H + 1}`);
    if (ok) candidates.push({ n, W, H, leaves });
    for (const c of n.children || []) pick(c, parentPicked || ok);
  };
  pick(rest, false);
  // repeated list items: ≥ 3 candidates sharing name+size whose vector geometry differs → content from the API, not UI icons
  const geomSig = (leaves) => leaves.map((l) => `${l.node.type}:${l.node.vectorData?.vectorNetworkBlob ?? ''}:${Math.round(l.size.x)}x${Math.round(l.size.y)}`).sort().join('|');
  const groups = new Map(); for (const c of candidates) { const k = `${c.n.name}|${c.W}×${c.H}`; (groups.get(k) || groups.set(k, []).get(k)).push(c); }
  const listContent = new Set(); for (const [k, g] of groups) if (g.length >= 3 && new Set(g.map((c) => geomSig(c.leaves))).size > 1) g.forEach((c) => listContent.add(c.n.id));
  mkdirSync(ICONS_DIR, { recursive: true });
  const slug = (t) => 'ic_' + (t || 'icon').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
  const seen = new Map(); const rows = []; let written = 0, noGeom = 0;
  for (const { n, W, H } of plainShapes) rows.push({ file: '', name: n.name, size: `${W}×${H}`, id: n.id, kind: 'shape', note: 'plain shape (draw in code), no vector geometry' });
  for (const { n, W, H, leaves } of candidates) {
    // static UI icon vs dynamic content (logo/thumbnail from the API)? Signals measured on real payloads:
    // imported artwork has normalizedSize ≫ rendered size; UI icons are drawn at size (ratio ≈ 1) and usually bind a color variable.
    let img = 0, grads = 0, varBound = 0, maxRatio = 0; const colors = new Set();
    for (const l of leaves) { for (const p of l.fills || []) { if (p.visible === false) continue; if (p.type === 'IMAGE') img++; else if (/GRADIENT/.test(p.type)) grads++; else if (p.color) { colors.add(colorToHex(p.color)); if (p.colorVar) varBound++; } }
      const ns = l.node.vectorData?.normalizedSize; if (l.node.type === 'VECTOR' && ns?.x && l.size?.x) maxRatio = Math.max(maxRatio, ns.x / l.size.x); }
    const dynName = /logo|avatar|thumb|poster|banner|cover|photo|image|img|ảnh|hình/i.test(n.name || '') || listContent.has(n.id);
    // priority: a fill bound to a colour variable is a themed UI glyph (static) unless it also paints a bitmap;
    // bitmap fills / content-like names are dynamic; a big normalizedSize ratio only counts when nothing is variable-bound
    // (instances often resize the glyph, which inflates the ratio for legitimate icons).
    const kind = img > 0 ? 'dynamic' : varBound > 0 ? 'static' : dynName ? 'dynamic' : maxRatio > 3 ? 'dynamic' : colors.size <= 2 ? 'static' : 'unsure';
    const why = `ratio ${maxRatio.toFixed(1)} · colors ${colors.size} · var ${varBound}${img ? ` · IMAGE ${img}` : ''}${grads ? ` · grad ${grads}` : ''}${listContent.has(n.id) ? ' · list item' : dynName ? ' · name' : ''}`;
    if (kind === 'dynamic' && !INCLUDE_DYNAMIC) { rows.push({ file: '', name: n.name, size: `${W}×${H}`, id: n.id, kind, note: `skipped (content) — ${why}` }); continue; }
    // background leaves: never a VECTOR; shapes covering ≥ 80 % of the container, or BG/glass/state-layer named shapes
    const area = W * H; const BGRE = /^(bg|background|fill|glass|material|state|overlay|theme|shadow|blur|chrome|ultrathin|thin|thick|regular|bounding box)\b/i;
    const parentName = (l) => { const pid = l.ancestors[l.ancestors.length - 1]; return byRestId.get(pid)?.name || ''; };
    const isBg = (l) => l.node.type !== 'VECTOR' && ((l.size.x * l.size.y >= 0.8 * area) || BGRE.test(l.node.name || '') || BGRE.test(parentName(l)));
    const glyph = leaves.filter((l) => !isBg(l) && !DECOR.has((l.node.name || '').toLowerCase()));
    // glyph root = nearest ancestor (within the container) that is an INSTANCE ≤ 48px, else a FRAME/GROUP ≤ 48px, else the container
    const GENERIC = /^(frame|group|vector|slot|leading|trailing|icon button|icon|container)(\s|\d|$)/i;
    const rootOf = (l) => { const chain = l.ancestors.slice(l.ancestors.indexOf(n.id)); let best = null;
      for (let i = chain.length - 1; i >= 0; i--) { const a = byRestId.get(chain[i]); if (!a || a === n) break; const bw = a.absoluteBoundingBox?.width || 0, bh = a.absoluteBoundingBox?.height || 0; if (bw > 48 || bh > 48) break; if (a.type === 'INSTANCE') { best = a; break; } if (!best && (a.type === 'FRAME' || a.type === 'GROUP')) best = a; }
      return best || n; };
    const groups = new Map(); for (const l of glyph) { const r = rootOf(l); (groups.get(r.id) || groups.set(r.id, { root: r, leaves: [] }).get(r.id)).leaves.push(l); }
    const targets = groups.size ? [...groups.values()] : [{ root: n, leaves }];
    for (const { root: target, leaves: tLeaves0 } of targets) {
    const tLeaves = tLeaves0;
    const tb = target.absoluteBoundingBox; const TW = Math.round(tb.width), TH = Math.round(tb.height);
    const key = masterOf.get(target.id) || target.id.split(';').pop();
    const b = tb; const cWorld = { m00: 1, m01: 0, m02: b.x, m10: 0, m11: 1, m12: b.y }; const cInv = inv(cWorld);
    const parts = [];
    for (const l of [...tLeaves].sort((a, z) => a.seq - z.seq)) {
      if (DECOR.has((l.node.name || '').toLowerCase())) continue;                       // same decorative filter as the scanner
      const T0 = mul(cInv, l.world); const fill = solid(l.fills), stroke = solid(l.strokes);
      const op = l.opacity !== undefined && l.opacity < 0.999 ? ` opacity="${l.opacity.toFixed(2)}"` : '';
      const strokeAttrs = stroke ? paintAttrs(stroke, 'stroke') + ` stroke-width="${f2(l.strokeWeight || 1)}"` + (l.node.strokeCap === 'ROUND' ? ' stroke-linecap="round"' : '') + (l.node.strokeJoin === 'ROUND' ? ' stroke-linejoin="round"' : '') : '';
      if (l.node.type === 'VECTOR' || l.node.type === 'STAR' || l.node.type === 'REGULAR_POLYGON') {
        const vn = l.node.vectorData?.vectorNetworkBlob; const bytes = typeof vn === 'number' ? blobBytes(vn) : null;
        if (!bytes) { noGeom++; continue; }
        const d = vectorNetworkBlobToPath(bytes); if (!d) { noGeom++; continue; }
        const ns = l.node.vectorData?.normalizedSize; const sx = ns?.x ? l.size.x / ns.x : 1, sy = ns?.y ? l.size.y / ns.y : 1;
        const T = mul(T0, { m00: sx, m01: 0, m02: 0, m10: 0, m11: sy, m12: 0 });
        parts.push(`<path d="${d}"${paintAttrs(fill, 'fill')}${fill ? ' fill-rule="evenodd"' : ''}${strokeAttrs}${op}${matAttr(T)}/>`);
      } else if (l.node.type === 'ELLIPSE') {
        parts.push(`<ellipse cx="${f2(l.size.x / 2)}" cy="${f2(l.size.y / 2)}" rx="${f2(l.size.x / 2)}" ry="${f2(l.size.y / 2)}"${paintAttrs(fill, 'fill')}${strokeAttrs}${op}${matAttr(T0)}/>`);
      } else if (l.node.type === 'RECTANGLE' || l.node.type === 'ROUNDED_RECTANGLE') {
        const r = l.node.rectangleTopLeftCornerRadius ?? l.node.cornerRadius ?? 0;
        parts.push(`<rect width="${f2(l.size.x)}" height="${f2(l.size.y)}"${r ? ` rx="${f2(r)}"` : ''}${paintAttrs(fill, 'fill')}${strokeAttrs}${op}${matAttr(T0)}/>`);
      } else if (l.node.type === 'LINE') {
        parts.push(`<line x1="0" y1="0" x2="${f2(l.size.x)}" y2="${f2(l.size.y)}"${strokeAttrs || ` stroke="${colorToHex(fill?.color)}" stroke-width="1"`}${op}${matAttr(T0)}/>`);
      }
    }
    if (!parts.length) { noGeom++; rows.push({ file: '', name: target.name, size: `${TW}×${TH}`, id: target.id, kind, note: 'no geometry in payload' }); continue; }
    const tName = GENERIC.test(target.name || '') && tLeaves.length === 1 && !GENERIC.test(tLeaves[0].node.name || '') ? tLeaves[0].node.name : target.name;
    let file = slug(tName) + `_${TW}x${TH}.svg`;
    if (seen.has(key)) { rows.push({ file: seen.get(key), name: target.name, size: `${TW}×${TH}`, id: target.id, kind, note: `reuse (in ${n.name})` }); continue; }
    let i = 2; while ([...seen.values()].includes(file)) file = slug(tName) + `_${TW}x${TH}_${i++}.svg`;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${TW}" height="${TH}" viewBox="0 0 ${TW} ${TH}">\n  ${parts.join('\n  ')}\n</svg>\n`;
    writeFileSync(join(ICONS_DIR, file), svg); seen.set(key, file); written++;
    rows.push({ file, name: tName, size: `${TW}×${TH}`, id: target.id, kind, note: `${parts.length} shape(s)${target !== n ? ` — glyph of "${n.name}" ${W}×${H}` : ''} — ${why}` });
    }
  }
  const md = ['# ICONS — containers the scanner flattened to `ICON` (viewBox = container box)', '', 'Kind: **static** = UI glyph to ship as a drawable · **dynamic** = content the app loads at runtime (logo/thumbnail), not exported unless `--include-dynamic` · **unsure** = exported, confirm or delete.', '', '| File | Figma name | Size | Kind | node-id | Note |', '|---|---|---|---|---|---|', ...rows.map((r) => `| ${r.file || '—'} | ${r.name} | ${r.size} | ${r.kind || ''} | ${r.id} | ${r.note} |`), '', `written ${written} · reused ${rows.filter((r) => r.note === 'reuse').length} · static ${rows.filter((r) => r.kind === 'static' && r.file).length} · unsure ${rows.filter((r) => r.kind === 'unsure' && r.file).length} · dynamic skipped ${rows.filter((r) => r.kind === 'dynamic' && !r.file).length} · no geometry ${noGeom}${ICON_FILTER ? ` · filter ${ICON_FILTER} (${allowIds ? allowIds.size + ' ids' : allow.size + ' ICON lines'})` : ''}`].join('\n');
  writeFileSync(join(ICONS_DIR, 'ICONS.md'), md);
  console.log(`icons: ${written} svg → ${ICONS_DIR} (reused ${rows.filter((r) => r.note === 'reuse').length}, no-geometry ${noGeom})`);
}
