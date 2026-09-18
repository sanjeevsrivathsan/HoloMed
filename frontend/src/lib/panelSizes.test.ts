import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clampPixelWidths, clampSizes, resizePair, resizePixelPair } from './panelSizes.ts';

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

// Imaging: studies | OHIF viewer (flexible) | clinical panel
const IMAGING = [{ min: 240, px: 320, maxPx: 500 }, { min: 400 }, { min: 280, px: 360, maxPx: 520 }];

test('pixel mode: dividers resize their fixed neighbour and respect px limits', () => {
  const w = [320, 0, 360];
  assert.deepEqual(resizePixelPair(w, 0, 120, IMAGING, 1600), [440, 0, 360]);      // studies wider
  assert.deepEqual(resizePixelPair(w, 0, 900, IMAGING, 1600), [500, 0, 360]);      // capped at maxPx
  assert.deepEqual(resizePixelPair(w, 0, -900, IMAGING, 1600), [240, 0, 360]);     // floored at min
  assert.deepEqual(resizePixelPair(w, 1, -100, IMAGING, 1600), [320, 0, 460]);     // clinical wider (drag left)
  assert.deepEqual(resizePixelPair(w, 1, 900, IMAGING, 1600), [320, 0, 280]);
});

test('pixel mode: the flexible viewer keeps its minimum width', () => {
  // 1000px: 1000 - 400 viewer min - 360 clinical = 240 left for studies
  assert.deepEqual(resizePixelPair([240, 0, 360], 0, 300, IMAGING, 1000), [240, 0, 360]);
  const clamped = clampPixelWidths([500, 0, 520], IMAGING, 1000);
  assert.ok(clamped[0] + clamped[2] + 400 <= 1000 || (clamped[0] === 240 && clamped[2] === 280), String(clamped));
  assert.deepEqual(clampPixelWidths([NaN, 0, 900], IMAGING, 1600), [320, 0, 520]);
});
