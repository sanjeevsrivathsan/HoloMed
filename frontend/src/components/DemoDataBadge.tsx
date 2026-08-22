import { FlaskConical } from 'lucide-react';

export function DemoDataBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-900/30 dark:text-violet-300 ${className}`}
    >
      <FlaskConical className="h-3 w-3" />
      Synthetic Demo Data
    </span>
  );
}
