// The .fig format: the fig-kiwi container, plus Figma's clipboard flavors.
//
// Container: the magic 'fig-kiwi', a version (uint32 LE), then blocks of [uint32 LE size][data].
// Block 0 is a binary kiwi schema (raw deflate); block 1 is the scene message (zstd these days).

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { inflateRawSync } from 'node:zlib';

import { decompress as zstdDecompress } from 'fzstd';
import { decodeBinarySchema, compileSchema } from 'kiwi-schema';

const MAGIC = 'fig-kiwi';
const ZSTD_MAGIC = 0xfd2fb528;

const FIGMETA_START = '<!--(figmeta)';
const FIGMETA_END = '(/figmeta)-->';
const FIGMA_START = '<!--(figma)';
const FIGMA_END = '(/figma)-->';

function unpack(block) {
  if (block.length >= 4 && block.readUInt32LE(0) === ZSTD_MAGIC) {
    return Buffer.from(zstdDecompress(block));
  }
  return inflateRawSync(block);
}

/** Parses a .fig buffer into a scene message. */
export function parseFigBuffer(buf) {
  if (buf.length < 12 || buf.subarray(0, 8).toString('utf8') !== MAGIC) {
    throw new Error('Not a fig-kiwi container: the file signature does not match.');
  }

  const version = buf.readUInt32LE(8);
  const blocks = [];
  let offset = 12;
  while (offset + 4 <= buf.length) {
    const size = buf.readUInt32LE(offset);
    offset += 4;
    blocks.push(buf.subarray(offset, offset + size));
    offset += size;
  }

  if (blocks.length < 2) {
    throw new Error(`Expected at least 2 data blocks, found ${blocks.length}.`);
  }

  const schema = compileSchema(decodeBinarySchema(unpack(blocks[0])));
  const message = schema.decodeMessage(unpack(blocks[1]));
  return { version, message };
}

/**
 * Expands a leading ~ to the home directory: paths are usually typed or pasted by a person,
 * and ~/Downloads/design.fig is how a person writes one.
 */
export function expandHome(filePath, home = homedir()) {
  if (filePath === '~') return home;
  if (filePath.startsWith('~/')) return join(home, filePath.slice(2));
  return filePath;
}

/** Reads a .fig saved through File - Save local copy. */
export function readFigFile(path) {
  const resolved = expandHome(path);
  return { source: `file ${resolved}`, ...parseFigBuffer(readFileSync(resolved)) };
}

/**
 * Reading the clipboard goes through osascript, which exists only on macOS.
 * Everything else in this package — .fig files included — works anywhere.
 */
export function assertClipboardSupport(platform = process.platform) {
  if (platform !== 'darwin') {
    throw new Error(
      `Reading the Figma clipboard needs macOS, and this is ${platform}. ` +
        'Save the design with File - Save local copy in Figma and load that .fig file instead.'
    );
  }
}

function clipboardFlavor(className) {
  const raw = execFileSync('osascript', ['-e', `the clipboard as «class ${className}»`], {
    encoding: 'utf8',
    maxBuffer: 512 * 1024 * 1024,
  }).trim();
  const hex = raw.replace(/^«data \w{4}/, '').replace(/»$/, '');
  return Buffer.from(hex, 'hex');
}

function between(text, start, end) {
  const from = text.indexOf(start);
  if (from < 0) return null;
  const to = text.indexOf(end, from);
  if (to < 0) return null;
  return text.slice(from + start.length, to);
}

/** Reads a selection copied in Figma (⌘C) from the HTML flavor of the macOS clipboard. */
export function readClipboard() {
  assertClipboardSupport();

  let html;
  try {
    html = clipboardFlavor('HTML').toString('utf8');
  } catch (e) {
    throw new Error(
      'The clipboard holds no Figma data. Select something in Figma, press ⌘C, and try again.'
    );
  }

  const metaB64 = between(html, FIGMETA_START, FIGMETA_END);
  const figB64 = between(html, FIGMA_START, FIGMA_END);
  if (!metaB64 || !figB64) {
    throw new Error(
      'The clipboard holds HTML, but not from Figma. Select something in Figma, press ⌘C, and try again.'
    );
  }

  const meta = JSON.parse(Buffer.from(metaB64, 'base64').toString('utf8'));
  const parsed = parseFigBuffer(Buffer.from(figB64, 'base64'));
  return { source: `clipboard, file ${meta.fileKey}`, meta, ...parsed };
}

/** Reads a PNG from the clipboard (⌘⇧C — Copy as PNG). */
export function readClipboardPng() {
  assertClipboardSupport();

  try {
    return clipboardFlavor('PNGf');
  } catch (e) {
    throw new Error(
      'The clipboard holds no PNG. Select a node in Figma, press ⌘⇧C (Copy as PNG), and try again.'
    );
  }
}
