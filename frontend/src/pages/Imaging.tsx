import { useState, useRef } from 'react';
import {
  ScanLine, Layers, ZoomIn, Hand, Sliders, Ruler, PenTool, Box, FileText,
  Sparkles, ShieldCheck, ExternalLink, Upload, Loader2,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { SafetyNotice } from '@/components/SafetyNotice';
import { EmptyState } from '@/components/States';
import { api, ApiError, type DicomUploadResponse } from '@/lib/api';
import { useToast } from '@/context/ToastContext';
import type { ImagingStudy } from '@/lib/types';

/**
 * OHIF is served by the FastAPI backend at /ohif/.
 * In development, Vite proxy forwards /ohif/* to 127.0.0.1:8000, so /ohif/ works.
 * In production, set VITE_OHIF_URL to the absolute URL if needed.
 */
const OHIF_BASE = (import.meta.env.VITE_OHIF_URL as string | undefined) ?? '/ohif/';

interface ImagingProps {
  studies: ImagingStudy[];
  studiesLoading: boolean;
  selectedStudyId: string | null;
  onSelectStudy: (id: string) => void;
  /** Called after a successful DICOM upload so the study list refreshes */
  onStudyUploaded: () => void;
}

const toolbarTools = [
  { key: '2d', label: '2D', icon: Layers },
  { key: 'mpr', label: 'MPR', icon: Box },
  { key: '3d', label: '3D', icon: Box },
  { key: 'zoom', label: 'Zoom', icon: ZoomIn },
  { key: 'pan', label: 'Pan', icon: Hand },
  { key: 'window', label: 'Window/Level', icon: Sliders },
  { key: 'measure', label: 'Measure', icon: Ruler },
  { key: 'annotate', label: 'Annotation', icon: PenTool },
];

export function Imaging({ studies, studiesLoading, selectedStudyId, onSelectStudy, onStudyUploaded }: ImagingProps) {
  const { addToast } = useToast();
  const [activeTool, setActiveTool] = useState('2d');
  const [viewerOpen, setViewerOpen] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedStudy = studies.find((s) => s.id === selectedStudyId) || null;
  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  // ── OHIF viewer URL ───────────────────────────────────────────────────────
  // When a study is selected, OHIF is opened with StudyInstanceUIDs query param.
  // The study ID is the StudyInstanceUID from the QIDO response.
  const ohifStudyUrl = selectedStudy
    ? `${OHIF_BASE}?StudyInstanceUIDs=${encodeURIComponent(selectedStudy.id)}`
    : OHIF_BASE;

  // ── DICOM upload ──────────────────────────────────────────────────────────
  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset file input so the same file can be re-uploaded if needed
    e.target.value = '';

    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.postMultipart<DicomUploadResponse>(
        '/api/v1/medical-data/dicom/upload',
        form,
      );
      addToast({
        title: 'DICOM uploaded',
        description: `Instance #${res.instance_id} stored successfully.`,
        variant: 'success',
      });
      // Refresh the study list so the new study appears
      onStudyUploaded();
    } catch (err) {
      if (err instanceof ApiError) {
        addToast({
          title: 'Upload failed',
          description: err.detail,
          variant: 'error',
        });
      } else {
        addToast({
          title: 'Upload failed',
          description: 'Could not reach the server.',
          variant: 'error',
        });
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3 lg:h-[calc(100vh-5rem)] lg:flex lg:flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-teal-600 dark:text-teal-400">Primary workspace</p>
          <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">OHIF Diagnostic Imaging</h2>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge variant={selectedStudy?.deidentified ? 'success' : 'warning'}>
            {selectedStudy?.deidentified ? 'De-identified study' : 'Check de-identification'}
          </StatusBadge>
          <Button variant="secondary" size="sm" onClick={() => setViewerOpen((open) => !open)}>
            {viewerOpen ? 'Hide viewer' : 'Show viewer'}
          </Button>
          <Button size="sm" onClick={() => window.open(ohifStudyUrl, '_blank', 'noopener,noreferrer')}>
            <ExternalLink className="h-3.5 w-3.5" /> Open OHIF
          </Button>
        </div>
      </div>

    <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-12 lg:min-h-0">
      {/* Left: Study List */}
      <div className="lg:col-span-3 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader
            title="Imaging Studies"
            icon={<ScanLine className="h-4.5 w-4.5" />}
            action={
              <div className="flex items-center gap-1">
                {/* Hidden file input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".dcm,application/dicom"
                  className="hidden"
                  onChange={handleFileSelected}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  title="Upload DICOM file"
                >
                  {uploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                </Button>
              </div>
            }
          />
          <div className="flex-1 divide-y divide-neutral-100 dark:divide-neutral-800 lg:overflow-y-auto">
            {studiesLoading ? (
              <div className="flex items-center justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
              </div>
            ) : studies.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="No studies"
                  description="Upload a DICOM file using the ↑ button above."
                  icon={<ScanLine className="h-6 w-6" />}
                />
              </div>
            ) : (
              studies.map((study) => (
                <button
                  key={study.id}
                  onClick={() => onSelectStudy(study.id)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedStudyId === study.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {formatDate(study.studyDate)}</p>
                  <div className="flex items-center gap-2">
                    <StatusBadge variant="success">
                      Available
                    </StatusBadge>
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
            <div className="space-y-1.5 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/50">
              <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Study Metadata</p>
              {selectedStudy ? (
                <div className="space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
                  <p className="break-all font-mono text-[10px]">UID: {selectedStudy.id}</p>
                  <p>Modality: {selectedStudy.modality}</p>
                  <p>Date: {formatDate(selectedStudy.studyDate)}</p>
                </div>
              ) : (
                <p className="text-xs text-neutral-400">Select a study to view metadata</p>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Center: Imaging Viewport */}
      <div className="lg:col-span-6 min-h-[560px]">
        <Card className="lg:h-full flex flex-col">
          {!selectedStudy ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState title="Select a study" description="Choose an imaging study from the list to open the viewer." icon={<ScanLine className="h-6 w-6" />} />
            </div>
          ) : (
            <>
              {/* Toolbar */}
              <div className="flex items-center gap-1 border-b border-neutral-200 p-2 dark:border-neutral-800">
                {toolbarTools.map((tool) => {
                  const Icon = tool.icon;
                  return (
                    <button
                      key={tool.key}
                      onClick={() => setActiveTool(tool.key)}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        activeTool === tool.key
                          ? 'bg-teal-600 text-white'
                          : 'text-neutral-500 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-800'
                      }`}
                      title={tool.label}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">{tool.label}</span>
                    </button>
                  );
                })}
              </div>

              <div className="relative flex flex-1 bg-neutral-950" style={{ minHeight: 400 }}>
                {viewerOpen ? (
                  <iframe
                    title="OHIF DICOM Viewer"
                    src={ohifStudyUrl}
                    className="h-full min-h-[440px] w-full border-0"
                    allow="fullscreen"
                  />
                ) : (
                  <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
                    <ScanLine className="h-10 w-10 text-neutral-600" />
                    <p className="mt-3 text-sm font-semibold text-neutral-300">Viewer hidden</p>
                    <p className="mt-1 text-xs text-neutral-500">Use Show viewer to return to OHIF, or open it in a dedicated tab.</p>
                  </div>
                )}
                <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-black/70 px-2.5 py-1.5 text-[11px] font-medium text-white">
                  OHIF Viewer · {activeTool.toUpperCase()} mode
                </div>
              </div>

              {/* Study info bar */}
              <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
                <div className="flex items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{selectedStudy.modality}</span>
                  <span>·</span>
                  <span className="max-w-[200px] truncate font-mono text-[10px]">{selectedStudy.id}</span>
                </div>
                <StatusBadge variant="success">Live</StatusBadge>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Right: Radiology Report / AI */}
      <div className="lg:col-span-3 lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Radiology Report" icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="flex-1 overflow-y-auto p-4">
            {!selectedStudy ? (
              <EmptyState title="No study selected" description="Select a study to view its radiology report." icon={<FileText className="h-6 w-6" />} />
            ) : !selectedStudy.reportText ? (
              <div className="space-y-3">
                <EmptyState title="No report available" description="This DICOM study has no associated radiology report text." icon={<FileText className="h-6 w-6" />} />
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-3 dark:border-teal-700/30 dark:bg-teal-950/10">
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                    <p className="text-xs font-semibold text-teal-600 dark:text-teal-400">AI Analysis</p>
                  </div>
                  <p className="text-xs leading-relaxed text-neutral-500 dark:text-neutral-400">
                    AI report analysis will be available once an Ollama model is configured on the backend.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <p className="mb-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Report Text</p>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-neutral-700 dark:text-neutral-300">{selectedStudy.reportText}</p>
                </div>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-3 dark:border-teal-700/30 dark:bg-teal-950/10">
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                    <p className="text-xs font-semibold text-teal-600 dark:text-teal-400">AI Analysis (not yet connected)</p>
                  </div>
                  <p className="text-xs leading-relaxed text-neutral-500 dark:text-neutral-400">
                    Connect the Ollama backend to enable AI-powered report explanations.
                  </p>
                </div>
                <SafetyNotice variant="compact" />
                <div className="flex items-center gap-2 text-xs text-neutral-400">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>Report text is from the stored DICOM metadata only.</span>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
      </div>
    </div>
  );
}
