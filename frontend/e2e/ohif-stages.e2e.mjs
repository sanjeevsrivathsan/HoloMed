// OHIF stage-by-stage regression: launch → config → QIDO → series → metadata → frame → decode → pixels.
// Runs twice: in a clean browser, and in a browser whose cache still holds an OLD app-config.js under the
// unversioned URL (the real-world failure: OHIF started without the `holomed` data source and stayed black).
// On failure it names the first stage that did not happen.
//
//   HOLOMED_E2E_BROWSER=<path to chrome/brave/edge.exe> npm run test:e2e:ohif-stages
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
const SERIES = '1.2.276.0.7230010.3.1.3.8323329.6904.1517875201.850817';
const SOP = '1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819';
// app-config.js as it was before the patient-scoped `holomed` data source existed.
const OLD_APP_CONFIG = 'window.config={routerBasename:"/ohif/",extensions:[],modes:[],showStudyList:true,defaultDataSourceName:"dicomweb",'
  + 'dataSources:[{namespace:"@ohif/extension-default.dataSourcesModule.dicomweb",sourceName:"dicomweb",configuration:{name:"local",'
  + 'qidoRoot:"/api/v1/dicomweb",wadoRoot:"/api/v1/dicomweb",wadoUriRoot:"/api/v1/dicomweb",imageRendering:"wadors",thumbnailRendering:"wadors"}}]};';

if (!fs.existsSync(FIXTURE)) {
  console.log(`SKIPPED: fixture not present at ${FIXTURE}`);
  process.exit(0);
}

async function run(label, staleCache) {
  const browser = await chromium.launch(process.env.HOLOMED_E2E_BROWSER
    ? { executablePath: process.env.HOLOMED_E2E_BROWSER, headless: true }
    : { channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    if (staleCache) {
      await context.route((url) => url.pathname === '/ohif/app-config.js' && !url.search,
        (route) => route.fulfill({ status: 200, contentType: 'text/javascript', body: OLD_APP_CONFIG }));
    }
    const page = await context.newPage();
    const seen = [];
    page.on('response', (r) => { const u = new URL(r.url()); if (u.pathname.startsWith('/ohif/') || u.pathname.includes('/dicomweb/')) seen.push({ u, r }); });
    const email = `ohif-stages-${label}-${Date.now()}@example.com`;
    await page.request.post(`${BASE}api/v1/auth/register`, { params: { email, password: 'Ohif-Stages-123' } });
    await page.request.post(`${BASE}api/v1/auth/login`, { form: { username: email, password: 'Ohif-Stages-123' } });
    const patient = await (await page.request.post(`${BASE}api/v1/patients`, { data: { name: 'Stage Patient', patient_code: 'HML-STAGE' } })).json();
    await page.request.post(`${BASE}api/v1/patients/${patient.id}/imaging`,
      { multipart: { file: { name: 'cxr.dcm', mimeType: 'application/dicom', buffer: fs.readFileSync(FIXTURE) } } });

    await page.goto(`${BASE}imaging`);
    await page.getByRole('tab', { name: 'OHIF Viewer' }).click({ timeout: 30000 });
    await page.locator(`[data-study-uid="${STUDY}"]`).click();
    await page.locator('iframe[title="OHIF DICOM Viewer"]').waitFor();
    const root = `/api/v1/patients/${patient.id}/dicomweb`;
    const find = (pred) => seen.find(({ u }) => pred(u));
    const stages = [
      ['launch URL names the study, series and patient config', async () => {
        const src = new URL(await page.locator('iframe[title="OHIF DICOM Viewer"]').getAttribute('src'), BASE);
        return src.pathname === '/ohif/viewer/holomed' && src.searchParams.get('studyInstanceUIDs') === STUDY
          && src.searchParams.get('SeriesInstanceUIDs') === SERIES && src.searchParams.get('url') === `${root}/ohif-config`;
      }],
      ['current (versioned) app-config.js loaded', async () => !!find((u) => u.pathname === '/ohif/app-config.js' && u.searchParams.get('v'))],
      ['OHIF data source initialised (ohif-config fetched)', async () => find((u) => u.pathname === `${root}/ohif-config`)?.r.status() === 200],
      ['QIDO study query', async () => find((u) => u.pathname === `${root}/studies` && u.searchParams.get('StudyInstanceUID') === STUDY)?.r.status() === 200],
      ['QIDO series query', async () => find((u) => u.pathname === `${root}/studies/${STUDY}/series`)?.r.status() === 200],
      ['WADO series metadata', async () => find((u) => u.pathname === `${root}/studies/${STUDY}/series/${SERIES}/metadata`)?.r.status() === 200],
      ['WADO frame 200 (image/jpeg multipart)', async () => {
        const f = find((u) => u.pathname === `${root}/studies/${STUDY}/series/${SERIES}/instances/${SOP}/frames/1`);
        return f?.r.status() === 200 && /^multipart\/related; type="image\/jpeg"/.test(f.r.headers()['content-type']);
      }],
      ['Cornerstone decoded the 1024×1024 CR', async () => {
        const frame = page.frames().find((f) => f.url().includes('/ohif/viewer'));
        return frame?.evaluate(() => {
          const vp = window.cornerstone?.getEnabledElements?.()[0]?.viewport; const id = vp?.getCurrentImageId?.();
          const img = id && window.cornerstone.cache.getImage(id);
          return !!img && img.rows === 1024 && img.columns === 1024;
        });
      }],
      ['viewport shows the image (not black)', async () => {
        const frame = page.frames().find((f) => f.url().includes('/ohif/viewer'));
        return frame?.evaluate(() => {
          const c = window.cornerstone.getEnabledElements()[0].viewport.canvas;
          const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          let bright = 0; const levels = new Set();
          for (let i = 0; i < d.length; i += 16) { const g = (d[i] + d[i + 1] + d[i + 2]) / 3; levels.add(Math.round(g)); if (g > 40) bright++; }
          return c.width > 100 && c.height > 100 && bright / (d.length / 16) > 0.15 && levels.size > 60;
        });
      }],
    ];
    for (const [name, check] of stages) {
      let ok = false;
      for (let i = 0; i < 60 && !ok; i++) {
        ok = await check().catch(() => false);
        if (!ok) await page.waitForTimeout(500);
      }
      assert.ok(ok, `[${label}] OHIF stopped at stage: ${name}`);
      console.log(`  [${label}] ✓ ${name}`);
    }
  } finally {
    await browser.close();
  }
}

await run('fresh browser', false);
await run('stale cached app-config.js', true);
console.log('OHIF STAGES E2E PASS');
