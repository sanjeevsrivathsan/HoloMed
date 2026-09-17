import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, ChevronRight, Download, FileSearch, FileText, Info, ListChecks, Settings2, Sparkles, Upload,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { ResizablePanels } from '@/components/ResizablePanels';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { Tabs } from '@/components/Tabs';
import { FilterBar, SelectFilter } from '@/components/FilterBar';
import { EmptyState, ErrorState, LoadingState } from '@/components/States';
import { UploadReportDialog } from '@/components/reports/UploadReportDialog';
import { ReviewPanel } from '@/components/reports/ReviewPanel';
import { ReportSummaryPanel } from '@/components/reports/ReportSummaryPanel';
import { ProcessingStagesList } from '@/components/reports/ProcessingStagesList';
import { failureMessage, uploadStages } from '@/lib/processingStages';
import {
  DEMO_SOURCE, dateSourceLabels, errorMessage, extractionMethodLabels, flagLabels, flagVariant, formatBytes, formatDay,
  isProcessing, reportStatusShort, reportStatusText, reportVariant, reportsApi, reviewStatusLabels,
  type ReportCapabilities, type ReportExtraction,
} from '@/lib/reports';
import type { MedicalMeasurement, Report } from '@/lib/types';

interface ReportsProps {
  reports: Report[];
  measurements: MedicalMeasurement[];
  selectedReportId: string | null;
  onSelectReport: (id: string) => void;
  /** Re-fetch reports + measurements from the backend. */
  onRefresh: () => Promise<void>;
  onNavigateClinical: (reportId: string) => void;
  onNavigateTimeline: () => void;
}

const typeLabels: Record<string, string> = {
  'Blood Test': 'Blood Test / Laboratory Report',
  'Imaging Report': 'Radiology Report',
};
const typeLabel = (t: string) => typeLabels[t] ?? t;

const reportTypes = ['All', 'Blood Test', 'Imaging Report', 'Discharge Summary', 'Clinical Note', 'Prescription', 'Other'];
const statusOptions = [
  { value: 'All', label: 'All' },
  { value: 'processing', label: 'Processing' },
  { value: 'needs_review', label: 'Needs review' },
  { value: 'partially_confirmed', label: 'Partially confirmed' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'failed', label: 'Processing failed' },
];
const statusKeyOf = (r: Report) =>
  r.processingStatus === 'processing' ? 'processing' : r.processingStatus === 'failed' ? 'failed' : r.reviewStatus ?? 'confirmed';

const formatDate = (d: string) => {
  const date = new Date(d.length === 10 ? `${d}T00:00:00` : d);
  return Number.isNaN(date.getTime()) ? d : date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

export function Reports({
  reports, measurements, selectedReportId, onSelectReport, onRefresh, onNavigateClinical, onNavigateTimeline,
}: ReportsProps) {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<ReportCapabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('values');
  const [extraction, setExtraction] = useState<ReportExtraction | null>(null);
  const [extractionError, setExtractionError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    reportsApi.capabilities()
      .then(setCapabilities)
      .catch((err) => setCapabilitiesError(errorMessage(err, 'Upload settings could not be loaded. Refresh the page to try again.')));
  }, []);

  const filteredReports = useMemo(() => reports.filter((r) => {
    const q = search.toLowerCase();
    if (q && !r.title.toLowerCase().includes(q) && !r.source.toLowerCase().includes(q)
      && !(r.laboratory ?? '').toLowerCase().includes(q)) return false;
    if (typeFilter !== 'All' && r.type !== typeFilter) return false;
    if (statusFilter !== 'All' && statusKeyOf(r) !== statusFilter) return false;
    return true;
  }), [reports, search, typeFilter, statusFilter]);

  const report = reports.find((r) => r.id === selectedReportId) || null;
  const reportMeasurements = useMemo(
    () => (report ? measurements.filter((m) => m.reportId === report.id) : []),
    [measurements, report],
  );

  // Load extracted content whenever the selected report or its status changes.
  const statusKey = report ? `${report.id}:${report.status}` : '';
  const loadExtraction = useCallback(async (id: string) => {
    try {
      setExtraction(await reportsApi.extraction(id));
      setExtractionError(null);
    } catch (err) {
      setExtraction(null);
      setExtractionError(errorMessage(err, 'Extracted content could not be loaded.'));
    }
  }, []);
  useEffect(() => {
    setExtraction((prev) => (prev && String(prev.report_id) === report?.id ? prev : null));
    setExtractionError(null);
    if (!report || report.status === 'ready') return;
    void loadExtraction(report.id);
    if (!isProcessing(report.status)) return;
    // While processing, follow the server-reported stages.
    const timer = window.setInterval(() => { void loadExtraction(report.id); }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusKey, loadExtraction]);

  useEffect(() => {
    if (report) setActiveTab(report.status === 'failed' ? 'details' : 'values');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id]);

  const retry = async () => {
    if (!report) return;
    setRetrying(true);
    try {
      await reportsApi.retry(report.id);
    } catch (err) {
      setExtractionError(errorMessage(err, 'Retry failed. Please try again.'));
    } finally {
      await onRefresh();
      setRetrying(false);
    }
  };

  const isImage = report?.mimeType?.startsWith('image/');
  const currentExtraction = extraction && String(extraction.report_id) === report?.id ? extraction : null;
  const liveStages = currentExtraction?.stages?.length ? currentExtraction.stages : uploadStages('server');
  const failure = currentExtraction?.status === 'failed' ? failureMessage(currentExtraction.stages) : null;
  const failedTextAvailable = report?.status === 'failed' && !!currentExtraction?.text;

  return (
    <>
    <ResizablePanels id="reports" className="lg:h-[calc(100vh-5rem)]" breakpoint={1024} panels={[
      { label: 'report list', min: 240, size: 26, max: 45 },
      { label: 'report detail', min: 380, size: 42 },
      { label: 'AI summary', min: 260, size: 32, max: 50 },
    ]}>
      {/* Left: report list */}
      <div className="h-full lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Reports" subtitle={`${reports.length} total`} icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="space-y-2 border-b border-neutral-200 px-4 pb-3 dark:border-neutral-800" data-testid="reports-toolbar">
            <FilterBar layout="stacked" searchValue={search} onSearchChange={setSearch} searchPlaceholder="Search reports…">
              <SelectFilter block label="Type" value={typeFilter} options={reportTypes.map((t) => ({ value: t, label: t === 'All' ? 'All' : typeLabel(t) }))} onChange={setTypeFilter} />
              <SelectFilter block label="Status" value={statusFilter} options={statusOptions} onChange={setStatusFilter} />
            </FilterBar>
            <Button className="w-full" onClick={() => setUploadOpen(true)} data-testid="open-upload">
              <Upload className="h-4 w-4" />
              Upload Report
            </Button>
          </div>
          <div className="flex-1 divide-y divide-neutral-100 dark:divide-neutral-800 lg:overflow-y-auto" data-testid="report-list">
            {filteredReports.length === 0 ? (
              <EmptyState
                title={reports.length === 0 ? 'No reports yet' : 'No reports found'}
                description={reports.length === 0
                  ? 'Upload a blood test or other medical report to get started. Synthetic demo data can be loaded from Settings.'
                  : 'Try adjusting your filters.'}
                icon={<FileSearch className="h-6 w-6" />}
              />
            ) : (
              filteredReports.map((r) => (
                <button
                  key={r.id}
                  onClick={() => onSelectReport(r.id)}
                  data-testid="report-list-item"
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedReportId === r.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{r.title}</p>
                    <ChevronRight className="h-4 w-4 shrink-0 text-neutral-300 dark:text-neutral-600" />
                  </div>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{typeLabel(r.type)}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-neutral-400">{formatDate(r.date)}</span>
                    <StatusBadge variant={reportVariant(r)} pulse={r.processingStatus === 'processing'}>{reportStatusShort(r)}</StatusBadge>
                    {r.processingStatus === 'processed' && r.dateConfirmed === false && <StatusBadge variant="neutral">Date unconfirmed</StatusBadge>}
                    {r.source === DEMO_SOURCE && <StatusBadge variant="neutral">Synthetic demo</StatusBadge>}
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Center: report detail */}
      <div className="h-full lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          {!report ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState title="Select a report" description="Choose a report to review its extracted values, text and AI summary." icon={<FileText className="h-6 w-6" />} />
            </div>
          ) : (
            <>
              <CardHeader
                title={report.title}
                subtitle={`${typeLabel(report.type)} · ${formatDate(report.date)}${report.dateConfirmed === false ? ' (date not confirmed)' : ''}`}
                action={
                  <div className="flex items-center gap-1">
                    <StatusBadge variant={reportVariant(report)} pulse={report.processingStatus === 'processing'}>
                      <span data-testid="report-status">{reportStatusText(report)}</span>
                    </StatusBadge>
                    <Button variant="ghost" size="sm" onClick={() => onNavigateClinical(report.id)}>
                      <Settings2 className="h-3.5 w-3.5" /> Clinical View
                    </Button>
                  </div>
                }
              />
              {report.source === DEMO_SOURCE && (
                <p className="mx-4 mb-2 rounded-lg bg-neutral-100 px-3 py-1.5 text-xs font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                  DEMONSTRATION DATA — synthetic document, not a real patient record.
                </p>
              )}
              <Tabs
                tabs={[
                  { key: 'values', label: report.reviewStatus && report.reviewStatus !== 'confirmed' ? 'Review values' : 'Values', icon: <ListChecks className="h-3.5 w-3.5" /> },
                  { key: 'text', label: 'Extracted Text', icon: <FileSearch className="h-3.5 w-3.5" /> },
                  { key: 'original', label: 'Original', icon: <FileText className="h-3.5 w-3.5" /> },
                  { key: 'details', label: 'Details', icon: <Info className="h-3.5 w-3.5" /> },
                ]}
                activeKey={activeTab}
                onChange={setActiveTab}
                className="px-4"
              />
              <div className="flex-1 overflow-y-auto p-4">
                {isProcessing(report.status) && activeTab !== 'original' && activeTab !== 'details' ? (
                  <div className="space-y-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800" data-testid="report-processing">
                    <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">Processing this document…</p>
                    <ProcessingStagesList stages={liveStages} />
                  </div>
                ) : report.status === 'failed' && activeTab !== 'original' && !(activeTab === 'text' && failedTextAvailable) ? (
                  <div className="space-y-3 rounded-lg border border-red-200 p-4 dark:border-red-700/40" data-testid="report-failed" role="alert">
                    <p className="text-sm font-semibold text-error-700 dark:text-red-400">Processing failed</p>
                    {currentExtraction && <ProcessingStagesList stages={currentExtraction.stages} />}
                    <p className="text-xs text-error-600">{failure ?? extractionError ?? 'The document could not be processed. You can retry processing.'}</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button size="sm" onClick={retry} disabled={retrying} data-testid="report-retry">
                        {retrying ? 'Retrying…' : 'Retry processing'}
                      </Button>
                      {failedTextAvailable && (
                        <Button size="sm" variant="ghost" onClick={() => setActiveTab('text')}>View extracted text</Button>
                      )}
                    </div>
                    <p className="text-xs text-neutral-400">The original file is kept unchanged and can still be opened.</p>
                  </div>
                ) : (
                  <>
                    {activeTab === 'values' && (
                      currentExtraction ? (
                        <div className="space-y-4">
                          <ConfirmedValues measurements={reportMeasurements} onOpenTimeline={onNavigateTimeline} legacy={false} />
                          <ReviewPanel
                            report={report}
                            extraction={currentExtraction}
                            onExtractionChange={setExtraction}
                            onChanged={onRefresh}
                          />
                        </div>
                      ) : report.status === 'ready' || extractionError?.includes('not been processed') ? (
                        <ConfirmedValues measurements={reportMeasurements} onOpenTimeline={onNavigateTimeline} legacy />
                      ) : extractionError ? (
                        <ErrorState message={extractionError} onRetry={() => loadExtraction(report.id)} />
                      ) : <LoadingState message="Loading extracted values…" />
                    )}
                    {activeTab === 'text' && (
                      extraction ? (
                        <div className="space-y-2" data-testid="extracted-text">
                          <p className="text-xs text-neutral-500">
                            {extractionMethodLabels[extraction.method]} · {extraction.page_count} page(s) · {extraction.char_count.toLocaleString()} characters
                            {' · '}{extraction.method === 'pdf_text' ? 'OCR not required' : 'OCR used'}
                            {extraction.quality === 'low' && ' · lower reliability — check against the original'}
                          </p>
                          <pre className="whitespace-pre-wrap rounded-lg bg-neutral-50 p-4 font-mono text-xs text-neutral-700 dark:bg-neutral-800/50 dark:text-neutral-300">{extraction.text}</pre>
                          <p className="text-xs text-neutral-400">Derived text. The original document is stored separately and never modified.</p>
                        </div>
                      ) : report.status === 'ready' ? (
                        <EmptyState title="No extracted text" description="This report was added before text extraction was available." />
                      ) : extractionError ? (
                        <ErrorState message={extractionError} onRetry={() => loadExtraction(report.id)} />
                      ) : <LoadingState message="Loading extracted text…" />
                    )}
                    {activeTab === 'details' && (
                      <ReportDetails report={report} extraction={extraction} measurementCount={reportMeasurements.length} />
                    )}
                  </>
                )}
                {activeTab === 'original' && (
                  <div className="flex h-full min-h-[500px] flex-col gap-2">
                    <div className="flex justify-end">
                      <a href={`/api/v1/reports/${report.id}/download`} target="_blank" rel="noopener noreferrer"
                        className="btn btn-secondary px-3 py-1.5 text-xs">
                        <Download className="h-3.5 w-3.5" /> Open original
                      </a>
                    </div>
                    {isImage ? (
                      <img src={`/api/v1/reports/${report.id}/download`} alt={`Original document: ${report.title}`}
                        className="max-h-[70vh] w-full rounded-lg border border-neutral-200 object-contain dark:border-neutral-700" />
                    ) : (
                      <iframe src={`/api/v1/reports/${report.id}/download`} title={report.title}
                        className="h-full min-h-[480px] w-full flex-1 rounded-lg border border-neutral-200 dark:border-neutral-700" />
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Right: AI summary */}
      <div className="h-full lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="AI Summary" icon={<Sparkles className="h-4.5 w-4.5" />} />
          <div className="flex-1 overflow-y-auto p-4">
            <ReportSummaryPanel report={report} onGenerated={onRefresh} />
          </div>
        </Card>
      </div>
    </ResizablePanels>

      <UploadReportDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        capabilities={capabilities}
        capabilitiesError={capabilitiesError}
        onUploaded={async (id) => { onSelectReport(id); await onRefresh(); }}
        onReviewReport={(id) => { onSelectReport(id); setActiveTab('values'); }}
      />
    </>
  );
}

function ConfirmedValues({ measurements, onOpenTimeline, legacy }: {
  measurements: MedicalMeasurement[];
  onOpenTimeline: () => void;
  legacy: boolean;
}) {
  if (measurements.length === 0) {
    if (!legacy) {
      return (
        <p className="rounded-lg border border-dashed border-neutral-300 px-3 py-2 text-xs text-neutral-500 dark:border-neutral-700" data-testid="no-confirmed-values">
          No confirmed values yet. Review the detected measurements below — only values you confirm are saved.
        </p>
      );
    }
    return (
      <EmptyState
        title="No confirmed values"
        description="This report was added before value extraction was available."
        icon={<ListChecks className="h-6 w-6" />}
      />
    );
  }
  return (
    <div className="space-y-3" data-testid="confirmed-values">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">Confirmed values <span className="font-normal text-neutral-500">· {measurements.length} saved to your health record</span></p>
        <Button variant="ghost" size="sm" onClick={onOpenTimeline}><Activity className="h-3.5 w-3.5" /> View in timeline</Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500 dark:border-neutral-800">
              <th className="px-2 py-2 font-medium">Test</th>
              <th className="px-2 py-2 text-right font-medium">Value</th>
              <th className="px-2 py-2 font-medium">Printed range</th>
              <th className="px-2 py-2 font-medium">Printed flag</th>
              <th className="px-2 py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {measurements.map((m) => (
              <tr key={m.id} className="border-b border-neutral-100 dark:border-neutral-800/50">
                <td className="px-2 py-2 text-xs font-medium text-neutral-900 dark:text-neutral-100">
                  {m.testName}
                  <span className="ml-1.5"><StatusBadge variant="success">Confirmed</StatusBadge></span>
                </td>
                <td className="px-2 py-2 text-right text-xs font-semibold text-neutral-900 dark:text-neutral-100">{m.value} {m.unit}</td>
                <td className="whitespace-nowrap px-2 py-2 text-xs text-neutral-500">{m.referenceRange || 'Not printed'}</td>
                <td className="whitespace-nowrap px-2 py-2"><StatusBadge variant={flagVariant(m.flag)}>{flagLabels[m.flag] ?? m.flag}</StatusBadge></td>
                <td className="px-2 py-2 text-xs text-neutral-400">{m.sourceLocation || '—'}{m.comments ? ` · ${m.comments}` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ReportDetails({ report, extraction, measurementCount }: {
  report: Report;
  extraction: ReportExtraction | null;
  measurementCount: number;
}) {
  const processing = report.processingStatus === 'processing' ? 'Processing'
    : report.processingStatus === 'failed' ? 'Processing failed' : 'Processed';
  const rows: [string, string][] = [
    ['Type', typeLabel(report.type)],
    ['Title', report.title],
    ['Report date', `${formatDay(report.date)}${report.dateConfirmed ? ' (confirmed)' : ' (not confirmed)'}`],
    ['Date provenance', report.dateSource ? dateSourceLabels[report.dateSource] ?? report.dateSource : 'Recorded before date confirmation existed'],
    ['Detected date', report.detectedDate ? formatDay(report.detectedDate) : '—'],
    ['Processing status', processing],
    ['Review status', report.reviewStatus ? reviewStatusLabels[report.reviewStatus] : '—'],
    ['Source', report.source],
    ['Laboratory', report.laboratory || '—'],
    ['Hospital', report.hospital || '—'],
    ['Original file', report.originalFilename || '—'],
    ['Format', report.mimeType === 'application/pdf' ? 'PDF' : report.mimeType?.startsWith('image/') ? 'Image' : report.mimeType || '—'],
    ['Size', report.fileSize ? formatBytes(report.fileSize) : '—'],
    ['Uploaded', report.uploadedAt ? new Date(report.uploadedAt).toLocaleString() : '—'],
    ['Extraction', extraction ? `${extractionMethodLabels[extraction.method]} (${extraction.status})` : '—'],
    ['OCR', extraction ? (extraction.method === 'pdf_text' ? 'Not required' : extraction.method === 'none' ? '—' : 'Used') : '—'],
    ['Detected values', String(report.candidateCount ?? 0)],
    ['Confirmed values', String(measurementCount)],
    ['Awaiting review', String(report.pendingCount ?? 0)],
    ['Ignored values', String(report.ignoredCount ?? 0)],
    ['Source document', `Report #${report.id} — original stored unchanged`],
  ];
  return (
    <table className="w-full text-sm" data-testid="report-details">
      <tbody>
        {rows.map(([field, value]) => (
          <tr key={field} className="border-b border-neutral-100 dark:border-neutral-800/50">
            <td className="w-40 px-3 py-2 text-xs font-medium text-neutral-500">{field}</td>
            <td className="px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300">{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
