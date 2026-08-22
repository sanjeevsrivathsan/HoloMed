import { useState, type ReactNode } from 'react';

interface Tab {
  key: string;
  label: string;
  icon?: ReactNode;
}

interface TabsProps {
  tabs: Tab[];
  activeKey: string;
  onChange: (key: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeKey, onChange, className = '' }: TabsProps) {
  return (
    <div className={`flex gap-1 border-b border-neutral-200 dark:border-neutral-800 ${className}`}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            activeKey === tab.key ? 'tab-active' : 'tab-inactive'
          }`}
          aria-selected={activeKey === tab.key}
          role="tab"
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function useTabs(initialKey: string) {
  const [activeKey, setActiveKey] = useState(initialKey);
  return { activeKey, setActiveKey };
}
