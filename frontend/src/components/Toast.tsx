import { CheckCircle2, AlertCircle, Info, XCircle, X } from 'lucide-react';
import { useToast } from '@/context/ToastContext';
import type { ToastMessage } from '@/lib/types';

const variantConfig = {
  success: { icon: CheckCircle2, color: 'text-success-600', border: 'border-success-200 dark:border-success-700/30' },
  warning: { icon: AlertCircle, color: 'text-warning-600', border: 'border-warning-200 dark:border-warning-700/30' },
  error: { icon: XCircle, color: 'text-error-600', border: 'border-error-200 dark:border-error-700/30' },
  info: { icon: Info, color: 'text-blue-600', border: 'border-blue-200 dark:border-blue-700/30' },
};

export function ToastContainer() {
  const { toasts, dismissToast } = useToast();

  return (
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]">
      {toasts.map((toast: ToastMessage) => {
        const config = variantConfig[toast.variant];
        const Icon = config.icon;
        return (
          <div
            key={toast.id}
            className={`flex items-start gap-3 rounded-lg border ${config.border} bg-white p-3 shadow-lg dark:bg-neutral-900 animate-slide-in`}
            role="alert"
          >
            <Icon className={`h-5 w-5 shrink-0 ${config.color}`} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{toast.title}</p>
              {toast.description && (
                <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">{toast.description}</p>
              )}
            </div>
            <button
              onClick={() => dismissToast(toast.id)}
              className="rounded p-0.5 text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
              aria-label="Dismiss notification"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
