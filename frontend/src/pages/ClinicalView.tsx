import { useMemo } from 'react';
import {
  ArrowDown, ArrowUp, ClipboardCheck, FileText, Fingerprint, Minus, ScanLine, Sparkles, Stethoscope,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { StatusBadge } from '@/components/StatusBadge';
import { SafetyNotice } from '@/components/SafetyNotice';
import { EmptyState } from '@/components/States';
import {
  AI_SAFETY_MESSAGE, DEMO_SOURCE, dateSourceLabels, flagLabels, flagVariant, formatDay,
  reportStatusText, reportVariant,
} from '@/lib/reports';
import type { Report, MedicalMeasurement, ImagingStudy } from '@/lib/types';

interface ClinicalViewProps {
  report: Report | null;
  measurements: MedicalMeasurement[];
  studies: ImagingStudy[];
  onOpenImaging: () => void;
  onOpenReport: (reportId: string) => void;
}

const typeLabel = (t: string) => ({ 'Blood Test': 'Blood Test / Laboratory Report', 'Imaging Report': 'Radiology Report' }[t] ?? t);

export function ClinicalView({ report, measurements, studies, onOpenImaging, onOpenReport }: ClinicalViewProps) {
  const reportMeasurements = useMemo(
    () => (report ? measurements.filter((m) => m.reportId === report.id) : []),
    [measurements, report],
  );

  /** Most recent earlier confirmed value of the same test (from other reports). */
  const previousOf = useMemo(() => {
    const map = new Map<string, MedicalMeasurement>();
    if (!report) return map;
    for (const m of reportMeasurements) {
      const earlier = measurements
        .filter((x) => x.reportId !== report.id && x.testName === m.testName && x.reportDate < m.reportDate)
        .sort((a, b) => b.reportDate.localeCompare(a.reportDate))[0];
      if (earlier) map.set(m.id, earlier);
    }
    return map;
  }, [measurements, report, reportMeasurements]);

  // Direction only; no colour judgement about whether a change is good or bad.
  const change = (current: MedicalMeasurement, prev?: MedicalMeasurement) => {
    if (!prev || prev.unit !== current.unit) return <span className="text-neutral-400">—</span>;
    const delta = Number((current.value - prev.value).toFixed(4));
    const Icon = delta > 0 ? ArrowUp : delta < 0 ? ArrowDown : Minus;
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap text-neutral-700 dark:text-neutral-300">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {delta > 0 ? '+' : ''}{delta} {current.unit}
        <span className="text-[10px] text-neutral-400">vs {prev.value} on {formatDay(prev.reportDate)}</span>
      </span>
    );
  };

  if (!report) {
    return (
      <Card>
        <EmptyState title="No report selected" description="Open a report from the Reports workspace to view the clinical perspective." icon={<Stethoscope className="h-6 w-6" />} />
      </Card>
    );
  }

  const summary = report.summary;
  const aiOverview = summary?.sections.find((s) => s.key === 'executive')?.content;
  const dataOverview = summary?.sections.find((s) => s.key === 'overview')?.content;
  const flagged = summary?.sections.find((s) => s.key === 'abnormal')?.content;
  const reviewDone = report.reviewStatus === 'confirmed';

  return (
    <div className="space-y-5" data-testid="clinical-view">
      {/* 1. Report header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-neutral-900 dark:text-white">{report.title}</h2>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">
            {typeLabel(report.type)} · {formatDay(report.date)}{report.dateConfirmed === false && ' (date not confirmed)'}
            {report.laboratory && ` · ${report.laboratory}`}
          </p>
          {report.source === DEMO_SOURCE && (
            <p className="mt-1 text-xs font-medium text-neutral-500">DEMONSTRATION DATA — synthetic document, not a real patient record.</p>
          )}
        </div>
        <button onClick={() => onOpenReport(report.id)} className="btn btn-secondary px-3 py-1.5 text-xs" data-testid="clinical-open-report">
          <FileText className="h-3.5 w-3.5" /> Open source report
        </button>
      </div>

      {/* 2. Status / confirmation state */}
      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3 text-xs" data-testid="clinical-status">
          <span className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-neutral-400" />
            <StatusBadge variant={reportVariant(report)}>{reportStatusText(report)}</StatusBadge>
          </span>
          <span className="text-neutral-500">
            Date: <strong className="text-neutral-700 dark:text-neutral-200">{report.dateConfirmed ? 'confirmed' : 'not confirmed'}</strong>
            {report.dateSource && ` · ${dateSourceLabels[report.dateSource] ?? report.dateSource}`}
          </span>
          <span className="text-neutral-500">
            {report.candidateCount ?? 0} detected · {reportMeasurements.length} confirmed · {report.pendingCount ?? 0} awaiting review
          </span>
          {!reviewDone && report.processingStatus === 'processed' && (
            <button onClick={() => onOpenReport(report.id)} className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
              Review in Reports →
            </button>
          )}
        </div>
      </Card>

      {/* 3. Structured measurements (user-confirmed source data) */}
      <Card>
        <CardHeader
          title="Structured Measurements"
          subtitle="Confirmed by the user · values, ranges and flags exactly as printed in the report"
          icon={<Stethoscope className="h-4.5 w-4.5" />}
        />
        {reportMeasurements.length === 0 ? (
          <div className="px-5 pb-5" data-testid="clinical-no-measurements">
            <div className="rounded-lg border border-dashed border-neutral-300 p-4 text-sm text-neutral-600 dark:border-neutral-700 dark:text-neutral-300">
              <p className="font-medium">No confirmed measurements yet.</p>
              <p className="mt-1 text-xs text-neutral-500">
                Review the extracted values in Reports and confirm them before they appear here.
              </p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto px-2 pb-3">
            <table className="w-full text-sm" data-testid="clinical-measurements">
              <thead>
                <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
                  <th className="px-3 py-2 font-medium">Test</th>
                  <th className="px-3 py-2 text-right font-medium">Value</th>
                  <th className="px-3 py-2 font-medium">Unit</th>
                  <th className="px-3 py-2 font-medium">Reference range</th>
                  <th className="px-3 py-2 font-medium">Report flag</th>
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Change since previous</th>
                </tr>
              </thead>
              <tbody>
                {reportMeasurements.map((m) => (
                  <tr key={m.id} className="border-b border-neutral-100 align-top dark:border-neutral-800/50" data-testid="clinical-measurement-row">
                    <td className="px-3 py-2 text-xs font-semibold text-neutral-800 dark:text-neutral-200">{m.testName}</td>
                    <td className="px-3 py-2 text-right text-xs font-semibold tabular-nums text-neutral-900 dark:text-neutral-100">{m.value}</td>
                    <td className="px-3 py-2 text-xs text-neutral-500">{m.unit || '—'}</td>
                    <td className="max-w-[14rem] px-3 py-2 text-xs text-neutral-500">{m.referenceRange || 'Not printed'}</td>
                    <td className="whitespace-nowrap px-3 py-2"><StatusBadge variant={flagVariant(m.flag)}>{flagLabels[m.flag] ?? m.flag}</StatusBadge></td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-neutral-500">{formatDay(m.reportDate)}</td>
                    <td className="px-3 py-2 text-xs text-neutral-500">
                      {report.originalFilename ?? report.title}{m.sourceLocation && <span className="block text-[10px]">{m.sourceLocation}</span>}
                    </td>
                    <td className="px-3 py-2 text-xs">{change(m, previousOf.get(m.id))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 4. AI explanation — visually distinct from source data */}
      <Card className="border-teal-300 dark:border-teal-700/50">
        <CardHeader
          title="AI Explanation"
          subtitle="AI-generated from confirmed data — advisory only, not source clinical data"
          icon={<Sparkles className="h-4.5 w-4.5" />}
        />
        <div className="space-y-3 px-5 pb-5">
          {!summary ? (
            <p className="text-sm text-neutral-500" data-testid="clinical-no-summary">
              No AI summary yet. Generate one from the Reports workspace once values are confirmed.
            </p>
          ) : (
            <>
              {(aiOverview || dataOverview) && (
                <div className="rounded-lg bg-teal-50/50 p-3 dark:bg-teal-950/10">
                  <p className="mb-1 text-xs font-semibold text-teal-600 dark:text-teal-400">{aiOverview ? 'Summary (AI-generated)' : 'Report overview (from confirmed data)'}</p>
                  <p className="whitespace-pre-line text-sm text-neutral-700 dark:text-neutral-300">{aiOverview ?? dataOverview}</p>
                </div>
              )}
              {flagged && (
                <div className="rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/40">
                  <p className="mb-1 text-xs font-semibold text-neutral-600 dark:text-neutral-300">Results flagged in the report (from confirmed data)</p>
                  <p className="whitespace-pre-line text-sm text-neutral-700 dark:text-neutral-300">{flagged}</p>
                </div>
              )}
            </>
          )}
          <SafetyNotice message={summary?.safetyMessage ?? AI_SAFETY_MESSAGE} />
        </div>
      </Card>

      {/* 5. Source clinical data */}
      <Card className="border-neutral-300 dark:border-neutral-700">
        <CardHeader title="Source Clinical Data" subtitle="Metadata of the original document — not AI-generated" icon={<FileText className="h-4.5 w-4.5" />} />
        <div className="grid grid-cols-2 gap-2 px-5 pb-5 text-xs sm:grid-cols-3">
          {[
            ['Source', report.source],
            ['Laboratory', report.laboratory || '—'],
            ['Hospital', report.hospital || '—'],
            ['Department', report.department || '—'],
            ['Doctor', report.doctor || '—'],
            ['Report date', formatDay(report.date)],
          ].map(([k, v]) => (
            <div key={k}><span className="text-neutral-400">{k}:</span> <span className="text-neutral-700 dark:text-neutral-300">{v}</span></div>
          ))}
        </div>
      </Card>

      {/* 6. Imaging */}
      <Card>
        <CardHeader title="Imaging Studies" subtitle="Studies in this workspace — not linked to this report" icon={<ScanLine className="h-4.5 w-4.5" />} />
        <div className="px-5 pb-5">
          {studies.length === 0 ? (
            <p className="text-sm text-neutral-400">No imaging studies in this workspace.</p>
          ) : (
            <div className="space-y-2">
              {studies.slice(0, 5).map((study) => (
                <div key={study.id} className="flex items-center justify-between gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <div>
                    <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {formatDay(study.studyDate)}</p>
                  </div>
                  <button onClick={onOpenImaging} className="btn btn-secondary px-3 py-1.5 text-xs">Open Imaging</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* 7. Provenance */}
      <Card>
        <CardHeader title="Provenance" subtitle="Where each kind of information comes from" icon={<Fingerprint className="h-4.5 w-4.5" />} />
        <ul className="space-y-1.5 px-5 pb-5 text-xs text-neutral-600 dark:text-neutral-300" data-testid="clinical-provenance">
          <li><strong>Source clinical data:</strong> {report.originalFilename ?? report.title} ({report.mimeType === 'application/pdf' ? 'PDF' : 'image'}) — original stored unchanged.</li>
          <li><strong>Extracted data:</strong> {report.extractionStatus === 'succeeded' ? 'text and value candidates derived from the original (see Reports → Extracted Text)' : 'not available'}.</li>
          <li><strong>User-confirmed data:</strong> {reportMeasurements.length} measurement(s) confirmed by the user; report date {report.dateConfirmed ? 'confirmed' : 'not confirmed'}.</li>
          <li><strong>AI-generated explanation:</strong> {summary ? `${summary.generator === 'structured-data' ? 'structured summary (no language model)' : 'language-model summary'} created ${new Date(summary.createdAt).toLocaleString()}` : 'none'} — advisory only.</li>
        </ul>
      </Card>
    </div>
  );
}
