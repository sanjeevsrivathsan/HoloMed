import { useState, useRef } from 'react';
import {
  ScanLine, FileText, Sparkles, ExternalLink, Upload, Loader2, User,
} from 'lucide-react';
import { Card, CardHeader } from '@/components/Card';
import { ResizablePanels } from '@/components/ResizablePanels';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { EmptyState } from '@/components/States';
import { ChestXrayScreening } from '@/components/vision/ChestXrayScreening';
import { api, ApiError, type DicomUploadResponse } from '@/lib/api';
import { useToast } from '@/context/ToastContext';
import type { ImagingStudy } from '@/lib/types';
import { hasViewableImages } from '@/lib/imagingStudies';
import { ohifViewerUrl, patientLabel, type PatientSummary } from '@/lib/patients';

/**
 * OHIF is served by the FastAPI backend at /ohif/ (Vite proxies it in development).
 * The viewer is launched per patient and study: see ohifViewerUrl.
 */
const OHIF_BASE = ((import.meta.env.VITE_OHIF_URL as string | undefined) ?? '/ohif/').replace(/\/?$/, '/');

export type ImagingMode = 'screening' | 'viewer';

interface ImagingProps {
  patient: PatientSummary | null;
  mode: ImagingMode;
  onModeChange: (mode: ImagingMode) => void;
  studies: ImagingStudy[];
  studiesLoading: boolean;
  selectedStudyId: string | null;
  onSelectStudy: (id: string) => void;
  /** Called after a DICOM is stored for the patient so the study list refreshes and opens it */
  onStudyUploaded: (studyInstanceUid: string) => void;
}

export function Imaging({
  patient, mode, onModeChange, studies, studiesLoading, selectedStudyId, onSelectStudy, onStudyUploaded,
}: ImagingProps) {
  const { addToast } = useToast();
  const [viewerOpen, setViewerOpen] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedStudy = studies.find((s) => s.id === selectedStudyId) || null;
  const formatDate = (d: string) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  // The selected study of the active patient — never a default or previous study.
  const ohifStudyUrl = patient && selectedStudy
    ? ohifViewerUrl(OHIF_BASE, patient.id, { studyInstanceUid: selectedStudy.id, seriesInstanceUid: selectedStudy.seriesInstanceUid })
    : null;

  const switchMode = (next: ImagingMode) => {
    onModeChange(next);
    setViewerOpen(true);
  };

  const openInOhif = (studyInstanceUid: string) => {
    onSelectStudy(studyInstanceUid);
    switchMode('viewer');
  };

  // ── DICOM upload (stored under the active patient) ────────────────────────
  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !patient) return;
    e.target.value = '';
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api.postMultipart<DicomUploadResponse>(`/api/v1/patients/${patient.id}/imaging`, form);
      addToast({
        title: 'DICOM uploaded',
        description: `${res.modality ?? 'Study'} stored for ${patient.patient_code}.`,
        variant: 'success',
      });
      onStudyUploaded(res.study_instance_uid);
      setViewerOpen(true);
    } catch (err) {
      addToast({
        title: 'Upload failed',
        description: err instanceof ApiError ? err.detail : 'Could not reach the server.',
        variant: 'error',
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className={`space-y-3 ${mode === 'viewer' ? 'lg:h-[calc(100vh-5rem)] lg:flex lg:flex-col' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-teal-600 dark:text-teal-400">Primary workspace</p>
            <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">
              {mode === 'screening' ? 'Chest X-Ray AI Screening' : 'OHIF Diagnostic Imaging'}
            </h2>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-neutral-500 dark:text-neutral-400" data-testid="imaging-patient">
              <User className="h-3 w-3" />
              {patient ? `Patient: ${patient.patient_code} · ${patient.name}` : 'No patient selected'}
            </p>
          </div>
          <div className="flex items-center gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-800" role="tablist" aria-label="Imaging mode">
            {([
              { key: 'screening', label: 'AI Screening', icon: Sparkles },
              { key: 'viewer', label: 'OHIF Viewer', icon: ScanLine },
            ] as const).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                role="tab"
                aria-selected={mode === key}
                onClick={() => switchMode(key)}
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  mode === key
                    ? 'bg-white text-teal-700 shadow-sm dark:bg-neutral-950 dark:text-teal-300'
                    : 'text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
        </div>
        {mode === 'viewer' && (
        <div className="flex items-center gap-2">
          <StatusBadge variant="warning">Check de-identification</StatusBadge>
          <Button variant="secondary" size="sm" onClick={() => setViewerOpen((open) => !open)}>
            {viewerOpen ? 'Hide viewer' : 'Show viewer'}
          </Button>
          <Button size="sm" disabled={!ohifStudyUrl} onClick={() => ohifStudyUrl && window.open(ohifStudyUrl, '_blank', 'noopener,noreferrer')}>
            <ExternalLink className="h-3.5 w-3.5" /> Open OHIF
          </Button>
        </div>
        )}
      </div>

    {mode === 'screening' && patient && (
      <ChestXrayScreening
        key={patient.id}
        patient={patient}
        study={selectedStudy}
        onSaved={(studyUid) => studyUid && onStudyUploaded(studyUid)}
        onOpenInOhif={openInOhif}
      />
    )}

    {mode === 'viewer' && (
    <ResizablePanels id="imaging-viewer" className="flex-1 lg:min-h-0" breakpoint={1024} panels={[
      { label: 'study list', min: 220, size: 20, max: 40 },
      { label: 'viewer', min: 480, size: 58 },
      { label: 'clinical panel', min: 220, size: 22, max: 40 },
    ]}>
      {/* Left: Study List */}
      <div className="h-full lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader
            title="Imaging Studies"
            subtitle={patient ? patient.patient_code : undefined}
            icon={<ScanLine className="h-4.5 w-4.5" />}
            action={
              <div className="flex items-center gap-1">
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
                  disabled={uploading || !patient}
                  title="Upload DICOM file for this patient"
                >
                  {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                </Button>
              </div>
            }
          />
          <div className="flex-1 divide-y divide-neutral-100 dark:divide-neutral-800 lg:overflow-y-auto" data-testid="study-list">
            {studiesLoading && studies.length === 0 ? (
              <div className="flex items-center justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
              </div>
            ) : studies.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title="No studies"
                  description="Upload a DICOM file using the ↑ button above, or run AI screening on a DICOM chest X-ray."
                  icon={<ScanLine className="h-6 w-6" />}
                />
              </div>
            ) : (
              studies.map((study) => (
                <button
                  key={study.id}
                  data-study-uid={study.id}
                  onClick={() => { onSelectStudy(study.id); setViewerOpen(true); }}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors ${
                    selectedStudyId === study.id ? 'bg-teal-50 dark:bg-teal-950/30' : 'hover:bg-neutral-50 dark:hover:bg-neutral-800/50'
                  }`}
                >
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{study.description}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{study.modality} · {formatDate(study.studyDate)}</p>
                  <p className="text-[11px] text-neutral-400">
                    {study.seriesCount} series · {study.instanceCount ?? 0} image{study.instanceCount === 1 ? '' : 's'}
                  </p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {hasViewableImages(study.modality) ? (
                      <StatusBadge variant="success">Available</StatusBadge>
                    ) : (
                      <StatusBadge variant="warning">No images</StatusBadge>
                    )}
                    {study.latestAnalysis && <StatusBadge variant="neutral">AI screened</StatusBadge>}
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">
            <div className="space-y-1.5 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/50" data-testid="study-metadata">
              <p className="text-xs font-medium text-neutral-500 dark:text-neutral-400">Study Metadata</p>
              {selectedStudy ? (
                <div className="space-y-1 text-xs text-neutral-600 dark:text-neutral-400">
                  <p className="break-all font-mono text-[10px]">Study UID: {selectedStudy.id}</p>
                  {selectedStudy.seriesInstanceUid && <p className="break-all font-mono text-[10px]">Series UID: {selectedStudy.seriesInstanceUid}</p>}
                  {selectedStudy.sopInstanceUid && <p className="break-all font-mono text-[10px]">SOP UID: {selectedStudy.sopInstanceUid}</p>}
                  <p>Modality: {selectedStudy.modality}</p>
                  <p>Date: {formatDate(selectedStudy.studyDate)}</p>
                  <p>Series: {selectedStudy.seriesCount} · Images: {selectedStudy.instanceCount ?? 0}</p>
                  {selectedStudy.rows && selectedStudy.columns && <p>Dimensions: {selectedStudy.columns}×{selectedStudy.rows}</p>}
                </div>
              ) : (
                <p className="text-xs text-neutral-400">Select a study to view metadata</p>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Center: the real OHIF viewer (its own toolbar provides zoom, pan, W/L, measurements, MPR/3D) */}
      <div className="h-full min-h-[640px]">
        <Card className="lg:h-full flex flex-col overflow-hidden">
          {!selectedStudy ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState title="Select a study" description="Choose an imaging study from the list to open the viewer." icon={<ScanLine className="h-6 w-6" />} />
            </div>
          ) : (
            <>
              <div className="relative flex flex-1 bg-neutral-950" style={{ minHeight: 600 }}>
                {!hasViewableImages(selectedStudy.modality) ? (
                  <div className="flex flex-1 flex-col items-center justify-center p-8 text-center" role="status">
                    <ScanLine className="h-10 w-10 text-neutral-600" />
                    <p className="mt-3 text-sm font-semibold text-neutral-300">No images to display</p>
                    <p className="mt-1 max-w-sm text-xs text-neutral-500">
                      This {selectedStudy.modality} study has no pixel data, so the OHIF image viewer cannot show it.
                      Select an imaging study such as a chest X-ray.
                    </p>
                  </div>
                ) : viewerOpen && ohifStudyUrl ? (
                  <iframe
                    key={ohifStudyUrl}
                    title="OHIF DICOM Viewer"
                    src={ohifStudyUrl}
                    className="h-full min-h-[600px] w-full border-0"
                    allow="fullscreen"
                  />
                ) : (
                  <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
                    <ScanLine className="h-10 w-10 text-neutral-600" />
                    <p className="mt-3 text-sm font-semibold text-neutral-300">Viewer hidden</p>
                    <p className="mt-1 text-xs text-neutral-500">Use Show viewer to return to OHIF, or open it in a dedicated tab.</p>
                  </div>
                )}
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
                <div className="flex min-w-0 items-center gap-3 text-xs text-neutral-500 dark:text-neutral-400">
                  <span>{selectedStudy.modality}</span>
                  <span>·</span>
                  <span className="truncate font-mono text-[10px]" data-testid="viewer-study-uid">{selectedStudy.id}</span>
                </div>
                <StatusBadge variant="success">OHIF · DICOMweb</StatusBadge>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* Right: AI result and report for the selected study */}
      <div className="h-full lg:overflow-y-auto">
        <Card className="lg:h-full flex flex-col">
          <CardHeader title="Clinical Panel" icon={<FileText className="h-4.5 w-4.5" />} />
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {!selectedStudy ? (
              <EmptyState title="No study selected" description="Select a study to see its AI screening result." icon={<FileText className="h-6 w-6" />} />
            ) : (
              <>
                <div className="rounded-lg border border-teal-200 bg-teal-50/50 p-3 dark:border-teal-700/30 dark:bg-teal-950/10" data-testid="study-ai-panel">
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-teal-600 dark:text-teal-400" />
                    <p className="text-xs font-semibold text-teal-600 dark:text-teal-400">AI Screening</p>
                  </div>
                  {selectedStudy.latestAnalysis ? (
                    <>
                      <p className="text-xs text-neutral-600 dark:text-neutral-400">
                        Primary model finding <span className="font-semibold text-neutral-900 dark:text-neutral-100">{selectedStudy.latestAnalysis.primaryPathology}</span>
                        {' '}· model score <span className="font-mono">{selectedStudy.latestAnalysis.primaryScore.toFixed(4)}</span>
                      </p>
                      <p className="mt-1 text-[11px] text-neutral-500">
                        Saved {new Date(selectedStudy.latestAnalysis.createdAt).toLocaleString()} · non-diagnostic model output, requires clinical review.
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-neutral-500 dark:text-neutral-400">This study has not been screened yet.</p>
                  )}
                  {hasViewableImages(selectedStudy.modality) && (
                    <Button size="sm" variant="outline" className="mt-2" onClick={() => switchMode('screening')}>
                      <Sparkles className="h-3.5 w-3.5" /> {selectedStudy.latestAnalysis ? 'Open in AI Screening' : 'Screen in AI Screening'}
                    </Button>
                  )}
                </div>
                {selectedStudy.reportText ? (
                  <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                    <p className="mb-1.5 text-xs font-semibold text-neutral-500 dark:text-neutral-400">Report Text</p>
                    <p className="whitespace-pre-wrap text-xs leading-relaxed text-neutral-700 dark:text-neutral-300">{selectedStudy.reportText}</p>
                  </div>
                ) : (
                  <p className="text-xs text-neutral-400">No radiology report text is stored with this DICOM study.</p>
                )}
                {patient && <p className="text-[11px] text-neutral-400">{patientLabel(patient)}</p>}
              </>
            )}
          </div>
        </Card>
      </div>
    </ResizablePanels>
    )}
    </div>
  );
}
