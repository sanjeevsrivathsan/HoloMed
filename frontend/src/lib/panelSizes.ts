/**
 * Panel size arithmetic for ResizablePanels (percentages that always add up to 100).
 * Kept free of path aliases so it runs under `node --test`.
 */

const round = (n: number) => Math.round(n * 100) / 100;

/** Move the divider after panel `index` by `delta` percent, respecting min/max of both neighbours. */
export function resizePair(sizes: number[], index: number, delta: number, mins: number[], maxes: number[]): number[] {
  const next = [...sizes];
  const a = index;
  const b = index + 1;
  if (b >= sizes.length) return next;
  const total = sizes[a] + sizes[b];
  let left = sizes[a] + delta;
  left = Math.max(left, mins[a], total - Math.min(maxes[b], 100));
  left = Math.min(left, maxes[a], total - mins[b]);
  if (mins[a] + mins[b] > total) left = sizes[a];          // not enough room: keep as is
  next[a] = round(left);
  next[b] = round(total - left);
  return next;
}

/** Normalise sizes to 100 and enforce minimums (e.g. after the window got narrower). */
export function clampSizes(sizes: number[], mins: number[], maxes: number[]): number[] {
  const sum = sizes.reduce((s, n) => s + n, 0) || 1;
  let next = sizes.map((n, i) => Math.min(Math.max((n / sum) * 100, mins[i]), maxes[i]));
  const excess = next.reduce((s, n) => s + n, 0) - 100;
  if (Math.abs(excess) > 0.01) {
    // take/give the difference from panels that have room above their minimum
    const flexible = next.map((n, i) => (excess > 0 ? n - mins[i] : maxes[i] - n));
    const room = flexible.reduce((s, n) => s + Math.max(n, 0), 0);
    if (room > 0) {
      next = next.map((n, i) => n - (excess * Math.max(flexible[i], 0)) / room);
    }
  }
  return next.map(round);
}
