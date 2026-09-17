/**
 * Report processing state machine for the UI.
 *
 * The browser owns the "Upload" stage (XHR progress); every later stage comes from the
 * backend (`GET /api/v1/reports/{id}/extraction` → `stages`). Later stages are never shown
 * as completed after an earlier failure, and "ready" is only reported when the server says so.
 *
 * Kept free of path aliases so it runs under `node --test` without a bundler.
 */

export type StageState = 'pending' | 'active' | 'completed' | 'skipped' | 'failed' | 'not_reached';

export interface ProcessingStage {
  key: string;
  label: string;
  state: StageState;
  detail: string | null;
}

export type UploadPhase = 'idle' | 'uploading' | 'upload_failed' | 'server';
export type PipelineOutcome = 'in_progress' | 'ready' | 'failed';

export const STAGE_TEMPLATE: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'upload', label: 'Upload' },
  { key: 'text_extraction', label: 'Extract text' },
  { key: 'ocr', label: 'OCR fallback' },
  { key: 'structured_extraction', label: 'Extract structured data' },
  { key: 'save', label: 'Save report' },
];

const ACTIVE_LABELS: Record<string, string> = {
  upload: 'Uploading',
  text_extraction: 'Extracting text',
  ocr: 'Running OCR fallback',
  structured_extraction: 'Extracting structured data',
  save: 'Saving report',
};

const SYMBOLS: Record<StageState, string> = {
  pending: '○',
  active: '●',
  completed: '✓',
  skipped: '—',
  failed: '✕',
  not_reached: '○',
};

function template(state: (key: string, index: number) => StageState, detail: (key: string) => string | null = () => null) {
  return STAGE_TEMPLATE.map((s, i) => ({ key: s.key, label: s.label, state: state(s.key, i), detail: detail(s.key) }));
}

/** Stages to display for the current upload phase. */
export function uploadStages(
  phase: UploadPhase,
  opts: { progress?: number; serverStages?: ProcessingStage[] | null; uploadError?: string | null } = {},
): ProcessingStage[] {
  switch (phase) {
    case 'idle':
      return template(() => 'pending');
    case 'uploading':
      return template((_, i) => (i === 0 ? 'active' : 'pending'),
        (k) => (k === 'upload' ? `${Math.round((opts.progress ?? 0) * 100)}%` : null));
    case 'upload_failed':
      return template((_, i) => (i === 0 ? 'failed' : 'not_reached'),
        (k) => (k === 'upload' ? opts.uploadError ?? 'Upload failed' : null));
    case 'server':
      if (opts.serverStages && opts.serverStages.length) return opts.serverStages;
      // Upload accepted; the server has not reported progress yet.
      return template((_, i) => (i === 0 ? 'completed' : i === 1 ? 'active' : 'pending'));
  }
}

export function pipelineOutcome(stages: ProcessingStage[]): PipelineOutcome {
  if (stages.some((s) => s.state === 'failed')) return 'failed';
  if (stages.length > 0 && stages.every((s) => s.state === 'completed' || s.state === 'skipped')) return 'ready';
  return 'in_progress';
}

/** One display line per stage, e.g. "✓ Extract text", "● Extracting text", "— OCR fallback not required". */
export function stageLine(stage: ProcessingStage): { symbol: string; text: string } {
  const symbol = SYMBOLS[stage.state];
  if (stage.state === 'active') return { symbol, text: ACTIVE_LABELS[stage.key] ?? stage.label };
  if (stage.state === 'skipped') return { symbol, text: `${stage.label} not required` };
  if (stage.state === 'not_reached') return { symbol, text: `${stage.label} (not reached)` };
  return { symbol, text: stage.label };
}

/** Human-readable reason for a failed pipeline (never a raw server error). */
export function failureMessage(stages: ProcessingStage[]): string | null {
  const failed = stages.find((s) => s.state === 'failed');
  if (!failed) return null;
  return failed.detail || `${failed.label} failed. You can retry processing.`;
}

export type TextAiState = 'connected' | 'configured' | 'not_running' | 'model_missing' | 'not_configured';

/**
 * AI summaries are optional and never part of report processing. This describes the summary
 * option separately so an unavailable text AI never looks like a processing failure.
 */
export function aiSummaryAvailability(state: TextAiState | null | undefined): { available: boolean | null; message: string } {
  if (state === undefined) return { available: null, message: 'Checking AI summary availability…' };
  if (state === 'connected' || state === 'configured') {
    return { available: true, message: 'AI summary: optional, available after you confirm the values.' };
  }
  const reason = state === 'model_missing' ? 'the text AI model is not installed'
    : state === 'not_configured' ? 'text AI is not configured'
    : state === 'not_running' ? 'the text AI service is not running'
    : 'text AI status is unknown';
  return {
    available: false,
    message: `AI summary unavailable (${reason}). Report processing and your confirmed values are not affected.`,
  };
}
