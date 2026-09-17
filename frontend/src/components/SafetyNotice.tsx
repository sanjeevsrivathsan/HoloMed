import { ShieldAlert } from 'lucide-react';
import type { ReactNode } from 'react';

interface SafetyNoticeProps {
  variant?: 'compact' | 'full';
  className?: string;
  /** Overrides the default notice text (e.g. AI screening wording). */
  message?: string;
  children?: ReactNode;
}

export function SafetyNotice({ variant = 'full', className = '', message, children }: SafetyNoticeProps) {
  return (
    <div
      className={`flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-700/30 dark:bg-amber-900/10 ${className}`}
      role="note"
    >
      <ShieldAlert className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
      <div className="min-w-0">
        <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">Safety Notice</p>
        {message ? (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400/90">{message}</p>
        ) : variant === 'full' ? (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400/90">
            AI-generated summaries are not a substitute for professional medical advice. Always verify findings with your healthcare provider. Do not make clinical decisions based solely on AI output.
          </p>
        ) : (
          <p className="text-xs text-amber-700 dark:text-amber-400/90">
            Verify with your healthcare provider.
          </p>
        )}
        {children}
      </div>
    </div>
  );
}
