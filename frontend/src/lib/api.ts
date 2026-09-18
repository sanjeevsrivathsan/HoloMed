/**
 * HoloMed API Client
 *
 * Centralizes all FastAPI calls. Every request:
 *   - Uses VITE_API_BASE_URL (default empty → Vite proxy forwards /api/* to :8000)
 *   - Sends credentials: 'include' so the HttpOnly session cookie is attached automatically
 *   - Returns typed responses; throws ApiError on non-2xx
 *
 * Backend token mechanism: HttpOnly cookie named `session` set by POST /api/v1/auth/login.
 * No Authorization header is needed. The browser sends the cookie automatically.
 *
 * NEVER put JWT_SECRET, database credentials, or private keys in this file.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';

// The active patient (set by PatientContext). Sent on every request; the backend verifies that the
// signed-in user owns it before using it, and scopes patient-owned data to it.
export const PATIENT_HEADER = 'X-HoloMed-Patient';
let activePatientId: string | null = null;

export function setActivePatientId(id: string | null): void {
  activePatientId = id;
}

export function getActivePatientId(): string | null {
  return activePatientId;
}

// ─── Error type ──────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

// ─── Internal fetch wrapper ───────────────────────────────────────────────────

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers = new Headers(init.headers);
  if (activePatientId && !headers.has(PATIENT_HEADER)) headers.set(PATIENT_HEADER, activePatientId);

  const res = await fetch(url, {
    ...init,
    headers,
    credentials: 'include', // always send the session cookie
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // response body is not JSON — keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// ─── Public helpers ───────────────────────────────────────────────────────────

export const api = {
  /** GET request — returns typed JSON */
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },

  /** POST with JSON body */
  post<T>(path: string, body: unknown, init: Pick<RequestInit, 'signal'> = {}): Promise<T> {
    return request<T>(path, {
      ...init,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  /**
   * POST with application/x-www-form-urlencoded body.
   * Required by OAuth2PasswordRequestForm (login endpoint).
   */
  postForm<T>(path: string, fields: Record<string, string>): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(fields).toString(),
    });
  },

  /**
   * POST with multipart/form-data body (DICOM file upload).
   * Do NOT set Content-Type manually — the browser sets the boundary automatically.
   */
  postMultipart<T>(path: string, form: FormData, init: Pick<RequestInit, 'signal'> = {}): Promise<T> {
    return request<T>(path, {
      ...init,
      method: 'POST',
      body: form,
    });
  },

  /** PUT with JSON body */
  put<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  /** PATCH with JSON body */
  patch<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  /** DELETE */
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' });
  },

  /** POST with no body (e.g. logout) */
  postEmpty<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'POST' });
  },
};

// ─── Typed response shapes (backend schema) ───────────────────────────────────

/** POST /api/v1/auth/register */
export interface RegisterResponse {
  id: number;
  email: string;
}

/** POST /api/v1/auth/login */
export interface LoginResponse {
  access_token: string;
  token_type: string;
}

/** GET /api/v1/auth/me */
export interface MeResponse {
  id: number;
  email: string;
  google_linked?: boolean;
}

/** POST /api/v1/medical-data/patients  |  GET /api/v1/medical-data/patients */
export interface PatientResponse {
  id: number;
  owner_id: number;
  external_id: string | null;
  display_name: string;
}

/** POST /api/v1/medical-data/dicom/upload  |  POST /api/v1/patients/{id}/imaging */
export interface DicomUploadResponse {
  instance_id: number;
  patient_id: string;
  study_instance_uid: string;
  series_instance_uid: string;
  sop_instance_uid: string;
  modality: string | null;
  created: boolean;
}

/** Saved AI screening (GET /api/v1/patients/{id}/analyses) */
export interface AnalysisSummary {
  id: string;
  study_instance_uid: string | null;
  sop_instance_uid: string | null;
  input_format: string;
  provider: string;
  model_name: string;
  model_weights: string;
  weight_sha256: string;
  primary_pathology: string;
  primary_score: number;
  selected_target: string | null;
  created_at: string;
}

/** GET /api/v1/patients/{id}/imaging */
export interface PatientImagingSeries {
  series_instance_uid: string;
  modality: string | null;
  description: string | null;
  instance_count: number;
  first_sop_instance_uid: string;
  rows: number | null;
  columns: number | null;
}

export interface PatientImagingStudy {
  study_instance_uid: string;
  modality: string | null;
  description: string | null;
  study_date: string | null;
  uploaded_at: string | null;
  series_count: number;
  instance_count: number;
  series: PatientImagingSeries[];
  latest_analysis: AnalysisSummary | null;
}

/** GET /api/v1/dicomweb/studies */
export interface StudyMeta {
  StudyInstanceUID: string;
  Modality: string;
  CreatedDate: string;
  Description: string | null;
}

/** GET /api/v1/dicomweb/studies/{uid}/series */
export interface SeriesMeta {
  SeriesInstanceUID: string;
  Modality: string;
}

/** GET /api/v1/dicomweb/studies/{uid}/series/{uid}/instances */
export interface InstanceMeta {
  SOPInstanceUID: string;
}
