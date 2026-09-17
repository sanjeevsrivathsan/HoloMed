/**
 * Medical report ingestion client (upload → extraction → review → summary).
 *
 * Uses the same-origin session cookie; no tokens are handled here.
 */
import { api, ApiError } from '@/lib/api';
import type { MeasurementFlag, Report, ReportStatus, ReportSummary, ReviewStatus as ReportReviewStatus, SummaryMode } from '@/lib/types';
import type { ProcessingStage, TextAiState } from '@/lib/processingStages';
import { dateKindLabels, type DetectedDate } from '@/lib/reportDates';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';

export const AI_SAFETY_MESSAGE =
  'AI-generated information — not a diagnosis. Consult a qualified healthcare professional.';

export interface ReportCapabilities {
  formats: { extension: string; mime_type: string; label: string }[];
  max_bytes: number;
  ocr_available: boolean;
  document_types: { value: string; label: string }[];
}

export type ReviewStatus = 'pending' | 'accepted' | 'rejected' | 'confirmed';

export interface ExtractedCandidate {
  id: number;
  test_name: string;
  source_name: string;
  value: number | null;
  value_text: string;
  unit: string;
  reference_range: string | null;
  flag: MeasurementFlag;
  confidence: 'high' | 'medium' | 'low';
  page: number | null;
  line_text: string;
  review_status: ReviewStatus;
  edited: boolean;
  measurement_id: number | null;
}

export interface ReportExtraction {
  report_id: number;
  status: 'pending' | 'processing' | 'succeeded' | 'failed';
  /** Last stage entered (on failure: the stage that failed). */
  stage: string | null;
  stages: ProcessingStage[];
  method: 'pdf_text' | 'ocr' | 'pdf_text+ocr' | 'none';
  quality: 'good' | 'low' | 'unknown';
  page_count: number;
  char_count: number;
  text: string;
  document_date: string | null;
  date_candidates: DateCandidate[];
  error_code: string | null;
  warnings: string[];
  timings: Record<string, number>;
  candidates: ExtractedCandidate[];
}

export type DateCandidate = DetectedDate;

export type CandidateUpdate = Partial<Pick<ExtractedCandidate, 'test_name' | 'value' | 'unit' | 'reference_range' | 'flag'>> & {
  review_status?: Exclude<ReviewStatus, 'confirmed'>;
};

export const reportStatusLabels: Record<ReportStatus, string> = {
  uploaded: 'Processing',
  processing: 'Processing',
  extracted: 'Needs review',
  needs_review: 'Needs review',
  partially_confirmed: 'Partially confirmed',
  confirmed: 'Confirmed',
  completed: 'Confirmed',
  failed: 'Processing failed',
  ready: 'Confirmed',
};

export const reviewStatusLabels: Record<ReportReviewStatus, string> = {
  needs_review: 'Needs review',
  partially_confirmed: 'Partially confirmed',
  confirmed: 'Confirmed',
};

/** Two-part status: processing state · review state, e.g. "Processed · 9 values confirmed". */
export function reportStatusText(report: Report): string {
  const processing = report.processingStatus ?? (isProcessing(report.status) ? 'processing'
    : report.status === 'failed' ? 'failed' : 'processed');
  if (processing === 'processing') return 'Processing';
  if (processing === 'failed') return 'Processing failed';
  const confirmed = report.measurementCount ?? 0;
  const review = report.reviewStatus;
  if (review === 'confirmed') {
    return confirmed > 0 ? `Processed · ${confirmed} value${confirmed === 1 ? '' : 's'} confirmed` : 'Processed · Reviewed';
  }
  if (review === 'partially_confirmed') return `Processed · ${confirmed} confirmed · ${report.pendingCount ?? 0} to review`;
  return 'Processed · Needs review';
}

export function reportStatusShort(report: Report): string {
  const processing = report.processingStatus;
  if (processing === 'processing') return 'Processing';
  if (processing === 'failed') return 'Failed';
  return report.reviewStatus ? reviewStatusLabels[report.reviewStatus] : reportStatusLabels[report.status];
}

export function reportVariant(report: Report): 'success' | 'warning' | 'error' | 'info' | 'processing' {
  if (report.processingStatus === 'processing') return 'processing';
  if (report.processingStatus === 'failed') return 'error';
  if (report.reviewStatus === 'confirmed') return 'success';
  if (report.reviewStatus === 'partially_confirmed') return 'info';
  if (report.reviewStatus === 'needs_review') return 'warning';
  return statusVariant(report.status);
}

export const dateSourceLabels: Record<string, string> = {
  extracted: 'Detected from the report and confirmed by you',
  user_override: 'Entered by you (differs from the detected date)',
  user_entered: 'Entered at upload',
  upload_default: 'Upload date (no date confirmed yet)',
};

export { dateKindLabels };

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export const extractionMethodLabels: Record<ReportExtraction['method'], string> = {
  pdf_text: 'PDF text layer',
  ocr: 'OCR (scanned document)',
  'pdf_text+ocr': 'PDF text layer + OCR',
  none: 'Not extracted',
};

export const flagLabels: Record<MeasurementFlag, string> = {
  high: 'Marked high',
  low: 'Marked low',
  abnormal: 'Marked abnormal',
  normal: 'Marked normal',
  unknown: 'Not flagged',
};

export function isProcessing(status: ReportStatus): boolean {
  return status === 'uploaded' || status === 'processing';
}

export function isReviewable(status: ReportStatus): boolean {
  return status === 'extracted' || status === 'needs_review' || status === 'partially_confirmed';
}

export function statusVariant(status: ReportStatus): 'success' | 'warning' | 'error' | 'info' | 'processing' {
  if (status === 'completed' || status === 'ready' || status === 'confirmed') return 'success';
  if (status === 'partially_confirmed') return 'info';
  if (status === 'failed') return 'error';
  if (status === 'needs_review' || status === 'extracted') return 'warning';
  return 'processing';
}

export function flagVariant(flag: string): 'warning' | 'neutral' | 'success' {
  if (flag === 'high' || flag === 'low' || flag === 'abnormal') return 'warning';
  if (flag === 'normal') return 'success';
  return 'neutral';
}

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return 'The server could not be reached. Check your connection and try again.';
    if (typeof err.detail === 'string' && err.detail && err.status < 500) return err.detail;
    if (err.status === 503 || err.status === 502) return err.detail || fallback;
  }
  return fallback;
}

export interface UploadFields {
  type: string;
  title?: string;
  laboratory?: string;
  hospital?: string;
}

export interface UploadHandle {
  promise: Promise<{ id: number }>;
  abort: () => void;
}

/** Upload with progress + cancel (XMLHttpRequest; fetch has no upload progress). */
export function uploadReport(file: File, fields: UploadFields, onProgress: (fraction: number) => void): UploadHandle {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<{ id: number }>((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);
    form.append('type', fields.type);
    if (fields.title?.trim()) form.append('title', fields.title.trim());
    if (fields.laboratory?.trim()) form.append('laboratory', fields.laboratory.trim());
    if (fields.hospital?.trim()) form.append('hospital', fields.hospital.trim());
    xhr.open('POST', `${API_BASE}/api/v1/reports`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let body: { id?: number; detail?: unknown } = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300 && typeof body.id === 'number') {
        resolve({ id: body.id });
      } else {
        const detail = typeof body.detail === 'string' ? body.detail : xhr.statusText || 'Upload failed';
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, 'Network error'));
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

export const reportsApi = {
  capabilities: () => api.get<ReportCapabilities>('/api/v1/reports/capabilities'),
  extraction: (id: string) => api.get<ReportExtraction>(`/api/v1/reports/${id}/extraction`),
  retry: (id: string) => api.postEmpty<unknown>(`/api/v1/reports/${id}/extraction/retry`),
  updateCandidate: (id: string, candidateId: number, body: CandidateUpdate) =>
    api.patch<ExtractedCandidate>(`/api/v1/reports/${id}/candidates/${candidateId}`, body),
  confirmDate: (id: string, reportDate: string) =>
    api.post<unknown>(`/api/v1/reports/${id}/date/confirm`, { report_date: reportDate }),
  confirmCandidate: (id: string, candidateId: number) =>
    api.postEmpty<ExtractedCandidate>(`/api/v1/reports/${id}/candidates/${candidateId}/confirm`),
  confirmCandidates: (id: string, candidateIds: number[]) =>
    api.post<{ report_id: number; status: ReportStatus; review_status: ReportReviewStatus | null; measurements_created: number }>(
      `/api/v1/reports/${id}/review/confirm`, { candidate_ids: candidateIds }),
  summarize: (id: string, mode: SummaryMode) => {
    const form = new FormData();
    form.append('mode', mode);
    return api.postMultipart<unknown>(`/api/v1/reports/${id}/summary`, form);
  },
  remove: (id: string) => api.delete<unknown>(`/api/v1/reports/${id}`),
  textAiStatus: () => api.get<{ provider: string; model: string | null; status: TextAiState }>('/api/v1/ai/status'),
  demoStatus: () => api.get<{ loaded: boolean; report_count: number }>('/api/v1/demo'),
  loadDemo: () => api.postEmpty<{ loaded: boolean; report_ids: number[] }>('/api/v1/demo/load'),
  clearDemo: () => api.delete<{ loaded: boolean; removed: number }>('/api/v1/demo'),
};

/** Backend report row (GET /api/v1/reports) → UI shape. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function summaryFromBackend(reportId: string, s: any): ReportSummary | undefined {
  if (!s) return undefined;
  return {
    id: String(s.id),
    reportId,
    mode: s.mode as SummaryMode,
    sections: typeof s.sections === 'string' ? JSON.parse(s.sections) : s.sections,
    createdAt: s.created_at,
    safetyMessage: s.safety_message ?? AI_SAFETY_MESSAGE,
    generator: s.generator ?? null,
  };
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export const DEMO_SOURCE = 'HoloMed demo (synthetic)';
