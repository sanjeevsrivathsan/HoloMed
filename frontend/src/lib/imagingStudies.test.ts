import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hasViewableImages, pickViewerStudy } from './imagingStudies.ts';

const mr = { id: 'mr', modality: 'MR' };
const ecg = { id: 'ecg', modality: 'ECG' };
const ot = { id: 'ot', modality: 'OT' };
const cxr = { id: 'cxr', modality: 'CR' };

test('waveform and document studies are not viewable images', () => {
  for (const m of ['ECG', 'ecg', 'SR', 'KO', 'PR', 'DOC', 'AU', 'HD']) assert.equal(hasViewableImages(m), false, m);
  for (const m of ['CR', 'DX', 'CT', 'MR', 'OT', 'US', 'MG', 'Unknown', '', null, undefined]) assert.equal(hasViewableImages(m), true, String(m));
});

test('a just-uploaded study is opened instead of the oldest one', () => {
  assert.equal(pickViewerStudy([mr, ecg, ot, cxr], 'cxr'), 'cxr');
});

test('without a preference the most recent study with images is opened, never a waveform', () => {
  assert.equal(pickViewerStudy([mr, ot, cxr, ecg], null), 'cxr');
  assert.equal(pickViewerStudy([ecg, mr], null), 'mr');
});

test('a preference that no longer exists falls back to an image study', () => {
  assert.equal(pickViewerStudy([ecg, cxr], 'deleted'), 'cxr');
});

test('only non-image studies or none', () => {
  assert.equal(pickViewerStudy([ecg], null), 'ecg');
  assert.equal(pickViewerStudy([], null), null);
});
