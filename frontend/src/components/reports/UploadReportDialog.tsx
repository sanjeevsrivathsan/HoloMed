import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { AlertTriangle, CheckCircle2, FileCheck, Sparkles, Upload, X } from 'lucide-react';
import { Modal } from '@/components/Modal';
import { Button } from '@/components/Button';
import { ProcessingStagesList } from '@/components/reports/ProcessingStagesList';
import {
  errorMessage, formatBytes, reportsApi, uploadReport,
  type ReportCapabilities, type ReportExtraction, type UploadHandle,
} from '@/lib/reports';
import {
  aiSummaryAvailability, failureMessage, pipelineOutcome, uploadStages,
  type TextAiState, type UploadPhase,
} from '@/lib/processingStages';

interface UploadReportDialogProps {
  open: boolean;
  onClose: () => void;
  capabilities: ReportCapabilities | null;
  capabilitiesError: string | null;
  /** Called after the server accepted the upload and whenever processing finishes (refresh lists). */
  onUploaded: (reportId: string) => Promise<void> | void;
  onReviewReport: (reportId: string) => void;
}

const POLL_MS = 800;

export function UploadReportDialog({
  open, onClose, capabilities, capabilitiesError, onUploaded, onReviewReport,
}: UploadReportDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [docType, setDocType] = useState('Blood Test');
  const [title, setTitle] = useState('');
  const [laboratory, setLaboratory] = useState('');
  const [phase, setPhase] = useState<UploadPhase>('idle');
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ReportExtraction | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [textAi, setTextAi] = useState<TextAiState | null | undefined>(undefined);
  const handle = useRef<UploadHandle | null>(null);
  const onUploadedRef = useRef(onUploaded);
  onUploadedRef.current = onUploaded;
  const inputRef = useRef<HTMLInputElement>(null);

  const formats = capabilities?.formats ?? [];
  const accept = formats.map((f) => `${f.extension},${f.mime_type}`).join(',');
  const formatList = formats.map((f) => f.label).join(', ');
  const maxBytes = capabilities?.max_bytes ?? 50 * 1024 * 1024;

  const stages = uploadStages(phase, { progress, uploadError, serverStages: extraction?.stages });
  const outcome = phase === 'server' && extraction ? pipelineOutcome(stages) : phase === 'upload_failed' ? 'failed' : 'in_progress';
  const failure = outcome === 'failed' ? failureMessage(stages) : null;

  useEffect(() => {
    if (!open) return;
    let stale = false;   // ignore a slow response from an earlier opening of the dialog
    setTextAi(undefined);
    reportsApi.textAiStatus()
      .then((s) => { if (!stale) setTextAi(s.status); })
      .catch(() => { if (!stale) setTextAi(null); });
    return () => { stale = true; };
  }, [open]);

  // Poll the server-reported stages until processing finishes (ready or failed).
  const finished = useRef(false);
  useEffect(() => {
    if (phase !== 'server' || !reportId) return;
    let cancelled = false;
    finished.current = false;
    const tick = async () => {
      try {
        const ex = await reportsApi.extraction(reportId);
        if (cancelled) return;
        setExtraction(ex);
        setPollError(null);
        if (ex.status === 'succeeded' || ex.status === 'failed') {
          if (!finished.current) {
            finished.current = true;
            await onUploadedRef.current(reportId);
          }
          return;
        }
      } catch (err) {
        if (cancelled) return;
        setPollError(errorMessage(err, 'Processing status could not be loaded. Retrying…'));
      }
      if (!cancelled) timer = window.setTimeout(tick, POLL_MS);
    };
    let timer = window.setTimeout(tick, 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [phase, reportId, retrying]);

  const reset = useCallback(() => {
    setFile(null);
    setFileError(null);
    setTitle('');
    setLaboratory('');
    setPhase('idle');
    setProgress(0);
    setUploadError(null);
    setNotice(null);
    setReportId(null);
    setExtraction(null);
    setPollError(null);
  }, []);

  const close = () => {
    if (phase === 'uploading') handle.current?.abort();
    reset();
    onClose();
  };

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    setFileError(null);
    setNotice(null);
    const ext = `.${f.name.split('.').pop()?.toLowerCase() ?? ''}`;
    const okExt = formats.some((fmt) => fmt.extension === ext || (fmt.extension === '.jpg' && ext === '.jpeg'));
    const okType = !f.type || formats.some((fmt) => fmt.mime_type === f.type);
    if (!okExt || !okType) {
      setFile(null);
      setFileError(`Unsupported file type. Supported formats: ${formatList}.`);
    } else if (f.size > maxBytes) {
      setFile(null);
      setFileError(`The file is ${formatBytes(f.size)}. The maximum size is ${formatBytes(maxBytes)}.`);
    } else if (f.size === 0) {
      setFile(null);
      setFileError('The file is empty.');
    } else {
      setFile(f);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const start = async () => {
    if (!file) return;
    setPhase('uploading');
    setProgress(0);
    setUploadError(null);
    setNotice(null);
    setExtraction(null);
    const h = uploadReport(file, { type: docType, title, laboratory }, setProgress);
    handle.current = h;
    try {
      const { id } = await h.promise;
      setReportId(String(id));
      setPhase('server');
      void onUploaded(String(id));
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setPhase('idle');
        setNotice('Upload cancelled. Nothing was saved.');
        return;
      }
      setUploadError(errorMessage(err, 'The upload failed. Check your connection and try again.'));
      setPhase('upload_failed');
    } finally {
      handle.current = null;
    }
  };

  const retryProcessing = async () => {
    if (!reportId) return;
    setRetrying(true);
    try {
      await reportsApi.retry(reportId);
      setExtraction(null);          // back to "in progress" until the server reports stages
      setPollError(null);
    } catch (err) {
      setPollError(errorMessage(err, 'Retry failed. Please try again.'));
    } finally {
      setRetrying(false);
    }
  };

  const selecting = phase === 'idle' || phase === 'upload_failed';
  const typeLabel = capabilities?.document_types.find((t) => t.value === docType)?.label ?? docType;
  const candidates = extraction?.candidates.filter((c) => c.review_status !== 'rejected').length ?? 0;
  const ai = aiSummaryAvailability(textAi);

  const footer = (
    <>
      {phase === 'uploading' && <Button variant="outline" onClick={() => handle.current?.abort()}>Cancel upload</Button>}
      {selecting && (
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button onClick={start} disabled={!file || !capabilities} data-testid="upload-submit">
            <Upload className="h-4 w-4" />
            {phase === 'upload_failed' ? 'Try again' : 'Upload'}
          </Button>
        </>
      )}
      {phase === 'server' && outcome === 'in_progress' && <Button variant="ghost" onClick={close}>Close</Button>}
      {phase === 'server' && outcome === 'failed' && (
        <>
          <Button variant="ghost" onClick={close}>Close</Button>
          <Button onClick={retryProcessing} disabled={retrying} data-testid="upload-retry">
            {retrying ? 'Retrying…' : 'Retry processing'}
          </Button>
        </>
      )}
      {phase === 'server' && outcome === 'ready' && (
        <>
          <Button variant="ghost" onClick={reset}>Upload another</Button>
          <Button onClick={() => { const id = reportId; close(); if (id) onReviewReport(id); }} data-testid="upload-review">
            Review extracted content
          </Button>
        </>
      )}
    </>
  );

  return (
    <Modal
      open={open}
      onClose={phase === 'uploading' ? () => undefined : close}
      title="Upload Report"
      description="Add a medical report. The original file is stored unchanged; extracted content is kept separately for your review."
      size="md"
      footer={footer}
    >
      <div className="space-y-4" data-testid="upload-dialog">
        {capabilitiesError && (
          <p className="rounded-lg bg-error-50 p-3 text-xs text-error-700 dark:bg-error-700/10 dark:text-red-400">{capabilitiesError}</p>
        )}

        {selecting ? (
          <>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Document</label>
              {!file ? (
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  onClick={() => inputRef.current?.click()}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click(); }}
                  role="button"
                  tabIndex={0}
                  data-testid="upload-dropzone"
                  className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors ${
                    dragging ? 'border-teal-500 bg-teal-50 dark:bg-teal-950/30' : 'border-neutral-300 hover:border-teal-500 dark:border-neutral-700'
                  }`}
                >
                  <Upload className="mb-2 h-8 w-8 text-neutral-400" />
                  <p className="text-sm text-neutral-600 dark:text-neutral-400">Drag a file here or click to choose</p>
                  <p className="text-xs text-neutral-400">
                    {capabilities ? `${formatList} · up to ${formatBytes(maxBytes)}` : 'Checking supported formats…'}
                  </p>
                  {capabilities && !capabilities.ocr_available && (
                    <p className="mt-1 text-xs text-neutral-400">Scanned documents need OCR, which is not installed on this server.</p>
                  )}
                  <input
                    ref={inputRef}
                    type="file"
                    accept={accept}
                    className="hidden"
                    data-testid="upload-input"
                    onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ''; }}
                  />
                </div>
              ) : (
                <div className="flex items-center gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                  <FileCheck className="h-5 w-5 text-success-600" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{file.name}</p>
                    <p className="text-xs text-neutral-400">{formatBytes(file.size)}</p>
                  </div>
                  <button onClick={() => setFile(null)} aria-label="Remove file" className="rounded p-1 text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800">
                    <X className="h-4 w-4" />
                  </button>
                </div>
              )}
              {fileError && <p className="mt-1.5 text-xs text-error-600" role="alert">{fileError}</p>}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Document type</span>
                <select value={docType} onChange={(e) => setDocType(e.target.value)} className="input" data-testid="upload-type">
                  {(capabilities?.document_types ?? []).map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Title (optional)</span>
                <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className="input" placeholder="Uses the file name if empty" />
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Laboratory or hospital (optional)</span>
                <input value={laboratory} onChange={(e) => setLaboratory(e.target.value)} maxLength={120} className="input" />
              </label>
            </div>
            <p className="text-xs text-neutral-400">Stored in HoloMed storage on this server.</p>
          </>
        ) : (
          <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">{file?.name}</p>
            <p className="text-xs text-neutral-400">{file ? formatBytes(file.size) : ''} · {typeLabel}</p>
          </div>
        )}

        {phase !== 'idle' && (
          <div className="space-y-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800" data-testid="upload-progress">
            <ProcessingStagesList stages={stages} />
            {phase === 'uploading' && (
              <div className="h-1.5 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800" role="progressbar"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
                <div className="h-full bg-teal-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            )}
            {outcome === 'ready' && (
              <p className="flex items-center gap-1.5 text-sm font-medium text-success-700 dark:text-green-400" data-testid="upload-outcome" data-outcome="ready">
                <CheckCircle2 className="h-4 w-4" />
                Report processed — {candidates > 0 ? `${candidates} value(s) ready for your review` : 'ready for your review'}
              </p>
            )}
            {outcome === 'failed' && (
              <div className="space-y-1" data-testid="upload-outcome" data-outcome="failed" role="alert">
                <p className="flex items-center gap-1.5 text-sm font-medium text-error-700 dark:text-red-400">
                  <AlertTriangle className="h-4 w-4" />
                  {phase === 'upload_failed' ? 'Upload failed' : 'Processing failed'}
                </p>
                <p className="text-xs text-error-600" data-testid="upload-message">{failure}</p>
                {phase === 'server' && <p className="text-xs text-neutral-400">The original file is kept unchanged.</p>}
              </div>
            )}
            {phase === 'server' && outcome !== 'failed' && (
              <p className={`flex items-start gap-1.5 text-xs ${ai.available === false ? 'text-warning-700 dark:text-amber-400' : 'text-neutral-500'}`} data-testid="upload-ai-status">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />{ai.message}
              </p>
            )}
          </div>
        )}
        {phase === 'server' && outcome === 'in_progress' && (
          <p className="text-xs text-neutral-400">You can close this dialog; processing continues and the report list updates automatically.</p>
        )}
        {pollError && <p className="text-xs text-warning-700" role="status">{pollError}</p>}
        {notice && <p className="text-xs text-neutral-500" role="status" data-testid="upload-notice">{notice}</p>}
      </div>
    </Modal>
  );
}
