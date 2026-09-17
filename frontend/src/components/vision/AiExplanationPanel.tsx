/**
 * Language-model explanation of the selected model output.
 *
 * Visually subordinate to the vision result and clearly labelled as generated
 * text. The explanation is produced server-side from the structured model
 * output only; the language model never sees the image.
 */

import type { ReactNode } from 'react';
import { AlertTriangle, BookOpen, Loader2, MessageSquareText, RefreshCw } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import type { TextExplanationResponse } from '@/lib/vision';

export type ExplanationState =
  | { status: 'loading' }
  | { status: 'ready'; data: TextExplanationResponse }
  | { status: 'error'; message: string; retryable: boolean };

interface AiExplanationPanelProps {
  target: string;
  state: ExplanationState | undefined;
  onRetry: () => void;
}

function displayName(pathology: string): string {
  return pathology.replace(/_/g, ' ');
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">{title}</p>
      <div className="mt-0.5 text-xs leading-relaxed text-neutral-700 dark:text-neutral-300">{children}</div>
    </div>
  );
}

export function AiExplanationPanel({ target, state, onRetry }: AiExplanationPanelProps) {
  const data = state?.status === 'ready' && state.data.target_pathology === target ? state.data : null;

  return (
    <div data-testid="ai-explanation"><Card className="border-dashed">
      <CardHeader
        title="AI Explanation"
        subtitle={`Generated text about the ${displayName(target)} model output`}
        icon={<MessageSquareText className="h-4 w-4" />}
        action={<StatusBadge variant="info">Language model</StatusBadge>}
      />
      <div className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5" aria-live="polite">
        {(!state || state.status === 'loading') && (
          <div className="space-y-2" data-testid="ai-explanation-loading">
            <p className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-600" />
              Generating explanation for {displayName(target)}… The screening result above is already complete.
            </p>
            {[80, 95, 70].map((w) => (
              <div key={w} className="h-2.5 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" style={{ width: `${w}%` }} />
            ))}
          </div>
        )}

        {state?.status === 'error' && (
          <div className="flex gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-700 dark:bg-neutral-800/50" role="status" data-testid="ai-explanation-error">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0 flex-1 text-xs text-neutral-700 dark:text-neutral-300">
              <p>{state.message}</p>
              {state.retryable && (
                <Button size="sm" variant="outline" className="mt-2" onClick={onRetry}>
                  <RefreshCw className="h-3.5 w-3.5" /> Try again
                </Button>
              )}
            </div>
          </div>
        )}

        {data && (
          <div className="space-y-3" data-testid="ai-explanation-ready">
            <p className="text-sm leading-relaxed text-neutral-800 dark:text-neutral-200">{data.explanation.summary}</p>
            <Section title="What this finding means">{data.explanation.finding_explanation}</Section>
            <Section title="What the model score means">{data.explanation.score_explanation}</Section>
            <Section title="About the visual explanation">{data.explanation.gradcam_explanation}</Section>
            <Section title="Limitations">
              <ul className="list-disc space-y-0.5 pl-4">
                {data.explanation.limitations.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </Section>
            <Section title="Requires clinical review">{data.explanation.clinical_review}</Section>
            <div className="space-y-1 border-t border-neutral-100 pt-2 dark:border-neutral-800">
              <p className="text-[11px] font-medium text-amber-700 dark:text-amber-400">{data.safety.message}</p>
              <p className="flex items-start gap-1.5 text-[11px] text-neutral-500 dark:text-neutral-400">
                <BookOpen className="mt-px h-3 w-3 shrink-0" />
                <span>
                  Written by a language model ({data.text_model}) from the structured model output only — it did not
                  view the image. Checked by HoloMed safety rules before display.
                </span>
              </p>
            </div>
          </div>
        )}
      </div>
    </Card></div>
  );
}
