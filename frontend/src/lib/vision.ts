/**
 * Chest X-ray AI screening client — POST /api/v1/vision/screen.
 *
 * Types mirror backend/services/vision/schemas.py (VisionScreenResponse).
 * The browser only talks to the HoloMed backend (session cookie via api.ts);
 * image bytes are sent once per request and never stored client-side.
 */

import { api, ApiError } from '@/lib/api';

// ─── Response schema (backend/services/vision/schemas.py) ─────────────────────

export interface VisionModelInfo {
  name: string;
  architecture: string;
  weights: string;
  weight_sha256: string;
  targets: number;
  target_list: string[];
  device: string;
  input_size: number;
  score_semantics: string;
}

export interface VisionInputInfo {
  format: 'png' | 'jpeg' | 'dicom';
  width: number;
  height: number;
  source_mode: string;
  bits_stored: number | null;
  modality: string | null;
  transfer_syntax: string | null;
  preprocessing: string[];
}

export interface VisionFinding {
  pathology: string;
  score: number;
}

export interface EncodedImage {
  media_type: 'image/png';
  encoding: 'base64';
  width: number;
  height: number;
  data: string;
}

export interface VisionExplanation {
  method: 'Grad-CAM';
  target_pathology: string;
  target_score: number;
  target_layer: string;
  description: string;
  original: EncodedImage;
  heatmap: EncodedImage;
  overlay: EncodedImage;
}

export interface VisionTiming {
  preprocessing_ms: number;
  inference_ms: number;
  gradcam_ms: number;
  rendering_ms: number;
  total_ms: number;
}

export interface VisionSafety {
  message: string;
  requires_clinical_review: boolean;
}

export interface VisionScreenResponse {
  model: VisionModelInfo;
  input: VisionInputInfo;
  primary_finding: VisionFinding;
  findings: VisionFinding[];
  explanation: VisionExplanation;
  timing: VisionTiming;
  inferred_at: string;
  safety: VisionSafety;
}

/** A screening response plus the browser-measured round-trip time. */
export interface ScreeningRun {
  response: VisionScreenResponse;
  roundTripMs: number;
}

// ─── Client-side validation (the backend re-validates everything) ─────────────

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // matches VISION_MAX_UPLOAD_BYTES default
export const ACCEPT_ATTR = '.png,.jpg,.jpeg,.dcm,.dicom,image/png,image/jpeg,application/dicom';
const REQUEST_TIMEOUT_MS = 90_000;

export type DetectedFormat = 'png' | 'jpeg' | 'dicom';

/** Identify PNG / JPEG / DICOM Part 10 from the file signature. */
export async function detectFormat(file: File): Promise<DetectedFormat | null> {
  const head = new Uint8Array(await file.slice(0, 132).arrayBuffer());
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (png.every((b, i) => head[i] === b)) return 'png';
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return 'jpeg';
  if (head.length >= 132 && String.fromCharCode(...head.slice(128, 132)) === 'DICM') return 'dicom';
  return null;
}

export async function validateUpload(file: File): Promise<{ format: DetectedFormat } | { error: string }> {
  if (file.size === 0) return { error: 'The selected file is empty.' };
  if (file.size > MAX_UPLOAD_BYTES) return { error: 'The file is larger than the 50 MB upload limit.' };
  const format = await detectFormat(file);
  if (!format) {
    return { error: 'Unsupported file type. Select a PNG, JPEG, or DICOM (.dcm) chest X-ray.' };
  }
  return { format };
}

// ─── Request ──────────────────────────────────────────────────────────────────

export async function screenChestXray(file: File, target?: string): Promise<ScreeningRun> {
  const form = new FormData();
  form.append('file', file);
  if (target) form.append('target', target);

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const started = performance.now();
  try {
    const response = await api.postMultipart<VisionScreenResponse>(
      '/api/v1/vision/screen', form, { signal: controller.signal },
    );
    return { response, roundTripMs: performance.now() - started };
  } finally {
    window.clearTimeout(timer);
  }
}

// ─── Error mapping (never surface raw server text) ────────────────────────────

export interface ScreeningError {
  title: string;
  message: string;
  kind: 'auth' | 'input' | 'unavailable' | 'network' | 'timeout' | 'unknown';
}

export function describeScreeningError(err: unknown): ScreeningError {
  if (err instanceof DOMException && err.name === 'AbortError') {
    return { kind: 'timeout', title: 'Request timed out', message: 'The screening request took too long. Please try again.' };
  }
  if (err instanceof ApiError) {
    const detail = typeof err.detail === 'string' ? err.detail.toLowerCase() : '';
    switch (err.status) {
      case 401:
        return { kind: 'auth', title: 'Session expired', message: 'Your session has ended. Please sign in again to run AI screening.' };
      case 400:
        return { kind: 'input', title: 'Image could not be read', message: 'The file appears to be corrupt, incomplete, or empty. Please select another image.' };
      case 413:
        return { kind: 'input', title: 'File too large', message: 'The file is larger than the 50 MB upload limit.' };
      case 415:
        return { kind: 'input', title: 'Unsupported file type', message: 'Select a PNG, JPEG, or DICOM (.dcm) chest X-ray.' };
      case 422:
        if (detail.includes('target')) {
          return { kind: 'input', title: 'Finding not available', message: 'The selected finding is not an output of this model.' };
        }
        return {
          kind: 'input',
          title: 'Image not supported for screening',
          message: 'Screening requires a single-frame grayscale chest radiograph (DICOM CR/DX, PNG, or JPEG) at least 64 px on each side.',
        };
      case 500:
      case 502:
      case 503:
      case 504:
        return { kind: 'unavailable', title: 'Screening unavailable', message: 'Screening service is temporarily unavailable. Please try again.' };
      default:
        return { kind: 'unknown', title: 'Screening failed', message: 'The screening request could not be completed. Please try again.' };
    }
  }
  if (err instanceof TypeError) {
    return { kind: 'network', title: 'Backend unreachable', message: 'Cannot reach the HoloMed backend. Check your connection and that the server is running, then try again.' };
  }
  return { kind: 'unknown', title: 'Screening failed', message: 'The screening request could not be completed. Please try again.' };
}

export function imageDataUrl(img: EncodedImage): string {
  return `data:${img.media_type};base64,${img.data}`;
}
