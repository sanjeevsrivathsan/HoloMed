// OHIF regression: the validated SIIM chest X-ray (CR) is requested over DICOMweb and actually rendered
// in the Imaging workspace viewer, including after the viewer was hidden.
//
// Needs the running stack (backend + Vite) and a Chromium-based browser:
//   HOLOMED_E2E_BROWSER=<path to chrome/brave/edge.exe> npm run test:e2e:ohif
// Optional: HOLOMED_E2E_BASE (default http://localhost:5173/), HOLOMED_REAL_CXR_DICOM (fixture path).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.HOLOMED_E2E_BASE ?? 'http://localhost:5173/';
const FIXTURE = process.env.HOLOMED_REAL_CXR_DICOM ?? path.resolve(here, '../../backend/tests/artifacts/real_cxr/source/'
  + '1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm');
const STUDY = '1.2.276.0.7230010.3.1.2.8323329.6904.1517875201.850818';
const SOP = '1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819';

if (!fs.existsSync(FIXTURE)) {
  // The SIIM DICOM is not committed (licensing); see backend/tests/artifacts/real_cxr/ATTRIBUTION.md.
  console.log(`SKIPPED: fixture not present at ${FIXTURE}`);
  process.exit(0);
}

const step = (name) => console.log(`- ${name}`);
const browser = await chromium.launch(process.env.HOLOMED_E2E_BROWSER
  ? { executablePath: process.env.HOLOMED_E2E_BROWSER, headless: true }
  : { channel: 'chrome', headless: true });
try {
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
  const dicomweb = [];
  const errors = [];
  page.on('response', (r) => { if (r.url().includes('/api/v1/dicomweb/')) dicomweb.push(r); });
  page.on('pageerror', (e) => errors.push(e.message));

  step('sign in as a fresh user and upload the fixture unchanged');
  const email = `ohif-cr-e2e-${Date.now()}@example.com`;
  await page.request.post(`${BASE}api/v1/auth/register`, { params: { email, password: 'Ohif-Cr-E2E-12345' } });
  assert.equal((await page.request.post(`${BASE}api/v1/auth/login`, { form: { username: email, password: 'Ohif-Cr-E2E-12345' } })).status(), 200);
  const upload = await page.request.post(`${BASE}api/v1/medical-data/dicom/upload`,
    { multipart: { file: { name: 'cxr.dcm', mimeType: 'application/dicom', buffer: fs.readFileSync(FIXTURE) } } });
  assert.equal(upload.status(), 200);
  assert.equal((await upload.json()).study_instance_uid, STUDY);

  step('Imaging → OHIF Viewer → select CR');
  await page.goto(BASE);
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click({ timeout: 30000 });
  const iframe = page.locator('iframe[title="OHIF DICOM Viewer"]');
  await page.locator('button', { hasText: 'CR ·' }).first().click();
  await iframe.waitFor({ timeout: 15000 });
  assert.equal(await iframe.getAttribute('src'), `/ohif/viewer?StudyInstanceUIDs=${encodeURIComponent(STUDY)}`);

  step('a hidden viewer is mounted again when the study is selected');
  await page.getByRole('button', { name: 'Hide viewer' }).click();
  await page.getByText('Viewer hidden').waitFor({ timeout: 5000 });
  assert.equal(await iframe.count(), 0);
  dicomweb.length = 0;
  await page.locator('button', { hasText: 'CR ·' }).first().click();
  await iframe.waitFor({ timeout: 15000 });

  step('Cornerstone receives the target instance');
  let viewer = null;
  for (let i = 0; i < 150 && !viewer; i++) {
    viewer = page.frames().find((f) => f.url().includes('/ohif/viewer')) ?? null;
    if (!viewer) await page.waitForTimeout(100);
  }
  assert.ok(viewer, 'OHIF frame not found');
  await viewer.waitForFunction(() => {
    const vp = window.cornerstone?.getEnabledElements?.()[0]?.viewport;
    const id = vp?.getCurrentImageId?.();
    return id && window.cornerstone.cache.getImage(id);
  }, null, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const image = await viewer.evaluate(() => {
    const cs = window.cornerstone;
    const vp = cs.getEnabledElements()[0].viewport;
    const id = vp.getCurrentImageId();
    const img = cs.cache.getImage(id);
    return { id, type: vp.type, rows: img.rows, columns: img.columns, sop: cs.metaData.get('instance', id)?.SOPInstanceUID };
  });
  assert.ok(image.id.startsWith('wadors:') && image.id.includes(`/instances/${SOP}/frames/1`), image.id);
  assert.deepEqual([image.sop, image.rows, image.columns, image.type], [SOP, 1024, 1024, 'stack']);

  step('the target frame was requested over DICOMweb and every request succeeded');
  const frame = dicomweb.find((r) => r.url().includes(`/instances/${SOP}/frames/1`));
  assert.ok(frame, 'frames request for the target SOP was not made');
  assert.equal(frame.status(), 200);
  assert.match(frame.headers()['content-type'], /^multipart\/related; type="image\/jpeg"/);
  assert.deepEqual(dicomweb.filter((r) => r.status() !== 200).map((r) => `${r.status()} ${r.url()}`), []);

  step('the viewport canvas shows an image, not a black frame');
  const pixels = await viewer.evaluate(() => {
    const canvas = window.cornerstone.getEnabledElements()[0].viewport.canvas;
    const { width, height } = canvas;
    const data = canvas.getContext('2d').getImageData(0, 0, width, height).data;
    const levels = new Set();
    let bright = 0;
    for (let i = 0; i < data.length; i += 4) {
      const grey = Math.round((data[i] + data[i + 1] + data[i + 2]) / 3);
      levels.add(grey);
      if (grey > 40) bright++;
    }
    return { width, height, levels: levels.size, bright: bright / (width * height) };
  });
  assert.ok(pixels.levels > 100 && pixels.bright > 0.15, `rendered canvas looks blank: ${JSON.stringify(pixels)}`);
  assert.deepEqual(errors, []);
  console.log(`PASS: CR ${image.rows}x${image.columns} rendered (${pixels.levels} grey levels, ${(pixels.bright * 100).toFixed(1)}% non-black)`);
} finally {
  await browser.close();
}
