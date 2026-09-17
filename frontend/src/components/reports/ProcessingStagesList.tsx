import { AlertTriangle, CheckCircle2, Circle, Loader2, MinusCircle } from 'lucide-react';
import { stageLine, type ProcessingStage } from '@/lib/processingStages';

const styles: Record<ProcessingStage['state'], { icon: typeof Circle; className: string }> = {
  pending: { icon: Circle, className: 'text-neutral-400' },
  not_reached: { icon: Circle, className: 'text-neutral-300 dark:text-neutral-600' },
  active: { icon: Loader2, className: 'text-teal-600 dark:text-teal-400' },
  completed: { icon: CheckCircle2, className: 'text-success-600' },
  skipped: { icon: MinusCircle, className: 'text-neutral-500' },
  failed: { icon: AlertTriangle, className: 'text-error-600' },
};

/** Report processing stages, one row each, with state conveyed by icon and text (not colour alone). */
export function ProcessingStagesList({ stages }: { stages: ProcessingStage[] }) {
  return (
    <ol className="space-y-1.5" data-testid="processing-stages" aria-live="polite">
      {stages.map((stage) => {
        const { icon: Icon, className } = styles[stage.state];
        const { text } = stageLine(stage);
        return (
          <li key={stage.key} className={`flex items-start gap-2 text-xs ${className}`}
            data-testid={`stage-${stage.key}`} data-state={stage.state}>
            <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${stage.state === 'active' ? 'animate-spin' : ''}`} aria-hidden />
            <span>
              <span className="font-medium">{text}</span>
              <span className="sr-only"> ({stage.state.replace('_', ' ')})</span>
              {stage.detail && stage.state !== 'failed' && <span className="text-neutral-400"> · {stage.detail}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
