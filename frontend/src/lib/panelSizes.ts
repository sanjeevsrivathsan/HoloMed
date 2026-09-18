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

// ── Pixel mode: fixed-width side panels plus one flexible panel that takes the rest ──

export interface PixelPanel {
  min: number;
  /** Default width in pixels; panels without it are the flexible panel. */
  px?: number;
  maxPx?: number;
}

/** Largest width fixed panel `i` may take: what is left after the other fixed panels and the flexible minimum. */
function roomFor(widths: number[], panels: PixelPanel[], i: number, width: number): number {
  const others = panels.reduce((s, p, j) => s + (j !== i && p.px !== undefined ? widths[j] : 0), 0);
  const flexibleMin = panels.reduce((s, p) => s + (p.px === undefined ? p.min : 0), 0);
  return width - others - flexibleMin;
}

/** Enforce min/max and keep the flexible panel at or above its minimum (e.g. after the window got narrower). */
export function clampPixelWidths(widths: number[], panels: PixelPanel[], width: number): number[] {
  const next = panels.map((p, i) => (p.px === undefined ? 0
    : Math.min(Math.max(Number.isFinite(widths[i]) ? widths[i] : p.px, p.min), p.maxPx ?? Infinity)));
  for (let i = panels.length - 1; i >= 0; i--) {       // shrink the rightmost fixed panels first
    if (panels[i].px === undefined) continue;
    const room = roomFor(next, panels, i, width);
    if (next[i] > room) next[i] = Math.max(panels[i].min, room);
  }
  return next.map((n) => Math.round(n));
}

/**
 * Move the divider after panel `index` by `delta` px. It resizes the fixed panel next to it
 * (the left one if fixed, otherwise the right one); the flexible panel absorbs the change.
 */
export function resizePixelPair(widths: number[], index: number, delta: number, panels: PixelPanel[], width: number): number[] {
  const next = [...widths];
  const target = panels[index]?.px !== undefined ? index : index + 1;
  if (panels[target]?.px === undefined) return next;
  const direction = target === index ? 1 : -1;
  const max = Math.max(panels[target].min, Math.min(panels[target].maxPx ?? Infinity, roomFor(widths, panels, target, width)));
  next[target] = Math.round(Math.min(Math.max(widths[target] + direction * delta, panels[target].min), max));
  return next;
}
