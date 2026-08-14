#!/usr/bin/env node
/**
 * CrowdFlow visual-verification capture.
 *
 * Launches the real rendered app in a browser, walks the P0 product loop with
 * best-effort UI driving, and saves screenshots + a manifest to
 * frontend/artifacts/screenshots. The PNGs are meant to be read by the
 * vision-capable `crowdflow-visual-reviewer` agent.
 *
 * Usage (from frontend/):
 *   node scripts/capture-screenshots.mjs                  # assumes servers already running
 *   node scripts/capture-screenshots.mjs --serve          # also start backend+vite
 *   node scripts/capture-screenshots.mjs --frontend=http://localhost:5173 --out=artifacts/screenshots
 *
 * Requirements: `playwright` devDependency + an installed Chrome/Edge, OR run
 * `npx playwright install chromium` once for the bundled browser.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..'); // frontend/
const repo = path.resolve(root, '..'); // crowdflow/

const args = process.argv.slice(2);
const cfg = {
  frontend: args.find((a) => a.startsWith('--frontend='))?.split('=')[1] ?? 'http://localhost:5173',
  backend: args.find((a) => a.startsWith('--backend='))?.split('=')[1] ?? 'http://localhost:8000',
  out: args.find((a) => a.startsWith('--out='))?.split('=')[1] ?? path.join(root, 'artifacts', 'screenshots'),
  serve: args.includes('--serve'),
  browser: args.find((a) => a.startsWith('--browser='))?.split('=')[1] ?? 'auto', // auto|chromium|chrome|msedge
  viewport: { width: 1440, height: 900 },
};

const shots = [];
const log = (...m) => console.log('[capture]', ...m);
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

async function startServers() {
  const procs = [];
  const start = (script, name, cwd = repo) => {
    log(`starting ${name}...`);
    const p = spawn(script, { cwd, shell: true, env: process.env });
    procs.push(p);
    p.stdout?.on('data', (d) => process.env.CF_VERBOSE && process.stdout.write(`[${name}] ${d}`));
    p.stderr?.on('data', (d) => process.env.CF_VERBOSE && process.stderr.write(`[${name}] ${d}`));
    return p;
  };
  if (!(await isUp(cfg.backend))) {
    start(`${path.join(repo, 'backend', '.venv', 'Scripts', 'python.exe')} -m uvicorn app.main:app --port 8000 --app-dir ${path.join(repo, 'backend')}`, 'backend', repo);
  }
  if (!(await isUp(cfg.frontend))) {
    start(`npm run dev`, 'vite', root);
  }
  // wait for both to be reachable
  for (let i = 0; i < 60; i++) {
    if ((await isUp(cfg.frontend)) && (await isUp(cfg.backend))) return procs;
    await sleep(1000);
  }
  throw new Error('Servers did not come up in 60s');
}

async function launch() {
  const channels = cfg.browser === 'auto' ? ['chrome', 'msedge', 'chromium'] : [cfg.browser];
  for (const ch of channels) {
    try {
      const b = ch === 'chromium'
        ? await chromium.launch({ headless: cfg.headless ?? true })
        : await chromium.launch({ channel: ch, headless: cfg.headless ?? true });
      log(`browser ready via ${ch}`);
      return b;
    } catch (e) {
      log(`browser channel '${ch}' unavailable (${e.message.split('\n')[0]}); trying next`);
    }
  }
  throw new Error('No usable browser. Install one: npx playwright install chromium');
}

// Best-effort text click. Returns true if clicked.
async function clickText(page, text, { exact = false, timeout = 2500 } = {}) {
  try {
    await page.getByText(text, { exact }).first().click({ timeout });
    return true;
  } catch {
    return false;
  }
}

async function capture(page, name, detail) {
  await page.waitForTimeout(600);
  const file = `${name}.png`;
  const p = path.join(cfg.out, file);
  await page.screenshot({ path: p, fullPage: false });
  const meta = { name, file, url: page.url(), detail };
  shots.push(meta);
  log(`saved ${file} — ${detail}`);
  return meta;
}

async function main() {
  await mkdir(cfg.out, { recursive: true });
  await rm(path.join(cfg.out, 'manifest.json'), { force: true }).catch(() => {});

  const procs = cfg.serve ? await startServers() : [];
  log('frontend reachable:', await isUp(cfg.frontend));
  log('backend reachable:', await isUp(cfg.backend));

  const browser = await launch();
  const page = await browser.newPage({ viewport: cfg.viewport });

  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  const steps = [];
  let ok = true;
  const run = async (label, fn) => {
    try { await fn(); steps.push({ step: label, status: 'ok' }); }
    catch (e) { ok = false; steps.push({ step: label, status: 'failed', error: e.message }); log(`STEP FAILED: ${label} — ${e.message}`); }
  };

  await run('open-app', async () => {
    await page.goto(cfg.frontend, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(7000);
    await capture(page, '01-launch', 'launch: world map + demand sources + scenario (auto-running)');
  });

  await run('run-live-scenario', async () => {
    // If the sim has not auto-started, press the primary action.
    const didClick = await clickText(page, 'RUN LIVE SCENARIO');
    // Push the simulation to 8x so the demo beats the wait.
    await clickText(page, '×8', { exact: true });
    await page.waitForTimeout(6000);
    await capture(page, '02-map-live', 'map live: world flows + gate queues + sources');
  });

  await run('congestion-builds', async () => {
    // let GATE_A's external queue + congestion build
    await page.waitForTimeout(18000);
    await capture(page, '03-congestion', 'world congestion: GATE_A queue + risk, predictions');
  });

  await run('predict-tool', async () => {
    await clickText(page, 'PREDICT', { exact: true });
    await page.waitForTimeout(2000);
    await capture(page, '04-predict', 'PREDICT: projected congestion + time-to-critical');
  });

  await run('enter-venue', async () => {
    await clickText(page, 'ENTER VENUE');
    await page.waitForTimeout(4000);
    await capture(page, '05-venue-live', 'venue twin: living crowd + Gate A stress');
  });

  await run('whatif-launcher', async () => {
    await clickText(page, 'WHAT-IF', { exact: true });
    await page.waitForTimeout(1500);
    await capture(page, '06-whatif-launcher', 'WHAT-IF launcher: real gate interventions');
    const didPick = await clickText(page, 'Restrict Gate A');
    await page.waitForTimeout(12000);
    await capture(page, '07-whatif-split', didPick ? 'what-if split: BASELINE vs counterfactual rerouting' : 'what-if (launcher pick failed)');
  });

  await run('whatif-map-reroute', async () => {
    await clickText(page, 'MAP', { exact: true });
    await page.waitForTimeout(2500);
    await capture(page, '08-map-reroute', 'map: baseline vs what-if rerouting strip (Gate A down, alt gates up)');
  });

  await run('optimize', async () => {
    await clickText(page, 'OPTIMIZE', { exact: true });
    await page.waitForTimeout(1000);
    await clickText(page, 'RUN OPTIMISATION');
    await page.waitForTimeout(9000);
    await capture(page, '09-optimize', 'OPTIMIZE: best intervention + expected impact + SIMULATE/APPLY');
  });

  await run('ai', async () => {
    await clickText(page, 'AI', { exact: true });
    await page.waitForTimeout(1500);
    await clickText(page, 'WHY', { exact: true });
    await page.waitForTimeout(12000);
    await capture(page, '10-ai', 'AI reasoning over live simulation state');
  });

  await run('final', async () => {
    await page.waitForTimeout(800);
    await capture(page, '11-final', 'final state');
  });

  await browser.close();

  const manifest = {
    captured_at: new Date().toISOString(),
    frontend: cfg.frontend,
    backend: cfg.backend,
    console_errors: consoleErrors,
    shots,
    steps,
  };
  await writeFile(path.join(cfg.out, 'manifest.json'), JSON.stringify(manifest, null, 2));
  log('manifest written.');
  log(`${shots.length} screenshots (${cfg.out}), ${consoleErrors.length} console errors, ${steps.length} steps, ok=${ok}`);
  if (consoleErrors.length) {
    console.error('Console errors detected:\n  ' + consoleErrors.slice(0, 20).join('\n  '));
  }
  procs.forEach((p) => { try { p.kill(); } catch {} });
  process.exit(ok ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });