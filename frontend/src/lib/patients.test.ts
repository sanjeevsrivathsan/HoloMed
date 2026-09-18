import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  filterPatients, normalizePatientCode, normalizePhone, ohifViewerUrl, parseAge, patientDetails, pickActivePatient,
  suggestPatientCode, validateNewPatient,
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
  const ok = { name: 'Test Patient Alpha', patient_code: 'HML-TEST-002', age: '25', sex: '', phone: ' +91 98765  43210 ' };
  assert.deepEqual(validateNewPatient(ok, []), {});
  for (const age of ['-1', '131', '25.5', 'abc', '1e2', '2 5']) {
    assert.match(validateNewPatient({ ...ok, age }, []).age ?? '', /0 to 130/, age);
  }
  assert.deepEqual(validateNewPatient({ ...ok, age: '0' }, []), {});
  assert.deepEqual(validateNewPatient({ ...ok, age: '' }, []), {});
  for (const phone of ['abc', '12345', '++91 98765', '98765+43210', '+91 98765 43210 12345 67']) {
    assert.match(validateNewPatient({ ...ok, phone }, []).phone ?? '', /valid phone/, phone);
  }
  for (const phone of ['+1 (555) 010-4477', '+44 20 7946 0958', '9876543210', '']) {
    assert.deepEqual(validateNewPatient({ ...ok, phone }, []), {}, phone);
  }
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

test('age parsing, phone normalisation and patient detail lines', () => {
  assert.equal(parseAge(' 25 '), 25);
  assert.equal(parseAge(''), null);
  assert.ok(Number.isNaN(parseAge('x')));
  assert.equal(normalizePhone('  +91  98765   43210 '), '+91 98765 43210');
  assert.deepEqual(patientDetails({ age: 24, sex: null, phone: '+91 98765 43210' }), [
    { label: 'Age', value: '24 years' }, { label: 'Sex', value: 'Not specified' }, { label: 'Phone', value: '+91 98765 43210' },
  ]);
  assert.equal(patientDetails({ age: null, sex: 'female', phone: null })[1].value, 'Female');
});
