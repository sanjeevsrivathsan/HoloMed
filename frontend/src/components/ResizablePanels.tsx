import { Children, useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { clampPixelWidths, clampSizes, resizePair, resizePixelPair } from '@/lib/panelSizes';

export interface PanelSpec {
  /** Accessible name of the panel (used for the divider label). */
  label: string;
  /** Minimum width in pixels. */
  min: number;
  /** Default share of the width, in percent (percent mode; all panels should add up to 100). */
  size: number;
  /** Maximum share of the width, in percent (percent mode). */
  max?: number;
  /**
   * Pixel mode: default width in pixels. When any panel sets `px`, panels with `px` get fixed,
   * user-resizable widths (clamped to min…maxPx) and the one panel without `px` takes the rest.
   */
  px?: number;
  /** Pixel mode: maximum width in pixels. */
  maxPx?: number;
}

interface ResizablePanelsProps {
  /** Storage key: sizes persist for the browser session. */
  id: string;
  panels: PanelSpec[];
  /** Below this viewport width the panels stack vertically and are not resizable. */
  breakpoint?: number;
  /** Fill the container's height (each panel gets the full row height and manages its own scrolling). */
  fill?: boolean;
  className?: string;
  children: ReactNode;
}

const DIVIDER = 10;          // px
const KEY_STEP = 2;          // percent per arrow key press (percent mode)
const KEY_STEP_PX = 16;      // pixels per arrow key press (pixel mode)

function storageKey(id: string, pixel: boolean): string {
  return `holomed.panels.${id}${pixel ? '.px' : ''}`;
}

function loadSizes(id: string, panels: PanelSpec[]): number[] {
  const defaults = panels.map((p) => p.size);
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(storageKey(id, false)) ?? 'null');
    if (Array.isArray(saved) && saved.length === panels.length && saved.every((n) => typeof n === 'number')) {
      return saved;
    }
  } catch { /* storage unavailable */ }
  return defaults;
}

/** Pixel mode: preferred widths keyed by panel label, so they survive panels being shown/hidden. */
function loadPixelPrefs(id: string): Record<string, number> {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(storageKey(id, true)) ?? 'null');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      return Object.fromEntries(Object.entries(saved).filter(([, v]) => typeof v === 'number' && Number.isFinite(v))) as Record<string, number>;
    }
  } catch { /* storage unavailable */ }
  return {};
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

/**
 * Side-by-side panels with draggable, keyboard-accessible dividers.
 * Percent mode uses CSS grid `minmax(min, share)` tracks; pixel mode uses fixed pixel tracks plus
 * one `minmax(min, 1fr)` track. Either way panels never shrink below their minimum and the layout
 * never overflows horizontally. While a divider is dragged, iframes inside ignore the pointer
 * (`data-resizing`) so an embedded viewer cannot swallow the drag; nothing covers them otherwise.
 */
export function ResizablePanels({ id, panels, breakpoint = 1024, fill = false, className = '', children }: ResizablePanelsProps) {
  const pixel = panels.some((p) => p.px !== undefined);
  const wide = useMediaQuery(`(min-width: ${breakpoint}px)`);
  const containerRef = useRef<HTMLDivElement>(null);
  // `sizes` is the user's preference; in pixel mode the rendered widths are derived from it and the
  // current container width, so a narrow window never overwrites the preference (widening restores it).
  const [percentSizes, setSizes] = useState<number[]>(() => (pixel ? [] : loadSizes(id, panels)));
  const [prefs, setPrefs] = useState<Record<string, number>>(() => (pixel ? loadPixelPrefs(id) : {}));
  const sizes = pixel ? panels.map((p) => prefs[p.label] ?? p.px ?? 0) : percentSizes;
  const [available, setAvailable] = useState(0);
  const [resizing, setResizing] = useState(false);
  const drag = useRef<{ index: number; startX: number; startSizes: number[]; width: number } | null>(null);
  const items = Children.toArray(children);

  const widthOf = () => (containerRef.current?.getBoundingClientRect().width ?? 0) - DIVIDER * (panels.length - 1);
  const minPercents = useCallback((width: number) => panels.map((p) => (width > 0 ? (p.min / width) * 100 : 0)), [panels]);

  const commit = useCallback((next: number[]) => {
    if (pixel) {
      setPrefs((prev) => {
        const merged: Record<string, number> = { ...prev };
        panels.forEach((p, i) => { if (p.px !== undefined && Number.isFinite(next[i])) merged[p.label] = next[i]; });
        try { window.sessionStorage.setItem(storageKey(id, true), JSON.stringify(merged)); } catch { /* ignore */ }
        return merged;
      });
      return;
    }
    setSizes(next);
    try { window.sessionStorage.setItem(storageKey(id, false), JSON.stringify(next)); } catch { /* ignore */ }
  }, [id, pixel, panels]);

  const clampAll = useCallback((s: number[], width: number) => (pixel
    ? clampPixelWidths(s, panels, width)
    : clampSizes(s, minPercents(width), panels.map((p) => p.max ?? 100))), [pixel, panels, minPercents]);

  // Track the container width; percent mode also re-normalises its stored shares to it.
  useLayoutEffect(() => {
    if (!wide || !containerRef.current) return;
    const apply = () => {
      const width = widthOf();
      if (width <= 0) return;
      setAvailable((w) => (Math.abs(w - width) < 0.5 ? w : width));
      if (pixel) return;
      setSizes((s) => {
        const next = clampAll(s, width);
        return next.length === s.length && next.every((v, i) => v === s[i]) ? s : next;   // no-op → no re-render
      });
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(containerRef.current);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide, clampAll]);

  const resizeBy = (start: number[], index: number, delta: number, width: number) => (pixel
    ? resizePixelPair(start, index, delta, panels, width)
    : resizePair(start, index, (delta / width) * 100, minPercents(width), panels.map((p) => p.max ?? 100)));

  // Reset: pixel mode stores the raw defaults (rendering clamps them); percent mode stores clamped shares.
  const defaults = (width: number) => (pixel ? panels.map((p) => p.px ?? 0) : clampAll(panels.map((p) => p.size), width));

  const shown = pixel && available > 0 ? clampPixelWidths(sizes, panels, available) : sizes;

  const onPointerDown = (index: number) => (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { index, startX: e.clientX, startSizes: shown, width: widthOf() };
    setResizing(true);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.width <= 0) return;
    const next = resizeBy(d.startSizes, d.index, e.clientX - d.startX, d.width);
    if (pixel) {
      setPrefs((prev) => {
        const merged: Record<string, number> = { ...prev };
        panels.forEach((p, i) => { if (p.px !== undefined) merged[p.label] = next[i]; });
        return merged;
      });
    } else {
      setSizes(next);
    }
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    drag.current = null;
    setResizing(false);
    commit(sizes);
  };
  const onKeyDown = (index: number) => (e: KeyboardEvent<HTMLDivElement>) => {
    const width = widthOf();
    const step = pixel ? KEY_STEP_PX : (KEY_STEP / 100) * width;
    let delta = 0;
    if (e.key === 'ArrowLeft') delta = -step;
    else if (e.key === 'ArrowRight') delta = step;
    else if (e.key === 'Home') delta = -width;
    else if (e.key === 'End') delta = width;
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      commit(defaults(width));
      return;
    }
    else return;
    e.preventDefault();
    commit(resizeBy(shown, index, delta, width));
  };

  if (!wide) {
    return <div className={`grid grid-cols-1 gap-4 ${className}`} data-testid={`panels-${id}`} data-layout="stacked">{items}</div>;
  }

  const template = panels
    .map((p, i) => (pixel
      ? (p.px !== undefined ? `${Math.round(shown[i])}px` : `minmax(${p.min}px, 1fr)`)
      : `minmax(${p.min}px, ${sizes[i]}fr)`))
    .join(` ${DIVIDER}px `);

  // The divider value reported to assistive tech: the width of the panel it sizes.
  const valueOf = (i: number) => {
    if (!pixel) return { now: Math.round(sizes[i]), min: 0, max: 100 };
    const target = panels[i].px !== undefined ? i : i + 1;
    return { now: Math.round(shown[target]), min: panels[target].min, max: panels[target].maxPx ?? Math.round(available) };
  };

  return (
    <div
      ref={containerRef}
      className={`grid min-w-0 ${fill ? 'h-full min-h-0' : ''} ${className}`}
      style={{ gridTemplateColumns: template, ...(fill ? { gridTemplateRows: 'minmax(0, 1fr)' } : {}) }}
      data-testid={`panels-${id}`}
      data-layout="split"
      data-resizing={resizing || undefined}
    >
      {items.flatMap((child, i) => {
        const panel = (
          <div key={`panel-${i}`} className={`min-w-0 ${fill ? 'h-full min-h-0' : 'lg:min-h-0'}`} data-panel={panels[i]?.label}>{child}</div>
        );
        if (i === items.length - 1) return [panel];
        const value = valueOf(i);
        return [panel, (
          <div
            key={`divider-${i}`}
            role="separator"
            aria-orientation="vertical"
            aria-label={`Resize ${panels[i].label} and ${panels[i + 1].label}`}
            aria-valuenow={value.now}
            aria-valuemin={value.min}
            aria-valuemax={value.max}
            tabIndex={0}
            onPointerDown={onPointerDown(i)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onKeyDown(i)}
            onDoubleClick={() => commit(defaults(widthOf()))}
            title="Drag to resize · double-click to reset"
            data-testid={`divider-${id}-${i}`}
            className="group relative flex cursor-col-resize touch-none select-none items-center justify-center rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <span className="h-full w-px bg-neutral-200 transition-colors group-hover:bg-teal-400 group-active:bg-teal-500 group-focus-visible:bg-teal-500 dark:bg-neutral-700 dark:group-hover:bg-teal-500" />
            <span className="absolute top-1/2 flex h-8 w-2 -translate-y-1/2 flex-col items-center justify-center gap-0.5 rounded bg-neutral-100 opacity-80 group-hover:bg-teal-100 dark:bg-neutral-800 dark:group-hover:bg-teal-900">
              <span className="h-0.5 w-0.5 rounded-full bg-neutral-400" />
              <span className="h-0.5 w-0.5 rounded-full bg-neutral-400" />
              <span className="h-0.5 w-0.5 rounded-full bg-neutral-400" />
            </span>
          </div>
        )];
      })}
    </div>
  );
}
