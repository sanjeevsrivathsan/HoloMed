import { useMemo } from 'react';
import { Stethoscope, TrendingUp, TrendingDown, Minus, Sparkles, FileText, ScanLine } from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { StatusBadge } from '@/components/StatusBadge';
import { SafetyNotice } from '@/components/SafetyNotice';
import { DemoDataBadge } from '@/components/DemoDataBadge';
import { EmptyState } from '@/components/States';
import type { Report, MedicalMeasurement, ImagingStudy } from '@/lib/types';

interface ClinicalViewProps {
  report: Report | null;
  measurements: MedicalMeasurement[];
  studies: ImagingStudy[];
  onOpenImaging: () => void;
}

export function ClinicalView({ report, measurements, studies, onOpenImaging }: ClinicalViewProps) {
  const reportMeasurements = useMemo(() => {
    if (!report) return [];
    return measurements.filter((m) => m.reportId === report.id);
  }, [measurements, report]);

  const previousMeasurements = useMemo(() => {
    if (!report) return [];
    const reportDate = report.date;
    return measurements.filter((m) =>
      m.reportDate < reportDate &&
      reportMeasurements.some((rm) => rm.testName === m.testName)
    );
  }, [measurements, report, reportMeasurements]);

  const getPreviousValue = (testName: string) => {
    const prev = previousMeasurements
      .filter((m) => m.testName === testName)
      .sort((a, b) => b.reportDate.localeCompare(a.reportDate))[0];
    return prev;
  };

  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const flagVariant = (flag: string) => {
    if (flag === 'normal') return 'success';
    if (flag === 'high' || flag === 'low' || flag === 'abnormal') return 'warning';
    return 'neutral';
  };

  const changeIcon = (current: number, previous: number | undefined) => {
    if (previous === undefined) return <Minus className="h-3.5 w-3.5 text-neutral-400" />;
    if (current > previous) return <TrendingUp className="h-3.5 w-3.5 text-warning-600" />;
    if (current < previous) return <TrendingDown className="h-3.5 w-3.5 text-success-600" />;
    return <Minus className="h-3.5 w-3.5 text-neutral-400" />;
  };

  if (!report) {
    return (
      <Card>
        <EmptyState title="No report selected" description="Open a report from the Reports workspace to view the clinical perspective." icon={<Stethoscope className="h-6 w-6" />} />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold text-neutral-900 dark:text-white">{report.title}</h2>
            <DemoDataBadge />
          </div>
          <p className="text-sm text-neutral-500 dark:text-neutral-400">{report.type} · {report.source} · {formatDate(report.date)}</p>
        </div>
      </div>

      {/* Structured Measurements Table */}
      <Card>
        <CardHeader title="Structured Measurements" subtitle="Current vs previous values with trends" icon={<Stethoscope className="h-4.5 w-4.5" />} />
        <div className="overflow-x-auto">
          {reportMeasurements.length === 0 ? (
            <EmptyState title="No measurements" description="This report has no structured measurement data." />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 dark:border-neutral-800">
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Test</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-neutral-500">Current</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-neutral-500">Previous</th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-neutral-500">Change</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Unit</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Ref Range</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Flag</th>
                </tr>
              </thead>
              <tbody>
                {reportMeasurements.map((m) => {
                  const prev = getPreviousValue(m.testName);
                  return (
                    <tr key={m.id} className="border-b border-neutral-100 dark:border-neutral-800/50">
                      <td className="px-3 py-2.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">{m.testName}</td>
                      <td className="px-3 py-2.5 text-right text-xs font-semibold text-neutral-900 dark:text-neutral-100">{m.value}</td>
                      <td className="px-3 py-2.5 text-right text-xs text-neutral-400">{prev?.value ?? '—'}</td>
                      <td className="px-3 py-2.5 text-center">{changeIcon(m.value, prev?.value)}</td>
                      <td className="px-3 py-2.5 text-xs text-neutral-400">{m.unit}</td>
                      <td className="px-3 py-2.5 text-xs text-neutral-400">{m.referenceRange || 'No source range'}</td>
                      <td className="px-3 py-2.5"><StatusBadge variant={flagVariant(m.flag)}>{m.flag}</StatusBadge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* AI Explanation — visually distinguished */}
      {report.summary && (
        <Card className="border-teal-300 dark:border-teal-700/50">
          <CardHeader
            title="AI Explanation"
            subtitle="AI-generated summary — visually distinct from source clinical data"
            icon={<Sparkles className="h-4.5 w-4.5" />}
            action={<DemoDataBadge />}
          />
          <div className="space-y-3 p-5">
            <div className="rounded-lg bg-teal-50/50 p-3 dark:bg-teal-950/10">
              <p className="mb-1 text-xs font-semibold text-teal-600 dark:text-teal-400">Executive Summary</p>
              <p className="text-sm text-neutral-700 dark:text-neutral-300">{report.summary.sections.find((s) => s.key === 'executive')?.content}</p>
            </div>
            <div className="rounded-lg bg-teal-50/50 p-3 dark:bg-teal-950/10">
              <p className="mb-1 text-xs font-semibold text-teal-600 dark:text-teal-400">Important Findings</p>
              <p className="text-sm text-neutral-700 dark:text-neutral-300">{report.summary.sections.find((s) => s.key === 'findings')?.content}</p>
            </div>
            <SafetyNotice variant="compact" />
          </div>
        </Card>
      )}

      {/* Source Data — visually distinguished */}
      <Card className="border-neutral-300 dark:border-neutral-700">
        <CardHeader title="Source Clinical Data" subtitle="Original report content — not AI-generated" icon={<FileText className="h-4.5 w-4.5" />} />
        <div className="space-y-3 p-5">
          <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <p className="mb-1 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Report Details</p>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
              <div><span className="text-neutral-400">Source:</span> <span className="text-neutral-700 dark:text-neutral-300">{report.source}</span></div>
              <div><span className="text-neutral-400">Hospital:</span> <span className="text-neutral-700 dark:text-neutral-300">{report.hospital || 'N/A'}</span></div>
              <div><span className="text-neutral-400">Laboratory:</span> <span className="text-neutral-700 dark:text-neutral-300">{report.laboratory || 'N/A'}</span></div>
              <div><span className="text-neutral-400">Department:</span> <span className="text-neutral-700 dark:text-neutral-300">{report.department || 'N/A'}</span></div>
              <div><span className="text-neutral-400">Doctor:</span> <span className="text-neutral-700 dark:text-neutral-300">{report.doctor || 'N/A'}</span></div>
              <div><span className="text-neutral-400">Date:</span> <span className="text-neutral-700 dark:text-neutral-300">{formatDate(report.date)}</span></div>
            </div>
          </div>
          <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <p className="mb-1 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Artifacts</p>
            <div className="flex flex-wrap gap-2">
              {report.artifacts.map((a) => (
                <StatusBadge key={a.id} variant="neutral">{a.type.replace(/_/g, ' ')}</StatusBadge>
              ))}
            </div>
          </div>
        </div>
      </Card>

      {/* Imaging Access */}
      <Card>
        <CardHeader title="Related Imaging" icon={<ScanLine className="h-4.5 w-4.5" />} />
        <div className="p-5">
          {studies.length === 0 ? (
            <p className="text-sm text-neutral-400">No imaging studies linked to this report.</p>
          ) : (
            <div className="space-y-2">
              {studies.map((study) => (
                <div key={study.id} className="flex items-center justify-between gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <div>
                    <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {formatDate(study.studyDate)}</p>
                  </div>
                  <button onClick={onOpenImaging} className="btn btn-secondary px-3 py-1.5 text-xs">Open Imaging</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
