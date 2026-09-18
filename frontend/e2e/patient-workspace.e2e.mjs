// Acceptance test for the patient-centric workspace: patients, persisted imaging/AI/report data,
// navigation and refresh, patient isolation, and OHIF opening exactly the selected study.
//
// Needs the running stack (backend with the local vision model + Vite) and a Chromium-based browser:
//   HOLOMED_E2E_BROWSER=<path to chrome/brave/edge.exe> npm run test:e2e:patients
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
const SERIES = '1.2.276.0.7230010.3.1.3.8323329.6904.1517875201.850817';
const SOP = '1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819';
const PASSWORD = 'Patient-Workspace-E2E-1';

if (!fs.existsSync(FIXTURE)) {
  console.log(`SKIPPED: fixture not present at ${FIXTURE}`);
  process.exit(0);
}

/** A one-page synthetic lab report PDF (text only; no real patient data). */
function syntheticPdf(lines) {
  const NL = String.fromCharCode(10);
  const text = lines.map((l, i) => `BT /F1 11 Tf 72 ${740 - i * 16} Td (${l.replace(/[()\\]/g, '')}) Tj ET`).join(NL);
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    [`<< /Length ${Buffer.byteLength(text)} >>`, 'stream', text, 'endstream'].join(NL),
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let pdf = '%PDF-1.4' + NL;
  const offsets = objects.map((body, i) => {
    const at = Buffer.byteLength(pdf);
    pdf += [`${i + 1} 0 obj`, body, 'endobj', ''].join(NL);
    return at;
  });
  const xref = Buffer.byteLength(pdf);
  pdf += ['xref', `0 ${objects.length + 1}`, '0000000000 65535 f ',
    ...offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n `), 'trailer',
    `<< /Size ${objects.length + 1} /Root 1 0 R >>`, 'startxref', String(xref), '%%EOF', ''].join(NL);
  return Buffer.from(pdf, 'latin1');
}

let step = 0;
const log = (name) => console.log(`${String(++step).padStart(2)}. ${name}`);
const SHOTS = process.env.HOLOMED_E2E_SHOTS;   // optional screenshot directory
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const shot = async (p, name) => { if (SHOTS) await p.screenshot({ path: path.join(SHOTS, `${name}.png`) }); };

const browser = await chromium.launch(process.env.HOLOMED_E2E_BROWSER
  ? { executablePath: process.env.HOLOMED_E2E_BROWSER, headless: true }
  : { channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const errors = [];
const dicomweb = [];
const failed = [];
const watch = (p) => {
  p.on('pageerror', (e) => errors.push(e.message));
  p.on('console', (m) => { if (m.type() === 'error' && !/401 \(Unauthorized\)|favicon/.test(m.text())) errors.push(m.text()); });
  p.on('response', (r) => {
    const u = new URL(r.url());
    if (u.pathname.includes('/dicomweb/')) dicomweb.push({ path: u.pathname, status: r.status() });
    if (r.status() >= 400 && !u.pathname.endsWith('/auth/me')) failed.push(`${r.status()} ${u.pathname}`);
  });
};
watch(page);

const activePatient = () => page.getByTestId('active-patient').innerText();
const studyButton = () => page.locator(`[data-study-uid="${STUDY}"]`);
const nav = (name) => page.getByRole('button', { name, exact: true }).first();

async function createPatient(name, code) {
  await page.getByTestId('patient-selector').click();
  await page.getByRole('button', { name: 'New Patient' }).click();
  await page.getByLabel('Patient Name *').fill(name);
  await page.getByLabel('Patient ID / Patient Code *').fill(code);
  await page.getByRole('button', { name: 'Create Patient' }).click();
  await page.waitForFunction((c) => document.querySelector('[data-testid="active-patient"]')?.textContent?.includes(c), code);
}

async function selectPatient(code) {
  await page.getByTestId('patient-selector').click();
  await page.getByRole('option', { name: new RegExp(code) }).click();
  await page.waitForFunction((c) => document.querySelector('[data-testid="active-patient"]')?.textContent?.includes(c), code);
}

async function viewerFrame(p) {
  for (let i = 0; i < 200; i++) {
    const f = p.frames().find((x) => x.url().includes('/ohif/viewer'));
    if (f) return f;
    await p.waitForTimeout(100);
  }
  throw new Error('OHIF frame not found');
}

async function renderedImage(frame) {
  await frame.waitForFunction(() => {
    const vp = window.cornerstone?.getEnabledElements?.()[0]?.viewport;
    const id = vp?.getCurrentImageId?.();
    return id && window.cornerstone.cache.getImage(id);
  }, null, { timeout: 60000 });
  await frame.waitForTimeout(1500);
  return frame.evaluate(() => {
    const cs = window.cornerstone;
    const vp = cs.getEnabledElements()[0].viewport;
    const id = vp.getCurrentImageId();
    const img = cs.cache.getImage(id);
    const canvas = vp.canvas;
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    const levels = new Set();
    let bright = 0;
    for (let i = 0; i < data.length; i += 16) {
      const g = Math.round((data[i] + data[i + 1] + data[i + 2]) / 3);
      levels.add(g);
      if (g > 40) bright++;
    }
    return { id, rows: img.rows, columns: img.columns, sop: cs.metaData.get('instance', id)?.SOPInstanceUID,
      type: vp.type, levels: levels.size, bright: bright / (data.length / 16) };
  });
}

try {
  // 1. Sign in
  const email = `patient-e2e-${Date.now()}@example.com`;
  assert.equal((await page.request.post(`${BASE}api/v1/auth/register`, { params: { email, password: PASSWORD } })).status(), 201);
  await page.goto(BASE);
  await page.getByPlaceholder('you@example.com').fill(email);
  await page.getByPlaceholder('••••••••').first().fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByTestId('active-patient').waitFor({ timeout: 30000 });
  log('signed in');

  // 2-3. Create and select Patient A
  await createPatient('Demo Chest X-Ray Patient', 'HML-TEST-001');
  assert.match(await activePatient(), /HML-TEST-001\s+Demo Chest X-Ray Patient/);
  log('created and selected Patient A (HML-TEST-001)');
  const patients = await (await page.request.get(`${BASE}api/v1/patients`)).json();
  const patientA = patients.find((p) => p.patient_code === 'HML-TEST-001');
  assert.ok(patientA && patientA.id.length === 36);

  // 4-8. Imaging → AI Screening on the SIIM CR
  await page.goto(`${BASE}imaging`);
  await page.getByTestId('imaging-patient').filter({ hasText: 'HML-TEST-001' }).waitFor();
  await page.getByTestId('cxr-file-input').setInputFiles(FIXTURE);
  await page.getByRole('button', { name: 'Run AI Screening' }).click();
  await page.getByTestId('primary-finding').waitFor({ timeout: 120000 });
  assert.equal((await page.getByTestId('primary-finding').innerText()).trim(), 'Mass');
  assert.equal((await page.getByTestId('primary-score').innerText()).trim(), '0.5589');
  assert.equal(await page.getByTestId('findings-list').locator('li').count(), 18);
  await page.getByTestId('saved-analysis').filter({ hasText: 'HML-TEST-001' }).waitFor();
  log('AI screening: Mass 0.5589, 18 findings, saved to HML-TEST-001');
  await shot(page, '01_ai_screening');

  // 6/9-11. The screened DICOM is the patient's study, and OHIF opens exactly it
  await page.getByTestId('open-in-ohif').click();
  await studyButton().waitFor({ timeout: 15000 });
  const iframe = page.locator('iframe[title="OHIF DICOM Viewer"]');
  const src = new URL(await iframe.getAttribute('src'), BASE);
  assert.equal(src.pathname, '/ohif/viewer/holomed');
  assert.equal(src.searchParams.get('studyInstanceUIDs'), STUDY);
  assert.equal(src.searchParams.get('SeriesInstanceUIDs'), SERIES);
  assert.equal(src.searchParams.get('url'), `/api/v1/patients/${patientA.id}/dicomweb/ohif-config`);
  const embedded = await renderedImage(await viewerFrame(page));
  assert.deepEqual([embedded.sop, embedded.rows, embedded.columns, embedded.type], [SOP, 1024, 1024, 'stack']);
  assert.ok(embedded.id.includes(`/api/v1/patients/${patientA.id}/dicomweb/studies/${STUDY}/series/${SERIES}/instances/${SOP}/frames/1`));
  assert.ok(embedded.levels > 100 && embedded.bright > 0.15, JSON.stringify(embedded));
  assert.equal((await page.getByTestId('viewer-study-uid').innerText()).trim(), STUDY);
  log(`OHIF (embedded) renders the CR: ${embedded.columns}x${embedded.rows}, ${embedded.levels} grey levels`);
  await shot(page, '02_ohif_embedded');

  await page.getByRole('button', { name: 'Hide viewer' }).click();
  await page.getByText('Viewer hidden').waitFor();
  await page.getByRole('button', { name: 'Show viewer' }).click();
  await iframe.waitFor();
  log('hide → show viewer remounts OHIF');

  // 12-13. Open OHIF → same study in a new tab
  const [tab] = await Promise.all([context.waitForEvent('page'), page.getByRole('button', { name: /Open OHIF/ }).click()]);
  watch(tab);
  const tabUrl = new URL(tab.url());
  assert.equal(tabUrl.searchParams.get('studyInstanceUIDs'), STUDY);
  const standalone = await renderedImage(tab.mainFrame());
  assert.equal(standalone.sop, SOP);
  await shot(tab, '03_ohif_standalone');
  await tab.close();
  log('Open OHIF: standalone tab renders the same CR instance');

  // Report for Patient A (reports are patient-owned too)
  const report = await page.request.post(`${BASE}api/v1/reports`, {
    headers: { 'X-HoloMed-Patient': patientA.id },
    multipart: { file: { name: 'Lab_Report.pdf', mimeType: 'application/pdf',
      buffer: syntheticPdf(['SYNTHETIC TEST LAB - NOT REAL PATIENT DATA', 'Report Date: 02-Sep-2026',
        'Hemoglobin 13.9 g/dL 13.0 - 17.0']) }, type: 'Blood Test' },
  });
  assert.equal(report.status(), 200, await report.text());
  const reportOk = true;

  // 14-18. Navigate away and back: data persists
  await nav('Reports').click();
  await nav('Clinical View').click();
  await nav('Settings').click();
  await nav('Imaging Workspace').click();
  await studyButton().waitFor({ timeout: 15000 });
  await page.getByRole('tab', { name: 'AI Screening' }).click();
  await page.getByTestId('primary-score').filter({ hasText: '0.5589' }).waitFor({ timeout: 30000 });
  log('Reports → Clinical View → Settings → Imaging: CR study and saved AI result still there');

  // 19-20. Refresh
  await page.reload();
  await page.getByTestId('active-patient').filter({ hasText: 'HML-TEST-001' }).waitFor({ timeout: 30000 });
  await page.getByTestId('primary-score').filter({ hasText: '0.5589' }).waitFor({ timeout: 30000 });
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await studyButton().waitFor({ timeout: 15000 });
  log('browser refresh: HML-TEST-001 still active, CR and saved AI result restored');

  // 21-23. Patient B sees none of Patient A's data
  await createPatient('Demo Patient Beta', 'HML-TEST-002');
  await page.getByText('No studies').waitFor({ timeout: 15000 });
  assert.equal(await studyButton().count(), 0);
  assert.equal(await page.locator('iframe[title="OHIF DICOM Viewer"]').count(), 0);
  await page.getByRole('tab', { name: 'AI Screening' }).click();
  await page.waitForTimeout(1500);
  assert.equal(await page.getByTestId('primary-finding').count(), 0);
  if (reportOk) {
    await nav('Reports').click();
    await page.waitForTimeout(1500);
    assert.ok(!(await page.locator('body').innerText()).includes('Lab_Report'), 'Patient B must not list Patient A report');
  }
  await nav('Imaging Workspace').click();
  await page.getByTestId('patient-selector').click();
  await shot(page, '04_patient_b_selector');
  await page.keyboard.press('Escape');   // closes the patient dropdown
  log('Patient B (HML-TEST-002): no CR, no AI result' + (reportOk ? ', no report' : ''));

  // 24-25. Back to Patient A
  await selectPatient('HML-TEST-001');
  await page.getByTestId('primary-score').filter({ hasText: '0.5589' }).waitFor({ timeout: 30000 });
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await studyButton().waitFor({ timeout: 15000 });
  await renderedImage(await viewerFrame(page));
  if (reportOk) {
    await nav('Reports').click();
    await page.getByText('Lab_Report').first().waitFor({ timeout: 15000 });
  }
  log('back to Patient A: CR, AI result' + (reportOk ? ' and report' : '') + ' visible again');

  const patientBId = (await (await page.request.get(`${BASE}api/v1/patients`)).json())
    .find((p) => p.patient_code === 'HML-TEST-002').id;
  assert.ok(dicomweb.length > 0 && dicomweb.every((r) => r.status === 200), JSON.stringify(dicomweb.filter((r) => r.status !== 200)));
  assert.ok(dicomweb.every((r) => r.path.startsWith(`/api/v1/patients/${patientA.id}/dicomweb/`)), 'OHIF queried outside Patient A');
  assert.ok(!dicomweb.some((r) => r.path.includes(patientBId)));
  assert.deepEqual(failed, []);
  assert.deepEqual(errors, []);
  log(`${dicomweb.length} DICOMweb requests, all 200 and all on Patient A's root; no failed requests or console errors`);
  console.log('PATIENT WORKSPACE E2E PASS');
} finally {
  await browser.close();
}
