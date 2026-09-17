// Run with: npm test  (Node's built-in test runner; no extra dependencies)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aiSummaryAvailability, failureMessage, pipelineOutcome, stageLine, uploadStages, type ProcessingStage, type StageState,
} from './processingStages.ts';

const states = (stages: ProcessingStage[]) => stages.map((s) => s.state);
const lines = (stages: ProcessingStage[]) => stages.map((s) => {
  const l = stageLine(s);
  return `${l.symbol} ${l.text}`;
});
const server = (...st: StageState[]): ProcessingStage[] =>
  ['upload', 'text_extraction', 'ocr', 'structured_extraction', 'save'].map((key, i) => ({
    key,
    label: ['Upload', 'Extract text', 'OCR fallback', 'Extract structured data', 'Save report'][i],
    state: st[i],
    detail: null,
  }));

test('initial state: everything pending, not ready', () => {
  const s = uploadStages('idle');
  assert.deepEqual(states(s), ['pending', 'pending', 'pending', 'pending', 'pending']);
  assert.deepEqual(lines(s), ['○ Upload', '○ Extract text', '○ OCR fallback', '○ Extract structured data', '○ Save report']);
  assert.equal(pipelineOutcome(s), 'in_progress');
});

test('uploading shows progress on the upload stage only', () => {
  const s = uploadStages('uploading', { progress: 0.42 });
  assert.deepEqual(states(s), ['active', 'pending', 'pending', 'pending', 'pending']);
  assert.equal(s[0].detail, '42%');
  assert.equal(stageLine(s[0]).text, 'Uploading');
});

test('upload accepted before server progress: extracting text is active, nothing else done', () => {
  const s = uploadStages('server', { serverStages: null });
  assert.deepEqual(lines(s), ['✓ Upload', '● Extracting text', '○ OCR fallback', '○ Extract structured data', '○ Save report']);
  assert.equal(pipelineOutcome(s), 'in_progress');
});

test('OCR not required while structured extraction runs', () => {
  const s = uploadStages('server', { serverStages: server('completed', 'completed', 'skipped', 'active', 'pending') });
  assert.deepEqual(lines(s), [
    '✓ Upload', '✓ Extract text', '— OCR fallback not required', '● Extracting structured data', '○ Save report']);
  assert.equal(pipelineOutcome(s), 'in_progress');
});

test('success is reported only when every stage is completed or skipped', () => {
  const s = server('completed', 'completed', 'skipped', 'completed', 'completed');
  assert.equal(pipelineOutcome(s), 'ready');
  assert.deepEqual(lines(s), [
    '✓ Upload', '✓ Extract text', '— OCR fallback not required', '✓ Extract structured data', '✓ Save report']);
  assert.equal(pipelineOutcome(server('completed', 'completed', 'completed', 'completed', 'active')), 'in_progress');
});

test('failed stage: later stages are not shown as completed and a readable reason is given', () => {
  const s = server('completed', 'completed', 'skipped', 'failed', 'not_reached');
  s[3].detail = 'The report text was extracted, but structured measurements could not be created. You can retry processing.';
  assert.equal(pipelineOutcome(s), 'failed');
  assert.deepEqual(lines(s), [
    '✓ Upload', '✓ Extract text', '— OCR fallback not required', '✕ Extract structured data', '○ Save report (not reached)']);
  assert.match(failureMessage(s) ?? '', /structured measurements could not be created/);
  assert.ok(!s.slice(4).some((x) => x.state === 'completed'));
});

test('failure without server detail still gives a retry hint', () => {
  assert.equal(failureMessage(server('completed', 'failed', 'not_reached', 'not_reached', 'not_reached')),
    'Extract text failed. You can retry processing.');
  assert.equal(failureMessage(server('completed', 'completed', 'skipped', 'completed', 'completed')), null);
});

test('upload failure blocks every later stage', () => {
  const s = uploadStages('upload_failed', { uploadError: 'The file is empty.' });
  assert.deepEqual(states(s), ['failed', 'not_reached', 'not_reached', 'not_reached', 'not_reached']);
  assert.equal(failureMessage(s), 'The file is empty.');
});

test('retry: a failed pipeline returns to in-progress when the server restarts processing', () => {
  const failed = server('completed', 'failed', 'not_reached', 'not_reached', 'not_reached');
  assert.equal(pipelineOutcome(failed), 'failed');
  const retried = uploadStages('server', { serverStages: server('completed', 'active', 'pending', 'pending', 'pending') });
  assert.equal(pipelineOutcome(retried), 'in_progress');
  assert.equal(failureMessage(retried), null);
});

test('OCR used: shown as completed, not skipped', () => {
  const s = server('completed', 'completed', 'completed', 'completed', 'completed');
  assert.equal(stageLine(s[2]).text, 'OCR fallback');
  assert.equal(stageLine({ ...s[2], state: 'active' }).text, 'Running OCR fallback');
});

test('AI summary unavailable never looks like a processing failure', () => {
  const ok = aiSummaryAvailability('connected');
  assert.equal(ok.available, true);
  for (const state of ['not_running', 'model_missing', 'not_configured', null] as const) {
    const r = aiSummaryAvailability(state);
    assert.equal(r.available, false);
    assert.match(r.message, /^AI summary unavailable/);
    assert.match(r.message, /Report processing and your confirmed values are not affected/);
  }
  // still checking is neither available nor a failure
  assert.deepEqual(aiSummaryAvailability(undefined), { available: null, message: 'Checking AI summary availability…' });
  // a completed pipeline stays "ready" regardless of text AI state
  assert.equal(pipelineOutcome(server('completed', 'completed', 'skipped', 'completed', 'completed')), 'ready');
});
