import { useEffect, useRef, useState, type DragEvent } from 'react';
import { AlertTriangle, CheckCircle2, FileCheck, Loader2, Upload, X } from 'lucide-react';
import { Modal } from '@/components/Modal';
import { Button } from '@/components/Button';
import {
  errorMessage, formatBytes, reportsApi, uploadReport,
  type ReportCapabilities, type UploadHandle,
} from '@/lib/reports';
import type { Report } from '@/lib/types';

interface UploadReportDialogProps {
  open: boolean;
  onClose: () => void;
  capabilities: ReportCapabilities | null;
  capabilitiesError: string | null;
  reports: Report[];
  /** Called after the server accepted the upload (processing continues server-side). */
  onUploaded: (reportId: string) => Promise<void> | void;
  onReviewReport: (reportId: string) => void;
}

type Stage = 'select' | 'uploading' | 'processing' | 'ready' | 'failed' | 'upload_failed';

export function UploadReportDialog({
  open, onClose, capabilities, capabilitiesError, reports, onUploaded, onReviewReport,
}: UploadReportDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [docType, setDocType] = useState('Blood Test');
  const [title, setTitle] = useState('');
  const [laboratory, setLaboratory] = useState('');
  const [stage, setStage] = useState<Stage>('select');
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const handle = useRef<UploadHandle | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const formats = capabilities?.formats ?? [];
  const accept = formats.map((f) => `${f.extension},${f.mime_type}`).join(',');
  const formatList = formats.map((f) => f.label).join(', ');
  const maxBytes = capabilities?.max_bytes ?? 50 * 1024 * 1024;

  // Follow the uploaded report's server-side status.
  const tracked = reportId ? reports.find((r) => r.id === reportId) : undefined;
  useEffect(() => {
    if (!tracked || (stage !== 'processing' && stage !== 'failed')) return;
    if (tracked.status === 'needs_review' || tracked.status === 'extracted') {
      setStage('ready');
    } else if (tracked.status === 'failed' && stage !== 'failed') {
      setStage('failed');
      reportsApi.extraction(tracked.id)
        .then((ex) => setMessage(ex.warnings[0] ?? 'The document could not be processed.'))
        .catch(() => setMessage('The document could not be processed.'));
    } else if (tracked.status === 'processing' && stage === 'failed' && !retrying) {
      setStage('processing');
    }
  }, [tracked, stage, retrying]);

  const reset = () => {
    setFile(null);
    setFileError(null);
    setTitle('');
    setLaboratory('');
    setStage('select');
    setProgress(0);
    setMessage(null);
    setReportId(null);
  };

  const close = () => {
    if (stage === 'uploading') handle.current?.abort();
    reset();
    onClose();
  };

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    setFileError(null);
    const ext = `.${f.name.split('.').pop()?.toLowerCase() ?? ''}`;
    const okExt = formats.some((fmt) => fmt.extension === ext || (fmt.extension === '.jpg' && ext === '.jpeg'));
    const okType = !f.type || formats.some((fmt) => fmt.mime_type === f.type);
    if (!okExt || !okType) {
      setFile(null);
      setFileError(`Unsupported file type. Supported formats: ${formatList}.`);
      return;
    }
    if (f.size > maxBytes) {
      setFile(null);
      setFileError(`The file is ${formatBytes(f.size)}. The maximum size is ${formatBytes(maxBytes)}.`);
      return;
    }
    if (f.size === 0) {
      setFile(null);
      setFileError('The file is empty.');
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const start = async () => {
    if (!file) return;
    setStage('uploading');
    setProgress(0);
    setMessage(null);
    const h = uploadReport(file, { type: docType, title, laboratory }, setProgress);
    handle.current = h;
    try {
      const { id } = await h.promise;
      setReportId(String(id));
      setStage('processing');
      await onUploaded(String(id));
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setStage('select');
        setMessage('Upload cancelled. Nothing was saved.');
        return;
      }
      setStage('upload_failed');
      setMessage(errorMessage(err, 'The upload failed. Check your connection and try again.'));
    } finally {
      handle.current = null;
    }
  };

  const retryProcessing = async () => {
    if (!reportId) return;
    setRetrying(true);
    try {
      await reportsApi.retry(reportId);
      setMessage(null);
      await onUploaded(reportId);   // refresh first so the tracked status is current
      setStage('processing');
    } catch (err) {
      setMessage(errorMessage(err, 'Retry failed. Please try again.'));
    } finally {
      setRetrying(false);
    }
  };

  const busy = stage === 'uploading';
  const typeLabel = capabilities?.document_types.find((t) => t.value === docType)?.label ?? docType;

  const footer = (
    <>
      {stage === 'uploading' && (
        <Button variant="outline" onClick={() => handle.current?.abort()}>Cancel upload</Button>
      )}
      {(stage === 'select' || stage === 'upload_failed') && (
        <>
          <Button variant="ghost" onClick={close}>Cancel</Button>
          <Button onClick={start} disabled={!file || !capabilities} data-testid="upload-submit">
            <Upload className="h-4 w-4" />
            {stage === 'upload_failed' ? 'Try again' : 'Upload'}
          </Button>
        </>
      )}
      {stage === 'processing' && <Button variant="ghost" onClick={close}>Close</Button>}
      {stage === 'failed' && (
        <>
          <Button variant="ghost" onClick={close}>Close</Button>
          <Button onClick={retryProcessing} disabled={retrying}>{retrying ? 'Retrying…' : 'Retry processing'}</Button>
        </>
      )}
      {stage === 'ready' && (
        <>
          <Button variant="ghost" onClick={reset}>Upload another</Button>
          <Button onClick={() => { const id = reportId; close(); if (id) onReviewReport(id); }}>Review extracted content</Button>
        </>
      )}
    </>
  );

  return (
    <Modal
      open={open}
      onClose={busy ? () => undefined : close}
      title="Upload Report"
      description="Add a medical report. The original file is stored unchanged; extracted content is kept separately for your review."
      size="md"
      footer={footer}
    >
      <div className="space-y-4" data-testid="upload-dialog">
        {capabilitiesError && (
          <p className="rounded-lg bg-error-50 p-3 text-xs text-error-700 dark:bg-error-700/10 dark:text-error-400">{capabilitiesError}</p>
        )}

        {stage === 'select' || stage === 'upload_failed' ? (
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

        {stage !== 'select' && (
          <div className="space-y-2 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800" data-testid="upload-progress" aria-live="polite">
            <Step done={stage !== 'uploading' && stage !== 'upload_failed'} active={stage === 'uploading'} failed={stage === 'upload_failed'}
              label={stage === 'uploading' ? `Uploading… ${Math.round(progress * 100)}%` : stage === 'upload_failed' ? 'Upload failed' : 'Uploaded'} />
            {stage === 'uploading' && (
              <div className="h-1.5 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
                <div className="h-full bg-teal-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            )}
            {stage !== 'uploading' && stage !== 'upload_failed' && (
              <Step done={stage === 'ready'} active={stage === 'processing'} failed={stage === 'failed'}
                label={stage === 'processing' ? 'Extracting text (OCR is used for scanned pages)…'
                  : stage === 'failed' ? 'Processing failed' : 'Text extracted'} />
            )}
            {stage === 'ready' && (
              <Step done active={false} failed={false}
                label={tracked?.status === 'needs_review'
                  ? `${tracked.candidateCount ?? 0} value(s) found — ready for your review`
                  : 'Ready for your review'} />
            )}
          </div>
        )}
        {stage === 'processing' && (
          <p className="text-xs text-neutral-400">You can close this dialog; processing continues and the report list updates automatically.</p>
        )}
        {message && (
          <p className={`text-xs ${stage === 'select' ? 'text-neutral-500' : 'text-error-600'}`} role="alert" data-testid="upload-message">{message}</p>
        )}
      </div>
    </Modal>
  );
}

function Step({ done, active, failed, label }: { done: boolean; active: boolean; failed: boolean; label: string }) {
  const Icon = failed ? AlertTriangle : done ? CheckCircle2 : Loader2;
  const color = failed ? 'text-error-600' : done ? 'text-success-600' : active ? 'text-teal-600 dark:text-teal-400' : 'text-neutral-400';
  return (
    <div className={`flex items-center gap-2 text-xs ${color}`}>
      <Icon className={`h-3.5 w-3.5 ${active && !done && !failed ? 'animate-spin' : ''}`} />
      <span>{label}</span>
    </div>
  );
}
