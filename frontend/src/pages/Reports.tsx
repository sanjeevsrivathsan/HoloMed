import { useState, useMemo } from 'react';
import {
  FileText, Upload, Sparkles, ChevronRight, FileCheck, Loader2, AlertTriangle,
  FileSearch, ListChecks, CheckCircle2, Settings2, X,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { Tabs } from '@/components/Tabs';
import { Modal } from '@/components/Modal';
import { FilterBar, SelectFilter } from '@/components/FilterBar';
import { SafetyNotice } from '@/components/SafetyNotice';
import { EmptyState, LoadingState, ErrorState } from '@/components/States';
import { reportStatusLabels, summaryModeLabels } from '@/lib/demo-data';
import type { Report, ReportStatus, SummaryMode, ReportSummarySection } from '@/lib/types';

interface ReportsProps {
  reports: Report[];
  selectedReportId: string | null;
  onSelectReport: (id: string) => void;
  onUpload: (file: File, storage: string) => void;
  uploadStage: UploadStage | null;
  onNavigateClinical: (reportId: string) => void;
  onGenerateSummary: (reportId: string, mode: SummaryMode) => void;
  isGeneratingSummary?: boolean;
}

export type UploadStage = 'uploading' | 'extracting' | 'ocr' | 'structured' | 'ready' | 'failed';

const stageLabels: Record<UploadStage, string> = {
  uploading: 'Uploading...',
  extracting: 'Extracting text...',
  ocr: 'OCR fallback in progress...',
  structured: 'Extracting structured data...',
  ready: 'Ready',
  failed: 'Processing failed',
};

const stageIcons: Record<UploadStage, typeof Loader2> = {
  uploading: Loader2,
  extracting: Loader2,
  ocr: Loader2,
  structured: Loader2,
  ready: CheckCircle2,
  failed: AlertTriangle,
};

const summarySections: { key: string; label: string }[] = [
  { key: 'executive', label: 'Executive Summary' },
  { key: 'findings', label: 'Important Findings' },
  { key: 'abnormal', label: 'Reported Abnormal Values' },
  { key: 'normal', label: 'Normal Values' },
  { key: 'terms', label: 'Medical Terms' },
  { key: 'questions', label: 'Questions for Doctor' },
];

const reportTypes = ['All', 'Blood Test', 'Imaging Report', 'Pathology', 'Discharge Summary', 'Consultation', 'Operative Report', 'Other'];
const statusOptions = ['All', 'ready', 'processing', 'extracting', 'failed'];

export function Reports({ reports, selectedReportId, onSelectReport, onUpload, uploadStage, onNavigateClinical, onGenerateSummary, isGeneratingSummary }: ReportsProps) {
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [hospitalFilter, setHospitalFilter] = useState('All');
  const [activeTab, setActiveTab] = useState('original');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [storageChoice, setStorageChoice] = useState('local');
  const [summaryMode, setSummaryMode] = useState<SummaryMode>('standard');
  const [customSections, setCustomSections] = useState<string[]>(['executive', 'findings', 'abnormal', 'normal', 'terms', 'questions']);

  const hospitals = useMemo(() => {
    const set = new Set<string>();
    reports.forEach((r) => { if (r.hospital) set.add(r.hospital); if (r.laboratory) set.add(r.laboratory); });
    return ['All', ...Array.from(set)];
  }, [reports]);

  const filteredReports = useMemo(() => {
    return reports.filter((r) => {
      if (search && !r.title.toLowerCase().includes(search.toLowerCase()) && !r.source.toLowerCase().includes(search.toLowerCase())) return false;
      if (typeFilter !== 'All' && r.type !== typeFilter) return false;
      if (statusFilter !== 'All' && r.status !== statusFilter) return false;
      if (hospitalFilter !== 'All' && r.hospital !== hospitalFilter && r.laboratory !== hospitalFilter) return false;
      return true;
    });
  }, [reports, search, typeFilter, statusFilter, hospitalFilter]);

  const selectedReport = reports.find((r) => r.id === selectedReportId) || null;

  const handleUpload = () => {
    if (!selectedFile) return;
    onUpload(selectedFile, storageChoice);
  };

  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const statusVariant = (s: ReportStatus) => s === 'ready' ? 'success' : s === 'failed' ? 'error' : 'processing';

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:h-[calc(100vh-5rem)]">
      {/* Left: Report List */}
      <div className="lg:col-span-3 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Reports" icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="px-4 pb-3">
            <FilterBar searchValue={search} onSearchChange={setSearch} searchPlaceholder="Search reports...">
              <SelectFilter label="Type" value={typeFilter} options={reportTypes.map(t => ({ value: t, label: t }))} onChange={setTypeFilter} />
              <SelectFilter label="Status" value={statusFilter} options={statusOptions.map(s => ({ value: s, label: s === 'All' ? 'All' : reportStatusLabels[s] || s }))} onChange={setStatusFilter} />
              <SelectFilter label="Source" value={hospitalFilter} options={hospitals.map(h => ({ value: h, label: h }))} onChange={setHospitalFilter} />
            </FilterBar>
          </div>
          <div className="flex-1 divide-y divide-neutral-100 dark:divide-neutral-800 lg:overflow-y-auto">
            {filteredReports.length === 0 ? (
              <EmptyState title="No reports found" description="Try adjusting your filters or upload a new report." icon={<FileSearch className="h-6 w-6" />} />
            ) : (
              filteredReports.map((report) => (
                <button
                  key={report.id}
                  onClick={() => onSelectReport(report.id)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedReportId === report.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{report.title}</p>
                    <ChevronRight className="h-4 w-4 shrink-0 text-neutral-300 dark:text-neutral-600" />
                  </div>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{report.type} · {report.source}</p>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-neutral-400">{formatDate(report.date)}</span>
                    <StatusBadge variant={statusVariant(report.status)} pulse={report.status !== 'ready'}>
                      {reportStatusLabels[report.status]}
                    </StatusBadge>
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
            <Button className="w-full" onClick={() => setUploadOpen(true)}>
              <Upload className="h-4 w-4" />
              Upload Report
            </Button>
          </div>
        </Card>
      </div>

      {/* Center: Report Viewer */}
      <div className="lg:col-span-5 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          {!selectedReport ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState
                title="Select a report"
                description="Choose a report from the list to view its contents, extracted data, and AI summary."
                icon={<FileText className="h-6 w-6" />}
              />
            </div>
          ) : selectedReport.status !== 'ready' ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <LoadingState message={`Report is ${reportStatusLabels[selectedReport.status] || 'processing'}...`} />
            </div>
          ) : (
            <>
              <CardHeader
                title={selectedReport.title}
                subtitle={`${selectedReport.type} · ${selectedReport.source} · ${formatDate(selectedReport.date)}`}
                action={
                  <Button variant="ghost" size="sm" onClick={() => onNavigateClinical(selectedReport.id)}>
                    <Settings2 className="h-3.5 w-3.5" />
                    Clinical View
                  </Button>
                }
              />
              <Tabs
                tabs={[
                  { key: 'original', label: 'Original PDF', icon: <FileText className="h-3.5 w-3.5" /> },
                  { key: 'markdown', label: 'Extracted Markdown', icon: <FileSearch className="h-3.5 w-3.5" /> },
                  { key: 'structured', label: 'Structured Data', icon: <ListChecks className="h-3.5 w-3.5" /> },
                ]}
                activeKey={activeTab}
                onChange={setActiveTab}
                className="px-4"
              />
              <div className="flex-1 overflow-y-auto p-4">
                {activeTab === 'original' && (
                  <div className="flex h-full min-h-[500px] flex-col rounded-lg border border-neutral-200 bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-800/50">
                    <iframe 
                      src={`/api/v1/reports/${selectedReport.id}/download`} 
                      className="h-full w-full rounded-lg"
                      title={selectedReport.title}
                    />
                  </div>
                )}
                {activeTab === 'markdown' && (
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <pre className="whitespace-pre-wrap rounded-lg bg-neutral-50 p-4 text-xs text-neutral-700 dark:bg-neutral-800/50 dark:text-neutral-300 font-mono">{`## ${selectedReport.title}

**Source:** ${selectedReport.source}
**Date:** ${formatDate(selectedReport.date)}
**Doctor:** ${selectedReport.doctor || 'N/A'}
**Department:** ${selectedReport.department || 'N/A'}

### Extracted Content

The MarkItDown pipeline converts the original PDF to structured markdown text server-side, with OCR fallback for scanned documents.

### Key Sections
- Patient demographics
- Clinical findings
- Laboratory values
- Impression and recommendations`}</pre>
                  </div>
                )}
                {activeTab === 'structured' && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-neutral-200 dark:border-neutral-800">
                          <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Field</th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-neutral-500">Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          ['Report ID', selectedReport.id],
                          ['Type', selectedReport.type],
                          ['Title', selectedReport.title],
                          ['Source', selectedReport.source],
                          ['Hospital', selectedReport.hospital || 'N/A'],
                          ['Laboratory', selectedReport.laboratory || 'N/A'],
                          ['Department', selectedReport.department || 'N/A'],
                          ['Doctor', selectedReport.doctor || 'N/A'],
                          ['Date', formatDate(selectedReport.date)],
                          ['Status', reportStatusLabels[selectedReport.status]],
                          ['Artifacts', String(selectedReport.artifacts.length)],
                        ].map(([field, value]) => (
                          <tr key={field} className="border-b border-neutral-100 dark:border-neutral-800/50">
                            <td className="px-3 py-2 text-xs font-medium text-neutral-500">{field}</td>
                            <td className="px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300">{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Right: AI Summary */}
      <div className="lg:col-span-4 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader
            title="AI Summary"
            subtitle={selectedReport?.summary ? `${summaryModeLabels[selectedReport.summary.mode]} mode` : undefined}
            icon={<Sparkles className="h-4.5 w-4.5" />}
          />
          <div className="flex-1 overflow-y-auto p-4">
            {!selectedReport ? (
              <EmptyState title="No report selected" description="Select a report to view its AI-generated summary." icon={<Sparkles className="h-6 w-6" />} />
            ) : !selectedReport.summary ? (
              <div className="flex flex-col items-center justify-center space-y-4 py-8">
                <EmptyState
                  title="No summary available"
                  description="This report has not been summarized yet."
                  icon={<FileSearch className="h-6 w-6" />}
                />
                <Button 
                  onClick={() => onGenerateSummary(selectedReport.id, summaryMode)}
                  disabled={isGeneratingSummary}
                >
                  {isGeneratingSummary ? 'Generating...' : 'Generate AI Summary'}
                </Button>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Summary Mode Selector */}
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Summary Mode</label>
                  <div className="flex flex-wrap gap-1.5">
                    {(['quick', 'standard', 'detailed', 'clinical', 'custom'] as SummaryMode[]).map((mode) => (
                      <button
                        key={mode}
                        onClick={() => setSummaryMode(mode)}
                        className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                          summaryMode === mode
                            ? 'bg-teal-600 text-white'
                            : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700'
                        }`}
                      >
                        {summaryModeLabels[mode]}
                      </button>
                    ))}
                  </div>
                  {summaryMode === 'custom' && (
                    <div className="mt-2 space-y-1.5 rounded-lg border border-neutral-200 p-2 dark:border-neutral-700">
                      {summarySections.map((s) => (
                        <label key={s.key} className="flex items-center gap-2 text-xs">
                          <input
                            type="checkbox"
                            checked={customSections.includes(s.key)}
                            onChange={(e) => {
                              if (e.target.checked) setCustomSections([...customSections, s.key]);
                              else setCustomSections(customSections.filter((k) => k !== s.key));
                            }}
                            className="rounded border-neutral-300 text-teal-600 focus:ring-teal-500"
                          />
                          <span className="text-neutral-600 dark:text-neutral-400">{s.label}</span>
                        </label>
                      ))}
                    </div>
                  )}
                  {selectedReport.summary && (
                    <div className="mt-4 flex justify-end">
                      <Button 
                        onClick={() => onGenerateSummary(selectedReport.id, summaryMode)}
                        disabled={isGeneratingSummary}
                        variant="outline"
                        size="sm"
                      >
                        {isGeneratingSummary ? 'Regenerating...' : 'Regenerate Summary'}
                      </Button>
                    </div>
                  )}
                </div>

                <SafetyNotice variant="compact" />

                {/* Summary Sections */}
                {selectedReport.summary.sections.filter((s: ReportSummarySection) => s.visible).map((section: ReportSummarySection) => (
                  <div key={section.key} className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                    <p className="mb-1.5 text-xs font-semibold text-teal-600 dark:text-teal-400">{section.label}</p>
                    <p className="text-sm leading-relaxed text-neutral-700 dark:text-neutral-300">{section.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Upload Modal */}
      <Modal
        open={uploadOpen}
        onClose={() => { setUploadOpen(false); setSelectedFile(null); }}
        title="Upload Report"
        description="Select a PDF to upload. Choose your primary storage destination."
        size="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => { setUploadOpen(false); setSelectedFile(null); }}>Cancel</Button>
            <Button onClick={handleUpload} disabled={!selectedFile || !!uploadStage}>
              {uploadStage ? 'Processing...' : 'Upload'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {/* File Selection */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">PDF Document</label>
            {!selectedFile ? (
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-neutral-300 p-6 transition-colors hover:border-teal-500 dark:border-neutral-700">
                <Upload className="mb-2 h-8 w-8 text-neutral-400" />
                <p className="text-sm text-neutral-600 dark:text-neutral-400">Click to select a PDF</p>
                <p className="text-xs text-neutral-400">Max 50MB</p>
                <input
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) setSelectedFile(f); }}
                />
              </label>
            ) : (
              <div className="flex items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                <FileCheck className="h-5 w-5 text-success-600" />
                <div className="flex-1 min-w-0">
                  <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{selectedFile.name}</p>
                  <p className="text-xs text-neutral-400">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
                <button onClick={() => setSelectedFile(null)} className="rounded p-1 text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800">
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>

          {/* Storage Selection */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Primary Storage</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setStorageChoice('local')}
                className={`flex items-center gap-2 rounded-lg border p-3 text-left transition-colors ${
                  storageChoice === 'local'
                    ? 'border-teal-500 bg-teal-50 dark:bg-teal-950/30'
                    : 'border-neutral-200 hover:border-neutral-300 dark:border-neutral-700'
                }`}
              >
                <FileText className="h-4 w-4 text-teal-600" />
                <div>
                  <p className="text-xs font-medium text-neutral-900 dark:text-neutral-100">Local Storage</p>
                  <p className="text-xs text-neutral-400">On this device</p>
                </div>
              </button>
              <button
                onClick={() => setStorageChoice('google_drive')}
                className={`flex items-center gap-2 rounded-lg border p-3 text-left transition-colors ${
                  storageChoice === 'google_drive'
                    ? 'border-teal-500 bg-teal-50 dark:bg-teal-950/30'
                    : 'border-neutral-200 hover:border-neutral-300 dark:border-neutral-700'
                }`}
              >
                <FileText className="h-4 w-4 text-neutral-400" />
                <div>
                  <p className="text-xs font-medium text-neutral-900 dark:text-neutral-100">Google Drive</p>
                  <p className="text-xs text-warning-600">Integration required</p>
                </div>
              </button>
            </div>
          </div>

          {/* Processing Stages */}
          {uploadStage && (
            <div className="space-y-2 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Processing Pipeline</p>
              {(['uploading', 'extracting', 'ocr', 'structured', 'ready'] as UploadStage[]).map((stage, idx) => {
                const stages = ['uploading', 'extracting', 'ocr', 'structured', 'ready'];
                const currentIdx = stages.indexOf(uploadStage);
                const isDone = idx < currentIdx;
                const isActive = idx === currentIdx;
                const Icon = isDone ? CheckCircle2 : stageIcons[stage];
                return (
                  <div key={stage} className={`flex items-center gap-2 text-xs ${isActive ? 'text-teal-600 dark:text-teal-400' : isDone ? 'text-success-600' : 'text-neutral-400'}`}>
                    <Icon className={`h-3.5 w-3.5 ${isActive ? 'animate-spin' : ''}`} />
                    <span>{stageLabels[stage]}</span>
                    {stage === 'ocr' && !isDone && !isActive && (
                      <span className="text-xs text-neutral-400">— if required</span>
                    )}
                  </div>
                );
              })}
              {uploadStage === 'failed' && (
                <div className="flex items-center gap-2 text-xs text-error-600">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span>Processing failed. Please try again.</span>
                </div>
              )}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
