import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clampSizes, resizePair } from './panelSizes.ts';

const sum = (a: number[]) => Math.round(a.reduce((s, n) => s + n, 0) * 100) / 100;

test('dragging moves space between the two neighbouring panels only', () => {
  const next = resizePair([25, 50, 25], 0, 10, [10, 30, 10], [100, 100, 100]);
  assert.deepEqual(next, [35, 40, 25]);
  assert.equal(sum(next), 100);
});

test('minimum widths are respected in both directions', () => {
  assert.deepEqual(resizePair([25, 50, 25], 0, -40, [20, 30, 20], [100, 100, 100]), [20, 55, 25]);
  assert.deepEqual(resizePair([25, 50, 25], 0, 60, [20, 30, 20], [100, 100, 100]), [45, 30, 25]);
  assert.deepEqual(resizePair([25, 50, 25], 1, 100, [20, 30, 20], [100, 100, 100]), [25, 55, 20]);
});

test('maximum widths are respected', () => {
  assert.deepEqual(resizePair([40, 60], 0, 30, [10, 10], [50, 100]), [50, 50]);
  assert.deepEqual(resizePair([40, 60], 0, -30, [10, 10], [100, 70]), [30, 70]);
});

test('no room: sizes stay unchanged; last panel has no divider', () => {
  assert.deepEqual(resizePair([30, 20], 0, 5, [30, 30], [100, 100]), [30, 20]);
  assert.deepEqual(resizePair([50, 50], 1, 5, [10, 10], [100, 100]), [50, 50]);
});

test('clamping normalises to 100 and restores minimums on narrow screens', () => {
  assert.deepEqual(clampSizes([1, 1], [0, 0], [100, 100]), [50, 50]);
  const clamped = clampSizes([10, 80, 10], [20, 30, 20], [100, 100, 100]);
  assert.equal(sum(clamped), 100);
  assert.ok(clamped[0] >= 20 && clamped[2] >= 20 && clamped[1] >= 30);
});
