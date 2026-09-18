import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  filterPatients, normalizePatientCode, ohifViewerUrl, pickActivePatient, suggestPatientCode, validateNewPatient,
} from './patients.ts';

const CR = {
  studyInstanceUid: '1.2.276.0.7230010.3.1.2.8323329.6904.1517875201.850818',
  seriesInstanceUid: '1.2.276.0.7230010.3.1.3.8323329.6904.1517875201.850817',
};

test('OHIF URL targets the selected study through the patient-scoped data source', () => {
  const url = new URL(ohifViewerUrl('/ohif/', 'p-123', CR), 'http://localhost');
  assert.equal(url.pathname, '/ohif/viewer/holomed');
  assert.equal(url.searchParams.get('url'), '/api/v1/patients/p-123/dicomweb/ohif-config');
  assert.equal(url.searchParams.get('studyInstanceUIDs'), CR.studyInstanceUid);
  assert.equal(url.searchParams.get('SeriesInstanceUIDs'), CR.seriesInstanceUid);
  assert.ok(!url.href.includes('ohif.org') && !url.href.includes('cloudfront'));
});

test('OHIF URL for a different study or patient differs; series is optional', () => {
  const a = ohifViewerUrl('/ohif', 'p-1', CR);
  assert.notEqual(a, ohifViewerUrl('/ohif', 'p-2', CR));
  assert.notEqual(a, ohifViewerUrl('/ohif', 'p-1', { studyInstanceUid: '1.2.3' }));
  assert.ok(!ohifViewerUrl('/ohif', 'p-1', { studyInstanceUid: '1.2.3' }).includes('SeriesInstanceUIDs'));
});

test('new patient validation mirrors the backend rules', () => {
  assert.deepEqual(validateNewPatient({ name: 'Demo Chest X-Ray Patient', patient_code: 'hml-test-001' }, []), {});
  assert.equal(validateNewPatient({ name: ' ', patient_code: 'HML-1' }, []).name, 'Patient name is required.');
  assert.match(validateNewPatient({ name: 'x'.repeat(121), patient_code: 'HML-1' }, []).name!, /at most 120/);
  assert.equal(validateNewPatient({ name: 'A', patient_code: '' }, []).patient_code, 'Patient ID is required.');
  assert.match(validateNewPatient({ name: 'A', patient_code: 'has space' }, []).patient_code!, /letters, digits/);
  assert.equal(validateNewPatient({ name: 'A', patient_code: 'hml-test-001' }, ['HML-TEST-001']).patient_code,
    'Patient ID HML-TEST-001 already exists.');
  assert.equal(validateNewPatient({ name: 'A', patient_code: 'HML-1', date_of_birth: '1/2/90' }, []).date_of_birth, 'Use YYYY-MM-DD.');
  assert.equal(normalizePatientCode('  hml-7 '), 'HML-7');
});

test('suggested codes skip used ones', () => {
  assert.equal(suggestPatientCode([]), 'HML-000001');
  assert.equal(suggestPatientCode(['HML-000001', 'HML-TEST-001', 'hml-000003']), 'HML-000004');
});

test('active patient: remembered if still present, else the first', () => {
  const list = [{ id: 'a' }, { id: 'b' }];
  assert.equal(pickActivePatient(list, 'b'), 'b');
  assert.equal(pickActivePatient(list, 'gone'), 'a');
  assert.equal(pickActivePatient([], 'b'), null);
});

test('patient search matches code or name, case-insensitively', () => {
  const list = [{ patient_code: 'HML-000001', name: 'Demo Patient Alpha' }, { patient_code: 'HML-000002', name: 'Beta' }];
  assert.deepEqual(filterPatients(list, 'alpha').map((p) => p.patient_code), ['HML-000001']);
  assert.deepEqual(filterPatients(list, '0002').map((p) => p.name), ['Beta']);
  assert.equal(filterPatients(list, '  ').length, 2);
});
