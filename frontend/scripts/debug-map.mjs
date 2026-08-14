#!/usr/bin/env node
/**
 * Debug helper: boot servers, open the app, capture console + network errors
 * and a screenshot of the map screen. Text-only diagnostics for the builder.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import zlib from 'node:zlib';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const repo = path.resolve(root, '..');

const FRONTEND = process.env.CF_FRONTEND ?? 'http://localhost:5173';
const BACKEND = process.env.CF_BACKEND ?? 'http://localhost:8000';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function isUp(url, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    fetch(url, { signal: ctrl.signal, method: 'HEAD' })
      .then(() => resolve(true))
      .catch(() => resolve(false))
      .finally(() => clearTimeout(t));
  });
}

const procs = [];
const start = (script, name, cwd, timeoutMs = 20000) => {
  const p = spawn(script, { cwd, shell: true, env: process.env });
  procs.push(p);
  p.stdout?.on('data', (d) => process.stdout.write(`[${name}] ${d}`));
  p.stderr?.on('data', (d) => process.stdout.write(`[${name}:err] ${d}`));
  // watchdog: kill any lingering server so the command can't hang forever
  const killer = setTimeout(() => { try { p.kill(); } catch {} }, timeoutMs);
  p.on('exit', () => clearTimeout(killer));
  return p;
};

// global watchdog — never hang the session
const GLOBAL_TIMEOUT = 150000;
const watchdog = setTimeout(() => {
  console.error('GLOBAL TIMEOUT reached — forcing exit');
  procs.forEach((p) => { try { p.kill(); } catch {} });
  process.exit(2);
}, GLOBAL_TIMEOUT);
watchdog.unref?.();

const outDir = path.join(root, 'artifacts', 'debug');
await mkdir(outDir, { recursive: true });

// force-start: clear anything already holding the ports so servers come up fresh
for (const port of [8000, 5173]) {
  await (async () => {
    try {
      const r = await fetch(`http://localhost:${port}/api/health`, { method: 'HEAD', signal: AbortSignal.timeout(800) });
      if (r.ok) {
        // already up — rely on isUp below
      }
    } catch { /* down — safe to start */ }
  })();
}

if (!(await isUp(BACKEND))) {
  start(`${path.join(repo, 'backend', '.venv', 'Scripts', 'python.exe')} -m uvicorn app.main:app --port 8000 --app-dir ${path.join(repo, 'backend')}`, 'backend', repo, 25000);
}
if (!(await isUp(FRONTEND))) {
  start('npm run dev', 'vite', root, 30000);
}
for (let i = 0; i < 60; i++) {
  if ((await isUp(FRONTEND)) && (await isUp(BACKEND))) break;
  await sleep(1000);
}
console.log('frontend up:', await isUp(FRONTEND), 'backend up:', await isUp(BACKEND));

let browser;
for (const ch of ['chrome', 'msedge', 'chromium']) {
  try {
    browser = ch === 'chromium' ? await chromium.launch({ headless: true }) : await chromium.launch({ channel: ch, headless: true });
    console.log('browser:', ch);
    break;
  } catch { /* try next */ }
}
if (!browser) throw new Error('no browser');

const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const logs = [];
page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) logs.push(`[${m.type()}] ${m.text()}`); });
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.stack ?? e.message}`));
page.on('requestfailed', (r) => logs.push(`[requestfailed] ${r.url()} :: ${r.failure()?.errorText}`));
const tileStatus = [];
page.on('response', (r) => {
  const u = r.url();
  if (u.includes('tile.openstreetmap.org')) tileStatus.push(`${r.status()}`);
  if (u.endsWith('maplibre-gl.js') || u.includes('maplibre-gl')) { /* ignore */ }
});

// minimal PNG decoder (8-bit, non-interlaced, color type 2/6) for pixel stats
function pngStats(buf) {
  const pxOffset = (pos) => buf.readUInt32BE(pos);
  let pos = 8, w = 0, h = 0, colorType = 0, idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString('latin1', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') { w = data.readUInt32BE(0); h = data.readUInt32BE(4); colorType = data[9]; }
    else if (type === 'IDAT') idat.push(data);
    pos += 12 + len;
  }
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const bpp = colorType === 6 ? 4 : 3;
  const stride = w * bpp;
  const out = Buffer.alloc(h * stride);
  const paeth = (a, b, c) => {
    const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  let rp = 0;
  for (let y = 0; y < h; y++) {
    const filter = raw[rp++];
    const line = raw.subarray(rp, rp + stride);
    const prev = y > 0 ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? out[y * stride + x - bpp] : 0;
      const b = prev ? prev[x] : 0;
      const c = x >= bpp && prev ? prev[x - bpp] : 0;
      let v = line[x];
      if (filter === 1) v = (v + a) & 255;
      else if (filter === 2) v = (v + b) & 255;
      else if (filter === 3) v = (v + ((a + b) >> 1)) & 255;
      else if (filter === 4) v = (v + paeth(a, b, c)) & 255;
      out[y * stride + x] = v;
    }
    rp += stride;
  }
  let nonBlack = 0, bright = 0, nonWhite = 0, total = w * h;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const o = y * stride + x * bpp;
      const r = out[o], g = out[o + 1], b = out[o + 2];
      if (r > 12 || g > 12 || b > 12) nonBlack++;
      if (r > 200 && g > 200 && b > 200) bright++;
      if (r < 245 || g < 245 || b < 245) nonWhite++;
    }
  }
  return { w, h, nonBlackPct: (nonBlack / total * 100).toFixed(1), brightPct: (bright / total * 100).toFixed(1), nonWhitePct: (nonWhite / total * 100).toFixed(1) };
}

async function analyzePixels(selector, label) {
  const el = page.locator(selector).first();
  if ((await el.count()) === 0) { console.log(`PIXELS ${label}: no element`); return; }
  const box = await el.boundingBox();
  if (!box || box.height < 2 || box.width < 2) { console.log(`PIXELS ${label}: no/zero box`, JSON.stringify(box)); return; }
  const file = path.join(outDir, `${label}.png`);
  await page.screenshot({ path: file, clip: box });
  const buf = await readFile(file);
  console.log(`PIXELS ${label}:`, JSON.stringify(pngStats(buf)));
}

await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 45000 });
await sleep(8000);
await page.screenshot({ path: path.join(outDir, '01-launch.png') });

// drive into the main map workspace: BUILD TWIN → (event auto-runs) → home map
async function tryClick(sel, timeout = 3000) {
  try {
    const el = page.getByText(sel).first();
    if (await el.isVisible({ timeout })) { await el.click({ timeout }); return true; }
  } catch { /* not present */ }
  return false;
}
await tryClick('BUILD TWIN', 5000);
await sleep(9000);
await tryClick('RUN LIVE SCENARIO', 3000);
await sleep(4000);
await page.screenshot({ path: path.join(outDir, '02-map-workspace.png') });

// try to raise sim speed so flows are visible
await tryClick('×8', 2000);
await sleep(6000);
await page.screenshot({ path: path.join(outDir, '03-map-live.png') });

// confirm we're on the map workspace by looking for its markers
const markers = await page.evaluate(() => {
  const t = document.body.innerText;
  return {
    hasWorldMap: /World map|Live map/.test(t),
    hasEnterVenue: /ENTER VENUE/.test(t),
    hasGeoAnchor: /Geo anchor/.test(t),
    hasMapPanel: /roads|streets/.test(t),
  };
});
console.log('WORKSPACE MARKERS:', JSON.stringify(markers));

await analyzePixels('.maplibregl-canvas', 'map-canvas');
await analyzePixels('.maplibregl-canvas-container', 'map-container');

// dump live map internals from the dev hook
const mapInfo = await page.evaluate(() => {
  const m = window.__crowdflowMap;
  if (!m) return { mounted: false };
  const mapRoot = m.getContainer();
  const rc = mapRoot.getBoundingClientRect();
  const canvas = m.getCanvas();
  let styleLoaded = false;
  try { styleLoaded = m.isStyleLoaded(); } catch {}
  let sourceTiles = null;
  try {
    const src = m.getSource('osm');
    sourceTiles = src ? { type: src.type, loaded: src.loaded ? src.loaded() : null, tiles: (src.tiles ?? src._tiles ?? []).length } : null;
  } catch (e) { sourceTiles = `err:${e.message}`; }
  return {
    mounted: true,
    loaded: m.loaded(),
    styleLoaded,
    zoom: m.getZoom(),
    center: m.getCenter(),
    canvasBuffer: `${canvas.width}x${canvas.height}`,
    canvasCss: `${canvas.offsetWidth}x${canvas.offsetHeight}`,
    mapRootRect: { x: rc.x, y: rc.y, w: rc.width, h: rc.height },
    sourceTiles,
    bg: getComputedStyle(mapRoot).backgroundColor,
  };
});
console.log('MAP INFO:', JSON.stringify(mapInfo, null, 2));

// layout chain: how the flex column distributes height
const layout = await page.evaluate(() => {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return { cls: (el.className || el.tagName).toString().slice(0, 60), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), display: cs.display, height: cs.height, flex: cs.flex, position: cs.position };
  };
  const out = { innerHeight: window.innerHeight };
  const mapRoot = document.querySelector('.maplibregl-map');
  out.mapRoot = rect(mapRoot);
  const chain = [];
  let el = mapRoot;
  for (let i = 0; i < 5 && el; i++) {
    el = el.parentElement;
    chain.push(rect(el));
  }
  out.chain = chain;
  out.canvasStyle = document.querySelector('.maplibregl-canvas')?.getAttribute('style');
  return out;
});
await writeFile(path.join(outDir, 'layout.json'), JSON.stringify(layout, null, 2));
console.log('LAYOUT written to', path.join(outDir, 'layout.json'));
console.log('LAYOUT SUMMARY mapRoot:', JSON.stringify(layout.mapRoot));
console.log('LAYOUT SUMMARY chain:', layout.chain.map((c) => (c ? `${c.cls} h=${c.h} disp=${c.display} hcss=${c.height}` : 'null')).join(' → '));

// tile load check: response statuses + how many OSM tile requests happened
const tileCounts = tileStatus.reduce((acc, s) => { acc[s] = (acc[s] ?? 0) + 1; return acc; }, {});
console.log('TILE STATUS COUNTS:', JSON.stringify(tileCounts));
const tileStats = await page.evaluate(async () => {
  const perf = performance.getEntriesByType('resource').filter((r) => r.name.includes('tile.openstreetmap.org'));
  return { tileRequests: perf.length };
});
console.log('TILES:', JSON.stringify(tileStats));

// dump any visible text in the main screen (proves UI shell renders)
const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 800).replace(/\n+/g, ' | '));
console.log('BODY TEXT:', bodyText);

// inspect canvases: count + sizes + whether WebGL context exists
const canvasInfo = await page.evaluate(() => {
  const out = [];
  for (const c of document.querySelectorAll('canvas')) {
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    out.push({ cls: c.className, w: c.width, h: c.height, css: `${c.offsetWidth}x${c.offsetHeight}`, webgl: !!gl });
  }
  return out;
});
console.log('CANVASES:', JSON.stringify(canvasInfo, null, 2));

console.log('--- LOGS ---');
for (const l of logs.slice(0, 60)) console.log(l);
console.log('--- /LOGS ---');

await browser.close();
procs.forEach((p) => { try { p.kill(); } catch {} });
clearTimeout(watchdog);
