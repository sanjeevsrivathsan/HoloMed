import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dateOptions, needsExplicitChoice, type DetectedDate } from './reportDates.ts';

const d = (kind: DetectedDate['kind'], label: string, text: string, value: string | null, alternatives: string[] = []): DetectedDate =>
  ({ kind, label, text, value, alternatives });

test('a single detected date can be used directly', () => {
  const opts = dateOptions([d('collected', 'Collected on', '14/09/2026', '2026-09-14')]);
  assert.deepEqual(opts, [{ value: '2026-09-14', labels: ['Collected'], printed: ['Collected on: 14/09/2026'], ambiguous: false }]);
  assert.equal(needsExplicitChoice(opts), false);
});

test('the same date printed under several labels is one option', () => {
  const opts = dateOptions([
    d('collected', 'Collected on', '14/09/2026', '2026-09-14'),
    d('reported', 'Reported on', '14/09/2026', '2026-09-14'),
  ]);
  assert.equal(opts.length, 1);
  assert.deepEqual(opts[0].labels, ['Collected', 'Reported']);
  assert.equal(needsExplicitChoice(opts), false);
});

test('different dates require an explicit choice', () => {
  const opts = dateOptions([
    d('collected', 'Collected on', '14/09/2026', '2026-09-14'),
    d('registered', 'Registration Time', '13/09/2026', '2026-09-13'),
    d('reported', 'Reported on', '15/09/2026', '2026-09-15'),
  ]);
  assert.deepEqual(opts.map((o) => o.value), ['2026-09-14', '2026-09-13', '2026-09-15']);
  assert.equal(needsExplicitChoice(opts), true);
});

test('ambiguous day/month dates offer both readings and are never auto-selected', () => {
  const opts = dateOptions([
    d('collected', 'Collected on', '05/09/2026', null, ['2026-09-05', '2026-05-09']),
    d('registered', 'Registration Time', '05/09/2026', null, ['2026-09-05', '2026-05-09']),
  ]);
  assert.deepEqual(opts.map((o) => o.value), ['2026-09-05', '2026-05-09']);
  assert.deepEqual(opts[0].labels, ['Collected (if read as day/month)', 'Registered (if read as day/month)']);
  assert.ok(opts.every((o) => o.ambiguous));
  assert.equal(needsExplicitChoice(opts), true);
});

test('no detected dates means manual entry', () => {
  assert.deepEqual(dateOptions([]), []);
  assert.equal(needsExplicitChoice([]), true);
});
