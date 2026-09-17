import { Children, useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { clampSizes, resizePair } from '@/lib/panelSizes';

export interface PanelSpec {
  /** Accessible name of the panel (used for the divider label). */
  label: string;
  /** Minimum width in pixels. */
  min: number;
  /** Default share of the width, in percent (all panels should add up to 100). */
  size: number;
  /** Maximum share of the width, in percent. */
  max?: number;
}

interface ResizablePanelsProps {
  /** Storage key: sizes persist for the browser session. */
  id: string;
  panels: PanelSpec[];
  /** Below this viewport width the panels stack vertically and are not resizable. */
  breakpoint?: number;
  className?: string;
  children: ReactNode;
}

const DIVIDER = 10;          // px
const KEY_STEP = 2;          // percent per arrow key press

function loadSizes(id: string, panels: PanelSpec[]): number[] {
  const defaults = panels.map((p) => p.size);
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(`holomed.panels.${id}`) ?? 'null');
    if (Array.isArray(saved) && saved.length === panels.length && saved.every((n) => typeof n === 'number')) {
      return saved;
    }
  } catch { /* storage unavailable */ }
  return defaults;
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
 * Widths use CSS grid `minmax(min, share)` tracks, so panels never shrink below their minimum
 * and the layout never overflows horizontally.
 */
export function ResizablePanels({ id, panels, breakpoint = 1024, className = '', children }: ResizablePanelsProps) {
  const wide = useMediaQuery(`(min-width: ${breakpoint}px)`);
  const containerRef = useRef<HTMLDivElement>(null);
  const [sizes, setSizes] = useState<number[]>(() => loadSizes(id, panels));
  const drag = useRef<{ index: number; startX: number; startSizes: number[]; width: number } | null>(null);
  const items = Children.toArray(children);

  const widthOf = () => (containerRef.current?.getBoundingClientRect().width ?? 0) - DIVIDER * (panels.length - 1);
  const minPercents = useCallback((width: number) => panels.map((p) => (width > 0 ? (p.min / width) * 100 : 0)), [panels]);

  const commit = useCallback((next: number[]) => {
    setSizes(next);
    try { window.sessionStorage.setItem(`holomed.panels.${id}`, JSON.stringify(next)); } catch { /* ignore */ }
  }, [id]);

  // keep stored sizes valid for the current width
  useEffect(() => {
    if (!wide) return;
    const width = widthOf();
    if (width > 0) setSizes((s) => clampSizes(s, minPercents(width), panels.map((p) => p.max ?? 100)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide]);

  const onPointerDown = (index: number) => (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { index, startX: e.clientX, startSizes: sizes, width: widthOf() };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.width <= 0) return;
    const delta = ((e.clientX - d.startX) / d.width) * 100;
    setSizes(resizePair(d.startSizes, d.index, delta, minPercents(d.width), panels.map((p) => p.max ?? 100)));
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    drag.current = null;
    commit(sizes);
  };
  const onKeyDown = (index: number) => (e: KeyboardEvent<HTMLDivElement>) => {
    const width = widthOf();
    const mins = minPercents(width);
    const maxes = panels.map((p) => p.max ?? 100);
    let delta = 0;
    if (e.key === 'ArrowLeft') delta = -KEY_STEP;
    else if (e.key === 'ArrowRight') delta = KEY_STEP;
    else if (e.key === 'Home') delta = -100;
    else if (e.key === 'End') delta = 100;
    else if (e.key === 'Enter' || e.key === ' ') { commit(panels.map((p) => p.size)); e.preventDefault(); return; }
    else return;
    e.preventDefault();
    commit(resizePair(sizes, index, delta, mins, maxes));
  };

  if (!wide) {
    return <div className={`grid grid-cols-1 gap-4 ${className}`} data-testid={`panels-${id}`} data-layout="stacked">{items}</div>;
  }

  const template = panels
    .map((p, i) => `minmax(${p.min}px, ${sizes[i]}fr)`)
    .join(` ${DIVIDER}px `);

  return (
    <div ref={containerRef} className={`grid min-w-0 ${className}`} style={{ gridTemplateColumns: template }}
      data-testid={`panels-${id}`} data-layout="split">
      {items.flatMap((child, i) => {
        const panel = (
          <div key={`panel-${i}`} className="min-w-0 lg:min-h-0" data-panel={panels[i]?.label}>{child}</div>
        );
        if (i === items.length - 1) return [panel];
        const now = Math.round(sizes[i]);
        return [panel, (
          <div
            key={`divider-${i}`}
            role="separator"
            aria-orientation="vertical"
            aria-label={`Resize ${panels[i].label} and ${panels[i + 1].label}`}
            aria-valuenow={now}
            aria-valuemin={0}
            aria-valuemax={100}
            tabIndex={0}
            onPointerDown={onPointerDown(i)}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onKeyDown={onKeyDown(i)}
            onDoubleClick={() => commit(panels.map((p) => p.size))}
            title="Drag to resize · double-click to reset"
            data-testid={`divider-${id}-${i}`}
            className="group relative flex cursor-col-resize touch-none select-none items-center justify-center rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <span className="h-full w-px bg-neutral-200 transition-colors group-hover:bg-teal-400 group-active:bg-teal-500 dark:bg-neutral-800" />
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
