// Bulk import of a real CT study through the UI, then viewing it in the embedded OHIF viewer.
//
// Create a patient → Imaging → OHIF Viewer → Import → Select ZIP Archive → upload a ZIP of a real,
// de-identified 143-slice chest CT (plus a README) → wait for the import → the study and its series
// appear → Open in OHIF → DICOMweb requests on the patient's root → 143 instances in the stack →
// a non-black CT slice → MPR (three orthographic views) → 3D four up (volume rendering).
//
// The CT comes from the workspace's OHIF test data (DICOM-TestData, "scoord-bounding-box", NLST,
// PatientIdentityRemoved=YES). The ZIP is built in a temporary directory and removed afterwards.
//
//   HOLOMED_E2E_BROWSER=<path to chrome/brave/edge.exe> npm run test:e2e:ct-import
//   (optional) HOLOMED_CT_FIXTURE_DIR=<folder of CT .dcm files>
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.HOLOMED_E2E_BASE ?? 'http://localhost:5173/';
const CT_SUBDIR = ['DICOM-TestData', 'viewer-testdata-master', 'dcm', 'scoord3d-and-scoord', 'scoord-bounding-box'];

function findFixture() {
  if (process.env.HOLOMED_CT_FIXTURE_DIR) return process.env.HOLOMED_CT_FIXTURE_DIR;
  for (let dir = here; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, ...CT_SUBDIR);
    if (fs.existsSync(candidate)) return candidate;
    if (path.dirname(dir) === dir) return null;
  }
}

/** A ZIP (stored, no compression) of [name, Buffer] entries. */
function storedZip(entries) {
  const locals = [];
  const central = [];
  let offset = 0;
  for (const [name, data] of entries) {
    const n = Buffer.from(name);
    const crc = zlib.crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(n.length, 26);
    locals.push(local, n, data);
    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0); entry.writeUInt16LE(20, 4); entry.writeUInt16LE(20, 6);
    entry.writeUInt32LE(crc, 16); entry.writeUInt32LE(data.length, 20); entry.writeUInt32LE(data.length, 24);
    entry.writeUInt16LE(n.length, 28); entry.writeUInt32LE(offset, 42);
    central.push(entry, n);
    offset += 30 + n.length + data.length;
  }
  const directory = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

const FIXTURE = findFixture();
if (!FIXTURE) {
  console.log('SKIPPED: CT fixture (DICOM-TestData) not present');
  process.exit(0);
}
const ctFiles = fs.readdirSync(FIXTURE).filter((f) => f.endsWith('.dcm') && !f.startsWith('SR'));
assert.equal(ctFiles.length, 143, 'expected the 143-slice CT series');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'holomed-ct-e2e-'));
const zipPath = path.join(tmp, 'chest-ct.zip');
fs.writeFileSync(zipPath, storedZip([
  ...ctFiles.map((f) => [`NLST/CT/${f}`, fs.readFileSync(path.join(FIXTURE, f))]),
  ['NLST/README.txt', Buffer.from('De-identified public test study.\n')],
]));
const zipSize = fs.statSync(zipPath).size;

// Pixel statistics of a Cornerstone viewport canvas (WebGL canvases are copied to a 2D canvas first).
const CANVAS_STATS = `(vp) => {
  const c = vp.canvas; const off = document.createElement('canvas'); off.width = c.width; off.height = c.height;
  const ctx = off.getContext('2d'); ctx.drawImage(c, 0, 0);
  const d = ctx.getImageData(0, 0, c.width, c.height).data; let bright = 0; const levels = new Set();
  for (let i = 0; i < d.length; i += 16) { const g = (d[i] + d[i + 1] + d[i + 2]) / 3; levels.add(Math.round(g)); if (g > 40) bright++; }
  return { type: vp.type, w: c.width, h: c.height, bright: bright / (d.length / 16), levels: levels.size };
}`;

async function until(label, check, tries = 120, wait = 500) {
  for (let i = 0; i < tries; i++) {
    const value = await check().catch(() => null);
    if (value) return value;
    await new Promise((r) => setTimeout(r, wait));
  }
  throw new Error(`timed out: ${label}`);
}

const browser = await chromium.launch(process.env.HOLOMED_E2E_BROWSER
  ? { executablePath: process.env.HOLOMED_E2E_BROWSER, headless: true }
  : { channel: 'chrome', headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();
  const responses = [];
  page.on('response', (r) => { const u = new URL(r.url()); if (u.pathname.includes('/dicomweb/')) responses.push({ u, r }); });

  const email = `ct-import-${Date.now()}@example.com`;
  await page.request.post(`${BASE}api/v1/auth/register`, { params: { email, password: 'Ct-Import-123' } });
  assert.equal((await page.request.post(`${BASE}api/v1/auth/login`, { form: { username: email, password: 'Ct-Import-123' } })).status(), 200);
  const patient = await (await page.request.post(`${BASE}api/v1/patients`, { data: { name: 'CT Import Patient', patient_code: 'HML-CT-IMPORT' } })).json();

  // ── Import dialog: three distinct input methods ─────────────────────────────
  await page.goto(`${BASE}imaging`);
  await page.getByTestId('imaging-patient').filter({ hasText: 'HML-CT-IMPORT' }).waitFor();
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await page.getByTestId('open-dicom-import').click();
  const dialog = page.getByTestId('modal');
  for (const [id, label, badge] of [['files', 'Select DICOM Files', 'Files'], ['folder', 'Select DICOM Folder', 'Folder'], ['zip', 'Select ZIP Archive', 'ZIP']]) {
    const option = dialog.getByTestId(`import-pick-${id}`);
    assert.ok((await option.innerText()).includes(label) && (await option.innerText()).includes(badge), `${label} option`);
  }
  assert.equal(await dialog.getByTestId('import-input-folder').getAttribute('webkitdirectory'), '');
  assert.equal(await dialog.getByTestId('import-input-files').getAttribute('multiple'), '');
  await dialog.getByTestId('import-input-zip').setInputFiles(zipPath);
  const selection = await dialog.getByTestId('import-selection').innerText();
  assert.ok(selection.includes('ZIP') && selection.includes('chest-ct.zip') && /7\d\.\d MB/.test(selection), selection);
  console.log(`  ✓ ZIP selected (${(zipSize / 1024 ** 2).toFixed(1)} MB, ${ctFiles.length + 1} files)`);

  // ── Upload and import, recording the progress the user sees ────────────────
  await dialog.getByTestId('import-start').click();
  const seen = new Set();
  await until('import summary', async () => {
    const progress = dialog.getByTestId('import-progress');
    if (await progress.count()) {
      seen.add(`${await progress.getAttribute('data-phase')}:${await progress.getAttribute('data-stage')}`);
      const active = await progress.locator('[data-state="active"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-step')));
      active.forEach((s) => seen.add(`step:${s}`));
    }
    if (await dialog.getByTestId('import-error').count()) throw new Error(await dialog.getByTestId('import-error').innerText());
    return (await dialog.getByTestId('import-summary').count()) > 0;
  }, 1200, 250);
  const summary = await dialog.getByTestId('import-summary').innerText();
  assert.ok(/1 study/.test(summary) && /1 series/.test(summary) && /143 instances/.test(summary), summary);
  assert.ok(/1 non-DICOM file/.test(summary), summary);
  const count = async (k) => (await dialog.getByTestId(`import-count-${k}`).innerText()).split('\n').pop();
  assert.equal(await count('discovered'), '144');
  assert.equal(await count('validated'), '144');
  assert.equal(await count('instances'), '143 / 143');
  assert.equal(await count('skipped'), '1');
  assert.equal(await count('failed'), '0');
  assert.ok(seen.has('step:uploading') && [...seen].some((s) => s.startsWith('server:')), [...seen].join(', '));
  assert.equal(await dialog.locator('[data-step="ready"]').getAttribute('data-state'), 'done');
  console.log(`  ✓ imported 1 study / 1 series / 143 instances, 1 file skipped (progress seen: ${[...seen].join(', ')})`);

  // ── The study list shows the imported study and series ─────────────────────
  const rows = await (await page.request.get(`${BASE}api/v1/patients/${patient.id}/imaging`)).json();
  assert.equal(rows.length, 1);
  const study = rows[0].study_instance_uid;
  const series = rows[0].series[0].series_instance_uid;
  assert.equal(rows[0].series.length, 1);
  assert.equal(rows[0].series[0].instance_count, 143);
  await dialog.getByTestId('import-open-ohif').click();
  const row = page.locator(`[data-study-uid="${study}"]`);
  await row.waitFor();
  assert.ok((await row.innerText()).includes('1 series · 143 images'), await row.innerText());
  assert.ok((await page.getByTestId('study-metadata').innerText()).includes(`Series UID: ${series}`));
  console.log('  ✓ study and series listed for the patient');

  // ── OHIF over the patient's DICOMweb root ──────────────────────────────────
  const iframe = page.locator('iframe[title="OHIF DICOM Viewer"]');
  await iframe.waitFor();
  const src = new URL(await iframe.getAttribute('src'), BASE);
  const root = `/api/v1/patients/${patient.id}/dicomweb`;
  assert.equal(src.searchParams.get('studyInstanceUIDs'), study);
  assert.equal(src.searchParams.get('SeriesInstanceUIDs'), series);
  const frame = await until('OHIF frame', async () => page.frames().find((f) => f.url().includes('/ohif/viewer')));
  const vpState = await until('CT stack loaded', () => frame.evaluate(() => {
    const vp = window.cornerstone?.getEnabledElements?.()[0]?.viewport;
    const ids = vp?.getImageIds?.() ?? [];
    return ids.length ? { type: vp.type, count: ids.length } : null;
  }), 240);
  assert.deepEqual(vpState, { type: 'stack', count: 143 });
  const found = (pred) => responses.find(({ u }) => pred(u));
  await until('DICOMweb requests', async () => found((u) => u.pathname === `${root}/studies/${study}/series/${series}/metadata`));
  assert.equal(found((u) => u.pathname === `${root}/ohif-config`)?.r.status(), 200);
  assert.equal(found((u) => u.pathname === `${root}/studies`)?.r.status(), 200);
  assert.equal(found((u) => u.pathname === `${root}/studies/${study}/series`)?.r.status(), 200);
  const metadata = await found((u) => u.pathname === `${root}/studies/${study}/series/${series}/metadata`).r.json();
  assert.equal(metadata.length, 143);
  assert.ok(responses.every(({ u }) => !u.pathname.startsWith('/api/v1/dicomweb') && u.pathname.startsWith(root)), 'only the patient root is used');

  // A middle slice: decoded 512×512 and visibly not black.
  await frame.evaluate(() => window.cornerstone.getEnabledElements()[0].viewport.setImageIdIndex(71));
  const slice = await until('slice 72 rendered', () => frame.evaluate(`(() => {
    const vp = window.cornerstone.getEnabledElements()[0].viewport;
    const img = window.cornerstone.cache.getImage(vp.getCurrentImageId());
    if (!img || vp.getCurrentImageIdIndex() !== 71) return null;
    const s = (${CANVAS_STATS})(vp);
    return s.bright > 0.1 && s.levels > 60 ? { rows: img.rows, cols: img.columns, ...s } : null;
  })()`), 120);
  assert.equal(slice.rows, 512);
  assert.equal(slice.cols, 512);
  const frames = responses.filter(({ u }) => u.pathname.startsWith(`${root}/studies/${study}/series/${series}/instances/`) && u.pathname.endsWith('/frames/1'));
  const sops = new Set(frames.filter(({ r }) => r.status() === 200).map(({ u }) => u.pathname.split('/instances/')[1].split('/')[0]));
  assert.ok(sops.size >= 2, `frames retrieved for ${sops.size} instance(s)`);
  console.log(`  ✓ OHIF stack: 143 instances, slice 72 rendered (bright ${slice.bright.toFixed(2)}, ${slice.levels} levels), frames of ${sops.size} instances fetched`);

  // ── MPR and 3D from OHIF's own layout menu ─────────────────────────────────
  const ohif = page.frameLocator('iframe[title="OHIF DICOM Viewer"]');
  const confirm = ohif.getByRole('button', { name: 'Confirm and Hide' });
  if (await confirm.count()) await confirm.click();
  const layout = async (name) => {
    await ohif.locator('[data-cy="Layout"]').click();
    await ohif.getByText(name, { exact: true }).first().click();
  };
  const viewports = (wanted) => until(`${wanted.join('+')} rendered`, () => frame.evaluate(`(() => {
    const stats = window.cornerstone.getEnabledElements().map((e) => (${CANVAS_STATS})(e.viewport));
    const types = stats.map((s) => s.type).sort();
    const ok = ${JSON.stringify(wanted)}.every((t) => types.filter((x) => x === t).length >= ${JSON.stringify(wanted)}.filter((x) => x === t).length)
      && stats.every((s) => s.bright > 0.05 && s.levels > 60);
    return ok ? stats : null;
  })()`), 240);

  await layout('MPR');
  const mpr = await viewports(['orthographic', 'orthographic', 'orthographic']);
  console.log(`  ✓ MPR: ${mpr.map((s) => `${s.type} ${s.levels} levels`).join(', ')}`);
  await page.screenshot({ path: path.join(tmp, 'mpr.png') });

  await layout('3D four up');
  const three = await viewports(['volume3d', 'orthographic', 'orthographic', 'orthographic']);
  const volume = three.find((s) => s.type === 'volume3d');
  console.log(`  ✓ 3D four up: volume3d rendered (bright ${volume.bright.toFixed(2)}, ${volume.levels} levels)`);

  // ── Folder and Files, through the same dialog (a small MR study) ───────────
  const mrDir = path.join(FIXTURE, '..', '..', 'Dummy');
  if (fs.existsSync(mrDir)) {
    const folder = path.join(tmp, 'MR-study');
    fs.mkdirSync(path.join(folder, 'series', 'nested'), { recursive: true });
    const mrFiles = fs.readdirSync(mrDir).filter((f) => f.endsWith('.dcm'));
    mrFiles.forEach((f, i) => fs.copyFileSync(path.join(mrDir, f), path.join(folder, 'series', i % 2 ? 'nested' : '.', f.replace(/\.dcm$/, ''))));
    fs.writeFileSync(path.join(folder, 'notes.txt'), 'not DICOM');
    const other = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    const p2 = await other.newPage();
    const email2 = `folder-import-${Date.now()}@example.com`;
    await p2.request.post(`${BASE}api/v1/auth/register`, { params: { email: email2, password: 'Folder-Import-1' } });
    await p2.request.post(`${BASE}api/v1/auth/login`, { form: { username: email2, password: 'Folder-Import-1' } });
    await p2.request.post(`${BASE}api/v1/patients`, { data: { name: 'Folder Import Patient', patient_code: 'HML-FOLDER' } });
    await p2.goto(`${BASE}imaging`);
    await p2.getByTestId('imaging-patient').filter({ hasText: 'HML-FOLDER' }).waitFor();
    await p2.getByRole('tab', { name: 'OHIF Viewer' }).click();
    await p2.getByTestId('open-dicom-import').click();
    const d2 = p2.getByTestId('modal');
    await d2.getByTestId('import-input-folder').setInputFiles(folder);
    assert.ok((await d2.getByTestId('import-selection').innerText()).includes('Folder'));
    await d2.getByTestId('import-start').click();
    await d2.getByTestId('import-summary').waitFor({ timeout: 180000 });
    const folderSummary = await d2.getByTestId('import-summary').innerText();
    assert.ok(new RegExp(`1 study[\\s\\S]*2 series[\\s\\S]*${mrFiles.length} instances`).test(folderSummary), folderSummary);
    assert.ok(/1 non-DICOM file/.test(folderSummary), folderSummary);   // notes.txt, skipped in the browser
    console.log(`  ✓ Folder (nested, no extensions): 1 study / 2 series / ${mrFiles.length} instances`);

    await d2.getByRole('button', { name: 'Import more' }).click();
    const again = mrFiles.slice(0, 3).map((f) => path.join(mrDir, f));
    await d2.getByTestId('import-input-files').setInputFiles(again);
    assert.ok((await d2.getByTestId('import-selection').innerText()).includes('3 files'));
    await d2.getByTestId('import-start').click();
    await d2.getByTestId('import-summary').waitFor({ timeout: 120000 });
    const filesSummary = await d2.getByTestId('import-summary').innerText();
    assert.ok(/0 instances/.test(filesSummary) && /3 instances already present/.test(filesSummary), filesSummary);
    const mrRows = await (await p2.request.get(`${BASE}api/v1/patients/${(await (await p2.request.get(`${BASE}api/v1/patients`)).json())[0].id}/imaging`)).json();
    assert.equal(mrRows.reduce((n, s) => n + s.instance_count, 0), mrFiles.length);
    console.log('  ✓ Files: re-importing 3 stored instances adds no duplicates');
    await other.close();
  }
  console.log('CT ZIP IMPORT E2E PASS');
} finally {
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}
