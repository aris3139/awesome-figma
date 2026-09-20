// Dump Figma clipboard (⌘C in Figma) → JSON. Handles both raw and HTML-escaped figmeta/figma markers.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { parseFigBuffer } from './figparse.js';
const out = process.argv[2] || 'clip.json';
if (process.argv.includes('--png')) { // ⌘⇧C (Copy as PNG) → file
  const raw = execFileSync('osascript', ['-e', 'the clipboard as «class PNGf»'], { encoding: 'utf8', maxBuffer: 512 * 1024 * 1024 }).trim();
  const png = Buffer.from(raw.replace(/^«data \w{4}/, '').replace(/»$/, ''), 'hex'); const dest = process.argv[process.argv.indexOf('--png') + 1] || 'screenshot.png';
  if (png.length < 100) { console.error('Clipboard has no PNG. In Figma select the frame, press ⌘⇧C (Copy as PNG), retry.'); process.exit(2); }
  writeFileSync(dest, png); console.log('png:', dest, (png.length / 1024).toFixed(0) + ' KB'); process.exit(0);
}
const raw = execFileSync('osascript', ['-e', 'the clipboard as «class HTML»'], { encoding: 'utf8', maxBuffer: 512 * 1024 * 1024 }).trim();
let html = Buffer.from(raw.replace(/^«data \w{4}/, '').replace(/»$/, ''), 'hex').toString('utf8');
html = html.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const between = (s, a, b) => { const i = s.indexOf(a); if (i < 0) return null; const j = s.indexOf(b, i); return j < 0 ? null : s.slice(i + a.length, j); };
const metaB64 = between(html, '<!--(figmeta)', '(/figmeta)-->'), figB64 = between(html, '<!--(figma)', '(/figma)-->');
if (!metaB64 || !figB64) { console.error('Clipboard has no Figma payload. Select in Figma, ⌘C, retry.'); process.exit(2); }
const meta = JSON.parse(Buffer.from(metaB64, 'base64').toString('utf8'));
const { version, message } = parseFigBuffer(Buffer.from(figB64, 'base64'));
// Opt-in: decode vector geometry to SVG here, while blob bytes are still live Uint8Arrays
// (line below strips them to `<bytes N>` placeholders). Writes {nodeId: {name,type,svg,w,h}}.
if (process.argv.includes('--svg')) {
  const svgOut = process.argv[process.argv.indexOf('--svg') + 1];
  const { extractSvgs } = await import('./svg.mjs');
  const map = extractSvgs(message);
  const obj = {}; for (const [id, v] of map) obj[id] = v;
  writeFileSync(svgOut, JSON.stringify(obj));
  console.log('svg:', svgOut, '| icons decoded:', map.size);
}
writeFileSync(out, JSON.stringify({ meta, version, message }, (k, v) => (v instanceof Uint8Array ? 'b64:' + Buffer.from(v).toString('base64') : typeof v === 'bigint' ? v.toString() : v))); // blobs kept as base64 (vector geometry for icons)
console.log('meta:', JSON.stringify(meta));
console.log('container v' + version, '| nodes:', message.nodeChanges.length, '| html:', (html.length / 1024).toFixed(0) + ' KB', '| out:', out);
