import { useState } from 'react';
import {
  LayoutDashboard,
  FileText,
  Search,
  Activity,
  ScanLine,
  LayoutTemplate,
  ShieldCheck,
  HardDrive,
  Settings,
  Cpu,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { Wordmark } from './Wordmark';
import { StatusBadge } from './StatusBadge';

export type PageKey =
  | 'dashboard'
  | 'reports'
  | 'search'
  | 'timeline'
  | 'imaging'
  | 'templates'
  | 'clinical'
  | 'privacy'
  | 'storage'
  | 'settings';

interface NavItem {
  key: PageKey;
  label: string;
  icon: typeof LayoutDashboard;
}

const navItems: NavItem[] = [
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'reports', label: 'Reports', icon: FileText },
  { key: 'search', label: 'Health Search', icon: Search },
  { key: 'timeline', label: 'Health Timeline', icon: Activity },
  { key: 'imaging', label: 'Imaging', icon: ScanLine },
  { key: 'templates', label: 'Templates', icon: LayoutTemplate },
  { key: 'clinical', label: 'Clinical View', icon: FileText },
  { key: 'privacy', label: 'Privacy Center', icon: ShieldCheck },
  { key: 'storage', label: 'Storage & Delivery', icon: HardDrive },
  { key: 'settings', label: 'Settings', icon: Settings },
];

interface SidebarProps {
  currentPage: PageKey;
  onNavigate: (page: PageKey) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  ollamaAvailable: boolean;
}

export function Sidebar({ currentPage, onNavigate, collapsed, onToggleCollapse, ollamaAvailable }: SidebarProps) {
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <aside
      className={`fixed left-0 top-0 z-30 flex h-screen flex-col border-r border-neutral-200 bg-white transition-all duration-200 dark:border-neutral-800 dark:bg-neutral-900 ${
        collapsed ? 'w-16' : 'w-60'
      }`}
    >
      <div className="flex h-16 items-center justify-between px-3">
        <Wordmark collapsed={collapsed} />
        <button
          onClick={onToggleCollapse}
          className="rounded-lg p-1.5 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 dark:hover:bg-neutral-800 dark:hover:text-neutral-300"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
        <ul className="space-y-0.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentPage === item.key;
            return (
              <li key={item.key}>
                <button
                  onClick={() => onNavigate(item.key)}
                  onMouseEnter={() => setHovered(item.key)}
                  onMouseLeave={() => setHovered(null)}
                  className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-300'
                      : 'text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800'
                  } ${collapsed ? 'justify-center' : ''}`}
                  aria-current={isActive ? 'page' : undefined}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon className="h-4.5 w-4.5 shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {collapsed && hovered === item.key && (
                    <span className="absolute left-14 z-50 whitespace-nowrap rounded-md bg-neutral-900 px-2 py-1 text-xs text-white shadow-lg dark:bg-neutral-700">
                      {item.label}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
        <div className={`flex items-center gap-2 ${collapsed ? 'justify-center' : ''}`}>
          <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${ollamaAvailable ? 'bg-success-100 text-success-600 dark:bg-success-700/20 dark:text-success-400' : 'bg-neutral-100 text-neutral-400 dark:bg-neutral-800'}`}>
            <Cpu className="h-4 w-4" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-300">Local AI · Ollama</p>
              <StatusBadge variant={ollamaAvailable ? 'success' : 'neutral'} pulse={!ollamaAvailable}>
                {ollamaAvailable ? 'Connected' : 'Not running'}
              </StatusBadge>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
