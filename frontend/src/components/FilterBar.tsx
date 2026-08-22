import type { ReactNode } from 'react';
import { Search, Filter } from 'lucide-react';

interface FilterBarProps {
  searchValue: string;
  onSearchChange: (v: string) => void;
  searchPlaceholder?: string;
  children?: ReactNode;
  className?: string;
}

export function FilterBar({ searchValue, onSearchChange, searchPlaceholder = 'Search...', children, className = '' }: FilterBarProps) {
  return (
    <div className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between ${className}`}>
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
        <input
          type="text"
          value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="input pl-9"
          aria-label="Search"
        />
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
}

export function SelectFilter({ label, value, options, onChange }: SelectFilterProps) {
  return (
    <div className="flex items-center gap-1.5">
      <label className="text-xs font-medium text-neutral-500 dark:text-neutral-400 whitespace-nowrap">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-neutral-300 bg-white px-2 py-1 text-xs text-neutral-700 focus:border-teal-500 focus:ring-1 focus:ring-teal-500 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
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
