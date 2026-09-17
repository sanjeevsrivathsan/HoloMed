import { useEffect, useState } from 'react';
import { FileSearch, Loader2, Sparkles } from 'lucide-react';
import { Button } from '@/components/Button';
import { EmptyState } from '@/components/States';
import { SafetyNotice } from '@/components/SafetyNotice';
import { summaryModeLabels } from '@/lib/demo-data';
import { AI_SAFETY_MESSAGE, errorMessage, isProcessing, reportsApi } from '@/lib/reports';
import { aiSummaryAvailability, type TextAiState } from '@/lib/processingStages';
import { ApiError } from '@/lib/api';
import type { Report, SummaryMode } from '@/lib/types';

const MODES: SummaryMode[] = ['quick', 'standard', 'detailed', 'clinical', 'custom'];
const SECTION_CHOICES = [
  { key: 'overview', label: 'Report overview' },
  { key: 'executive', label: 'Summary' },
  { key: 'findings', label: 'Confirmed results' },
  { key: 'abnormal', label: 'Results flagged in the report' },
  { key: 'normal', label: 'Results marked normal' },
  { key: 'terms', label: 'What these tests measure' },
  { key: 'trends', label: 'Changes since earlier results' },
  { key: 'questions', label: 'Questions for your clinician' },
  { key: 'extraction', label: 'Extraction notes' },
  { key: 'limitations', label: 'Data limitations' },
  { key: 'provenance', label: 'Source and provenance' },
];
const MODE_HELP: Record<SummaryMode, string> = {
  quick: 'Short overview, confirmed results and laboratory flags.',
  standard: 'Overview, results, flags, test explanations, changes over time and questions.',
  detailed: 'Everything in Standard plus page references, values marked normal and extraction notes.',
  clinical: 'Concise structured summary with dates, flags, changes and provenance. No language model is used.',
  custom: 'All sections; choose which to show.',
};
/** Sections written by the language model; the others are copied from confirmed report data. */
const AI_SECTIONS = new Set(['executive', 'terms', 'questions']);

interface ReportSummaryPanelProps {
  report: Report | null;
  onGenerated: () => Promise<void> | void;
}

export function ReportSummaryPanel({ report, onGenerated }: ReportSummaryPanelProps) {
  const [mode, setMode] = useState<SummaryMode>('standard');
  const [custom, setCustom] = useState<string[]>(SECTION_CHOICES.map((s) => s.key));
  const [generatingFor, setGeneratingFor] = useState<string | null>(null);
  const [error, setError] = useState<{ reportId: string; text: string } | null>(null);
  const [textAi, setTextAi] = useState<TextAiState | null | undefined>(undefined);

  useEffect(() => {
    let stale = false;   // ignore a slow response for a previously selected report
    reportsApi.textAiStatus()
      .then((s) => { if (!stale) setTextAi(s.status); })
      .catch(() => { if (!stale) setTextAi(null); });
    return () => { stale = true; };
  }, [report?.id]);

  if (!report) {
    return <EmptyState title="No report selected" description="Select a report to view its AI summary." icon={<Sparkles className="h-6 w-6" />} />;
  }

  const generating = generatingFor === report.id;
  const processed = report.processingStatus ? report.processingStatus === 'processed'
    : !isProcessing(report.status) && report.status !== 'failed';
  const confirmed = report.measurementCount ?? 0;
  const detected = report.candidateCount ?? 0;
  const ready = processed && (confirmed > 0 || detected === 0);

  const generate = async () => {
    setGeneratingFor(report.id);
    setError(null);
    try {
      await reportsApi.summarize(report.id, mode);
      await onGenerated();
    } catch (err) {
      const unavailable = err instanceof ApiError && err.status === 503;
      if (unavailable) setTextAi('not_running');
      setError({
        reportId: report.id,
        text: unavailable
          ? 'AI summary unavailable: the text AI service is not running. The report is processed and your confirmed values are saved.'
          : errorMessage(err, 'The summary could not be generated. Please try again.'),
      });
    } finally {
      setGeneratingFor(null);
    }
  };

  const summary = report.summary;
  const ai = textAi === undefined ? null : aiSummaryAvailability(textAi);
  const visibleKeys = mode === 'custom' ? custom : null;
  const sections = (summary?.sections ?? []).filter((s) => s.visible && (!visibleKeys || visibleKeys.includes(s.key)));

  return (
    <div className="space-y-4" data-testid="summary-panel">
      <SafetyNotice message={summary?.safetyMessage ?? AI_SAFETY_MESSAGE} />

      {!ready ? (
        <EmptyState
          title="Summary not available yet"
          description={report.status === 'failed'
            ? 'This document could not be processed, so there is nothing to summarise.'
            : processed
              ? `${detected} value(s) were detected but none is confirmed yet. Confirm values in the Values tab — summaries only use information you have confirmed.`
              : 'The document is still being processed.'}
          icon={<FileSearch className="h-6 w-6" />}
        />
      ) : (
        <>
          <div className="rounded-lg bg-success-50 px-3 py-2 text-xs text-success-700 dark:bg-success-700/10 dark:text-green-400" data-testid="report-processed">
            Report processed{report.measurementCount ? ` · ${report.measurementCount} confirmed value(s) saved` : ''}
          </div>
          {ai && ai.available === false && (
            <p className="rounded-lg border border-amber-200 bg-warning-50 px-3 py-2 text-xs text-amber-800 dark:border-warning-700/30 dark:bg-warning-700/10 dark:text-amber-300" data-testid="summary-unavailable">
              {ai.message}
            </p>
          )}
          <div>
            <p className="mb-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-400">Summary mode</p>
            <div className="flex flex-wrap gap-1.5">
              {MODES.map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  aria-pressed={mode === m}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    mode === m
                      ? 'bg-teal-600 text-white'
                      : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                  }`}
                >
                  {summaryModeLabels[m]}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-neutral-500" data-testid="summary-mode-help">{MODE_HELP[mode]}</p>
            {mode === 'custom' && (
              <div className="mt-2 space-y-1.5 rounded-lg border border-neutral-200 p-2 dark:border-neutral-700">
                {SECTION_CHOICES.map((s) => (
                  <label key={s.key} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={custom.includes(s.key)}
                      onChange={(e) => setCustom(e.target.checked ? [...custom, s.key] : custom.filter((k) => k !== s.key))}
                      className="rounded border-neutral-300 text-teal-600 focus:ring-teal-500"
                    />
                    <span className="text-neutral-600 dark:text-neutral-400">{s.label}</span>
                  </label>
                ))}
              </div>
            )}
            <div className="mt-3 flex items-center justify-end gap-2">
              {generating && <span className="text-xs text-neutral-400" role="status">Generating summary… this can take up to a minute with a local model.</span>}
              <Button onClick={generate} disabled={generating} size="sm" variant={summary ? 'outline' : 'primary'} data-testid="summary-generate">
                {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {generating ? 'Generating…' : summary ? 'Regenerate summary' : 'Generate AI summary'}
              </Button>
            </div>
            {error?.reportId === report.id && <p className="mt-2 text-xs text-error-600" role="alert" data-testid="summary-error">{error.text}</p>}
          </div>

          {!summary ? (
            <p className="text-center text-sm text-neutral-500 dark:text-neutral-400">This report has not been summarised yet.</p>
          ) : (
            <div className="space-y-3" data-testid="summary-sections">
              <p className="text-xs text-neutral-400">
                {summaryModeLabels[summary.mode]} summary · {new Date(summary.createdAt).toLocaleString()} · AI text is marked; result lists are copied from your confirmed data
              </p>
              {sections.map((section) => (
                <div key={section.key} className="rounded-lg border border-teal-200 bg-teal-50/40 p-3 dark:border-teal-800/50 dark:bg-teal-950/10">
                  <p className="mb-1.5 flex items-center justify-between gap-2 text-xs font-semibold text-teal-700 dark:text-teal-400">
                    {section.label}
                    <span className="font-normal text-neutral-400">{(section.source ? section.source === 'ai' : AI_SECTIONS.has(section.key)) ? 'AI-generated' : 'From confirmed report data'}</span>
                  </p>
                  <p className="whitespace-pre-line text-sm leading-relaxed text-neutral-700 dark:text-neutral-300">{section.content}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
