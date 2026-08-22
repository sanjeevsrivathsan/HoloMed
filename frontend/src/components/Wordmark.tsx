import { Activity, ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';

export function Wordmark({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-teal-500 to-teal-700 text-white shadow-sm">
        <Activity className="h-5 w-5" />
      </div>
      {!collapsed && (
        <div className="min-w-0">
          <p className="truncate text-sm font-bold tracking-tight text-neutral-900 dark:text-white">
            HoloMed AI
          </p>
          <p className="truncate text-xs text-neutral-400 dark:text-neutral-500">
            Clinical Intelligence
          </p>
        </div>
      )}
      {collapsed && <ChevronLeft className="h-4 w-4 text-neutral-400" />}
    </div>
  );
}

export function SidebarLogo({ collapsed }: { collapsed: boolean }) {
  return <Wordmark collapsed={collapsed} />;
}

export function SidebarTagline({ children }: { children: ReactNode }) {
  return <p className="px-3 text-xs text-neutral-400">{children}</p>;
}
