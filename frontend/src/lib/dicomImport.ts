/** Bulk DICOM import helpers (pure; no React, no network). Mirrors backend/services/dicom_import.py. */

export type ImportSource = 'files' | 'folder' | 'zip';
export type ServerStage = 'receiving' | 'extracting' | 'validating' | 'grouping' | 'importing' | 'done' | 'failed' | 'cancelled';

export interface ImportCounts {
  files_received: number;
  bytes_received: number;
  files_validated: number;
  dicom_files: number;
  skipped_non_dicom: number;
  invalid_dicom: number;
  failed: number;
  to_import: number;
  instances_imported: number;
  duplicates: number;
  studies: number;
  series: number;
}

export interface ImportSeries {
  series_instance_uid: string;
  modality: string | null;
  description: string | null;
  series_number: number | null;
  instance_count: number;
  imported: number;
  duplicates: number;
}

export interface ImportStudy {
  study_instance_uid: string;
  modality: string | null;
  description: string | null;
  series_count: number;
  instance_count: number;
  series: ImportSeries[];
}

export interface ImportJob {
  id: string;
  source: ImportSource;
  stage: ServerStage;
  archive: { name: string; size: number; members: number } | null;
  counts: ImportCounts;
  studies: ImportStudy[];
  skipped: { name: string; reason: string }[];
  warnings: string[];
  error: string | null;
  limits: { max_files: number; max_batch_files: number; max_file_bytes: number; max_archive_bytes: number };
}

export const SOURCE_LABELS: Record<ImportSource, string> = { files: 'Files', folder: 'Folder', zip: 'ZIP' };

export const TERMINAL_STAGES: ServerStage[] = ['done', 'failed', 'cancelled'];

// Files a browser folder selection often contains that are certainly not DICOM images. Everything
// else — including names without an extension — is sent and identified by its content on the server.
const NOT_DICOM_EXTENSIONS = new Set([
  'txt', 'md', 'pdf', 'htm', 'html', 'xml', 'json', 'csv', 'tsv', 'log', 'ini', 'cfg', 'rtf', 'doc', 'docx',
  'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tif', 'tiff', 'webp', 'svg', 'ico',
  'mp4', 'avi', 'mov', 'mp3', 'wav', 'exe', 'dll', 'msi', 'bat', 'cmd', 'sh', 'js', 'css', 'zip', 'rar', '7z',
  'gz', 'tar', 'lnk', 'url', 'db', 'sqlite', 'nii', 'mhd',
]);
const NOT_DICOM_NAMES = new Set(['thumbs.db', 'desktop.ini', 'dicomdir', 'autorun.inf']);

/** True for files that are skipped in the browser without being uploaded (hidden, system, known non-DICOM types). */
export function isObviouslyNotDicom(path: string): boolean {
  const name = (path.split('/').pop() ?? '').toLowerCase();
  if (!name || name.startsWith('.') || NOT_DICOM_NAMES.has(name)) return true;
  if (path.toLowerCase().split('/').includes('__macosx')) return true;
  const dot = name.lastIndexOf('.');
  return dot > 0 && NOT_DICOM_EXTENSIONS.has(name.slice(dot + 1));
}

/** Relative path of a picked file: the folder-relative path for folder selections, else its name. */
export function relativePath(file: { name: string; webkitRelativePath?: string }): string {
  return file.webkitRelativePath || file.name;
}

/** Split files into upload requests of at most `maxFiles` files and (unless one file is larger) `maxBytes`. */
export function planBatches(sizes: number[], maxFiles: number, maxBytes: number): number[][] {
  const batches: number[][] = [];
  let current: number[] = [];
  let bytes = 0;
  sizes.forEach((size, index) => {
    if (current.length && (current.length >= maxFiles || bytes + size > maxBytes)) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(index);
    bytes += size;
  });
  if (current.length) batches.push(current);
  return batches;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

export type StepKey = 'preparing' | 'uploading' | 'validating' | 'grouping' | 'importing' | 'refreshing' | 'ready';
export type StepState = 'pending' | 'active' | 'done' | 'error';

export const STEPS: { key: StepKey; label: string }[] = [
  { key: 'preparing', label: 'Preparing files' },
  { key: 'uploading', label: 'Uploading' },
  { key: 'validating', label: 'Validating DICOM' },
  { key: 'grouping', label: 'Grouping studies/series' },
  { key: 'importing', label: 'Importing' },
  { key: 'refreshing', label: 'Refreshing studies' },
  { key: 'ready', label: 'Ready' },
];

/** Where the import is: the browser's phase, then the server stage once the upload is complete. */
export type ImportPhase = 'preparing' | 'uploading' | 'server' | 'refreshing' | 'ready';

/**
 * State of each progress step. Files and folders are validated by the server as each batch arrives,
 * so for them Validating runs together with Uploading; a ZIP is validated after it is extracted.
 */
export function stepStates(source: ImportSource, phase: ImportPhase, stage: ServerStage | null, failed: boolean): Record<StepKey, StepState> {
  const order: StepKey[] = STEPS.map((s) => s.key);
  let current: StepKey;
  if (phase === 'server') {
    current = stage === 'extracting' || stage === 'validating' ? 'validating'
      : stage === 'grouping' ? 'grouping'
      : stage === 'importing' ? 'importing'
      : stage === 'done' ? 'refreshing' : 'validating';
  } else {
    current = phase;
  }
  const at = order.indexOf(current);
  const states = {} as Record<StepKey, StepState>;
  order.forEach((key, i) => {
    states[key] = i < at ? 'done' : i === at ? (failed ? 'error' : phase === 'ready' ? 'done' : 'active') : 'pending';
  });
  if (source !== 'zip' && phase === 'uploading' && !failed) states.validating = 'active';
  return states;
}

export interface ImportTotals {
  studies: number;
  series: number;
  instances: number;
  duplicates: number;
  skippedNonDicom: number;
  invalid: number;
  failed: number;
}

/** Final numbers for the summary; files skipped or rejected in the browser are included. */
export function importTotals(job: ImportJob, browserSkipped: number, browserFailed: number): ImportTotals {
  const c = job.counts;
  return {
    studies: c.studies,
    series: c.series,
    instances: c.instances_imported,
    duplicates: c.duplicates,
    skippedNonDicom: c.skipped_non_dicom + browserSkipped,
    invalid: c.invalid_dicom,
    failed: c.failed + browserFailed,
  };
}

const count = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export function summaryLines(t: ImportTotals): { imported: string[]; skipped: string[] } {
  const imported = [count(t.studies, 'study', 'studies'), count(t.series, 'series', 'series'),
    count(t.instances, 'instance', 'instances')];
  if (t.duplicates) imported.push(`${count(t.duplicates, 'instance', 'instances')} already present (not duplicated)`);
  const skipped: string[] = [];
  if (t.skippedNonDicom) skipped.push(count(t.skippedNonDicom, 'non-DICOM file', 'non-DICOM files'));
  if (t.invalid) skipped.push(count(t.invalid, 'invalid DICOM file', 'invalid DICOM files'));
  if (t.failed) skipped.push(`${count(t.failed, 'file', 'files')} failed`);
  return { imported, skipped };
}

/** The study to show after an import: the first study that received instances, else the first study. */
export function importedStudyUid(job: ImportJob): string | null {
  const withImages = job.studies.find((s) => s.series.some((se) => se.imported + se.duplicates > 0));
  return (withImages ?? job.studies[0])?.study_instance_uid ?? null;
}
