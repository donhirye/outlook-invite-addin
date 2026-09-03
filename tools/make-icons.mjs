/*
 * Generates the add-in button icons (16, 32, 80 px) as PNGs with no external
 * dependencies. Draws a rounded blue tile with a white "+" (create) glyph.
 *
 * Run from the add-in folder:  node tools/make-icons.mjs
 */
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "assets");
mkdirSync(OUT_DIR, { recursive: true });

const BG = [11, 92, 168]; // Wi-Tronix-ish blue
const FG = [255, 255, 255];

function makePng(size) {
  const px = new Uint8Array(size * size * 4); // RGBA
  const radius = Math.round(size * 0.18);
  const barThick = Math.max(2, Math.round(size * 0.14));
  const margin = Math.round(size * 0.28);
  const c = size / 2;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const inTile = insideRoundedRect(x, y, 0, 0, size, size, radius);
      if (!inTile) {
        px[i + 3] = 0; // transparent outside the tile
        continue;
      }
      // Draw a white plus sign centered in the tile.
      const inVert = Math.abs(x - c) <= barThick / 2 && y >= margin && y <= size - margin;
      const inHorz = Math.abs(y - c) <= barThick / 2 && x >= margin && x <= size - margin;
      const color = inVert || inHorz ? FG : BG;
      px[i] = color[0];
      px[i + 1] = color[1];
      px[i + 2] = color[2];
      px[i + 3] = 255;
    }
  }
  return encodePng(size, size, px);
}

function insideRoundedRect(x, y, rx, ry, w, h, r) {
  const minx = rx, miny = ry, maxx = rx + w - 1, maxy = ry + h - 1;
  if (x < minx || x > maxx || y < miny || y > maxy) return false;
  const corners = [
    [minx + r, miny + r], [maxx - r, miny + r],
    [minx + r, maxy - r], [maxx - r, maxy - r],
  ];
  const nearLeft = x < minx + r, nearRight = x > maxx - r;
  const nearTop = y < miny + r, nearBottom = y > maxy - r;
  if ((nearLeft || nearRight) && (nearTop || nearBottom)) {
    const cx = nearLeft ? corners[0][0] : corners[1][0];
    const cy = nearTop ? corners[0][1] : corners[2][1];
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
  }
  return true;
}

function encodePng(width, height, rgba) {
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 6;  // color type RGBA
  ihdr[10] = 0; // compression
  ihdr[11] = 0; // filter
  ihdr[12] = 0; // interlace

  // Raw image data: each scanline prefixed with filter byte 0.
  const raw = Buffer.alloc(height * (width * 4 + 1));
  for (let y = 0; y < height; y++) {
    const rowStart = y * (width * 4 + 1);
    raw[rowStart] = 0;
    rgba.slice(y * width * 4, (y + 1) * width * 4).forEach((b, k) => {
      raw[rowStart + 1 + k] = b;
    });
  }
  const idat = deflateSync(raw);

  return Buffer.concat([
    sig,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0, 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

for (const size of [16, 32, 80]) {
  writeFileSync(join(OUT_DIR, `icon-${size}.png`), makePng(size));
  console.log(`wrote assets/icon-${size}.png`);
}
