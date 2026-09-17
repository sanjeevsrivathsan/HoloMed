import type { ReactNode } from 'react';
import { Search, Filter } from 'lucide-react';

interface FilterBarProps {
  searchValue: string;
  onSearchChange: (v: string) => void;
  searchPlaceholder?: string;
  children?: ReactNode;
  className?: string;
  /**
   * "inline" (default): search and filters share a row from the `sm` breakpoint.
   * "stacked": full-width search above a two-column filter grid — for narrow panels, where the
   * viewport breakpoint says nothing about the space actually available.
   */
  layout?: 'inline' | 'stacked';
}

function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="relative min-w-0">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="input h-9 w-full pl-9"
        aria-label="Search"
      />
    </div>
  );
}

export function FilterBar({
  searchValue, onSearchChange, searchPlaceholder = 'Search...', children, className = '', layout = 'inline',
}: FilterBarProps) {
  if (layout === 'stacked') {
    return (
      <div className={`flex flex-col gap-2 ${className}`} data-testid="filter-bar">
        <SearchInput value={searchValue} onChange={onSearchChange} placeholder={searchPlaceholder} />
        {children && <div className="grid grid-cols-2 gap-2">{children}</div>}
      </div>
    );
  }
  return (
    <div className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between ${className}`} data-testid="filter-bar">
      <div className="flex-1 max-w-md">
        <SearchInput value={searchValue} onChange={onSearchChange} placeholder={searchPlaceholder} />
      </div>
      {children && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-xs text-neutral-400">
            <Filter className="h-3.5 w-3.5" />
          </div>
          {children}
        </div>
      )}
    </div>
  );
}

interface SelectFilterProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  /** Label above a full-width select (for grid layouts). */
  block?: boolean;
}

export function SelectFilter({ label, value, options, onChange, block = false }: SelectFilterProps) {
  const selectClass = 'rounded-lg border border-neutral-300 bg-white px-2 text-xs text-neutral-700 focus:border-teal-500 focus:ring-1 focus:ring-teal-500 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300';
  if (block) {
    return (
      <label className="flex min-w-0 flex-col gap-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{label}</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} className={`${selectClass} h-9 w-full min-w-0`}>
          {options.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
        </select>
      </label>
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      <label className="text-xs font-medium text-neutral-500 dark:text-neutral-400 whitespace-nowrap">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${selectClass} py-1`}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
