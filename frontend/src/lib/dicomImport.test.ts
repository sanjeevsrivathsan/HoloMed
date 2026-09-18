import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  formatBytes, importedStudyUid, importTotals, isObviouslyNotDicom, planBatches, relativePath, stepStates,
  summaryLines, type ImportJob,
} from './dicomImport.ts';

test('only certainly non-DICOM files are skipped in the browser', () => {
  for (const p of ['CT/.DS_Store', 'CT/Thumbs.db', 'CT/readme.txt', 'x/report.PDF', 'a/__MACOSX/b', 'study/DICOMDIR', 'img.png', '.hidden'])
    assert.equal(isObviouslyNotDicom(p), true, p);
  for (const p of ['CT/IM0001', 'CT/slice.dcm', 'CT/1.2.840.113619.2.5', 'MR/I0000123.DCM', 'noext', 'x.dicom', 'series/0001.ima'])
    assert.equal(isObviouslyNotDicom(p), false, p);
});

test('folder selections keep the relative path', () => {
  assert.equal(relativePath({ name: 'a.dcm', webkitRelativePath: 'Study/CT/a.dcm' }), 'Study/CT/a.dcm');
  assert.equal(relativePath({ name: 'a.dcm', webkitRelativePath: '' }), 'a.dcm');
  assert.equal(relativePath({ name: 'a.dcm' }), 'a.dcm');
});

test('batches respect the file count and byte budget', () => {
  assert.deepEqual(planBatches([1, 1, 1, 1, 1], 2, 100), [[0, 1], [2, 3], [4]]);
  assert.deepEqual(planBatches([60, 50, 10, 200], 10, 100), [[0], [1, 2], [3]]);
  assert.deepEqual(planBatches([], 10, 100), []);
  const many = planBatches(Array(250).fill(500_000), 50, 64 * 1024 ** 2);
  assert.equal(many.length, 5);
  assert.equal(many.flat().length, 250);
});

test('byte sizes are readable', () => {
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(2048), '2.0 KB');
  assert.equal(formatBytes(75 * 1024 ** 2), '75.0 MB');
  assert.equal(formatBytes(1.5 * 1024 ** 3), '1.5 GB');
});

test('progress steps follow the upload and the server stage', () => {
  const files = stepStates('files', 'uploading', null, false);
  assert.equal(files.preparing, 'done');
  assert.equal(files.uploading, 'active');
  assert.equal(files.validating, 'active');        // files are validated as each batch arrives
  const zipUpload = stepStates('zip', 'uploading', null, false);
  assert.equal(zipUpload.validating, 'pending');   // a ZIP is validated after extraction
  const importing = stepStates('zip', 'server', 'importing', false);
  assert.deepEqual([importing.validating, importing.grouping, importing.importing, importing.refreshing], ['done', 'done', 'active', 'pending']);
  assert.equal(stepStates('zip', 'server', 'extracting', false).validating, 'active');
  const ready = stepStates('folder', 'ready', 'done', false);
  assert.ok(Object.values(ready).every((s) => s === 'done'));
  assert.equal(stepStates('zip', 'server', 'importing', true).importing, 'error');
});

const job = (over: Partial<ImportJob> = {}): ImportJob => ({
  id: 'j', source: 'zip', stage: 'done', archive: null, skipped: [], warnings: [], error: null,
  limits: { max_files: 10000, max_batch_files: 100, max_file_bytes: 50 * 1024 ** 2, max_archive_bytes: 2 * 1024 ** 3 },
  counts: { files_received: 500, bytes_received: 0, files_validated: 500, dicom_files: 487, skipped_non_dicom: 12,
    invalid_dicom: 3, failed: 0, to_import: 487, instances_imported: 487, duplicates: 0, studies: 2, series: 4 },
  studies: [
    { study_instance_uid: 's-empty', modality: 'SR', description: null, series_count: 1, instance_count: 0,
      series: [{ series_instance_uid: 'x', modality: 'SR', description: null, series_number: 1, instance_count: 1, imported: 0, duplicates: 0 }] },
    { study_instance_uid: 's-ct', modality: 'CT', description: 'Chest', series_count: 1, instance_count: 120,
      series: [{ series_instance_uid: 'y', modality: 'CT', description: null, series_number: 2, instance_count: 120, imported: 120, duplicates: 0 }] },
  ],
  ...over,
});

test('the summary reports imported and skipped files in words', () => {
  const lines = summaryLines(importTotals(job(), 0, 0));
  assert.deepEqual(lines.imported, ['2 studies', '4 series', '487 instances']);
  assert.deepEqual(lines.skipped, ['12 non-DICOM files', '3 invalid DICOM files']);
  const one = summaryLines({ studies: 1, series: 1, instances: 120, duplicates: 5, skippedNonDicom: 1, invalid: 0, failed: 2 });
  assert.deepEqual(one.imported, ['1 study', '1 series', '120 instances', '5 instances already present (not duplicated)']);
  assert.deepEqual(one.skipped, ['1 non-DICOM file', '2 files failed']);
  assert.equal(importTotals(job(), 4, 1).skippedNonDicom, 16);
  assert.equal(importTotals(job(), 4, 1).failed, 1);
});

test('after an import the study that received images is shown', () => {
  assert.equal(importedStudyUid(job()), 's-ct');
  assert.equal(importedStudyUid(job({ studies: [] })), null);
});
