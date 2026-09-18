// UI layout acceptance test: Create Patient modal, patient dropdown, scrolling, the resizable
// Imaging workspace around the real OHIF viewer, and the HoloMed favicon. Measures real geometry
// and scroll reachability in the browser (not CSS class names).
//
//   HOLOMED_E2E_BROWSER=<path to chrome/brave/edge.exe> npm run test:e2e:layout
// Optional: HOLOMED_E2E_BASE, HOLOMED_REAL_CXR_DICOM, HOLOMED_E2E_SHOTS (screenshot directory).
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
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
const VIEWPORTS = [[1920, 1080], [1600, 900], [1440, 900], [1280, 800]];
const PAGES = ['imaging', 'reports', 'clinical', 'overview', 'search', 'timeline', 'templates', 'privacy', 'storage', 'settings'];

if (!fs.existsSync(FIXTURE)) {
  console.log(`SKIPPED: fixture not present at ${FIXTURE}`);
  process.exit(0);
}

// ── Minimal synthetic DICOM writer (Explicit VR Little Endian, 8-bit MONOCHROME2) ──
const uid = () => `2.25.${BigInt(`0x${crypto.randomBytes(15).toString('hex')}`).toString()}`;
function element(group, elem, vr, value) {
  let data = Buffer.isBuffer(value) ? value : Buffer.from(String(value), 'latin1');
  if (data.length % 2) data = Buffer.concat([data, Buffer.from([vr === 'UI' || vr === 'OB' ? 0 : 0x20])]);
  const long = ['OB', 'OW', 'OF', 'SQ', 'UT', 'UN'].includes(vr);
  const head = Buffer.alloc(long ? 12 : 8);
  head.writeUInt16LE(group, 0); head.writeUInt16LE(elem, 2); head.write(vr, 4, 'latin1');
  if (long) head.writeUInt32LE(data.length, 8); else head.writeUInt16LE(data.length, 6);
  return Buffer.concat([head, data]);
}
const us = (n) => { const b = Buffer.alloc(2); b.writeUInt16LE(n); return b; };
function syntheticDicom(description) {
  const sopClass = '1.2.840.10008.5.1.4.1.1.7';
  const sop = uid();
  const rows = 64;
  const meta = Buffer.concat([
    element(0x0002, 0x0001, 'OB', Buffer.from([0, 1])), element(0x0002, 0x0002, 'UI', sopClass),
    element(0x0002, 0x0003, 'UI', sop), element(0x0002, 0x0010, 'UI', '1.2.840.10008.1.2.1'),
    element(0x0002, 0x0012, 'UI', '2.25.1'),
  ]);
  const groupLength = element(0x0002, 0x0000, 'UL', (() => { const b = Buffer.alloc(4); b.writeUInt32LE(meta.length); return b; })());
  const pixels = Buffer.alloc(rows * rows);
  for (let i = 0; i < pixels.length; i++) pixels[i] = (i * 7) % 256;
  const dataset = Buffer.concat([
    element(0x0008, 0x0016, 'UI', sopClass), element(0x0008, 0x0018, 'UI', sop), element(0x0008, 0x0020, 'DA', '20260918'),
    element(0x0008, 0x0060, 'CS', 'OT'), element(0x0008, 0x1030, 'LO', description), element(0x0010, 0x0010, 'PN', 'Synthetic^Layout'),
    element(0x0010, 0x0020, 'LO', 'SYN-LAYOUT'), element(0x0020, 0x000d, 'UI', uid()), element(0x0020, 0x000e, 'UI', uid()),
    element(0x0020, 0x0011, 'IS', '1'), element(0x0020, 0x0013, 'IS', '1'), element(0x0028, 0x0002, 'US', us(1)),
    element(0x0028, 0x0004, 'CS', 'MONOCHROME2'), element(0x0028, 0x0010, 'US', us(rows)), element(0x0028, 0x0011, 'US', us(rows)),
    element(0x0028, 0x0100, 'US', us(8)), element(0x0028, 0x0101, 'US', us(8)), element(0x0028, 0x0102, 'US', us(7)),
    element(0x0028, 0x0103, 'US', us(0)), element(0x7fe0, 0x0010, 'OB', pixels),
  ]);
  return Buffer.concat([Buffer.alloc(128), Buffer.from('DICM'), groupLength, meta, dataset]);
}

let n = 0;
const ok = (msg) => console.log(`${String(++n).padStart(2)}. ${msg}`);
const SHOTS = process.env.HOLOMED_E2E_SHOTS;
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch(process.env.HOLOMED_E2E_BROWSER
  ? { executablePath: process.env.HOLOMED_E2E_BROWSER, headless: true }
  : { channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error' && !/401 \(Unauthorized\)|favicon/.test(m.text())) errors.push(m.text()); });
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) }); };

const inViewport = (box, vp) => box && box.y >= -0.5 && box.x >= -0.5 && box.y + box.height <= vp.height + 0.5 && box.x + box.width <= vp.width + 0.5;
const api = (p, opts) => page.request.fetch(`${BASE}${p}`, opts);

async function openSelector() {
  if (!(await page.getByTestId('patient-panel').count())) await page.getByTestId('patient-selector').click();
  await page.getByTestId('patient-panel').waitFor();
}

/** Reachability: scroll `container` to its end and check its last item lies within it (and within the viewport). */
async function assertReachable(container, itemSelector, name) {
  const r = await container.evaluate((el, sel) => {
    const items = el.querySelectorAll(sel);
    const last = items[items.length - 1];
    const before = { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight };
    el.scrollTop = el.scrollHeight;
    const c = el.getBoundingClientRect();
    const l = last?.getBoundingClientRect();
    return { ...before, count: items.length, scrolledTo: el.scrollTop,
      lastVisible: !!l && l.bottom <= c.bottom + 1 && l.top >= c.top - 1 && l.bottom <= window.innerHeight + 1 };
  }, itemSelector);
  assert.ok(r.count > 0 && r.lastVisible, `${name}: last item not reachable ${JSON.stringify(r)}`);
  return r;
}

try {
  // ── setup: account, patients, imaging ────────────────────────────────────
  const email = `layout-e2e-${Date.now()}@example.com`;
  await api('api/v1/auth/register', { method: 'POST', params: { email, password: 'Layout-E2E-12345' } });
  assert.equal((await api('api/v1/auth/login', { method: 'POST', form: { username: email, password: 'Layout-E2E-12345' } })).status(), 200);
  const imagingPatient = await (await api('api/v1/patients', { method: 'POST', data: { name: 'Imaging Layout Patient', patient_code: 'HML-TEST-010' } })).json();
  const upload = (buffer, name) => api(`api/v1/patients/${imagingPatient.id}/imaging`, { method: 'POST',
    multipart: { file: { name, mimeType: 'application/dicom', buffer } } });
  assert.equal((await upload(fs.readFileSync(FIXTURE), 'cxr.dcm')).status(), 200);
  for (let i = 1; i <= 10; i++) assert.equal((await upload(syntheticDicom(`Synthetic layout study ${i}`), `syn${i}.dcm`)).status(), 200);
  assert.equal((await api(`api/v1/patients/${imagingPatient.id}/imaging/${STUDY}/screen`, { method: 'POST' })).status(), 200);
  ok('setup: patient HML-TEST-010 with the SIIM CR + 10 synthetic studies and a saved AI result');

  // ── title + favicon ───────────────────────────────────────────────────────
  await page.goto(BASE);
  await page.getByTestId('patient-selector').waitFor({ timeout: 30000 });
  assert.equal(await page.title(), 'HoloMed AI');
  const icons = await page.evaluate(() => [...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]')].map((l) => l.getAttribute('href')));
  assert.ok(icons.includes('/favicon.svg') && !icons.some((h) => /google|gstatic|vite\.svg|bolt/i.test(h)), icons.join(','));
  for (const href of icons) {
    const r = await api(href.replace(/^\//, ''));
    assert.equal(r.status(), 200, href);
    assert.match(r.headers()['content-type'], href.endsWith('manifest') ? /json|manifest/ : /^image\//, href);
  }
  ok(`title "HoloMed AI"; ${icons.length} HoloMed icon links resolve (${icons.join(', ')})`);

  // ── Create Patient modal @1600×900 ──────────────────────────────────────
  await openSelector();
  await page.getByRole('button', { name: 'New Patient' }).click();
  const dialog = page.getByRole('dialog', { name: 'Create Patient' });
  await dialog.waitFor();
  assert.equal(await page.getByTestId('patient-panel').count(), 0, 'dropdown must close');
  const vp = page.viewportSize();
  assert.ok(inViewport(await dialog.boundingBox(), vp), 'modal clipped');
  assert.equal(await page.evaluate(() => document.body.style.overflow), 'hidden');
  assert.equal(await dialog.getByLabel('Date of Birth').count(), 0, 'Date of Birth must be gone');
  for (let i = 0; i < 14; i++) {
    await page.keyboard.press(i % 3 === 2 ? 'Shift+Tab' : 'Tab');
    assert.ok(await dialog.evaluate((d) => d.contains(document.activeElement)), 'focus left the modal');
  }
  await dialog.getByLabel(/^Patient Name/).fill('Test Patient Alpha');
  await dialog.getByLabel(/^Patient ID \/ Patient Code/).fill('HML-TEST-002');
  await dialog.getByLabel('Age', { exact: true }).fill('131');
  await dialog.getByLabel('Phone Number', { exact: true }).fill('abc');
  await page.getByRole('button', { name: 'Create Patient' }).click();
  await page.getByText('Enter whole years from 0 to 130.').waitFor();
  await page.getByText('Enter a valid phone number, e.g. +91 98765 43210.').waitFor();
  assert.ok(await dialog.isVisible());
  await dialog.getByLabel('Age', { exact: true }).fill('25');
  await dialog.getByLabel('Sex', { exact: true }).selectOption({ label: 'Not specified' });
  await dialog.getByLabel('Phone Number', { exact: true }).fill('+91 98765 43210');
  await shot('01_create_patient_1600');
  await page.getByRole('button', { name: 'Create Patient' }).click();
  await dialog.waitFor({ state: 'detached' });
  await page.getByTestId('active-patient').filter({ hasText: 'HML-TEST-002' }).waitFor();
  assert.match(await page.getByTestId('active-patient').innerText(), /HML-TEST-002\s+Test Patient Alpha/);
  assert.equal(await page.evaluate(() => document.body.style.overflow), '', 'page scroll lock not released');
  const created = (await (await api('api/v1/patients')).json()).find((p) => p.patient_code === 'HML-TEST-002');
  assert.deepEqual([created.age, created.sex, created.phone], [25, null, '+91 98765 43210']);
  await openSelector();
  const details = await page.getByTestId('active-patient-details').innerText();
  assert.ok(/25 years/.test(details) && /Not specified/.test(details) && /\+91 98765 43210/.test(details), details);
  await page.keyboard.press('Escape');
  ok('Create Patient @1600×900: fully visible, focus trapped, validation shown, HML-TEST-002 created (age 25, +91 98765 43210) and active');

  // Cancel + Escape close; small viewport → body scrolls, footer stays reachable
  await page.setViewportSize({ width: 1024, height: 480 });
  await openSelector();
  await page.getByRole('button', { name: 'New Patient' }).click();
  await dialog.waitFor();
  const small = page.viewportSize();
  const scrollAtOpen = await page.evaluate(() => window.scrollY);
  const body = page.getByTestId('modal-body');
  const geometry = await body.evaluate((b) => ({ scrollHeight: b.scrollHeight, clientHeight: b.clientHeight }));
  assert.ok(geometry.scrollHeight > geometry.clientHeight, `modal body should need scrolling at 1024×480: ${JSON.stringify(geometry)}`);
  assert.ok(inViewport(await dialog.boundingBox(), small), 'modal clipped at 1024×480');
  assert.ok(inViewport(await page.getByRole('button', { name: 'Create Patient' }).boundingBox(), small), 'footer not visible');
  await body.evaluate((b) => { b.scrollTop = b.scrollHeight; });
  const phone = await dialog.getByLabel('Phone Number', { exact: true }).boundingBox();
  const bodyBox = await body.boundingBox();
  assert.ok(phone.y + phone.height <= bodyBox.y + bodyBox.height + 1, 'last field not reachable in modal body');
  await page.mouse.wheel(0, 600);   // wheel over the backdrop must not scroll the page either
  assert.equal(await page.evaluate(() => window.scrollY), scrollAtOpen, 'page scrolled behind the modal');
  await shot('02_create_patient_1024x480');
  await page.getByRole('button', { name: 'Cancel' }).click();
  await dialog.waitFor({ state: 'detached' });
  await openSelector();
  await page.getByRole('button', { name: 'New Patient' }).click();
  await dialog.waitFor();
  await page.keyboard.press('Escape');
  await dialog.waitFor({ state: 'detached' });
  ok('Create Patient @1024×480: body scrolls to the last field, footer visible, page does not scroll; Cancel/Escape close');

  // ── Patient dropdown with many patients ──────────────────────────────────
  for (let i = 0; i < 30; i++) {
    await api('api/v1/patients', { method: 'POST', data: { name: `Scroll Patient ${i}`, patient_code: `HML-SCROLL-${String(i).padStart(2, '0')}` } });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  await openSelector();
  const list = page.getByTestId('patient-list');
  const reach = await assertReachable(list, '[role="option"]', 'patient list');
  assert.ok(reach.scrollHeight > reach.clientHeight && reach.count >= 32, JSON.stringify(reach));
  assert.ok(inViewport(await page.getByTestId('patient-panel').boundingBox(), page.viewportSize()), 'dropdown clipped');
  assert.ok(inViewport(await page.getByRole('button', { name: 'New Patient' }).boundingBox(), page.viewportSize()), 'New Patient hidden');
  await page.getByLabel('Search patients').focus();
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('role')), 'option');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByTestId('patient-panel').count(), 0);
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-testid')), 'patient-selector');
  ok(`patient dropdown: ${reach.count} patients, list scrolls to the last one, New Patient always visible, ↓/Escape work`);

  // ── Imaging workspace at each viewport ───────────────────────────────────
  await openSelector();
  await page.getByRole('option', { name: /HML-TEST-010/ }).click();
  await page.goto(`${BASE}imaging`);
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await page.locator(`[data-study-uid="${STUDY}"]`).click();
  const iframe = page.locator('iframe[title="OHIF DICOM Viewer"]');
  await iframe.waitFor();
  const viewerFrame = async () => {
    for (let i = 0; i < 200; i++) {
      const f = page.frames().find((x) => x.url().includes('/ohif/viewer'));
      if (f) return f;
      await page.waitForTimeout(100);
    }
    throw new Error('OHIF frame not found');
  };
  const image = async () => {
    const frame = await viewerFrame();
    await frame.waitForFunction(() => {
      const vp = window.cornerstone?.getEnabledElements?.()[0]?.viewport;
      const id = vp?.getCurrentImageId?.();
      return id && window.cornerstone.cache.getImage(id);
    }, null, { timeout: 60000 });
    await page.waitForTimeout(800);
    return frame.evaluate(() => {
      const cs = window.cornerstone; const vp = cs.getEnabledElements()[0].viewport; const id = vp.getCurrentImageId();
      const img = cs.cache.getImage(id); const c = vp.canvas;
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let bright = 0; const levels = new Set();
      for (let i = 0; i < d.length; i += 16) { const g = Math.round((d[i] + d[i + 1] + d[i + 2]) / 3); levels.add(g); if (g > 40) bright++; }
      return { sop: cs.metaData.get('instance', id)?.SOPInstanceUID, rows: img.rows, cols: img.columns,
        bright: bright / (d.length / 16), levels: levels.size, voi: vp.getProperties().voiRange, zoom: vp.getZoom(), pan: vp.getPan(),
        marker: window.__holomedMarker ?? null };
    });
  };
  const first = await image();
  assert.deepEqual([first.sop, first.rows, first.cols], [SOP, 1024, 1024]);
  const src0 = await iframe.getAttribute('src');
  assert.equal(new URL(src0, BASE).searchParams.get('studyInstanceUIDs'), STUDY);
  assert.equal(new URL(src0, BASE).searchParams.get('SeriesInstanceUIDs'), SERIES);

  const widths = () => page.getByTestId('panels-imaging-viewer').evaluate((el) =>
    [...el.querySelectorAll(':scope > [data-panel]')].map((p) => Math.round(p.getBoundingClientRect().width)));
  for (const [w, h] of VIEWPORTS) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(700);
    const size = page.viewportSize();
    assert.equal(await page.getByTestId('panels-imaging-viewer').getAttribute('data-layout'), 'split', `${w}: not split`);
    const doc = await page.evaluate(() => ({ h: document.scrollingElement.scrollHeight, w: document.scrollingElement.scrollWidth }));
    assert.ok(doc.h <= size.height + 1 && doc.w <= size.width + 1, `${w}×${h}: page overflows ${JSON.stringify(doc)}`);
    const toggle = page.getByRole('button', { name: /clinical panel/i });
    let panels = await widths();
    if (panels.length === 2) {
      // Too narrow for three usable columns: the clinical panel starts collapsed, the viewer keeps ≥560px.
      assert.ok(panels[0] >= 240 && panels[1] >= 560, `${w}×${h}: compact widths ${panels}`);
      assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
      await toggle.click();
      await page.getByTestId('clinical-panel-body').waitFor();
      await page.waitForTimeout(400);
      const opened = await widths();
      assert.ok(opened.length === 3 && opened[1] >= 400 && opened[2] >= 280, `${w}×${h}: opened ${opened}`);
      await assertReachable(page.getByTestId('clinical-panel-body'), ':scope > *', `${w}×${h} clinical panel (opened)`);
      await shot(`03_imaging_${w}x${h}_clinical_open`);
      await toggle.click();
      await page.waitForTimeout(400);
      panels = await widths();
      assert.equal(panels.length, 2, `${w}×${h}: clinical panel did not collapse again`);
    } else {
      assert.ok(panels[0] >= 240 && panels[1] >= 560 && panels[2] >= 280, `${w}×${h}: widths ${panels}`);
      await assertReachable(page.getByTestId('clinical-panel-body'), ':scope > *', `${w}×${h} clinical panel`);
    }
    const frameBox = await iframe.boundingBox();
    assert.ok(frameBox.height >= 380 && inViewport(frameBox, size), `${w}×${h}: viewer ${JSON.stringify(frameBox)}`);
    assert.ok(inViewport(await page.getByTestId('study-metadata').boundingBox(), size), `${w}×${h}: metadata section not visible`);
    await assertReachable(page.getByTestId('study-metadata'), 'p', `${w}×${h} study metadata`);
    await assertReachable(page.getByTestId('study-list'), '[data-study-uid]', `${w}×${h} study list`);
    const img = await image();
    assert.ok(img.sop === SOP && img.bright > 0.1 && img.levels > 60, `${w}×${h}: image ${JSON.stringify(img)}`);
    await shot(`03_imaging_${w}x${h}`);
    ok(`Imaging @${w}×${h}: fits the viewport (no page scroll), panels ${panels.join('/')}px${panels.length === 2 ? ' (clinical panel collapsed; toggle opens it)' : ''}, study list + clinical panel reachable, CR rendered`);
  }
  const studyList = await page.getByTestId('study-list').evaluate((el) => ({ s: el.scrollHeight, c: el.clientHeight }));
  assert.ok(studyList.s > studyList.c, `study list should overflow with 11 studies: ${JSON.stringify(studyList)}`);

  // ── Resizing with the real dividers @1920×1080 (room to move; the viewer keeps ≥560px) ──
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(600);
  // Hiding the clinical panel (at 1280) is an explicit choice that persists; bring it back.
  const clinicalToggle = page.getByRole('button', { name: /clinical panel/i });
  if ((await clinicalToggle.getAttribute('aria-pressed')) === 'false') {
    await clinicalToggle.click();
    await page.getByTestId('clinical-panel-body').waitFor();
    await page.waitForTimeout(400);
  }
  assert.equal((await widths()).length, 3);
  await (await viewerFrame()).evaluate(() => { window.__holomedMarker = 'mounted-before-resize'; });
  const drag = async (index, dx) => {
    const box = await page.getByTestId(`divider-imaging-viewer-${index}`).boundingBox();
    const x = box.x + box.width / 2; const y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx / 2, y, { steps: 6 });
    await page.mouse.move(x + dx, y, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(400);
  };
  const w0 = await widths();
  await drag(0, 120);
  const w1 = await widths();
  assert.ok(w1[0] - w0[0] >= 110 && w1[0] - w0[0] <= 130 && w0[1] - w1[1] >= 110 && Math.abs(w1[2] - w0[2]) <= 2, `${w0} → ${w1}`);
  await drag(1, -100);
  const w2 = await widths();
  assert.ok(w2[2] - w1[2] >= 90 && w2[2] - w1[2] <= 110 && Math.abs(w2[0] - w1[0]) <= 2, `${w1} → ${w2}`);
  await drag(1, 100);
  const w3 = await widths();
  assert.ok(Math.abs(w3[2] - w1[2]) <= 3, `${w2} → ${w3}`);
  const afterResize = await image();
  assert.equal(afterResize.marker, 'mounted-before-resize', 'OHIF was reloaded by the resize');
  assert.ok(afterResize.sop === SOP && afterResize.bright > 0.1, JSON.stringify(afterResize));
  assert.equal(await iframe.getAttribute('src'), src0);
  ok(`dividers: studies ${w0[0]}→${w1[0]}px, clinical ${w1[2]}→${w2[2]}→${w3[2]}px; OHIF stayed mounted on the same study, CR rendered`);

  await drag(0, -2000);
  assert.equal((await widths())[0], 240);
  await drag(0, 2000);
  assert.equal((await widths())[0], 500);
  await drag(1, -2000);
  const squeezed = await widths();
  assert.ok(squeezed[1] >= 400 && squeezed[2] <= 520, String(squeezed));
  const divider = page.getByTestId('divider-imaging-viewer-0');
  await divider.focus();
  await page.keyboard.press('Home');
  const v0 = Number(await divider.getAttribute('aria-valuenow'));
  await page.keyboard.press('ArrowRight');
  assert.equal(Number(await divider.getAttribute('aria-valuenow')), v0 + 16);
  assert.equal(await divider.getAttribute('role'), 'separator');
  await page.keyboard.press('Enter');
  const reset = await widths();
  assert.deepEqual([reset[0], reset[2]], [320, 360]);
  ok(`limits: studies 240–500px, viewer ≥400px, clinical ≤520px; keyboard (Home/→/Enter) works, Enter resets to 320/360`);

  await drag(0, 80);
  const kept = await widths();
  await page.reload();
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await page.getByTestId('panels-imaging-viewer').waitFor();
  await page.waitForTimeout(500);
  assert.ok(Math.abs((await widths())[0] - kept[0]) <= 2, 'width not kept for the session');
  ok('panel widths persist for the browser session');

  // OHIF interaction after resizing: W/L (left), zoom (right), pan (middle) on the viewport
  await page.locator(`[data-study-uid="${STUDY}"]`).click();
  const before = await image();
  const vb = await iframe.boundingBox();
  const cx = vb.x + vb.width * 0.62; const cy = vb.y + vb.height * 0.5;
  const mouseDrag = async (button, dx, dy) => {
    await page.mouse.move(cx, cy); await page.mouse.down({ button });
    for (let i = 1; i <= 8; i++) await page.mouse.move(cx + (dx * i) / 8, cy + (dy * i) / 8);
    await page.mouse.up({ button }); await page.waitForTimeout(400);
  };
  const dismiss = (await viewerFrame()).getByRole('button', { name: /Confirm and Hide/i });
  if (await dismiss.isVisible().catch(() => false)) await dismiss.click();
  await mouseDrag('left', 110, 50);
  const wl = await image();
  await mouseDrag('right', 0, -120);
  const zoomed = await image();
  await mouseDrag('middle', 90, 60);
  const panned = await image();
  assert.notDeepEqual(wl.voi, before.voi, 'window/level did not change');
  assert.notEqual(zoomed.zoom, wl.zoom, 'zoom did not change');
  assert.notDeepEqual(panned.pan, zoomed.pan, 'pan did not change');
  ok('OHIF controls after resizing: window/level, zoom and pan change the viewport');

  // AI Screening ↔ OHIF keeps the study; Open OHIF opens the same one
  await page.getByRole('tab', { name: 'AI Screening' }).click();
  await page.getByTestId('primary-finding').waitFor({ timeout: 30000 });
  await page.getByRole('tab', { name: 'OHIF Viewer' }).click();
  await iframe.waitFor();
  assert.equal(new URL(await iframe.getAttribute('src'), BASE).searchParams.get('studyInstanceUIDs'), STUDY);
  const [tab] = await Promise.all([context.waitForEvent('page'), page.getByRole('button', { name: /Open OHIF/ }).click()]);
  assert.equal(new URL(tab.url()).searchParams.get('studyInstanceUIDs'), STUDY);
  await tab.close();
  ok('AI Screening ↔ OHIF keeps the CR selected; Open OHIF targets the same study');

  // ── Page scrolling / clipping audit ──────────────────────────────────────
  for (const [w, h] of [[1280, 800], [1920, 1080]]) {
    await page.setViewportSize({ width: w, height: h });
    for (const p of PAGES) {
      await page.goto(`${BASE}${p}`);
      await page.getByTestId('patient-selector').waitFor();
      await page.waitForTimeout(p === 'imaging' ? 1500 : 800);
      const audit = await page.evaluate(() => {
        const clipped = [];
        for (const el of document.querySelectorAll('main *, aside *, header *')) {
          const cs = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          if (r.height < 40 || r.width < 40 || el.tagName === 'IFRAME' || el.closest('[aria-hidden="true"]')) continue;
          const hidden = (v) => v === 'hidden' || v === 'clip';
          if (hidden(cs.overflowY) && el.scrollHeight > el.clientHeight + 4 && cs.textOverflow !== 'ellipsis') {
            clipped.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ').slice(0, 3).join('.')} ${el.scrollHeight}>${el.clientHeight}`);
          }
        }
        const main = document.querySelector('main');
        window.scrollTo(0, document.scrollingElement.scrollHeight);
        const last = main.lastElementChild?.getBoundingClientRect();
        return { clipped, bottomReachable: !last || last.bottom <= window.innerHeight + 1,
          horizontal: document.scrollingElement.scrollWidth > window.innerWidth + 1 };
      });
      assert.deepEqual(audit.clipped, [], `${p} @${w}×${h}: clipped content`);
      assert.ok(audit.bottomReachable && !audit.horizontal, `${p} @${w}×${h}: ${JSON.stringify(audit)}`);
    }
    ok(`all ${PAGES.length} pages @${w}×${h}: no clipped content, page bottom reachable, no horizontal overflow`);
  }
  await page.setViewportSize({ width: 1280, height: 480 });
  await page.goto(`${BASE}settings`);
  const nav = page.locator('aside nav').first();
  await assertReachable(nav, 'li', 'sidebar navigation @1280×480');
  ok('sidebar navigation scrolls to Settings on a short viewport');

  assert.deepEqual(errors, []);
  ok('no console errors');
  console.log('UI LAYOUT E2E PASS');
} finally {
  await browser.close();
}
