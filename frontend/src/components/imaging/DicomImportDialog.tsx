import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import {
  AlertTriangle, Check, Circle, FileArchive, Files, FolderOpen, Loader2, ScanLine, X,
} from 'lucide-react';
import { Modal } from '@/components/Modal';
import { Button } from '@/components/Button';
import { StatusBadge } from '@/components/StatusBadge';
import { api, ApiError, uploadWithProgress } from '@/lib/api';
import {
  formatBytes, importedStudyUid, importTotals, isObviouslyNotDicom, planBatches, relativePath, SOURCE_LABELS,
  STEPS, stepStates, summaryLines, TERMINAL_STAGES, type ImportJob, type ImportPhase, type ImportSource,
} from '@/lib/dicomImport';
import type { PatientSummary } from '@/lib/patients';

interface DicomImportDialogProps {
  open: boolean;
  onClose: () => void;
  patient: PatientSummary;
  /** Refreshes the patient's study list (and selects the study); awaited as the "Refreshing studies" step. */
  onImported: (studyInstanceUid: string | null) => Promise<void>;
  onOpenInOhif: (studyInstanceUid: string) => void;
}

interface Selection {
  source: ImportSource;
  files: File[];
  bytes: number;
  folder?: string;
}

type Phase = 'select' | ImportPhase;

const BATCH_FILES = 50;
const BATCH_BYTES = 48 * 1024 * 1024;
const POLL_MS = 500;

const OPTIONS: { source: ImportSource; title: string; hint: string; icon: typeof Files }[] = [
  { source: 'files', title: 'Select DICOM Files', hint: 'One or more DICOM files', icon: Files },
  { source: 'folder', title: 'Select DICOM Folder', hint: 'A folder and all its subfolders', icon: FolderOpen },
  { source: 'zip', title: 'Select ZIP Archive', hint: 'One .zip containing a study', icon: FileArchive },
];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const isAbort = (err: unknown) => err instanceof DOMException && err.name === 'AbortError';

/**
 * Imports a complete study into the selected patient from DICOM files, a folder or one ZIP archive.
 * Files are validated by the backend (by content, not extension), grouped study → series → instance
 * and stored in the patient's existing DICOM storage, from where OHIF loads them over DICOMweb.
 */
export function DicomImportDialog({ open, onClose, patient, onImported, onOpenInOhif }: DicomImportDialogProps) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [phase, setPhase] = useState<Phase>('select');
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [uploaded, setUploaded] = useState({ bytes: 0, total: 0, files: 0 });
  const [browser, setBrowser] = useState({ skipped: 0, failed: 0 });
  const abortRef = useRef<AbortController | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);
  const base = `/api/v1/patients/${patient.id}/imaging/imports`;
  const running = phase !== 'select' && phase !== 'ready' && !error && !cancelled;

  // Folder selection: React has no typed prop for these attributes.
  useEffect(() => {
    folderRef.current?.setAttribute('webkitdirectory', '');
    folderRef.current?.setAttribute('directory', '');
  }, [open]);

  const reset = () => {
    setSelection(null);
    setPhase('select');
    setJob(null);
    setError(null);
    setCancelled(false);
    setUploaded({ bytes: 0, total: 0, files: 0 });
    setBrowser({ skipped: 0, failed: 0 });
    jobIdRef.current = null;
    abortRef.current = null;
  };

  const close = () => {
    if (running) return;      // an import in progress is stopped with "Cancel import", not by dismissing
    reset();
    onClose();
  };

  const pick = (source: ImportSource) => (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (!files.length) return;
    setError(null);
    if (source === 'zip') {
      const zip = files[0];
      if (!/\.zip$/i.test(zip.name)) {
        setError(`${zip.name} is not a .zip archive.`);
        return;
      }
      setSelection({ source, files: [zip], bytes: zip.size });
      return;
    }
    const folder = source === 'folder' ? relativePath(files[0]).split('/')[0] : undefined;
    setSelection({ source, files, bytes: files.reduce((n, f) => n + f.size, 0), folder });
  };

  const poll = async (jobId: string): Promise<ImportJob> => {
    for (;;) {
      await sleep(POLL_MS);
      const current = await api.get<ImportJob>(`${base}/${jobId}`);
      setJob(current);
      if (TERMINAL_STAGES.includes(current.stage)) return current;
    }
  };

  const run = async () => {
    if (!selection) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase('preparing');
    setError(null);
    try {
      let created = await api.post<ImportJob>(base, { source: selection.source });
      jobIdRef.current = created.id;
      setJob(created);
      const maxFile = created.limits.max_file_bytes;

      setPhase('uploading');
      if (selection.source === 'zip') {
        const zip = selection.files[0];
        setUploaded({ bytes: 0, total: zip.size, files: 0 });
        created = await uploadWithProgress<ImportJob>('PUT', `${base}/${created.id}/archive?filename=${encodeURIComponent(zip.name)}`, zip, {
          contentType: 'application/zip', signal: controller.signal,
          onProgress: (loaded) => setUploaded({ bytes: loaded, total: zip.size, files: 0 }),
        });
        setUploaded({ bytes: zip.size, total: zip.size, files: created.counts.files_received });
        setJob(created);
      } else {
        // Obvious non-DICOM files are skipped here; files over the per-file limit are not sent.
        const skipped = selection.files.filter((f) => isObviouslyNotDicom(relativePath(f))).length;
        const sendable = selection.files.filter((f) => !isObviouslyNotDicom(relativePath(f)));
        const tooLarge = sendable.filter((f) => f.size > maxFile).length;
        const files = sendable.filter((f) => f.size <= maxFile);
        setBrowser({ skipped, failed: tooLarge });
        if (!files.length) throw new Error('None of the selected files can be DICOM images.');
        const total = files.reduce((n, f) => n + f.size, 0);
        let sentBytes = 0;
        let sentFiles = 0;
        for (const batch of planBatches(files.map((f) => f.size), Math.min(BATCH_FILES, created.limits.max_batch_files), BATCH_BYTES)) {
          const form = new FormData();
          for (const i of batch) form.append('files', files[i], relativePath(files[i]));
          const batchBytes = batch.reduce((n, i) => n + files[i].size, 0);
          created = await uploadWithProgress<ImportJob>('POST', `${base}/${created.id}/files`, form, {
            signal: controller.signal,
            onProgress: (loaded, size) => setUploaded({ bytes: sentBytes + Math.min(batchBytes, size ? (loaded / size) * batchBytes : 0), total, files: sentFiles }),
          });
          sentBytes += batchBytes;
          sentFiles += batch.length;
          setUploaded({ bytes: sentBytes, total, files: sentFiles });
          setJob(created);
        }
      }

      setPhase('server');
      await api.post(`${base}/${created.id}/start`, {});
      const finished = await poll(created.id);
      if (finished.stage === 'failed') {
        setError(finished.error ?? 'Import failed.');
        return;
      }
      if (finished.stage === 'cancelled') setCancelled(true);
      if (finished.counts.instances_imported + finished.counts.duplicates > 0) {
        setPhase('refreshing');
        await onImported(importedStudyUid(finished));
      }
      if (finished.stage === 'done') setPhase('ready');
    } catch (err) {
      if (isAbort(err) || controller.signal.aborted) {
        setCancelled(true);
      } else {
        setError(err instanceof ApiError ? err.detail : err instanceof Error ? err.message : 'Import failed.');
        // The server ends a rejected import itself; this also stops one that failed in the browser.
        if (jobIdRef.current) api.delete(`${base}/${jobIdRef.current}`).catch(() => undefined);
      }
    }
  };

  const cancel = async () => {
    abortRef.current?.abort();
    const jobId = jobIdRef.current;
    if (!jobId) {
      setCancelled(true);
      return;
    }
    try {
      setJob(await api.delete<ImportJob>(`${base}/${jobId}`));
    } catch {
      /* the import may already have finished */
    }
    if (phase !== 'server') setCancelled(true);   // while importing, polling reports the cancellation
  };

  const counts = job?.counts;
  const states = stepStates(selection?.source ?? 'files', phase === 'select' ? 'preparing' : phase, job?.stage ?? null, !!error || cancelled);
  const totals = job ? importTotals(job, browser.skipped, browser.failed) : null;
  const lines = totals ? summaryLines(totals) : null;
  const shownStudy = job ? importedStudyUid(job) : null;
  const finished = phase === 'ready' || !!error || cancelled;
  const discovered = selection?.source === 'zip' ? (job?.archive?.members ?? null) : selection?.files.length ?? 0;
  const tiles: { key: string; label: string; value: string | number }[] = counts ? [
    { key: 'discovered', label: 'Files discovered', value: discovered ?? '—' },
    { key: 'uploaded', label: 'Files uploaded', value: selection?.source === 'zip' ? (job?.archive ? `${counts.files_received} in ZIP` : '—') : uploaded.files },
    { key: 'validated', label: 'Files validated', value: counts.files_validated },
    { key: 'studies', label: 'Studies', value: counts.studies },
    { key: 'series', label: 'Series', value: counts.series },
    { key: 'instances', label: 'Instances', value: counts.to_import ? `${counts.instances_imported + counts.duplicates} / ${counts.to_import}` : counts.dicom_files },
    { key: 'skipped', label: 'Skipped', value: counts.skipped_non_dicom + counts.invalid_dicom + browser.skipped },
    { key: 'failed', label: 'Failed', value: counts.failed + browser.failed },
  ] : [];

  const footer = phase === 'select' ? (
    <>
      <Button variant="secondary" onClick={close}>Cancel</Button>
      <Button onClick={run} disabled={!selection} data-testid="import-start">
        {selection?.source === 'zip' ? 'Import archive' : `Import ${selection ? selection.files.length.toLocaleString() : ''} file${selection?.files.length === 1 ? '' : 's'}`}
      </Button>
    </>
  ) : running ? (
    <Button variant="danger" onClick={cancel} data-testid="import-cancel"><X className="h-4 w-4" /> Cancel import</Button>
  ) : (
    <>
      <Button variant="secondary" onClick={reset}>Import more</Button>
      {shownStudy && (job?.counts.instances_imported || job?.counts.duplicates) ? (
        <Button variant="outline" onClick={() => { onOpenInOhif(shownStudy); close(); }} data-testid="import-open-ohif">
          <ScanLine className="h-4 w-4" /> Open in OHIF Viewer
        </Button>
      ) : null}
      <Button onClick={close}>Close</Button>
    </>
  );

  return (
    <Modal open={open} onClose={close} size="lg" title="Import DICOM study"
      description={`Images are stored for ${patient.patient_code} · ${patient.name}. Patient details inside the DICOM files do not change the selected patient.`}
      footer={footer}>
      <input ref={filesRef} type="file" multiple accept=".dcm,.dicom,application/dicom" className="hidden" onChange={pick('files')} data-testid="import-input-files" />
      <input ref={folderRef} type="file" multiple className="hidden" onChange={pick('folder')} data-testid="import-input-folder" />
      <input ref={zipRef} type="file" accept=".zip,application/zip,application/x-zip-compressed" className="hidden" onChange={pick('zip')} data-testid="import-input-zip" />

      {phase === 'select' ? (
        <div className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="Import source">
            {OPTIONS.map(({ source, title, hint, icon: Icon }) => (
              <button
                key={source}
                type="button"
                onClick={() => (source === 'files' ? filesRef : source === 'folder' ? folderRef : zipRef).current?.click()}
                aria-pressed={selection?.source === source}
                data-testid={`import-pick-${source}`}
                className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors ${
                  selection?.source === source
                    ? 'border-teal-500 bg-teal-50 dark:border-teal-500/70 dark:bg-teal-950/30'
                    : 'border-neutral-200 hover:border-teal-300 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800/60'
                }`}
              >
                <span className="flex items-center gap-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">
                  <Icon className="h-4 w-4 text-teal-600 dark:text-teal-400" /> {title}
                </span>
                <span className="text-xs text-neutral-500 dark:text-neutral-400">{hint}</span>
                <StatusBadge variant="neutral" className="mt-1">{SOURCE_LABELS[source]}</StatusBadge>
              </button>
            ))}
          </div>
          {selection && (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm dark:border-neutral-700 dark:bg-neutral-800/50" data-testid="import-selection">
              <div className="flex items-center gap-2">
                <StatusBadge variant="info">{SOURCE_LABELS[selection.source]}</StatusBadge>
                <span className="truncate font-medium text-neutral-900 dark:text-neutral-100">
                  {selection.source === 'zip' ? selection.files[0].name : selection.folder ?? `${selection.files.length} file${selection.files.length === 1 ? '' : 's'}`}
                </span>
              </div>
              <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                {selection.source === 'zip'
                  ? `ZIP archive · ${formatBytes(selection.bytes)} · extracted and checked on the server`
                  : `${selection.files.length.toLocaleString()} file${selection.files.length === 1 ? '' : 's'} · ${formatBytes(selection.bytes)}`
                    + (selection.source === 'folder' ? ' · including subfolders' : '')}
              </p>
            </div>
          )}
          {error && <p className="text-sm text-error-600 dark:text-red-400" role="alert">{error}</p>}
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            DICOM is recognised by its content, so files without a .dcm extension are included. Instances already stored for this patient are not duplicated.
          </p>
        </div>
      ) : (
        <div className="space-y-4" data-testid="import-progress" data-phase={phase} data-stage={job?.stage ?? ''}>
          <ol className="grid gap-1.5 sm:grid-cols-2">
            {STEPS.map(({ key, label }) => {
              const state = states[key];
              return (
                <li key={key} className="flex items-center gap-2 text-sm" data-step={key} data-state={state}>
                  {state === 'done' ? <Check className="h-4 w-4 text-teal-600" />
                    : state === 'active' ? <Loader2 className="h-4 w-4 animate-spin text-teal-600" />
                    : state === 'error' ? <AlertTriangle className="h-4 w-4 text-error-600" />
                    : <Circle className="h-4 w-4 text-neutral-300 dark:text-neutral-600" />}
                  <span className={state === 'pending' ? 'text-neutral-400' : 'text-neutral-800 dark:text-neutral-200'}>
                    {label}
                    {key === 'validating' && job?.stage === 'extracting' ? ' (extracting archive)' : ''}
                  </span>
                </li>
              );
            })}
          </ol>
          {phase === 'uploading' && uploaded.total > 0 && (
            <div>
              <div className="h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
                <div className="h-full bg-teal-500 transition-[width]" style={{ width: `${Math.round((uploaded.bytes / uploaded.total) * 100)}%` }} />
              </div>
              <p className="mt-1 text-xs text-neutral-500">{formatBytes(uploaded.bytes)} of {formatBytes(uploaded.total)}</p>
            </div>
          )}
          {tiles.length > 0 && (
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {tiles.map((t) => (
                <div key={t.key} className="rounded-lg bg-neutral-50 p-2 dark:bg-neutral-800/50" data-testid={`import-count-${t.key}`}>
                  <dt className="text-[11px] text-neutral-500 dark:text-neutral-400">{t.label}</dt>
                  <dd className="text-sm font-semibold tabular-nums text-neutral-900 dark:text-neutral-100">{typeof t.value === 'number' ? t.value.toLocaleString() : t.value}</dd>
                </div>
              ))}
            </dl>
          )}
          {error && (
            <div className="rounded-lg border border-error-100 bg-error-50 p-3 text-sm text-error-700 dark:border-error-700/30 dark:bg-error-700/10 dark:text-red-300" role="alert" data-testid="import-error">
              {error}
            </div>
          )}
          {cancelled && (
            <p className="text-sm text-neutral-600 dark:text-neutral-300" role="status" data-testid="import-cancelled">
              Import cancelled.{job?.counts.instances_imported ? ` ${job.counts.instances_imported} instance(s) imported before cancelling were kept.` : ' Nothing was imported.'}
            </p>
          )}
          {finished && lines && !error && (
            <div className="space-y-2 rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-700" data-testid="import-summary">
              <div>
                <p className="font-semibold text-neutral-900 dark:text-neutral-100">Imported:</p>
                <ul className="ml-4 list-disc text-neutral-700 dark:text-neutral-300">{lines.imported.map((l) => <li key={l}>{l}</li>)}</ul>
              </div>
              {lines.skipped.length > 0 && (
                <div>
                  <p className="font-semibold text-neutral-900 dark:text-neutral-100">Skipped:</p>
                  <ul className="ml-4 list-disc text-neutral-700 dark:text-neutral-300">{lines.skipped.map((l) => <li key={l}>{l}</li>)}</ul>
                </div>
              )}
              {job && job.studies.length > 0 && (
                <ul className="space-y-1 text-xs text-neutral-600 dark:text-neutral-400" data-testid="import-studies">
                  {job.studies.map((s) => (
                    <li key={s.study_instance_uid}>
                      <span className="font-medium text-neutral-800 dark:text-neutral-200">{s.description ?? 'Study'}</span> · {s.modality ?? '—'} · {s.series_count} series · {s.instance_count} instances
                      <ul className="ml-4">
                        {s.series.map((se) => (
                          <li key={se.series_instance_uid}>{se.modality ?? '—'} {se.description ?? ''} — {se.instance_count} instance{se.instance_count === 1 ? '' : 's'}</li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {job && job.warnings.length > 0 && (
            <ul className="space-y-1 rounded-lg border border-amber-200 bg-warning-50 p-3 text-xs text-amber-800 dark:border-warning-700/30 dark:bg-warning-700/10 dark:text-amber-300" data-testid="import-warnings">
              {job.warnings.map((w) => <li key={w} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</li>)}
            </ul>
          )}
          {finished && job && job.skipped.length > 0 && (
            <details className="text-xs text-neutral-500 dark:text-neutral-400">
              <summary className="cursor-pointer">Files not imported ({job.skipped.length}{job.skipped.length >= 100 ? '+' : ''})</summary>
              <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
                {job.skipped.map((s, i) => <li key={`${s.name}-${i}`} className="break-all"><span className="font-mono">{s.name}</span> — {s.reason}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </Modal>
  );
}
