// update figma check — clipboard payload → per-screen context.txt hash vs manifest → changed / new / unchanged / unknown.
// Usage: node figclip_check.mjs <feature-dir> [clip.json]   (no clip.json → dump the clipboard first)
// Writes <feature>/_scan/CHANGES.md and keeps <feature>/_scan/clips/<timestamp>.clip.json for property-level diff later.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCANNER = join(HERE, '..', 'figma_deep_scan.py');
const [feature, clipArg] = process.argv.slice(2);
if (!feature) { console.error('usage: figclip_check.mjs <feature-dir> [clip.json]'); process.exit(1); }
const scanDir = join(feature, '_scan'); mkdirSync(join(scanDir, 'clips'), { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const clip = clipArg || join(scanDir, 'clips', `${stamp}.clip.json`);
if (!clipArg) execFileSync('node', [join(HERE, 'figclip_dump.mjs'), clip], { stdio: 'inherit' });

const manifest = JSON.parse(readFileSync(join(scanDir, 'manifest.json'), 'utf8'));
const byNode = new Map(Object.entries(manifest.screens || {}).map(([name, s]) => [s.node_id, { name, ...s }]));
const { message, meta } = JSON.parse(readFileSync(clip, 'utf8'));
const nodes = message.nodeChanges; const gid = (g) => `${g.sessionID}:${g.localID}`;
const byId = new Map(nodes.map((n) => [gid(n.guid), n]));
const canvas = new Set(nodes.filter((n) => n.type === 'CANVAS' && !/Internal/.test(n.name)).map((n) => gid(n.guid)));
const isPhone = (n) => n.size && n.size.x >= 360 && n.size.x <= 480 && n.size.y >= 640 && n.size.y <= 1100;
// candidate screens = phone-sized FRAME/INSTANCE/SECTION whose parent is a non-internal CANVAS, ANY SECTION
// (recurses into nested sections at any depth), or a top-level frame directly under such a canvas. Screens never
// nest inside screens, so we key off the parent type rather than descending into phone frames — this avoids
// picking up phone-sized sub-frames inside big mockups (e.g. a "Remote" group) while still seeing every section.
const childrenOf = new Map();
for (const n of nodes) { const p = n.parentIndex && n.parentIndex.guid && gid(n.parentIndex.guid); if (p) { if (!childrenOf.has(p)) childrenOf.set(p, []); childrenOf.get(p).push(n); } }
const reachable = new Set(); { const stack = [...canvas]; while (stack.length) { for (const c of (childrenOf.get(stack.pop()) || [])) { const cid = gid(c.guid); if (!reachable.has(cid)) { reachable.add(cid); stack.push(cid); } } } }
const sections = new Set(nodes.filter((n) => n.type === 'SECTION' && reachable.has(gid(n.guid))).map((n) => gid(n.guid)));
const topFrames = new Set(nodes.filter((n) => n.type === 'FRAME' && n.parentIndex && canvas.has(gid(n.parentIndex.guid))).map((n) => gid(n.guid)));
const isScreenParent = (pid) => canvas.has(pid) || sections.has(pid) || topFrames.has(pid);
const expanded = nodes.filter((n) => isPhone(n) && ['FRAME', 'INSTANCE', 'SECTION'].includes(n.type) && n.parentIndex && reachable.has(gid(n.guid)) && isScreenParent(gid(n.parentIndex.guid)));
if (meta.fileKey && manifest.figma_file_key && meta.fileKey !== manifest.figma_file_key) console.warn(`⚠ fileKey differs: clipboard ${meta.fileKey} vs manifest ${manifest.figma_file_key} (draft copy vs Design file? node-ids still compared)`);

const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const tmp = join(scanDir, '.check_tmp'); rmSync(tmp, { recursive: true, force: true });
const rows = []; const seen = new Set();
for (const s of expanded) {
  const id = gid(s.guid); seen.add(id);
  const dir = join(tmp, id.replace(':', '_')); mkdirSync(dir, { recursive: true });
  execFileSync('node', [join(HERE, 'kiwi_to_rest.mjs'), clip, id, join(dir, 'raw.json')], { stdio: 'ignore' });
  execFileSync('python3', [SCANNER, '--context', '--tokens', '--exclude', 'Status Bar', 'Bottom Bar', 'Scroll Edge Effect', '-o', dir, '--', join(dir, 'raw.json')], { stdio: 'ignore' });
  const ctx = readFileSync(join(dir, 'context.txt'));
  const h = sha(ctx); const known = byNode.get(id);
  if (!known) rows.push({ id, name: s.name, status: 'new', note: `${ctx.toString().split('\n').length} lines` });
  else if (known.content_hash === h) rows.push({ id, name: known.name, status: 'unchanged', note: '' });
  else {
    let note = 'context.txt differs';
    const old = join(feature, 'screens', known.name, 'context.txt');
    if (existsSync(old)) { const a = readFileSync(old, 'utf8').split('\n'), b = ctx.toString().split('\n'); const added = b.filter((l) => !a.includes(l)).length, removed = a.filter((l) => !b.includes(l)).length; note = `+${added} −${removed} lines`; }
    rows.push({ id, name: known.name, status: 'changed', note });
  }
}
for (const [id, s] of byNode) if (!seen.has(id)) rows.push({ id, name: s.name, status: 'unknown', note: 'not in clipboard selection' });
rows.sort((a, b) => ['changed', 'new', 'unchanged', 'unknown'].indexOf(a.status) - ['changed', 'new', 'unchanged', 'unknown'].indexOf(b.status));
const md = [`# CHANGES — ${stamp} (clipboard fileKey ${meta.fileKey})`, '', '| Screen | node-id | Status | Note |', '|---|---|---|---|', ...rows.map((r) => `| ${r.name} | ${r.id} | ${r.status} | ${r.note} |`), '',
  `changed ${rows.filter((r) => r.status === 'changed').length} · new ${rows.filter((r) => r.status === 'new').length} · unchanged ${rows.filter((r) => r.status === 'unchanged').length} · unknown ${rows.filter((r) => r.status === 'unknown').length}`,
  '', 'Next: `update figma replace <node>` for changed, `update figma add` for new, then /awesome:build delta rebuild. Unknown = not copied, not deleted.'].join('\n');
writeFileSync(join(scanDir, 'CHANGES.md'), md); rmSync(tmp, { recursive: true, force: true });
console.log(md);
