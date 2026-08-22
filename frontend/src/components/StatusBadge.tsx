import type { ReactNode } from 'react';

type Variant = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'processing';

interface StatusBadgeProps {
  variant?: Variant;
  children: ReactNode;
  icon?: ReactNode;
  pulse?: boolean;
  className?: string;
}

const variantClasses: Record<Variant, string> = {
  success: 'bg-success-100 text-success-700 dark:bg-success-700/20 dark:text-success-400',
  warning: 'bg-warning-100 text-warning-700 dark:bg-warning-700/20 dark:text-warning-400',
  error: 'bg-error-100 text-error-700 dark:bg-error-700/20 dark:text-error-400',
  info: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  neutral: 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400',
  processing: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400',
};

export function StatusBadge({ variant = 'neutral', children, icon, pulse = false, className }: StatusBadgeProps) {
  return (
    <span className={`badge ${variantClasses[variant]} ${pulse ? 'animate-pulse-soft' : ''} ${className ?? ''}`}>
      {icon}
      {children}
    </span>
  );
}
